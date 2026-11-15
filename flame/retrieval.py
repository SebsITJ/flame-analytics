"""Deterministic part of the engine: read conditions, rank rows, compute facts.

Nothing in this module calls the LLM. Every number shown to the user or passed
to Gemini is computed here with pandas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from . import config
from .classify import Classification, Subject, classify_question, fuel_matches, normalize_fuel, normalize_text
from .i18n import t, terms

_NUM = r"(\d+(?:[.,]\d+)?)"
# (?<![a-z]) keeps the "o2" inside "CO2" from being read as oxygen.
_O2 = r"(?<![a-z])(?:o2|o₂|oxygen|oxígeno|oxigeno)"
# A percentage that belongs to another gas ("oxygen with 15% CO2") is not the oxygen level.
_OTHER_GAS = r"(?!\s*(?:of\s+|de\s+)?(?:co2|co₂|n2|n₂|carbon|di[oó]xido|nitrogen|nitr[oó]geno|helium|helio|he\b|argon|ar\b))"
_OXYGEN_PATTERNS = [
    re.compile(rf"{_NUM}\s*(?:%|percent|vol\s*%)\s*(?:of\s+|de\s+)?{_O2}", re.IGNORECASE),
    re.compile(rf"{_O2}[^0-9%]{{0,30}}?{_NUM}\s*(?:%|percent){_OTHER_GAS}", re.IGNORECASE),
]
_PRESSURE = re.compile(rf"{_NUM}\s*(psia|psi|kpa|mbar|bar|atm|torr|mmhg|pa)\b", re.IGNORECASE)

# Kept for compatibility; phase detection is done in classify.py.
PHASE_WORDS = {
    "extinguish": ["extinguish", "suppress", "put out", "extinction", "extinguisher", "quench",
                   "co2", "helium", "dilution", "water mist", "apagar", "extinguir"],
    "detect": ["detect", "smoke", "alarm", "sensor", "aerosol", "particle", "detector", "detectar", "humo"],
    "prevent": ["prevent", "ignit", "flammab", "flame spread", "material", "prevenir", "inflamab"],
}

_STOPWORDS = set(
    "a an the of in on at to for and or with without how what which when where why who do does did "
    "is are was were be been can could should would i we you it this that these those my our "
    "fire flame flames spacecraft space experiment experiments data database tell me about "
    "oxygen pressure percent atm psi kpa test tests tested used using happened happen result results "
    "before after during visible there their them than then also "
    "el la los las un una de del en por con para como que se al lo su sus "
    "fuego llama llamas oxigeno presion".split()
)

# Spanish/English function words that the accent-folded tokenizer now keeps (review #1).
_STOPWORDS |= set(
    "cual cuales cuanto cuanta cuantos tiempo donde cuando sobre entre mejor peor mas menos este esta estos "
    "estas desde hasta hacia porque pero tambien muy hay tiene tienen puede pueden debe deben ser estar "
    "will would much many more most less long role play".split()
)
# Roots of phase / outcome words. As keywords they were matched as substrings of `resultado`, so a
# question saying "extinguish" pulled up rows that say "flame extinguished" and biased the N/8 count
# (and Spanish never matched the English text). Phase is scored by its own component instead.
_NOT_KEYWORDS = (
    "extin", "exting", "apag", "burn", "quem", "arde", "ardi", "ignit", "ignic", "encend", "prevent",
    "preven", "evit", "detect", "flam", "llam", "combust", "suppress", "supres", "smold", "sofoc",
    "put", "self-ext", "autoext",
)


def clean_keywords(words) -> list[str]:
    """Accent-folded keywords without stopwords or phase/outcome roots."""
    out = []
    for w in words:
        w = normalize_text(str(w)).strip()
        if len(w) >= 4 and w not in _STOPWORDS and not w.startswith(_NOT_KEYWORDS):
            out.append(w)
    return list(dict.fromkeys(out))


def microgravity_only(df: pd.DataFrame) -> pd.DataFrame:
    """Rows whose gravity column says microgravity (all rows when the column is missing)."""
    if df is None or "gravedad" not in df.columns:
        return df
    return df[df["gravedad"].astype(str).str.contains(config.MICROGRAVITY_PATTERN, case=False, na=False)]


COMPONENT_LABELS = {
    "oxygen": "oxygen",
    "pressure": "pressure",
    "fuel": "fuel",
    "phase": "phase",
    "keywords": "keywords",
    "subject": "subject",
}

# How a row shows that it MEASURED a detection variable or USED a suppression agent.
# Each entry: ([(enriched column, threshold)], pattern searched in resultado + notas).
# Threshold None = any recorded value counts (0 ppm is still a reading);
# a number = the value must exceed it (a mole fraction of 0 means the gas was absent).
_SMOKE = r"smoke|soot|aerosol|particle|particulate"
_MEASURED: dict[str, tuple[list[tuple[str, float | None]], str]] = {
    "CO": ([("co_start_ppm", None), ("co_end_ppm", None)], r"carbon monoxide"),
    "CO2": ([("co2_start_ppm", None), ("co2_end_ppm", None)], r"CO2 (?:produced|generated|rise)"),
    "O2 depletion": ([("o2_end_pct", None)], r"XO2 before/after"),
    "smoke": ([], _SMOKE),
    "particles": ([], _SMOKE),
    "temperature": ([], r"temperature|\d\s*(?:°C|K)\b"),
    "HCN": ([], r"\bHCN\b"),
    "HCl": ([], r"\bHCl\b"),
    "HF": ([], r"\bHF\b"),
    "acid gases": ([], r"\bH(?:CN|Cl|F)\b|acid gas"),
    "mass loss rate": ([], r"(?:mass|weight) loss|burning rate|fuel rate"),
    "flame radiation": ([], r"radiat|radiometer"),
}
_AGENT: dict[str, tuple[list[tuple[str, float | None]], str]] = {
    "CO2": ([("x_co2", 0.0)], r"CO2 (?:diluent|dilution|extinguish)|carbon dioxide"),
    "He": ([("x_he", 0.0)], r"\bhelium\b"),
    "N2": ([("x_n2", 0.79)], r"\bnitrogen (?:dilut|purge|flood)|N2 (?:dilut|purge|flood)"),  # more N2 than air
    "Ar": ([], r"\bargon\b"),
    "water mist": ([], r"water mist|water spray|\bmist\b"),
    "Halon": ([], r"halon"),
    "foam": ([], r"\bfoam\b"),
    "portable extinguisher": ([], r"extinguisher|\bPFE\b"),
    "ventilation shutdown": ([], r"flow (?:off|stopped|shut)|ventilation (?:shut|off)|fan(?:s)? (?:off|stopped)"),
    "O2 cutoff": ([], r"oxygen (?:reduced|lowered|cut|shut)|o2 cutoff|cut(?:ting)? the oxygen"),
    "depressurization": ([], r"depressur"),
    "diluent (unspecified)": ([("x_co2", 0.0), ("x_he", 0.0), ("x_n2", 0.79)], r"diluent|dilution"),
}


def _subject_specs(cond: "Conditions") -> list[tuple[str, list, str]]:
    """Subject terms a row can be checked against, by role: measured variable or agent used."""
    subj = cond.subject
    specs: dict[str, tuple[str, list, str]] = {}
    if subj is not None and cond.phase != "extinguish":
        for d in subj.detection_vars:
            if d in _MEASURED:
                specs.setdefault(f"{d} (measured)", (d, *_MEASURED[d]))
    if subj is not None and cond.phase != "detect":
        for a in subj.inhibitors:
            if a in _AGENT:
                specs.setdefault(f"{a} (agent)", (a, *_AGENT[a]))
    return list(specs.values())


def subject_items(cond: "Conditions", lang: str = "en") -> list[str]:
    items = list(dict.fromkeys(label for label, _, _ in _subject_specs(cond)))
    return terms(items, lang) if lang != "en" else items


def subject_match(df: pd.DataFrame, specs: list[tuple[str, list, str]]) -> pd.Series:
    """Share of the named subject terms that each row records (0–1)."""
    text = df["resultado"].astype(str)
    if "notas" in df.columns:
        text = text + " " + df["notas"].fillna("").astype(str)
    score = pd.Series(0.0, index=df.index)
    for _, cols, pattern in specs:
        hit = text.str.contains(pattern, case=False, regex=True)
        for col, above in cols:
            if col in df.columns:
                value = pd.to_numeric(df[col], errors="coerce")
                hit = hit | (value.notna() if above is None else (value > above))
        score += hit.astype(float)
    return score / len(specs)


def _tie_band(frame: pd.DataFrame) -> pd.DataFrame:
    eligible = frame[frame["relevance"] >= config.MIN_SCORE]
    if eligible.empty:
        return eligible
    return eligible[eligible["relevance"] >= eligible["relevance"].iloc[0] - config.TIE_BAND]


def tied_count(frame: pd.DataFrame) -> int:
    """How many equally relevant rows the top-k was sampled from (0 when they all fit)."""
    band = _tie_band(frame)
    return len(band) if len(band) > config.TOP_K else 0


def _spaced(group: pd.DataFrame, q: int) -> pd.DataFrame:
    n = len(group)
    if q >= n:
        return group
    if q == 1:
        return group.iloc[[0]]
    return group.iloc[sorted({round(j * (n - 1) / (q - 1)) for j in range(q)})]


def _top(frame: pd.DataFrame) -> pd.DataFrame:
    """Top rows above the minimum score. When more rows are tied at the top than fit, take an evenly
    spaced sample of the tied rows, spread across experiments, instead of the first rows of the CSV
    (review #1: file order made the N/8 depend on how the table happens to be sorted)."""
    k = config.TOP_K
    eligible = frame[frame["relevance"] >= config.MIN_SCORE]
    if len(eligible) <= k:
        return eligible
    band = _tie_band(frame)
    if len(band) <= k:
        return eligible.head(k)
    groups = [g for _, g in band.groupby("experimento", sort=False)]
    quota = [0] * len(groups)
    left = k
    while left:
        moved = False
        for i, g in enumerate(groups):
            if left and quota[i] < len(g):
                quota[i] += 1
                left -= 1
                moved = True
        if not moved:
            break
    picked = pd.concat([_spaced(g, q) for g, q in zip(groups, quota) if q])
    return picked.sort_values(["relevance", "info"], ascending=False, kind="stable")


@dataclass
class Conditions:
    oxygen: float | None = None  # % O2
    pressure_atm: float | None = None
    pressure_text: str | None = None  # as written in the question, e.g. "10.2 psi"
    fuel: str | None = None
    phase: str | None = None
    keywords: list[str] = field(default_factory=list)
    extracted_by: str = "rules"
    notes: list[str] = field(default_factory=list)
    phase_confidence: float = 0.0
    matched_keywords: list[str] = field(default_factory=list)
    subject: Subject = field(default_factory=Subject)
    classification: Classification | None = None
    material_category: str | None = None  # e.g. "cabin materials"
    comparison_metric: str | None = None  # key of config.COMPARISON_METRICS

    def is_empty(self) -> bool:
        return not any([self.oxygen is not None, self.pressure_atm, self.fuel, self.phase, self.keywords])


@dataclass
class Retrieval:
    hits: pd.DataFrame  # rows sent to Gemini, ranked
    ranked: pd.DataFrame  # every row with its score
    gaps: list[str]  # stated conditions with no matching data
    facts: dict  # numbers computed with pandas
    weight_used: dict = field(default_factory=dict)  # renormalized weights actually applied
    tied: int = 0  # >0: the hits are a spaced sample of this many equally relevant rows


# ---------------------------------------------------------------------------
# Reading conditions from the question (rules; Gemini output is checked against this)
# ---------------------------------------------------------------------------

def _num(text: str) -> float:
    return float(text.replace(",", "."))


def numbers_in_question(question: str) -> set[float]:
    return {_num(n) for n in re.findall(r"\d+(?:[.,]\d+)?", question)}


_CABIN_MATERIALS = re.compile(
    r"\b(?:cabin|spacecraft)\s+materials?\b|\bmateriales?\s+(?:de\s+(?:la\s+)?)?(?:cabina|nave)\b", re.I)
_METRIC_PATTERNS = (  # first match wins; EN + ES
    ("flame_spread_rate", re.compile(
        r"\b(?:burns?\s+fast(?:est|er)|flame\s+spread(?:\s+rate)?|spread\s+rate|"
        r"(?:se\s+)?quema(?:n)?\s+m[aá]s\s+r[aá]pido|velocidad\s+de\s+propagaci[oó]n|propagaci[oó]n\s+de\s+(?:la\s+)?llama)", re.I)),
    ("flame_duration", re.compile(
        r"\b(?:flame\s+duration|burn(?:ing)?\s+duration|burn\s+time|how\s+long\b.*\bburns?\b|"
        r"duraci[oó]n\s+de\s+(?:la\s+)?llama|tiempo\s+de\s+(?:combusti[oó]n|quemado)|cu[aá]nto\s+(?:tiempo\s+)?dura|"
        r"cu[aá]nto\s+(?:tiempo\s+)?(?:arde|arden|se\s+quema|se\s+queman)|tiempo\s+(?:que\s+)?arde)", re.I)),
    ("burning_rate", re.compile(
        r"\b(?:burning\s+rate|burn\s+rate|(?:tasa|velocidad)\s+de\s+combusti[oó]n)", re.I)),
    ("fuel_consumption_rate", re.compile(
        r"\b(?:fuel\s+(?:consumption\s+)?rate|fuel\s+consumption|"
        r"(?:tasa|velocidad)\s+de\s+consumo|consumo\s+de\s+combustible)", re.I)),
    ("mass_loss_rate", re.compile(
        r"\b(?:mass\s+loss(?:\s+rates?)?|rate\s+of\s+mass\s+loss|p[eé]rdida\s+de\s+masa)", re.I)),
)


def detect_comparison(question: str) -> tuple[str | None, str | None]:
    """(material_category, comparison_metric) named in the question, or None."""
    material = "cabin materials" if _CABIN_MATERIALS.search(question) else None
    metric = next((key for key, pattern in _METRIC_PATTERNS if pattern.search(question)), None)
    return material, metric


_BURNING_RATE_TEXT = r"burning rate(?: constant)?\s+(?P<value>[-+]?\d+(?:\.\d+)?)(?:\s*\(source unit label '(?P<unit>[^']*)'\))?"


def metric_rows(df: pd.DataFrame, metric: str | None, fuel: str | None = None) -> pd.DataFrame:
    """Microgravity rows with a numeric value for ``metric`` (optionally one fuel). result_metric is numeric."""
    spec = config.COMPARISON_METRICS.get(metric or "")
    need = {"result_metric", "result_metric_name", "result_metric_unit", "gravedad", "combustible"}
    if spec is None or not need.issubset(df.columns):
        return df.iloc[0:0]
    df = microgravity_only(df)
    if spec.get("from_text"):
        found = df["resultado"].astype(str).str.extract(_BURNING_RATE_TEXT)
        mask = found["value"].notna()
        out = df[mask].copy()
        out["result_metric"] = pd.to_numeric(found.loc[mask, "value"])
        out["result_metric_name"] = spec["names"][0]
        out["result_metric_unit"] = found.loc[mask, "unit"].map(
            lambda u: f"source unit label '{u}'" if isinstance(u, str) and u else "unit not stated in source")
    else:
        values = pd.to_numeric(df["result_metric"], errors="coerce")
        mask = (
            df["result_metric_name"].astype(str).isin(spec["names"])
            & (df["result_metric_unit"].astype(str) == spec["unit"])
            & values.notna()
        )
        out = df[mask].copy()
        out["result_metric"] = values[mask]
    if fuel:
        out = out[out["combustible"].map(lambda f: fuel_matches(str(f), fuel))]
    return out


def filter_by_oxygen(rows: pd.DataFrame, oxygen: float | None,
                     tolerance: float | None = None) -> tuple[pd.DataFrame, str, float | None]:
    """Narrow metric rows to the O2 asked in the question (used by the chart; no number is changed).

    Returns (rows, mode, level): mode "all" (no O2 asked, or no row has numeric O2), "band" (rows within
    ±tolerance of the asked O2) or "nearest" (nothing in the band: rows within ±tolerance of the closest
    O2 level that was tested; level is that O2 value).
    """
    tol = config.METRIC_CHART_O2_TOLERANCE if tolerance is None else tolerance
    if oxygen is None or rows.empty or "oxigeno_num" not in rows.columns:
        return rows, "all", None
    o2 = pd.to_numeric(rows["oxigeno_num"], errors="coerce")
    if o2.notna().sum() == 0:
        return rows, "all", None
    dist = (o2 - float(oxygen)).abs()
    band = rows[dist <= tol + 1e-9]
    if not band.empty:
        return band, "band", float(oxygen)
    nearest = float(o2[dist == dist.min()].iloc[0])
    return rows[(o2 - nearest).abs() <= tol + 1e-9], "nearest", nearest


def parse_rules(question: str, known_fuels: list[str], lang: str = "en") -> Conditions:
    cond = Conditions(extracted_by="rules")
    q = question.lower()

    for pattern in _OXYGEN_PATTERNS:
        match = pattern.search(question)
        if match:
            cond.oxygen = _num(match.group(1))
            break

    match = _PRESSURE.search(question)
    if match:
        value, unit = _num(match.group(1)), match.group(2).lower()
        cond.pressure_atm = value * config.TO_ATM[unit]
        cond.pressure_text = f"{match.group(1)} {match.group(2)}"

    clf = classify_question(question, known_fuels, lang)
    cond.classification = clf
    cond.subject = clf.subject
    cond.fuel = clf.subject.fuel
    cond.phase = clf.phase
    cond.phase_confidence = clf.confidence
    cond.matched_keywords = list(clf.matched_keywords)
    cond.material_category, cond.comparison_metric = detect_comparison(question)

    tokens = re.findall(r"[a-z][a-z0-9\-]{3,}", normalize_text(question))
    cond.keywords = clean_keywords(tokens)[:6]
    return cond


def merge_conditions(question: str, rules: Conditions, llm: dict | None, lang: str = "en") -> Conditions:
    """Combine Gemini's reading with the rule-based one.

    Numbers: the literal reading from the question wins. A number from Gemini is
    accepted only if it is written in the question, so the model cannot slip in
    values it inferred. Fuel, phase and keywords: Gemini first, rules fill gaps.
    An out-of-scope classification from the rules is kept.
    """
    if not llm:
        return rules

    cond = Conditions(extracted_by="gemini + rules")
    allowed = numbers_in_question(question)

    def accept(value) -> float | None:
        if value is None:
            return None
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        if any(abs(v - a) < 1e-9 for a in allowed):
            return v
        cond.notes.append(t("note.llm_number", lang, value=value))
        return None

    cond.oxygen = rules.oxygen if rules.oxygen is not None else accept(llm.get("oxygen_percent"))

    if rules.pressure_atm is not None:
        cond.pressure_atm, cond.pressure_text = rules.pressure_atm, rules.pressure_text
    else:
        value = accept(llm.get("pressure_value"))
        unit = str(llm.get("pressure_unit") or "").lower().strip()
        if value is not None and unit in config.TO_ATM:
            cond.pressure_atm = value * config.TO_ATM[unit]
            cond.pressure_text = f"{value:g} {unit}"
        elif value is not None:
            cond.notes.append(t("note.pressure_unit", lang, value=f"{value:g}"))

    fuel = (llm.get("fuel") or "").strip()
    cond.fuel = fuel or rules.fuel

    if rules.phase == "out_of_scope":
        cond.phase = "out_of_scope"
    else:
        phase = str(llm.get("phase") or "").strip().lower()
        cond.phase = phase if phase in config.PHASES else rules.phase

    kws = clean_keywords(k for k in (llm.get("keywords") or []) if str(k).strip())
    cond.keywords = list(dict.fromkeys(kws + rules.keywords))[:8]
    # The confidence belongs to the rules' phase: show it only when Gemini picked the same phase (review #7).
    cond.phase_confidence = rules.phase_confidence if cond.phase == rules.phase else 0.0
    cond.matched_keywords = list(rules.matched_keywords)
    cond.subject = rules.subject
    cond.classification = rules.classification
    cond.material_category = rules.material_category
    cond.comparison_metric = rules.comparison_metric
    return cond


# ---------------------------------------------------------------------------
# Ranking and computed facts
# ---------------------------------------------------------------------------

def _fmt(x: float | None, digits: int = 3) -> str:
    return "n/a" if x is None or pd.isna(x) else f"{round(float(x), digits):g}"


def _span(series: pd.Series) -> str:
    lo, hi = _fmt(series.min()), _fmt(series.max())
    return lo if lo == hi else f"{lo}–{hi}"


def _breakdown_text(row: pd.Series, weights: dict[str, float], lang: str = "en") -> str:
    bits = []
    for key in COMPONENT_LABELS:
        label = t(f"component.{key}", lang)
        match_col, score_col = f"match_{key}", f"score_{key}"
        if match_col in row.index and pd.notna(row[match_col]):
            w = weights.get(key, 0.0)
            bits.append(f"{label} {float(row[match_col]):.2f} × {w:.2f} = {float(row[score_col]):.3f}")
    total = float(row["relevance_raw"]) if "relevance_raw" in row.index else float(row["relevance"])
    text = "; ".join(bits) + f" → {total:.3f}"
    if bool(row.get("outcome_not_listed")):
        text += t("breakdown.outcome", lang, factor=f"{config.OUTCOME_MISSING_FACTOR:g}", value=f"{float(row['relevance']):.3f}")
    return text


def rank(df: pd.DataFrame, cond: Conditions, lang: str = "en") -> Retrieval:
    parts = pd.DataFrame(index=df.index)
    gaps: list[str] = []

    scope = df
    if cond.fuel:
        fuel_scope = df[df["combustible"].map(lambda f: fuel_matches(str(f), cond.fuel))]
        if not fuel_scope.empty:
            scope = fuel_scope

    if cond.oxygen is not None:
        diff = (df["oxigeno_num"] - cond.oxygen).abs()
        # 1 at an exact match, 0.5 at the tolerance edge, 0 at twice the tolerance
        parts["oxygen"] = (1 - diff / (2 * config.OXYGEN_TOLERANCE)).clip(lower=0).fillna(0)
        scope_diff = (scope["oxigeno_num"] - cond.oxygen).abs()
        if not (scope_diff <= config.OXYGEN_TOLERANCE).any():
            o2 = scope["oxigeno_num"].dropna()
            if o2.empty:
                gaps.append(t("gap.no_o2_values", lang))
            else:
                closest = o2.iloc[(o2 - cond.oxygen).abs().argsort().iloc[0]]
                gaps.append(
                    t("gap.o2", lang, tol=_fmt(config.OXYGEN_TOLERANCE), o2=_fmt(cond.oxygen),
                      span=_span(o2), closest=_fmt(closest))
                )

    if cond.pressure_atm is not None:
        rel = (df["presion_num"] - cond.pressure_atm).abs() / cond.pressure_atm
        parts["pressure"] = (1 - rel / (2 * config.PRESSURE_TOLERANCE)).clip(lower=0).fillna(0)
        scope_rel = (scope["presion_num"] - cond.pressure_atm).abs() / cond.pressure_atm
        if not (scope_rel <= config.PRESSURE_TOLERANCE).any():
            p = scope["presion_num"].dropna()
            asked = f"{cond.pressure_text} ({_fmt(cond.pressure_atm)} atm)" if cond.pressure_text else f"{_fmt(cond.pressure_atm)} atm"
            span = f"{_span(p)} atm" if not p.empty else t("gap.no_numeric", lang)
            gaps.append(t("gap.pressure", lang, tol=f"{config.PRESSURE_TOLERANCE:.0%}", asked=asked, span=span))

    if cond.fuel:
        parts["fuel"] = df["combustible"].map(lambda f: 1.0 if fuel_matches(f, cond.fuel) else 0.0)
        if parts["fuel"].sum() == 0:
            fuels = ", ".join(sorted(df["combustible"].unique()))
            gaps.append(t("gap.fuel", lang, fuel=cond.fuel, fuels=fuels))
    elif cond.subject is not None and cond.subject.material:
        gaps.append(t("gap.material", lang, material=cond.subject.material))

    specs = _subject_specs(cond)
    if specs:
        parts["subject"] = subject_match(df, specs)
        if parts["subject"].sum() == 0:
            gaps.append(t("gap.subject", lang, items=", ".join(subject_items(cond, lang))))

    if cond.phase and cond.phase in config.PHASES:
        parts["phase"] = (df["fase"] == cond.phase).astype(float)

    if cond.keywords and config.KEYWORDS_IN_RELEVANCE:
        text = (df["experimento"] + " " + df["combustible"] + " " + df["resultado"]).str.lower()
        parts["keywords"] = text.map(lambda t: sum(k in t for k in cond.keywords) / len(cond.keywords))

    ranked = df.copy()
    weight_used: dict[str, float] = {}
    if parts.columns.empty:
        ranked["relevance_raw"] = 0.0
        ranked["relevance"] = 0.0
    else:
        weights = {k: config.WEIGHTS[k] for k in parts.columns}
        total = sum(weights.values())
        weight_used = {k: w / total for k, w in weights.items()}
        ranked["relevance_raw"] = sum(parts[k] * w for k, w in weight_used.items())
        for k in parts.columns:
            ranked[f"match_{k}"] = parts[k].round(2)
            ranked[f"score_{k}"] = (parts[k] * weight_used[k]).round(3)
        ranked["relevance_raw"] = ranked["relevance_raw"].round(3)
        ranked["relevance"] = ranked["relevance_raw"]

    if "outcome_not_listed" not in ranked.columns:
        ranked["outcome_not_listed"] = False
    else:
        ranked["outcome_not_listed"] = ranked["outcome_not_listed"].fillna(False).astype(bool)

    ranked.loc[ranked["outcome_not_listed"], "relevance"] = (
        ranked.loc[ranked["outcome_not_listed"], "relevance"] * config.OUTCOME_MISSING_FACTOR
    ).round(3)
    ranked["relevance"] = ranked["relevance"].round(3)
    ranked["relevance_breakdown"] = ranked.apply(lambda r: _breakdown_text(r, weight_used, lang), axis=1)
    # Tie-break: prefer rows that carry more recorded values (O2, pressure, metric, gas readings).
    info_cols = [c for c in ("oxigeno_num", "presion_num", "result_metric", "o2_end_pct", "co2_end_ppm", "co_end_ppm") if c in ranked.columns]
    ranked["info"] = ranked[info_cols].notna().sum(axis=1)
    ranked = ranked.sort_values(["relevance", "info"], ascending=False, kind="stable")

    hits = _top(ranked)
    if cond.fuel:
        is_fuel = ranked["combustible"].map(lambda f: fuel_matches(str(f), cond.fuel))
        fuel_ranked = ranked[is_fuel]
        if not fuel_ranked.empty:
            hits = _top(fuel_ranked)
            if hits.empty:
                hits = fuel_ranked.head(config.TOP_K)
                gaps.append(t("gap.min_relevance_fuel", lang, fuel=cond.fuel, min=f"{config.MIN_SCORE:g}"))
    if hits.empty and not cond.is_empty():
        gaps.append(t("gap.min_relevance", lang, min=f"{config.MIN_SCORE:g}"))
    if cond.is_empty():
        gaps.append(t("gap.empty", lang))

    tied = 0
    if not hits.empty:
        source = ranked
        if cond.fuel:
            fr = ranked[ranked["combustible"].map(lambda f: fuel_matches(str(f), cond.fuel))]
            source = fr if not fr.empty else ranked
        tied = tied_count(source)
    return Retrieval(hits=hits, ranked=ranked, gaps=gaps, facts=compute_facts(hits, cond), weight_used=weight_used,
                     tied=tied)


def compute_facts(hits: pd.DataFrame, cond: Conditions) -> dict:
    facts: dict = {"rows_retrieved": int(len(hits))}
    if hits.empty:
        return facts
    facts["distinct_experiments"] = int(hits["experimento"].nunique())
    o2, p = hits["oxigeno_num"].dropna(), hits["presion_num"].dropna()
    if not o2.empty:
        facts["oxygen_range_pct"] = _span(o2)
    if not p.empty:
        facts["pressure_range_atm"] = _span(p)
    facts["rows_per_phase"] = {k: int(v) for k, v in hits["fase"].value_counts().items()}
    facts["simulated_rows"] = int(hits["simulated"].sum())
    if "outcome_not_listed" in hits.columns:
        facts["rows_with_outcome_not_listed"] = int(hits["outcome_not_listed"].sum())

    full = pd.Series(True, index=hits.index)
    if cond.oxygen is not None:
        full &= (hits["oxigeno_num"] - cond.oxygen).abs() <= config.OXYGEN_TOLERANCE
    if cond.pressure_atm is not None:
        full &= ((hits["presion_num"] - cond.pressure_atm).abs() / cond.pressure_atm) <= config.PRESSURE_TOLERANCE
    if cond.fuel:
        full &= hits["combustible"].map(lambda f: fuel_matches(f, cond.fuel))
    facts["rows_matching_all_stated_conditions"] = int(full.sum())
    if cond.pressure_atm is not None:
        facts["requested_pressure_atm"] = _fmt(cond.pressure_atm)
    return facts
