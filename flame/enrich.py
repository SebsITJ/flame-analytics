"""Pull explicit gas and outcome fields out of resultado / notas.

All values are copied from the source text. When the compound or the unit is
not stated, the cell is left empty and the display helper returns the fixed
phrase "source does not specify compound/units".
"""

from __future__ import annotations

import re

import pandas as pd

from .i18n import t

UNSPECIFIED = t("unspecified", "en")  # English wording; display_gas(lang=...) gives the Spanish one

# 1 % by volume = 10_000 ppm (mole fraction), used only when the source unit is % vol.
PCT_TO_PPM = 10_000

_NUM = r"([-+]?\d+(?:\.\d+)?|n/?a)"

# BASS-II style: "O2 22.2 -> 22.2 % vol (initial -> final)"
_PAIR = {
    "o2": re.compile(rf"\bO2\s+{_NUM}\s*->\s*{_NUM}\s*(% ?vol|%|ppm)", re.I),
    "co2": re.compile(rf"\bCO2\s+{_NUM}\s*->\s*{_NUM}\s*(% ?vol|%|ppm)", re.I),
    "co": re.compile(rf"\bCO\s+{_NUM}\s*->\s*{_NUM}\s*(% ?vol|%|ppm)", re.I),
}

# FLEX / CFI: "ambient mole fractions O2=0.21, N2=0.79, CO2=0.0, He=0.0"
_MOLE_FRACTIONS = re.compile(
    r"(?:ambient\s+)?mole fractions\s+([^;]+)",
    re.I,
)
_MF_PAIR = re.compile(r"(O2|N2|CO2|He)\s*=\s*([-+]?\d+(?:\.\d+)?)", re.I)

# CFI-G: "XO2 before/after 0.3939/0.389822946" (mole fractions)
_XO2 = re.compile(r"XO2\s+before/after\s*([-+]?\d+(?:\.\d+)?)\s*/\s*([-+]?\d+(?:\.\d+)?)", re.I)

# Outcome language. Three different outcomes that must not be merged:
#   no_ignition  - a flame never formed (evidence of non-flammability at that condition)
#   extinguished - a flame formed and then went out during the test
#   burned       - a flame formed and no extinction was recorded
# `ignited` = a flame existed at the row's oxygen level (extinguished or not).
_MISSING = re.compile(r"outcome not listed", re.I)
_NO_IGNITION = re.compile(
    r"\b(?:no hot ignition|flash only|did not ignite|no ignition|failed to ignite|not ignited?)\b", re.I
)
_SUSTAINED = re.compile(r"no extinction observed|kept burning|burned to completion", re.I)
_DID_EXTINGUISH = re.compile(
    r"flame extinguished|extinction noted|extinguished after|dilution extinguished"
    r"|self-?extinguish\w*|blow-?off|time to extinction|flame extinction",
    re.I,
)
_DID_BURN = re.compile(
    r"(?:burned to completion|kept burning|no extinction observed|hot ignition|"
    r"large-scale burn|flame spread|ignition on first|flames ignited)",
    re.I,
)
# "no flame spread", "did not burn": removed from the text before looking for burn wording.
_NEGATED = re.compile(r"\b(?:no|not|without|never)\s+(?:\w+\s+){0,2}?(?:flame spread|hot ignition|ignit\w*|burn\w*)", re.I)
_COOL_FLAME = re.compile(r"cool[- ]flame", re.I)
_FLAME_RUN = re.compile(
    r"spherical diffusion flame run|laminar jet flame run|cool-flame droplet test run",
    re.I,
)
# A positive value of one of these metrics means a flame existed.
# "fuel rate" and "mass loss rate" are not included: a planned flow or pyrolysis loss
# can be recorded without a flame.
_FLAME_METRICS = {"burn time", "time to extinction", "flame duration", "burning rate", "spread rate"}
_NO_UNIT = "unit not stated in source"
_RATE_UNIT = r"(mm\^?2/s|mm²/s|mg/s|mg/min|g/s|g/min|mm/s)?"

