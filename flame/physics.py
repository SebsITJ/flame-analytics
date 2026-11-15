"""Deterministic physics calculations shown under "Calculations".

Every number comes from the question, the reference atmospheres in config, or
pandas arithmetic on the retrieved / matching rows. No LLM is involved.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from . import config
from .classify import fuel_matches
from .i18n import ref_label, t, term
from .retrieval import Conditions

ATM_TO_KPA = 101.325
ATM_TO_PSI = 14.6959

# English wording of the two fixed notes; the Spanish text lives in flame/i18n.py.
EXTRAPOLATION = t("phy.extrapolation", "en")


def po2(oxygen_pct: float, pressure_atm: float) -> dict[str, float]:
    """Partial pressure of O2: pO2 = (O2 % / 100) × P."""
    atm = (float(oxygen_pct) / 100.0) * float(pressure_atm)
    return {
        "atm": round(atm, 6),
        "kpa": round(atm * ATM_TO_KPA, 4),
        "psi": round(atm * ATM_TO_PSI, 4),
    }


def _fmt(x: float | None, digits: int = 4) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "n/a"
    return f"{round(float(x), digits):g}"


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    n = len(xs)
    if n < 3:
        return None
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xx = sum(x * x for x in xs)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-12:
        return None
    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    return intercept, slope


# Molar heat capacities Cp° at 298.15 K, J/(mol·K), NIST-JANAF thermochemical tables
# (Chase, M.W., Jr., NIST-JANAF Thermochemical Tables, 4th ed., J. Phys. Chem. Ref. Data
# Monograph 9, 1998). Rounded as commonly tabulated: N2 29.1, O2 29.4, CO2 37.1, He 20.8, Ar 20.8.
# These are standard-temperature values, not flame-temperature means. At flame temperatures
# CO2's Cp rises more than N2's, so a high-T index would show a larger CO2 advantage;
# that is not computed here.
CP_298K = {"N2": 29.1, "O2": 29.4, "CO2": 37.1, "He": 20.8, "Ar": 20.8}
X_O2_AIR = 0.2095
SEA_LEVEL_PO2_KPA = X_O2_AIR * ATM_TO_KPA  # 21.2 kPa

PHYSICS_NOTE = t("phy.note", "en")


def atmosphere_indices(oxygen_pct: float, pressure_atm: float | None = None, x_co2: float = 0.0, x_he: float = 0.0) -> dict:
    """Composition indicators for an O2 / N2 (/ CO2 / He) atmosphere. No flame model.

    inert_per_o2    moles of inert gas per mole of O2 (21 % O2 in N2: 3.76)
    ballast         heat capacity of that inert gas per mole of O2, J/K
                    (21 % O2 / 79 % N2 at 298.15 K: 109.5). Lower means a hotter flame.
                    It ignores transport and radiation, so it understates helium
                    (high thermal diffusivity) and CO2 (radiation). Cp values are
                    NIST-JANAF Cp° at 298.15 K, not flame-temperature means.
    normoxic_o2_pct O2 % that gives sea-level pO2 at this total pressure
    """
    x = float(oxygen_pct) / 100.0
    if not 0 < x <= 1:
        return {}
    x_co2 = 0.0 if x_co2 is None or pd.isna(x_co2) else float(x_co2)
    x_he = 0.0 if x_he is None or pd.isna(x_he) else float(x_he)
    x_n2 = max(0.0, 1.0 - x - x_co2 - x_he)
    out = {
        "x_o2": x,
        "inert_per_o2": round((1.0 - x) / x, 4),
        "ballast": round((x_n2 * CP_298K["N2"] + x_co2 * CP_298K["CO2"] + x_he * CP_298K["He"]) / x, 2),
    }
    if pressure_atm:
        out["po2"] = po2(oxygen_pct, pressure_atm)
        out["normoxic_o2_pct"] = round(min(100.0, 100.0 * X_O2_AIR / float(pressure_atm)), 2)
    return out


def _ref_atmospheres(lang: str = "en") -> list[dict]:
    rows = []
    for ref in config.REFERENCE_ATMOSPHERES:
        p_atm = ref["pressure_psi"] * config.TO_ATM["psi"]
        idx = atmosphere_indices(ref["oxygen"], p_atm)
        rows.append(
            {
                "label": ref_label(ref, lang),
                "oxygen": ref["oxygen"],
                "pressure_atm": round(p_atm, 6),
                "pressure_psi": ref["pressure_psi"],
                "po2_atm": idx["po2"]["atm"],
                "po2_kpa": idx["po2"]["kpa"],
                "po2_psi": idx["po2"]["psi"],
                "inert_per_o2": idx["inert_per_o2"],
                "ballast": idx["ballast"],
            }
        )
    return rows


@dataclass
class PhysicsReport:
    query_po2: dict[str, float] | None = None
    indices: dict | None = None
    references: list[dict] = field(default_factory=list)
    bracket: dict | None = None
    lowest_o2_burned: float | None = None  # lowest O2 at which a flame was recorded for the fuel
    lowest_po2_burned_atm: float | None = None
    burned_rows: list[str] = field(default_factory=list)
    extinguished_o2: list[float] = field(default_factory=list)
    extinguished_rows: list[str] = field(default_factory=list)
    margin_o2: float | None = None
    trend: dict | None = None
    diluent: dict | None = None
    warnings: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

    def as_facts(self) -> dict:
        """Flat, JSON-friendly numbers for the Gemini payload and the verifier."""
        facts: dict = {}
        if self.query_po2:
            facts["query_pO2_atm"] = _fmt(self.query_po2["atm"])
            facts["query_pO2_kPa"] = _fmt(self.query_po2["kpa"])
            facts["query_pO2_psi"] = _fmt(self.query_po2["psi"])
        if self.indices:
            facts["query_inert_mol_per_mol_O2"] = _fmt(self.indices["inert_per_o2"], 3)
            facts["query_inert_heat_capacity_J_per_K_per_mol_O2"] = _fmt(self.indices["ballast"], 1)
        if self.lowest_o2_burned is not None:
            facts["lowest_O2_pct_with_recorded_flame"] = _fmt(self.lowest_o2_burned)
        if self.bracket and self.bracket.get("highest_nonburn_below"):
            facts["highest_O2_pct_without_flame_below_it"] = _fmt(self.bracket["highest_nonburn_below"]["o2"])
        if self.margin_o2 is not None:
            facts["stated_O2_minus_lowest_flame_O2_points"] = _fmt(self.margin_o2)
        if self.trend:
            facts["trend"] = (
                f"{self.trend['metric']} = {_fmt(self.trend['intercept'], 5)} + "
                f"{_fmt(self.trend['slope'], 5)} × O2%  (n={self.trend['n']}, R2={_fmt(self.trend['r2'], 3)})"
            )
        return facts


def _matching_pool(df: pd.DataFrame, hits: pd.DataFrame, cond: Conditions) -> tuple[pd.DataFrame, bool]:
    """All rows of the named fuel (True), or just the retrieved rows when no fuel is named (False)."""
    if df is not None and "gravedad" in df.columns:  # same microgravity filter as metric_rows (review #9)
        df = df[df["gravedad"].astype(str).str.contains(config.MICROGRAVITY_PATTERN, case=False, na=False)]
    if cond.fuel and df is not None and not df.empty:
        pool = df[df["combustible"].map(lambda f: fuel_matches(str(f), cond.fuel))]
        if not pool.empty:
            return pool, True
    return (hits if hits is not None else df), False


def flammability_bracket(pool: pd.DataFrame) -> dict | None:
    """Observed oxygen bound for ONE fuel: lowest O2 with a flame, and no-flame evidence below it.

    This is not an oxygen index. LOI and NASA's upward-propagation limit are normal-gravity tests;
    here the rows mix apparatus, flow, pressure and sample size, so the result is a bracket, never
    one interpolated number. "No test below X" is reported as missing data, not as safety.
    """
    need = {"oxigeno_num", "ignited", "no_ignition", "extinguished", "row_id"}
    if pool is None or pool.empty or not need <= set(pool.columns):
        return None
    has_o2 = pool["oxigeno_num"].notna()
    flame = pool[has_o2 & (pool["ignited"] == True)]
    # Final O2 after an extinguished test is NOT used as no-flame evidence: in BASS-II
    # the flame often goes out from blow-off or burnout while O2 barely changes, and
    # some end values are inconsistent with a closed-volume limit.
    nonburn: list[dict] = [
        {"o2": float(r.oxigeno_num), "row_id": r.row_id, "kind": "did not ignite"}
        for r in pool[has_o2 & (pool["no_ignition"] == True)].itertuples()
    ]
    if flame.empty and not nonburn:
        return None
    out: dict = {"flame_rows": int(len(flame)), "nonburn_rows": len(nonburn), "lowest_flame": None, "highest_nonburn_below": None, "overlap": 0}
    if flame.empty:
        out["highest_nonburn"] = max(nonburn, key=lambda n: n["o2"])
        return out
    row = flame.loc[flame["oxigeno_num"].idxmin()]
    lowest = float(row["oxigeno_num"])
    out["lowest_flame"] = {
        "o2": lowest,
        "row_id": row["row_id"],
        "experiment": str(row.get("experimento", "")),
        "pressure_atm": None if pd.isna(row.get("presion_num")) else float(row["presion_num"]),
    }
    below = [n for n in nonburn if n["o2"] < lowest]
    if below:
        out["highest_nonburn_below"] = max(below, key=lambda n: n["o2"])
    out["overlap"] = sum(1 for n in nonburn if n["o2"] >= lowest)
    return out


def _diluent_effect(pool: pd.DataFrame) -> dict | None:
    """CO2 and He rows against an N2-only baseline, using only rows that state ambient mole fractions."""
    need = {"x_o2", "x_co2", "x_he", "extinguished", "oxigeno_num"}
    if pool is None or pool.empty or not need <= set(pool.columns):
        return None
    study = pool[pool["x_o2"].notna()]
    if study.empty:
        return None
    co2, he = study["x_co2"].fillna(0), study["x_he"].fillna(0)
    base = study[(co2 == 0) & (he == 0)]  # helium rows are not part of the CO2 baseline, and vice versa
    if base.empty:
        return None

    def summarise(frame: pd.DataFrame) -> dict:
        o2 = frame["oxigeno_num"].dropna()
        ballast = [
            atmosphere_indices(r.x_o2 * 100, None, r.x_co2, r.x_he).get("ballast")
            for r in frame.itertuples()
        ]
        ballast = [b for b in ballast if b is not None]
        return {
            "rows": len(frame),
            "extinguished": int(frame["extinguished"].sum()),
            "burned": int(frame["burned"].sum()) if "burned" in frame.columns else 0,
            "cool_flame": int(frame["cool_flame"].sum()) if "cool_flame" in frame.columns else 0,
            "o2_median": None if o2.empty else float(o2.median()),
            "o2_range": None if o2.empty else f"{_fmt(o2.min(), 3)}–{_fmt(o2.max(), 3)}",
            "ballast_mean": round(sum(ballast) / len(ballast), 1) if ballast else None,
            "row_ids": frame["row_id"].head(8).tolist() if "row_id" in frame.columns else [],
        }

    result: dict = {}
    for gas, frame in (("CO2", study[(co2 > 0) & (he == 0)]), ("He", study[(he > 0) & (co2 == 0)])):
        if frame.empty:
            result[gas] = None
            continue
        w, wo = summarise(frame), summarise(base)
        same_o2 = (
            w["o2_median"] is not None and wo["o2_median"] is not None
            and abs(w["o2_median"] - wo["o2_median"]) <= 2.0
        )
        result[gas] = {"diluent": gas, "with": w, "without": wo, "comparable": same_o2}
    return result if any(result.values()) else None


def _r2(xs: list[float], ys: list[float], intercept: float, slope: float) -> float | None:
    mean = sum(ys) / len(ys)
    total = sum((y - mean) ** 2 for y in ys)
    if total < 1e-12:
        return None
    return round(1 - sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys)) / total, 4)


def _trend(pool: pd.DataFrame) -> dict | None:
    """Metric vs O2 inside ONE fuel, ONE experiment and ONE metric; never across apparatus or fuels."""
    need = {"oxigeno_num", "result_metric", "result_metric_name", "combustible", "experimento"}
    if pool is None or pool.empty or not need <= set(pool.columns):
        return None
    usable = pool.dropna(subset=["oxigeno_num", "result_metric"])
    usable = usable[usable["result_metric_name"].astype(str) != ""]
    if "result_metric_unit" not in usable.columns:
        usable = usable.assign(result_metric_unit="")
    usable = usable.assign(result_metric_unit=usable["result_metric_unit"].fillna("").astype(str))
    best = None
    # One unit per fit too: "burning rate" can carry mm²/s in one row and mg/s in another (review #11).
    for (*key, _unit), grp in usable.groupby(["combustible", "experimento", "result_metric_name", "result_metric_unit"], sort=False):
        key = tuple(key)
        xs = grp["oxigeno_num"].astype(float)
        # A fit over a nearly flat O2 range is a numerical artefact, not a trend.
        if len(grp) >= 3 and xs.round(3).nunique() >= 3 and (xs.max() - xs.min()) >= 2.0:
            if best is None or len(grp) > len(best[1]):
                best = (key, grp)
    if best is None:
        return None
    (fuel, experiment, name), grp = best
    xs, ys = grp["oxigeno_num"].astype(float).tolist(), grp["result_metric"].astype(float).tolist()
    fit = _linear_fit(xs, ys)
    if not fit:
        return None
    intercept, slope = fit
    exponent = None
    if min(ys) > 0 and min(xs) > 0:  # power law: metric ∝ (O2 %)^n, the usual form for spread and burning rates
        log_fit = _linear_fit([math.log(x) for x in xs], [math.log(y) for y in ys])
        exponent = round(log_fit[1], 3) if log_fit else None
    return {
        "metric": str(name),
        "unit": str(grp["result_metric_unit"].iloc[0] or "") if "result_metric_unit" in grp.columns else "",
        "fuel": str(fuel),
        "experiment": str(experiment),
        "n": len(grp),
        "intercept": round(intercept, 6),
        "slope": round(slope, 6),
        "r2": _r2(xs, ys, intercept, slope),
        "exponent": exponent,
        "o2_range": f"{_fmt(min(xs), 3)}–{_fmt(max(xs), 3)}",
        "row_ids": grp["row_id"].tolist() if "row_id" in grp.columns else [],
    }


def _ids(ids: list[str], limit: int = 4) -> str:
    return " " + ", ".join(f"[{i}]" for i in ids[:limit]) if ids else ""


def compute_physics(df: pd.DataFrame, hits: pd.DataFrame, cond: Conditions, lang: str = "en") -> PhysicsReport:
    """Numbers and sentences for "Calculations". ``lang`` changes the wording only, never a number."""

    def T(key: str, **kw) -> str:
        return t(key, lang, **kw)

    report = PhysicsReport(references=_ref_atmospheres(lang), warnings=[T("phy.extrapolation")])
    lines: list[str] = []

    # --- 1. Atmosphere: partial pressure (breathing) and inert gas per mole of O2 (flammability) ---
    if cond.oxygen is not None:
        report.indices = atmosphere_indices(cond.oxygen, cond.pressure_atm) or None
    idx = report.indices
    if idx and "po2" in idx:
        report.query_po2 = p = idx["po2"]
        lines.append(T(
            "phy.stated_atm", o2=_fmt(cond.oxygen, 3), p=_fmt(cond.pressure_atm, 4), atm=_fmt(p["atm"]),
            kpa=_fmt(p["kpa"]), psi=_fmt(p["psi"]), inert=_fmt(idx["inert_per_o2"], 3),
            ballast=_fmt(idx["ballast"], 1),
        ))
        lines.append(T("phy.normoxic", sea=_fmt(SEA_LEVEL_PO2_KPA, 3), pct=_fmt(idx["normoxic_o2_pct"], 3)))
    elif idx:
        lines.append(T(
            "phy.stated_o2_only", o2=_fmt(cond.oxygen, 3), inert=_fmt(idx["inert_per_o2"], 3),
            ballast=_fmt(idx["ballast"], 1),
        ))
    else:
        lines.append(T("phy.no_o2"))
    lines.append(T("phy.refs_header"))
    for ref in report.references:
        lines.append(T(
            "phy.ref_line", label=ref["label"], o2=_fmt(ref["oxygen"], 3), psi=_fmt(ref["pressure_psi"], 3),
            atm=_fmt(ref["po2_atm"]), kpa=_fmt(ref["po2_kpa"], 3), inert=_fmt(ref["inert_per_o2"], 3),
            ballast=_fmt(ref["ballast"], 1),
        ))
    if idx:
        air = report.references[0]
        change = 100.0 * (idx["ballast"] - air["ballast"]) / air["ballast"]
        if abs(change) >= 1:
            lines.append(T(
                "phy.vs_air", label=air["label"], pct=_fmt(abs(change), 2),
                less_more=T("word.less") if change < 0 else T("word.more"),
                more_less=T("word.more") if change < 0 else T("word.less"),
            ))
    lines.append(T("phy.note"))

    # --- 2. Observed oxygen bound for the named fuel ---
    pool, fuel_specific = _matching_pool(df, hits, cond)
    if pool is None:
        pool = hits
    if not fuel_specific:
        lines.append(T("phy.no_fuel"))
    else:
        report.bracket = b = flammability_bracket(pool)
        if not b:
            lines.append(T("phy.no_outcome", fuel=cond.fuel))
        elif not b["lowest_flame"]:
            n = b["highest_nonburn"]
            lines.append(T("phy.no_flame", fuel=cond.fuel, o2=_fmt(n["o2"], 3), kind=term(n["kind"], lang), row=n["row_id"]))
        else:
            low = b["lowest_flame"]
            report.lowest_o2_burned = low["o2"]
            report.burned_rows = [low["row_id"]]
            where = low["experiment"] + (f", {_fmt(low['pressure_atm'], 3)} atm" if low["pressure_atm"] is not None else "")
            if low["pressure_atm"] is not None:
                report.lowest_po2_burned_atm = po2(low["o2"], low["pressure_atm"])["atm"]
            lines.append(T(
                "phy.lowest_flame", fuel=cond.fuel, o2=_fmt(low["o2"], 3), row=low["row_id"], where=where,
                n=b["flame_rows"],
            ))
            under = b["highest_nonburn_below"]
            if under:
                lines.append(T(
                    "phy.highest_nonburn", o2=_fmt(under["o2"], 3), kind=term(under["kind"], lang),
                    row=under["row_id"], a=_fmt(under["o2"], 3), b=_fmt(low["o2"], 3),
                ))
            else:
                lines.append(T("phy.no_below", b=_fmt(low["o2"], 3)))
            if b["overlap"]:
                lines.append(T("phy.overlap", n=b["overlap"], o2=_fmt(low["o2"], 3)))
            if cond.oxygen is not None:
                report.margin_o2 = round(float(cond.oxygen) - low["o2"], 4)
                if report.margin_o2 >= 0:
                    verdict = T("phy.verdict_inside")
                elif under and cond.oxygen <= under["o2"]:
                    verdict = T("phy.verdict_below_nonburn")
                else:
                    verdict = T("phy.verdict_untested")
                lines.append(T(
                    "phy.margin", o2=_fmt(cond.oxygen, 3), m=_fmt(abs(report.margin_o2), 3),
                    dir=T("word.above") if report.margin_o2 >= 0 else T("word.below"), verdict=verdict,
                ))
        ext = pool[(pool["extinguished"] == True) & pool["oxigeno_num"].notna()] if "extinguished" in pool.columns else pool.iloc[0:0]
        report.extinguished_o2 = [float(x) for x in ext["oxigeno_num"].tolist()]
        report.extinguished_rows = ext["row_id"].head(8).tolist() if "row_id" in ext.columns else []
        if "o2_end_pct" in pool.columns:
            ext_end = pool[(pool["extinguished"] == True) & pool["o2_end_pct"].notna()]
            if not ext_end.empty:
                lo, hi = float(ext_end["o2_end_pct"].min()), float(ext_end["o2_end_pct"].max())
                lines.append(T("phy.ext_final", n=len(ext_end), lo=_fmt(lo, 3), hi=_fmt(hi, 3)))

    # --- 3. Trend of a numeric metric with oxygen ---
    report.trend = tr = _trend(pool)
    if tr:
        metric = term(tr["metric"], lang)
        unit = T("phy.in_unit", unit=term(tr["unit"], lang)) if tr["unit"] else ""
        text = T(
            "phy.trend", experiment=tr["experiment"], fuel=tr["fuel"], n=tr["n"], metric=metric, unit=unit,
            range=tr["o2_range"], a=_fmt(tr["intercept"], 5), b=_fmt(tr["slope"], 5),
            r2=(f", R² = {_fmt(tr['r2'], 3)}" if tr["r2"] is not None else ""),
        )
        if tr["exponent"] is not None:
            text += T("phy.power", metric=metric, e=_fmt(tr["exponent"], 3))
        text += T("phy.trend_caveat") + _ids(tr["row_ids"])
        lines.append(text)
    else:
        lines.append(T("phy.no_trend"))

    # --- 4. Diluent comparison ---
    report.diluent = _diluent_effect(pool)
    if report.diluent:
        for gas, block in report.diluent.items():
            if not block:
                continue
            w, wo = block["with"], block["without"]
            text = T(
                "phy.diluent", gas=gas, n=w["rows"], med=_fmt(w["o2_median"], 3), ballast=_fmt(w["ballast_mean"], 1),
                ext=w["extinguished"], ids=_ids(w["row_ids"]), n2=wo["rows"], med2=_fmt(wo["o2_median"], 3),
                ballast2=_fmt(wo["ballast_mean"], 1), ext2=wo["extinguished"], ids2=_ids(wo["row_ids"]),
            )
            text += T("phy.diluent_comparable") if block["comparable"] else T("phy.diluent_not_comparable")
            if w["cool_flame"] or wo["cool_flame"]:
                text += T("phy.diluent_cool", n=w["cool_flame"] + wo["cool_flame"])
            lines.append(text)
    else:
        lines.append(T("phy.no_diluent"))

    lines.append(T("phy.extrapolation"))
    report.lines = lines
    return report
