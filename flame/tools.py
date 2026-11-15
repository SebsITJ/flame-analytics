"""Whitelisted tools Gemini may call (v7). Thin wrappers over the engine: they only read the table and call
the existing retrieval / physics functions; nothing here changes how a number is computed.

Every tool result is registered in a Ledger. Rows keep their dataset id (R1…R1982) and every result gets a
fact id (E1, E2…). The verifier (flame/verify.py) accepts only numbers and ids that are in the ledger.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from . import config
from .classify import fuel_matches
from .physics import _diluent_effect, _trend, atmosphere_indices, flammability_bracket
from .retrieval import Conditions, metric_rows, microgravity_only, parse_rules, rank

PHASES = ["prevent", "detect", "extinguish"]
METRICS = list(config.COMPARISON_METRICS)
# Columns of every table a tool returns; the chart spec may only name these.
TABLE_COLUMNS = ["row_id", "experimento", "combustible", "oxigeno", "presion", "fase",
                 "extinguished", "flame_recorded", "did_not_ignite", "metric_value"]
_RESULT_CHARS = 220  # result text sent per row (get_rows sends the full text)


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if hasattr(v, "item"):  # numpy scalar
        v = v.item()
        if isinstance(v, float) and math.isnan(v):
            return None
    return v


def _row_brief(r: pd.Series, full: bool = False) -> dict:
    text = str(r.get("resultado", ""))
    out = {
        "row_id": str(r["row_id"]),
        "experimento": str(r.get("experimento", "")),
        "combustible": str(r.get("combustible", "")),
        "oxigeno": _clean(r.get("oxigeno_num")),
        "presion": _clean(r.get("presion_num")),
        "fase": str(r.get("fase", "")),
        # Outcome flags read from the result text (flame/enrich.py). flame_recorded=false does NOT mean
        # "did not ignite": only did_not_ignite=true says that; outcome_not_listed=true means unknown.
        "flame_recorded": bool(r.get("ignited", False)),
        "did_not_ignite": bool(r.get("no_ignition", False)),
        "extinguished": bool(r.get("extinguished", False)),
        "outcome_not_listed": bool(r.get("outcome_not_listed", False)),
        "resultado": text if full else text[:_RESULT_CHARS],
    }
    if full:
        out["notas"] = str(r.get("notas", ""))
        out["fuente"] = str(r.get("fuente", ""))
        out["flujo"] = str(r.get("flujo", ""))
    return out


def _table_row(r: pd.Series, metric_value=None) -> dict:
    return {
        "row_id": str(r["row_id"]),
        "experimento": str(r.get("experimento", "")),
        "combustible": str(r.get("combustible", "")),
        "oxigeno": _clean(r.get("oxigeno_num")),
        "presion": _clean(r.get("presion_num")),
        "fase": str(r.get("fase", "")),
        "extinguished": bool(r.get("extinguished", False)),
        "flame_recorded": bool(r.get("ignited", False)),
        "did_not_ignite": bool(r.get("no_ignition", False)),
        "metric_value": _clean(metric_value if metric_value is not None else r.get("result_metric")),
    }


@dataclass
class Ledger:
    """Everything the engine returned to Gemini. The verifier only accepts what is in here."""

    rows: dict = field(default_factory=dict)  # "R12" -> brief row dict
    facts: dict = field(default_factory=dict)  # "E3" -> {"tool", "args", "values", "table"}
    calls: list = field(default_factory=list)  # trace for the UI: {"tool","args","ok","evidence_id","n_rows","error"}
    agents: list = field(default_factory=list)  # specialist agents the router activated (flame/agent.py)

    def add_rows(self, frame: pd.DataFrame, full: bool = False) -> list[dict]:
        out = []
        for _, r in frame.iterrows():
            brief = _row_brief(r, full)
            if full or brief["row_id"] not in self.rows:
                self.rows[brief["row_id"]] = brief
            out.append(brief)
        return out

    def add_fact(self, tool: str, args: dict, values: dict, table: list[dict] | None = None) -> str:
        eid = f"E{len(self.facts) + 1}"
        self.facts[eid] = {"tool": tool, "args": args, "values": values, "table": table or []}
        return eid

    def as_pack(self) -> dict:
        """The evidence pack sent to the interpret step (rows + facts, nothing else)."""
        pack = {
            "rows": list(self.rows.values()),
            "facts": [{"evidence_id": k, "tool": v["tool"], "args": v["args"], "values": v["values"],
                       "table_columns": sorted(v["table"][0]) if v["table"] else [],
                       "table_rows": len(v["table"]),
                       **({"agent": v["agent"]} if v.get("agent") else {})}
                      for k, v in self.facts.items()],
        }
        if self.agents:
            pack["active_agents"] = list(self.agents)
        return pack


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pool(df: pd.DataFrame) -> pd.DataFrame:
    return microgravity_only(df)


def resolve_fuel(df: pd.DataFrame, name: str | None) -> str | None:
    """A fuel as Gemini wrote it (maybe Spanish: "metanol") -> a name that matches dataset rows."""
    if not name or not str(name).strip():
        return None
    name = str(name).strip()
    if df["combustible"].map(lambda f: fuel_matches(str(f), name)).any():
        return name
    fuels = df["combustible"].dropna().unique().tolist()
    for lang in ("es", "en"):
        found = parse_rules(name, fuels, lang).fuel
        if found:
            return found
    return name


def _fuel_rows(df: pd.DataFrame, fuel: str | None) -> pd.DataFrame:
    pool = _pool(df)
    if not fuel:
        return pool
    return pool[pool["combustible"].map(lambda f: fuel_matches(str(f), fuel))]


def _num(value, name: str, lo: float, hi: float) -> float | None:
    if value is None or value == "":
        return None
    v = float(value)
    if not lo <= v <= hi:
        raise ValueError(f"{name} must be between {lo:g} and {hi:g}")
    return v


def _gas_signals(scope: pd.DataFrame) -> dict:
    """Gas readings of the matching rows (start -> end of the test), for the detection path."""
    out: dict = {}
    for col, name, unit in (("co_delta_ppm", "CO", "ppm"), ("co2_delta_ppm", "CO2", "ppm"), ("o2_delta_pct", "O2", "pct")):
        if col not in scope.columns:
            continue
        vals = pd.to_numeric(scope[col], errors="coerce").dropna()
        out[f"rows_with_{name}_reading"] = int(len(vals))
        if len(vals):
            out[f"{name}_change_{unit}_median"] = _clean(float(f"{vals.median():.4g}"))
            out[f"{name}_change_{unit}_min"] = _clean(float(f"{vals.min():.4g}"))
            out[f"{name}_change_{unit}_max"] = _clean(float(f"{vals.max():.4g}"))
    if out:
        out["gas_note"] = "Change = end minus start reading of each test, as recorded in the rows."
    return out


def _share(part: int, total: int) -> float | None:
    return None if not total else round(100.0 * part / total, 1)


# ---------------------------------------------------------------------------
# The tools
# ---------------------------------------------------------------------------

def search_experiments(df, ledger: Ledger, fuel: str | None = None, o2_min=None, o2_max=None,
                       phase: str | None = None, limit: int = 8, with_gas_change: bool = False) -> dict:
    o2_min = _num(o2_min, "o2_min", 0, 100)
    o2_max = _num(o2_max, "o2_max", 0, 100)
    if o2_min is not None and o2_max is not None and o2_min > o2_max:
        o2_min, o2_max = o2_max, o2_min
    if phase not in (None, "", *PHASES):
        raise ValueError(f"phase must be one of {PHASES}")
    limit = max(1, min(int(limit or 8), config.AGENT_MAX_ROWS_PER_CALL))
    wanted = resolve_fuel(df, fuel)
    oxygen = None
    if o2_min is not None and o2_max is not None:
        oxygen = (o2_min + o2_max) / 2
    elif o2_min is not None or o2_max is not None:
        oxygen = o2_min if o2_min is not None else o2_max
    pool = _pool(df)
    cond = Conditions(oxygen=oxygen, fuel=wanted, phase=phase or None)
    ranked = rank(pool, cond).ranked
    scope = ranked
    if wanted:
        scope = scope[scope["combustible"].map(lambda f: fuel_matches(str(f), wanted))]
    if o2_min is not None:
        scope = scope[scope["oxigeno_num"] >= o2_min - 1e-9]
    if o2_max is not None:
        scope = scope[scope["oxigeno_num"] <= o2_max + 1e-9]
    if phase:
        scope = scope[scope["fase"] == phase]
    if with_gas_change:  # rows that recorded a gas at the start AND the end of the test
        gas_cols = [c for c in ("co2_delta_ppm", "co_delta_ppm", "o2_delta_pct") if c in scope.columns]
        scope = scope[scope[gas_cols].notna().any(axis=1)] if gas_cols else scope.iloc[0:0]
    if "relevance" in scope.columns:
        scope = scope.sort_values("relevance", ascending=False, kind="stable")
    top = scope.head(limit)
    rows = ledger.add_rows(top)
    n = int(len(scope))
    n_ext = int(scope["extinguished"].sum()) if n else 0
    n_ign = int(scope["ignited"].sum()) if n else 0
    n_noign = int(scope["no_ignition"].sum()) if n else 0
    n_unknown = int(scope["outcome_not_listed"].sum()) if n else 0
    values = {
        "fuel_matched": wanted,
        "matching_rows": n,
        "matching_rows_extinguished": n_ext,
        "matching_rows_flame_recorded": n_ign,
        "matching_rows_did_not_ignite": n_noign,
        "matching_rows_outcome_not_listed": n_unknown,
        "extinguished_share_pct": _share(n_ext, n),
        "experiments": sorted(scope["experimento"].astype(str).unique().tolist())[:12],
        "returned_rows": len(rows),
    }
    if with_gas_change:
        values.update(_gas_signals(scope))
    if phase == "detect":  # what these experiments measured (PSI table; instruments only when the data name them)
        from .lead import MEASUREMENTS
        values["measurement_types"] = {e: MEASUREMENTS[e]["en"] for e in values["experiments"] if e in MEASUREMENTS}
        sig = _gas_signals(scope) if n else {}
        values["gas_readings_in_these_rows"] = bool(sig.get("rows_with_CO_reading") or sig.get("rows_with_CO2_reading"))
    table = [_table_row(r) for _, r in scope.head(200).iterrows()]
    args = {"fuel": fuel, "o2_min": o2_min, "o2_max": o2_max, "phase": phase, "limit": limit}
    if with_gas_change:
        args["with_gas_change"] = True
    eid = ledger.add_fact("search_experiments", args, values, table)
    return {"evidence_id": eid, **values, "rows": rows}


def get_rows(df, ledger: Ledger, row_ids: list | None = None) -> dict:
    ids = [str(i).strip().upper() for i in (row_ids or [])][: config.AGENT_MAX_ROWS_PER_CALL]
    if not ids:
        raise ValueError("row_ids is empty")
    frame = df[df["row_id"].str.upper().isin(ids)]
    rows = ledger.add_rows(frame, full=True)
    missing = [i for i in ids if i not in {r["row_id"].upper() for r in rows}]
    eid = ledger.add_fact("get_rows", {"row_ids": ids}, {"returned_rows": len(rows), "unknown_ids": missing},
                          [_table_row(r) for _, r in frame.iterrows()])
    return {"evidence_id": eid, "rows": rows, "unknown_ids": missing}


def oxygen_bracket(df, ledger: Ledger, fuel: str = "") -> dict:
    wanted = resolve_fuel(df, fuel)
    if not wanted:
        raise ValueError("fuel is required")
    pool = _fuel_rows(df, wanted)
    br = flammability_bracket(pool) if not pool.empty else None
    values: dict = {"fuel_matched": wanted, "rows_for_fuel": int(len(pool)), "bracket_found": br is not None}
    ids: list[str] = []
    if br:
        values["rows_with_flame"] = br.get("flame_rows")
        values["rows_without_ignition"] = br.get("nonburn_rows")
        lf = br.get("lowest_flame")
        if lf:
            values["lowest_O2_pct_with_flame"] = lf["o2"]
            values["lowest_flame_row"] = lf["row_id"]
            values["lowest_flame_experiment"] = lf["experiment"]
            values["lowest_flame_pressure_atm"] = lf["pressure_atm"]
            ids.append(lf["row_id"])
        hb = br.get("highest_nonburn_below") or br.get("highest_nonburn")
        if hb:
            values["highest_O2_pct_without_ignition_below"] = hb["o2"]
            values["no_ignition_row"] = hb["row_id"]
            ids.append(hb["row_id"])
        values["no_ignition_rows_at_or_above_lowest_flame"] = br.get("overlap", 0)
    values["note"] = ("Observed bracket from these rows only; not an oxygen index. A failed ignition is not "
                      "an extinction limit.")
    rows = ledger.add_rows(df[df["row_id"].isin(ids)])
    table = [_table_row(r) for _, r in pool.dropna(subset=["oxigeno_num"]).head(200).iterrows()]
    eid = ledger.add_fact("oxygen_bracket", {"fuel": fuel}, values, table)
    return {"evidence_id": eid, **values, "rows": rows}


def compare_diluents(df, ledger: Ledger, fuel: str | None = None) -> dict:
    wanted = resolve_fuel(df, fuel)
    pool = _fuel_rows(df, wanted)
    eff = _diluent_effect(pool) if not pool.empty else None
    values: dict = {"fuel_matched": wanted, "comparison_found": eff is not None}
    ids: list[str] = []
    table: list[dict] = []
    if eff:
        base = None
        for gas in ("CO2", "He"):
            g = eff.get(gas)
            if not g:
                values[gas] = None
                continue
            w, wo = g["with"], g["without"]
            base = wo
            values[gas] = {
                "rows": w["rows"], "extinguished": w["extinguished"],
                "extinguished_share_pct": _share(w["extinguished"], w["rows"]),
                "o2_range": w["o2_range"], "inert_heat_capacity_mean_J_per_K_per_mol_O2": w["ballast_mean"],
                "comparable_O2_with_baseline": g["comparable"], "row_ids": w["row_ids"],
            }
            ids += w["row_ids"]
        if base:
            values["N2_only_baseline"] = {
                "rows": base["rows"], "extinguished": base["extinguished"],
                "extinguished_share_pct": _share(base["extinguished"], base["rows"]),
                "o2_range": base["o2_range"], "inert_heat_capacity_mean_J_per_K_per_mol_O2": base["ballast_mean"],
                "row_ids": base["row_ids"],
            }
            ids += base["row_ids"]
        study = pool[pool["x_o2"].notna()]
        for _, r in study.head(300).iterrows():
            row = _table_row(r)
            co2, he = (r.get("x_co2") or 0), (r.get("x_he") or 0)
            row["diluente"] = "CO2" if co2 and co2 > 0 and not he else ("He" if he and he > 0 and not co2 else
                                                                        ("N2" if not co2 and not he else "mix"))
            table.append(row)
    ledger.add_rows(df[df["row_id"].isin(ids)])
    eid = ledger.add_fact("compare_diluents", {"fuel": fuel}, values, table)
    return {"evidence_id": eid, **values}


def metric_trend(df, ledger: Ledger, fuel: str = "", metric: str = "flame_duration", at_o2=None) -> dict:
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {METRICS}")
    at_o2 = _num(at_o2, "at_o2", 0.1, 100)
    wanted = resolve_fuel(df, fuel)
    pool = metric_rows(df, metric, wanted)
    tr = _trend(pool) if not pool.empty else None
    values: dict = {"fuel_matched": wanted, "metric": metric, "rows_with_metric": int(len(pool)),
                    "trend_found": tr is not None}
    ids: list[str] = []
    if tr:
        values.update({k: tr[k] for k in ("experiment", "n", "intercept", "slope", "r2", "exponent", "o2_range", "unit")})
        values["formula"] = f"{tr['metric']} = {tr['intercept']} + {tr['slope']} × O2%"
        values["note"] = "Fit inside one fuel, one experiment and one metric only."
        ids = tr["row_ids"][:12]
        fit_rows = pool[pool["row_id"].isin(tr["row_ids"])]
        lo, hi = float(fit_rows["oxigeno_num"].min()), float(fit_rows["oxigeno_num"].max())
        values["fit_min_value"] = _clean(float(fit_rows["result_metric"].min()))
        values["fit_max_value"] = _clean(float(fit_rows["result_metric"].max()))
        if at_o2 is not None:
            # The ENGINE evaluates the fit at the asked O2, so the interpreter can quote an estimate it did
            # not compute. Outside the tested range it is labelled as an extrapolation, and a negative
            # result (a time or rate cannot be negative) is not reported.
            est = tr["intercept"] + tr["slope"] * at_o2
            inside = lo - 1e-9 <= at_o2 <= hi + 1e-9
            values["estimate_at_O2_pct"] = at_o2
            values["estimate_kind"] = ("interpolation inside the tested O2 range" if inside
                                       else "extrapolation outside the tested O2 range")
            if est > 0:
                values["estimated_value"] = float(f"{est:.3g}")
                values["estimate_unit"] = tr["unit"]
            else:
                values["estimated_value"] = None
                values["estimate_note"] = "the linear fit gives a non-physical (non-positive) value at this O2"
    elif not pool.empty:
        values["unit"] = str(pool["result_metric_unit"].iloc[0])
        values["min_value"] = _clean(float(pool["result_metric"].min()))
        values["max_value"] = _clean(float(pool["result_metric"].max()))
        ids = pool["row_id"].head(8).tolist()
    ledger.add_rows(df[df["row_id"].isin(ids)])
    table = [_table_row(r, r["result_metric"]) for _, r in pool.head(200).iterrows()]
    args = {"fuel": fuel, "metric": metric}
    if at_o2 is not None:
        args["at_o2"] = at_o2
    eid = ledger.add_fact("metric_trend", args, values, table)
    return {"evidence_id": eid, **values, "row_ids": ids}


def atmosphere(df, ledger: Ledger, o2_pct=None, pressure_atm=None, x_co2=0.0, x_he=0.0) -> dict:
    o2 = _num(o2_pct, "o2_pct", 0.1, 100)
    if o2 is None:
        raise ValueError("o2_pct is required")
    p = _num(pressure_atm, "pressure_atm", 0.01, 10)
    xc = _num(x_co2, "x_co2", 0, 1) or 0.0
    xh = _num(x_he, "x_he", 0, 1) or 0.0
    idx = atmosphere_indices(o2, p, xc, xh)
    values = {"o2_pct": o2, "pressure_atm": p, "x_co2": xc, "x_he": xh,
              "inert_mol_per_mol_O2": idx.get("inert_per_o2"),
              "inert_heat_capacity_J_per_K_per_mol_O2": idx.get("ballast"),
              "note": "NIST-JANAF Cp at 298.15 K; composition index, not a flame model."}
    if idx.get("po2"):
        values.update({"pO2_atm": idx["po2"]["atm"], "pO2_kPa": idx["po2"]["kpa"], "pO2_psi": idx["po2"]["psi"],
                       "O2_pct_for_sea_level_pO2": idx.get("normoxic_o2_pct")})
    eid = ledger.add_fact("atmosphere", {"o2_pct": o2_pct, "pressure_atm": pressure_atm, "x_co2": x_co2, "x_he": x_he},
                          values, [])
    return {"evidence_id": eid, **values}


HANDLERS = {
    "search_experiments": search_experiments,
    "get_rows": get_rows,
    "oxygen_bracket": oxygen_bracket,
    "compare_diluents": compare_diluents,
    "metric_trend": metric_trend,
    "atmosphere": atmosphere,
}

# JSON Schemas of the tools, as Gemini sees them (FunctionDeclaration.parameters_json_schema).
TOOL_SCHEMAS = {
    "search_experiments": (
        "Search the NASA PSI microgravity combustion rows. Call it before stating anything. Returns the "
        "matching row count, how many recorded extinction or ignition, and up to `limit` rows with row_id.",
        {"type": "object", "properties": {
            "fuel": {"type": "string", "description": "Fuel or material, e.g. methanol, heptane, PMMA, cotton"},
            "o2_min": {"type": "number", "minimum": 0, "maximum": 100, "description": "Lowest O2 % by volume"},
            "o2_max": {"type": "number", "minimum": 0, "maximum": 100, "description": "Highest O2 % by volume"},
            "phase": {"type": "string", "enum": PHASES},
            "limit": {"type": "integer", "minimum": 1, "maximum": config.AGENT_MAX_ROWS_PER_CALL},
            "with_gas_change": {"type": "boolean", "description": "Only rows with O2 / CO2 / CO recorded at the start and the end"},
        }},
    ),
    "get_rows": (
        "Full text, notes and source of rows already returned (by row_id such as R12).",
        {"type": "object", "properties": {"row_ids": {"type": "array", "items": {"type": "string"},
                                                       "maxItems": config.AGENT_MAX_ROWS_PER_CALL}},
         "required": ["row_ids"]},
    ),
    "oxygen_bracket": (
        "Observed oxygen bound for ONE fuel: lowest O2 % with a recorded flame and highest O2 % below it "
        "without ignition. Not an oxygen index.",
        {"type": "object", "properties": {"fuel": {"type": "string"}}, "required": ["fuel"]},
    ),
    "compare_diluents": (
        "Extinction counts with CO2 or helium added against an N2-only baseline, from rows that state the "
        "ambient mole fractions. Optional fuel filter.",
        {"type": "object", "properties": {"fuel": {"type": "string"}}},
    ),
    "metric_trend": (
        "Linear fit of a metric against O2 % inside one fuel and one experiment (n, slope, R2), or the "
        "range of values when no fit is possible. With at_o2 the engine also evaluates the fit at that O2 % "
        "and says whether it is an interpolation or an extrapolation.",
        {"type": "object", "properties": {"fuel": {"type": "string"},
                                          "metric": {"type": "string", "enum": METRICS},
                                          "at_o2": {"type": "number", "minimum": 0.1, "maximum": 100}},
         "required": ["metric"]},
    ),
    "atmosphere": (
        "Composition indices of an atmosphere: pO2 and inert-gas heat capacity per mole of O2 (NIST Cp at 298 K).",
        {"type": "object", "properties": {
            "o2_pct": {"type": "number", "minimum": 0.1, "maximum": 100},
            "pressure_atm": {"type": "number", "minimum": 0.01, "maximum": 10},
            "x_co2": {"type": "number", "minimum": 0, "maximum": 1},
            "x_he": {"type": "number", "minimum": 0, "maximum": 1}},
         "required": ["o2_pct"]},
    ),
}


def declarations():
    """google.genai FunctionDeclarations for the whitelisted tools (imported lazily)."""
    from google.genai import types

    return [types.FunctionDeclaration(name=n, description=d, parameters_json_schema=s)
            for n, (d, s) in TOOL_SCHEMAS.items()]


def dispatch(name: str, args: dict, df: pd.DataFrame, ledger: Ledger) -> dict:
    """Run one tool call. Unknown tools and bad arguments come back as {"error": ...} for Gemini to fix."""
    handler = HANDLERS.get(name)
    if handler is None:
        out = {"error": f"unknown tool '{name}'. Allowed: {sorted(HANDLERS)}"}
    else:
        allowed = set(TOOL_SCHEMAS[name][1].get("properties", {}))
        extra = sorted(set(args) - allowed)
        clean = {k: v for k, v in args.items() if k in allowed}
        try:
            out = handler(df, ledger, **clean)
            if extra:
                out["ignored_arguments"] = extra
        except (TypeError, ValueError, KeyError) as err:
            out = {"error": f"{type(err).__name__}: {str(err)[:200]}"}
    ledger.calls.append({
        "tool": name, "args": args, "ok": "error" not in out, "evidence_id": out.get("evidence_id"),
        "n_rows": len(out.get("rows", []) or out.get("row_ids", []) or []), "error": out.get("error"),
    })
    return out