# Numeric result metrics, tried in this order (first with >= 3 points is used later).
METRIC_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    ("burn time", "s", re.compile(r"burn time\s+([-+]?\d+(?:\.\d+)?)\s*s\b", re.I)),
    ("time to extinction", "s", re.compile(r"time to extinction\s+([-+]?\d+(?:\.\d+)?)\s*s\b", re.I)),
    ("flame duration", "s", re.compile(r"flame duration\s+([-+]?\d+(?:\.\d+)?)\s*s\b", re.I)),
    # Unit read from the text; the compound is always the row's fuel (combustible column).
    ("burning rate", "", re.compile(r"burning rate(?: constant)?\s+([-+]?\d+(?:\.\d+)?)\s*" + _RATE_UNIT, re.I)),
    ("mass loss rate", "", re.compile(r"(?:mass|weight) loss rate\s+([-+]?\d+(?:\.\d+)?)\s*" + _RATE_UNIT, re.I)),
    ("extinction diameter", "mm", re.compile(r"visible flame extinction diameter\s+([-+]?\d+(?:\.\d+)?)\s*mm\b", re.I)),
    ("fuel rate", "mg/s", re.compile(r"fuel rate\s+([-+]?\d+(?:\.\d+)?)\s*mg/s\b", re.I)),
    ("spread rate", "mm/s", re.compile(r"(?:microgravity )?spread rate\s+([-+]?\d+(?:\.\d+)?)\s*mm/s\b", re.I)),
]


def _to_float(text: str) -> float | None:
    raw = str(text).strip().lower()
    if raw in {"", "n/a", "na", "none", "~"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _is_pct(unit: str) -> bool:
    return "%" in unit.lower() and "ppm" not in unit.lower()


def _pair(text: str, key: str) -> tuple[float | None, float | None, str | None]:
    match = _PAIR[key].search(text)
    if not match:
        return None, None, None
    start, end, unit = _to_float(match.group(1)), _to_float(match.group(2)), match.group(3).strip()
    return start, end, unit


def parse_mole_fractions(text: str) -> dict[str, float]:
    found: dict[str, float] = {}
    for block in _MOLE_FRACTIONS.findall(text):
        for m in _MF_PAIR.finditer(block):
            found[m.group(1).upper().replace("O2", "O2")] = float(m.group(2))
    # Normalise keys
    clean = {}
    for k, v in found.items():
        key = k.upper()
        if key in {"O2", "N2", "CO2", "HE"}:
            clean["He" if key == "HE" else key] = v
    return clean


def _diluent_label(fracs: dict[str, float]) -> str:
    parts = []
    for gas in ("CO2", "He", "N2"):
        if gas in fracs and fracs[gas] and fracs[gas] > 0:
            parts.append(f"{gas} {fracs[gas]:g}")
    return ", ".join(parts)


def parse_row_text(resultado: str, notas: str = "") -> dict:
    """Extract gas start/end values, diluent fractions and a coarse outcome flag."""
    text = f"{resultado}\n{notas}"
    out: dict = {
        "o2_start_pct": None,
        "o2_end_pct": None,
        "co2_start_pct": None,
        "co2_end_pct": None,
        "co2_start_ppm": None,
        "co2_end_ppm": None,
        "co_start_ppm": None,
        "co_end_ppm": None,
        "co2_unit": "",
        "co_unit": "",
        "x_o2": None,
        "x_n2": None,
        "x_co2": None,
        "x_he": None,
        "diluent": "",
        "outcome_not_listed": False,
        "burned": False,
        "extinguished": False,
        "no_ignition": False,
        "ignited": False,
        "cool_flame": False,
        "o2_delta_pct": None,
        "co2_delta_ppm": None,
        "co_delta_ppm": None,
        "co_co2_ratio": None,
        "result_metric": None,
        "result_metric_name": "",
        "result_metric_unit": "",
    }

    o2s, o2e, o2u = _pair(text, "o2")
    if o2u:
        if _is_pct(o2u):
            out["o2_start_pct"], out["o2_end_pct"] = o2s, o2e
        # mole-fraction style written as 0.21 without % is not produced by this pattern

    co2s, co2e, co2u = _pair(text, "co2")
    if co2u:
        out["co2_unit"] = co2u
        if _is_pct(co2u):
            out["co2_start_pct"], out["co2_end_pct"] = co2s, co2e
            if co2s is not None:
                out["co2_start_ppm"] = round(co2s * PCT_TO_PPM, 3)
            if co2e is not None:
                out["co2_end_ppm"] = round(co2e * PCT_TO_PPM, 3)
        else:
            out["co2_start_ppm"], out["co2_end_ppm"] = co2s, co2e

    cos, coe, cou = _pair(text, "co")
    if cou:
        out["co_unit"] = cou
        if _is_pct(cou):
            if cos is not None:
                out["co_start_ppm"] = round(cos * PCT_TO_PPM, 3)
            if coe is not None:
                out["co_end_ppm"] = round(coe * PCT_TO_PPM, 3)
        else:
            out["co_start_ppm"], out["co_end_ppm"] = cos, coe

    fracs = parse_mole_fractions(text)
    if fracs:
        out["x_o2"] = fracs.get("O2")
        out["x_n2"] = fracs.get("N2")
        out["x_co2"] = fracs.get("CO2")
        out["x_he"] = fracs.get("He")
        out["diluent"] = _diluent_label(fracs)
        if out["o2_start_pct"] is None and out["x_o2"] is not None:
            out["o2_start_pct"] = round(out["x_o2"] * 100, 4)

    xo2 = _XO2.search(text)
    if xo2 and out["o2_start_pct"] is None:
        start, end = float(xo2.group(1)), float(xo2.group(2))
        # Values in CFI-G are mole fractions (~0.2–0.85), not percents.
        if start <= 1.5 and end <= 1.5:
            out["o2_start_pct"] = round(start * 100, 4)
            out["o2_end_pct"] = round(end * 100, 4)
            out["x_o2"] = start
        else:
            out["o2_start_pct"], out["o2_end_pct"] = start, end

    for name, unit, pattern in METRIC_PATTERNS:
        m = pattern.search(text)
        if m:
            if not unit:  # unit captured from the text, never assumed
                unit = (m.group(2) if m.lastindex and m.lastindex >= 2 and m.group(2) else _NO_UNIT)
            out["result_metric"] = _to_float(m.group(1))
            out["result_metric_name"] = name
            out["result_metric_unit"] = unit
            break

    # Outcome flags come from resultado first. A "No ignition" note in the comments
    # must not override a stated hot ignition or a recorded burn time in resultado
    # (seen in CFI-G, where an igniter attempt is logged next to a later successful run).
    out["outcome_not_listed"] = bool(_MISSING.search(resultado) or _MISSING.search(text))

    def _flags(blob: str) -> tuple[bool, bool, bool, bool]:
        no_ign = bool(_NO_IGNITION.search(blob))
        sustained = bool(_SUSTAINED.search(blob))
        went_out = bool(_DID_EXTINGUISH.search(blob)) and not sustained and not no_ign
        flame_metric = out["result_metric_name"] in _FLAME_METRICS and (out["result_metric"] or 0) > 0
        # flame_metric is only taken from resultado (already parsed from the full text);
        # it is applied only when we are reading resultado, below.
        ignited = (not no_ign) and (
            sustained or went_out or bool(_DID_BURN.search(_NEGATED.sub(" ", blob))) or bool(_FLAME_RUN.search(blob))
        )
        return no_ign, sustained, went_out, ignited

    no_ign_r, sustained_r, went_out_r, ignited_r = _flags(resultado)
    flame_metric = out["result_metric_name"] in _FLAME_METRICS and (out["result_metric"] or 0) > 0
    if flame_metric and not no_ign_r:
        ignited_r = True
    no_ign_n, _, went_out_n, ignited_n = _flags(notas)
    if ignited_r or went_out_r or sustained_r:
        no_ignition, went_out, ignited = False, went_out_r, ignited_r or went_out_r
    else:
        no_ignition = no_ign_r or no_ign_n
        went_out = went_out_r or (went_out_n and not no_ignition)
        ignited = (not no_ignition) and (ignited_r or ignited_n or went_out)
    out["no_ignition"] = no_ignition
    out["ignited"] = ignited
    out["extinguished"] = went_out
    out["burned"] = ignited and not went_out
    out["cool_flame"] = bool(_COOL_FLAME.search(text))

    # Change over the test: what the fire consumed (O2) and produced (CO2, CO).
    def _delta(start, end):
        return None if start is None or end is None else round(end - start, 6)

    out["o2_delta_pct"] = _delta(out["o2_start_pct"], out["o2_end_pct"])
    out["co2_delta_ppm"] = _delta(out["co2_start_ppm"], out["co2_end_ppm"])
    out["co_delta_ppm"] = _delta(out["co_start_ppm"], out["co_end_ppm"])
    if (out["co2_delta_ppm"] or 0) > 0 and (out["co_delta_ppm"] or 0) >= 0 and out["co_delta_ppm"] is not None:
        out["co_co2_ratio"] = round(out["co_delta_ppm"] / out["co2_delta_ppm"], 5)

    return out


def enrich_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Add gas, diluent and outcome columns next to the original ones."""
    notas = df["notas"] if "notas" in df.columns else pd.Series("", index=df.index)
    parsed = [
        parse_row_text(r, n)
        for r, n in zip(df["resultado"].astype(str), notas.fillna("").astype(str))
    ]
    extra = pd.DataFrame(parsed, index=df.index)
    for col in extra.columns:
        df[col] = extra[col]
    return df


def display_gas(value, unit: str | None = None, lang: str = "en") -> str:
    """Format a gas reading, or the fixed disclaimer when the source is silent."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return t("unspecified", lang)
    if unit:
        return f"{round(float(value), 4):g} {unit}"
    return f"{round(float(value), 4):g}"
