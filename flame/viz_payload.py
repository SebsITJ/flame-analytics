"""Data for the two visual stages of the Assistant tab, built from what the engine already produced.

* ``build_animation_payload``  JSON-safe dict for the mission-control animation (stage 2,
  ``flame.animation.build_mission_html``).
* ``build_dashboard_view``     JSON-safe dict for the one-screen result dashboard (stage 3,
  ``flame.dashboard``).

Nothing here ranks, filters or computes physics: every number is read from the table (``df``) or from the
``Result`` returned by ``flame.pipeline.answer_question``. The only derived figures are counts of rows
(how many rows have a numeric O2, how many share the fuel of the question, how many of the top rows record
an extinction...), and they are counted with the same columns the engine uses for its own text.

Animation payload (all keys always present):

    version      1
    lang         "en" / "es"
    state        "prevent" / "detect" / "extinguish" / "unclear" / "out_of_scope"
    mode         "scatter"  top rows have numeric O2: cloud + question point + colour flip
                 "bars"     top rows have no numeric O2 (typical for detect): bars of matched variables
                 "empty"    in scope, but no row reached the minimum relevance
                 "scope"    out of scope: the question is not classified into a bin, no data scene
    question     {"text", "segments": [{"t": text, "k": kind or None}, ...]}
                 kinds: "phase", "fuel", "o2", "pressure", "agent", "detection"
    detected     {"phase", "phase_label", "confidence", "keywords", "fuel", "o2", "pressure_atm",
                  "pressure_text", "agents", "detection", "readouts": [{"k", "label", "value"}, ...]}
    phases       [{"key", "label", "color", "n"}, ...] rows per phase in the whole table
    cloud        {"x_domain", "y_domain", "points": [[o2, pressure|None, phase_index, in_subset], ...],
                  "n_total", "n_plotted", "n_no_o2", "n_no_pressure", "sampled"}
    funnel       [{"n", "label"}, ...] total -> subset -> top-k ("{n}" in a label is filled by the animation)
    subset       {"kind", "n", "fuel", "experiments", "phase"}
    topk         [{"id", "o2", "p", "experiment", "fuel", "phase", "relevance", "status"}, ...]
                 status: "extinguished" / "burned" / "other", or "reading" / "none" for detect
    verdict      {"kind", "n", "k", "counts": {...}, "top_relevance"}
    bars         [{"group", "label", "value", "max", "text"}, ...]  (bars mode; empty otherwise)
    qpoint       {"o2", "p"} when the question states O2; {"o2", "p", "estimated": True, "n"} (median of the
                 retrieved rows, drawn hollow) when it does not; None when no retrieved row has a numeric O2
    colors       hex colours used by the animation
    labels       every UI string the animation shows, already in ``lang``
    auto_seconds seconds until Streamlit moves on by itself (0 = no countdown shown)
"""

from __future__ import annotations

import math
import re
import unicodedata
from difflib import SequenceMatcher

import pandas as pd

from . import config
from .i18n import normalize_lang, phase_name, t, term

VERSION = 1
MAX_QUESTION_CHARS = 220
MAX_POINTS = 6000  # cloud points sent to the browser; larger tables are thinned evenly (subset rows are kept)
MAX_EXPERIMENTS_IN_LABEL = 2

SEGMENT_KINDS = ("phase", "fuel", "o2", "pressure", "agent", "detection")
# Later kinds win when two readings claim the same characters ("helio" is a keyword and an agent).
_KIND_PRIORITY = ("phase", "detection", "agent", "fuel", "pressure", "o2")

GAS_COLUMNS = (("O2", "o2_delta_pct"), ("CO2", "co2_delta_ppm"), ("CO", "co_delta_ppm"))

# Other ways a question may write a canonical engine label. Only used to highlight words of the question.
_ALIASES = {
    "CO2": ("co2", "carbon dioxide", "dioxido de carbono", "anhidrido carbonico"),
    "He": ("helium", "helio"),
    "N2": ("n2", "nitrogen", "nitrogeno"),
    "Ar": ("argon",),
    "CO": ("co", "carbon monoxide", "monoxido de carbono"),
    "smoke": ("smoke", "humo"),
    "methanol": ("metanol",),
    "ethanol": ("etanol",),
}

STATUS_COLORS = {
    "extinguished": config.PHASE_COLORS["extinguish"],
    "burned": config.PHASE_COLORS["detect"],
    "reading": config.TELEMETRY_COLOR,
    "other": "#8b93a7",
    "none": "#8b93a7",
}
UI_COLORS = {"accent": config.ACCENT_COLOR, "telemetry": config.TELEMETRY_COLOR, "question": config.QUESTION_COLOR,
             "muted": "#8b93a7"}

_DOI = re.compile(r"10\.\d{4,9}/[^\s,;\"'<>\]\)]+")
_ROW_REF = re.compile(r"\[(R\d+)\]")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _get(obj, name: str, default=None):
    """Attribute or dict key, whichever ``obj`` has."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _num(value, digits: int = 4):
    """Plain float, or None for missing / NaN / non-numeric."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, digits)


def _flag(value) -> bool:
    try:
        return bool(value) and not (isinstance(value, float) and math.isnan(value))
    except (TypeError, ValueError):
        return False


def _clean(value):
    """Make a nested structure JSON-safe: no NaN, no numpy / pandas scalars."""
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_clean(v) for v in value]
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if hasattr(value, "item"):  # numpy scalar
        try:
            return _clean(value.item())
        except (TypeError, ValueError):
            return str(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def fold(text: str) -> str:
    """Lowercase, accent-free copy with the SAME length as ``text`` (so character positions still match)."""
    out = []
    for ch in str(text):
        base = unicodedata.normalize("NFKD", ch)
        first = next((c for c in base if not unicodedata.combining(c)), ch).lower()
        out.append(first if len(first) == 1 else ch.lower()[:1] or ch)
    return "".join(out)


def _short(question: str) -> str:
    text = re.sub(r"\s+", " ", str(question or "")).strip()
    return text if len(text) <= MAX_QUESTION_CHARS else text[: MAX_QUESTION_CHARS - 1].rstrip() + "…"


def _names(values) -> list[str]:
    return [str(v) for v in (values or []) if str(v).strip()]


def result_state(result) -> str:
    """"prevent" / "detect" / "extinguish" / "unclear" / "out_of_scope" for a pipeline Result."""
    cond = _get(result, "conditions")
    clf = _get(result, "classification") or _get(cond, "classification")
    phase = _get(cond, "phase") or _get(clf, "phase")
    if _flag(_get(clf, "out_of_scope")) or phase == "out_of_scope":
        return "out_of_scope"
    return str(phase) if phase in config.PHASES else "unclear"


def _hits(result) -> pd.DataFrame:
    hits = _get(_get(result, "retrieval"), "hits")
    return hits if isinstance(hits, pd.DataFrame) else pd.DataFrame()


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    """Column ``name`` or an all-missing column, so optional enrichment columns never raise."""
    if name in frame.columns:
        return frame[name]
    return pd.Series([None] * len(frame), index=frame.index, dtype=object)


def _bool_column(frame: pd.DataFrame, name: str) -> pd.Series:
    return _column(frame, name).map(_flag).astype(bool)


# ---------------------------------------------------------------------------
# Question -> highlighted segments
# ---------------------------------------------------------------------------

def _candidates(label: str) -> set[str]:
    """Folded spellings under which a canonical label may appear in a question (EN and ES)."""
    out = {fold(label), fold(term(label, "en")), fold(term(label, "es"))}
    out.update(fold(a) for a in _ALIASES.get(label, ()))
    return {c.strip() for c in out if len(c.strip()) >= 2 and c.strip() != "he"}  # "he" is an English word


def _mark(kinds: list, folded: str, needle: str, kind: str, *, prefix: bool = False) -> None:
    """Tag every whole-word occurrence of ``needle`` (``prefix=True``: the word may continue after it)."""
    if not needle:
        return
    tail = r"[^\W_]*" if prefix else r"(?![^\W_])"
    for m in re.finditer(r"(?<![^\W_])" + re.escape(needle) + tail, folded):
        for i in range(m.start(), m.end()):
            kinds[i] = kind


def _mark_fuel(kinds: list, folded: str, fuel: str) -> None:
    for cand in _candidates(fuel):
        _mark(kinds, folded, cand, "fuel")
    fuel_words = [w for w in _WORD.findall(fold(fuel)) if len(w) >= 4]
    for cand in fuel_words:
        _mark(kinds, folded, cand, "fuel")
    # "metanol" for "methanol", "heptano" for "n-heptane": same word, other language.
    for m in _WORD.finditer(folded):
        word = m.group(0)
        if len(word) >= 4 and any(SequenceMatcher(None, word, fw).ratio() >= 0.8 for fw in fuel_words):
            for i in range(m.start(), m.end()):
                kinds[i] = "fuel"


def _mark_oxygen(kinds: list, text: str, oxygen: float) -> None:
    best = None
    for m in _NUMBER.finditer(text):
        try:
            value = float(m.group(0).replace(",", "."))
        except ValueError:
            continue
        if abs(value - float(oxygen)) > 1e-9:
            continue
        end = m.end()
        pct = re.match(r"\s?%", text[end:])
        span = (m.start(), end + (pct.end() if pct else 0))
        if pct:
            best = span
            break
        best = best or span
    if best:
        for i in range(*best):
            kinds[i] = "o2"


def question_segments(
    question: str,
    *,
    oxygen: float | None = None,
    pressure_text: str = "",
    fuel: str | None = None,
    agents=(),
    detection=(),
    keywords=(),
) -> list[dict]:
    """Split the question into plain and highlighted pieces: ``[{"t": text, "k": kind or None}, ...]``.

    The pieces joined together give back the (whitespace-collapsed, possibly shortened) question.
    """
    text = _short(question)
    if not text:
        return []
    folded = fold(text)
    kinds: list = [None] * len(text)

    marks = {
        "phase": lambda: [_mark(kinds, folded, fold(k).strip(), "phase", prefix=True) for k in _names(keywords)],
        "detection": lambda: [_mark(kinds, folded, c, "detection") for d in _names(detection) for c in _candidates(d)],
        "agent": lambda: [_mark(kinds, folded, c, "agent") for a in _names(agents) for c in _candidates(a)],
        "fuel": lambda: _mark_fuel(kinds, folded, str(fuel)) if fuel else None,
        "pressure": lambda: _mark(kinds, folded, fold(pressure_text).strip(), "pressure") if pressure_text else None,
        "o2": lambda: _mark_oxygen(kinds, text, oxygen) if oxygen is not None else None,
    }
    for kind in _KIND_PRIORITY:
        marks[kind]()

    segments: list[dict] = []
    start = 0
    for i in range(1, len(text) + 1):
        if i == len(text) or kinds[i] != kinds[start]:
            segments.append({"t": text[start:i], "k": kinds[start]})
            start = i
    return segments


# ---------------------------------------------------------------------------
# Pieces of the animation payload
# ---------------------------------------------------------------------------

def _experiments_label(experiments: list[str]) -> str:
    shown = experiments[:MAX_EXPERIMENTS_IN_LABEL]
    extra = len(experiments) - len(shown)
    return ", ".join(shown) + (f" +{extra}" if extra > 0 else "")


def subset_of(df: pd.DataFrame, hits: pd.DataFrame, fuel: str | None, phase: str | None) -> tuple[pd.Series, dict]:
    """The middle step of the funnel: the rows that share fuel / experiment (or phase) with the question.

    Returns a boolean mask over ``df`` and ``{"kind", "n", "fuel", "experiments", "phase"}``.
    kind: "fuel_exp", "fuel", "phase", "exp" or "all".
    """
    experiments = list(dict.fromkeys(_column(hits, "experimento").dropna().astype(str))) if len(hits) else []
    in_exps = df["experimento"].astype(str).isin(experiments) if experiments else pd.Series(False, index=df.index)
    info = {"kind": "all", "n": int(len(df)), "fuel": None, "experiments": [], "phase": None}

    if fuel:
        # Same whole-word / synonym rule the engine retrieves with ("PMMA" matches "100 micron PMMA film").
        try:
            from .classify import fuel_matches

            same_fuel = df["combustible"].astype(str).map(lambda f: bool(fuel_matches(f, str(fuel))))
        except Exception:
            same_fuel = df["combustible"].astype(str).str.casefold() == str(fuel).casefold()
        both = same_fuel & in_exps
        if both.any():
            info.update(kind="fuel_exp", n=int(both.sum()), fuel=str(fuel),
                        experiments=[e for e in experiments if (same_fuel & (df["experimento"].astype(str) == e)).any()])
            return both, info
        if same_fuel.any():
            info.update(kind="fuel", n=int(same_fuel.sum()), fuel=str(fuel))
            return same_fuel, info
    if phase in config.PHASES:
        same_phase = df["fase"].astype(str) == phase
        if same_phase.any():
            info.update(kind="phase", n=int(same_phase.sum()), phase=str(phase))
            return same_phase, info
    if in_exps.any():
        info.update(kind="exp", n=int(in_exps.sum()), experiments=experiments)
        return in_exps, info
    return pd.Series(True, index=df.index), info


def _subset_label(info: dict, lang: str) -> str:
    kind = info["kind"]
    if kind == "fuel_exp":
        return t("viz.subset_fuel_exp", lang, n="{n}", fuel=term(str(info["fuel"]), lang), experiments=_experiments_label(info["experiments"]))
    if kind == "fuel":
        return t("viz.subset_fuel", lang, n="{n}", fuel=term(str(info["fuel"]), lang))
    if kind == "phase":
        return t("viz.subset_phase", lang, n="{n}", phase=phase_name(info["phase"], lang))
    if kind == "exp":
        return t("viz.subset_exp", lang, n="{n}", experiments=_experiments_label(info["experiments"]))
    return t("viz.subset_all", lang, n="{n}")


def cloud_of(df: pd.DataFrame, in_subset: pd.Series, extra_x=(), extra_y=()) -> dict:
    """Every row with a numeric O2 as ``[o2, pressure | None, phase_index, in_subset]`` plus the axes."""
    o2 = pd.to_numeric(df["oxigeno_num"], errors="coerce")
    plotted = o2.notna()
    pressure = pd.to_numeric(df["presion_num"], errors="coerce")
    phase_index = {p: i for i, p in enumerate(config.PHASES)}

    idx = [i for i, ok in enumerate(plotted.tolist()) if ok]
    sampled = False
    if len(idx) > MAX_POINTS:
        step = math.ceil(len(idx) / MAX_POINTS)
        subset_flags = in_subset.tolist()
        idx = [i for n, i in enumerate(idx) if n % step == 0 or subset_flags[i]]
        sampled = True

    o2_list, p_list = o2.tolist(), pressure.tolist()
    phase_list, subset_list = df["fase"].astype(str).tolist(), in_subset.tolist()
    points = []
    for i in idx:
        p = _num(p_list[i], 3)
        points.append([_num(o2_list[i], 2), p, phase_index.get(phase_list[i], -1), 1 if subset_list[i] else 0])

    xs = [pt[0] for pt in points] + [x for x in extra_x if x is not None]
    ys = [pt[1] for pt in points if pt[1] is not None] + [y for y in extra_y if y is not None]
    if xs:
        x_lo, x_hi = math.floor(min(xs) / 10) * 10, math.ceil(max(xs) / 10) * 10
        if x_hi - x_lo < 10:
            x_hi = x_lo + 10
    else:
        x_lo, x_hi = 0, 100
    y_hi = max(1, math.ceil(max(ys))) if ys else 1

    return {
        "x_domain": [max(0, x_lo), min(100, x_hi) if x_hi > x_lo else x_lo + 10],
        "y_domain": [0, y_hi],
        "points": points,
        "n_total": int(len(df)),
        "n_plotted": int(plotted.sum()),
        "n_no_o2": int((~plotted).sum()),
        "n_no_pressure": int((plotted & pressure.isna()).sum()),
        "sampled": sampled,
    }


def topk_of(hits: pd.DataFrame, state: str) -> list[dict]:
    """The retrieved rows, in rank order, with the outcome flag the animation colours them by."""
    if hits.empty:
        return []
    extinguished = _bool_column(hits, "extinguished").tolist()
    burned = _bool_column(hits, "burned").tolist()
    gas_cols = [c for _, c in GAS_COLUMNS if c in hits.columns]
    has_reading = hits[gas_cols].notna().any(axis=1).tolist() if gas_cols else [False] * len(hits)

    rows = []
    for n, r in enumerate(hits.itertuples(index=False)):
        if state == "detect":
            status = "reading" if has_reading[n] else "none"
        else:
            status = "extinguished" if extinguished[n] else "burned" if burned[n] else "other"
        rows.append({
            "id": str(getattr(r, "row_id", n + 1)),
            "o2": _num(getattr(r, "oxigeno_num", None), 2),
            "p": _num(getattr(r, "presion_num", None), 3),
            "experiment": str(getattr(r, "experimento", "")),
            "fuel": str(getattr(r, "combustible", "")),
            "phase": str(getattr(r, "fase", "")),
            "relevance": _num(getattr(r, "relevance", None), 3),
            "status": status,
        })
    return rows


def verdict_of(topk: list[dict], state: str, hits: pd.DataFrame, metric: str | None = None) -> dict:
    """The N / K the animation counts up to. Same columns as the engine's own answer text.

    When the question asks for a metric (duration, spread rate...), the count is neutral ("rows retrieved"):
    counting `burned` for PREVENT read as "methanol does not burn" for self-extinguishing droplets
    (review #2a). The ring still shows the outcomes."""
    k = len(topk)
    counts = {s: sum(1 for r in topk if r["status"] == s) for s in ("extinguished", "burned", "other", "reading", "none")}
    has_outcomes = "extinguished" in hits.columns or "burned" in hits.columns
    if metric and state in ("prevent", "extinguish"):
        kind, n = "rows", k
    elif state == "detect" and not counts["reading"]:
        kind, n = "rows", k  # these rows measured smoke / soot / dust, not gases: "0 of N" would read as a result
    elif state == "detect":
        kind, n = "reading", counts["reading"]
    elif state == "extinguish" and has_outcomes:
        kind, n = "extinguished", counts["extinguished"]
    elif state == "prevent" and has_outcomes:
        kind, n = "burned", counts["burned"]
    else:
        kind, n = "rows", k
    relevance = [r["relevance"] for r in topk if r["relevance"] is not None]
    return {"kind": kind, "n": int(n), "k": int(k), "counts": counts, "top_relevance": max(relevance) if relevance else None}


def bars_of(hits: pd.DataFrame, lang: str) -> list[dict]:
    """Fallback for rows without numeric O2: what matched, and which readings those rows record."""
    bars: list[dict] = []
    if hits.empty:
        return bars
    k = len(hits)
    for col in hits.columns:
        if not str(col).startswith("match_"):
            continue
        comp = str(col)[len("match_"):]
        values = pd.to_numeric(hits[col], errors="coerce").dropna()
        if values.empty:
            continue
        mean = float(min(1.0, max(0.0, values.mean())))
        label = t(f"component.{comp}", lang)
        bars.append({"group": "match", "label": comp if label == f"component.{comp}" else label,
                     "value": round(mean, 3), "max": 1, "text": f"{mean:.2f}"})
    for gas, col in GAS_COLUMNS:
        if col not in hits.columns:
            continue
        n = int(hits[col].notna().sum())
        bars.append({"group": "readings", "label": t("viz.bar_reading", lang, gas=gas), "value": n, "max": k, "text": f"{n}/{k}"})
    return bars


def _phase_counts(df: pd.DataFrame, lang: str, colors: dict) -> list[dict]:
    counts = df["fase"].astype(str).value_counts()
    return [{"key": p, "label": phase_name(p, lang).upper(), "color": colors[p], "n": int(counts.get(p, 0))} for p in config.PHASES]


def _detected(result, state: str, lang: str) -> dict:
    cond = _get(result, "conditions")
    clf = _get(result, "classification") or _get(cond, "classification")
    subject = _get(cond, "subject") or _get(clf, "subject")
    oxygen = _num(_get(cond, "oxygen"))
    pressure_atm = _num(_get(cond, "pressure_atm"))
    pressure_text = str(_get(cond, "pressure_text") or "")
    fuel = _get(cond, "fuel") or None
    material = _get(subject, "material") or None
    if isinstance(material, (list, tuple)):
        material = material[0] if material else None
    # O2 is the oxidizer, not a suppression agent (review #8: the chip showed "Agent: O2").
    agents = [a for a in dict.fromkeys(_names(_get(subject, "gases")) + _names(_get(subject, "inhibitors")))
              if a != "O2"]
    detection = _names(_get(subject, "detection_vars"))
    keywords = _names(_get(cond, "matched_keywords")) or _names(_get(clf, "matched_keywords"))
    confidence = _num(_get(cond, "phase_confidence")) or _num(_get(clf, "confidence")) or 0.0

    phase_label = (t("anim.out_of_scope", lang) if state == "out_of_scope"
                   else t("anim.unclear", lang) if state == "unclear" else phase_name(state, lang).upper())
    readouts = [{"k": "phase", "label": t("label.phase", lang), "value": phase_label}]
    if fuel or material:
        readouts.append({"k": "fuel", "label": t("col.fuel", lang), "value": term(str(fuel or material), lang)})
    if oxygen is not None:
        readouts.append({"k": "o2", "label": "O2", "value": f"{oxygen:g} %"})
    if pressure_atm is not None:
        readouts.append({"k": "pressure", "label": t("word.pressure", lang), "value": f"{pressure_atm:.3g} atm"})
    if agents:
        readouts.append({"k": "agent", "label": t("viz.kind_agent", lang), "value": ", ".join(term(a, lang) for a in agents)})
    if detection:
        readouts.append({"k": "detection", "label": t("viz.kind_detection", lang), "value": ", ".join(term(d, lang) for d in detection)})

    return {
        "phase": state, "phase_label": phase_label, "confidence": confidence, "keywords": keywords,
        "fuel": str(fuel) if fuel else None, "material": str(material) if material else None,
        "o2": oxygen, "pressure_atm": pressure_atm, "pressure_text": pressure_text,
        "agents": agents, "detection": detection, "readouts": readouts,
    }


_LABEL_KEYS = (
    "viz.step_classify", "viz.step_locate", "viz.step_narrow", "viz.step_verdict",
    "viz.kind_fuel", "viz.kind_agent", "viz.kind_detection", "viz.kind_pressure",
    "viz.axis_o2", "viz.axis_pressure", "viz.cloud_title", "viz.cloud_note",
    "viz.your_question", "viz.your_question_est", "viz.no_pressure_stated", "viz.no_o2_stated",
    "viz.status_extinguished", "viz.status_burned", "viz.status_other", "viz.status_reading", "viz.status_none",
    "viz.verdict_extinguished", "viz.verdict_burned", "viz.verdict_reading", "viz.verdict_rows",
    "viz.bars_match", "viz.bars_readings", "viz.phase_strip", "viz.empty", "viz.cta", "viz.cta_below",
    "viz.replay", "viz.skip", "viz.auto", "viz.credit", "viz.legend_top", "viz.sampled",
    "anim.classifying", "anim.out_of_scope", "anim.out_of_scope_hint", "anim.unclear", "anim.unclear_hint",
    "word.confidence", "word.keywords", "label.phase", "btn.see_results",
)


def _labels(lang: str, cloud: dict, verdict: dict, detected: dict) -> dict:
    labels = {key: t(key, lang) for key in _LABEL_KEYS}
    labels["viz.strip"] = t("viz.strip", lang, n=cloud["n_no_pressure"])
    labels["viz.cloud_note"] = t("viz.cloud_note", lang, plotted=cloud["n_plotted"], hidden=cloud["n_no_o2"])
    labels["viz.relevance"] = (t("viz.relevance", lang, value=f"{verdict['top_relevance']:g}")
                               if verdict["top_relevance"] is not None else "")
    labels["viz.kind_phase"] = detected["phase_label"]
    labels["viz.kind_o2"] = "O2"
    labels["anim.verdict"] = t("anim.verdict", lang, phase=detected["phase_label"])
    for p in config.PHASES:
        labels[f"phase.{p}"] = phase_name(p, lang).upper()
    return labels


def estimated_qpoint(topk: list[dict]) -> dict | None:
    """Where to draw a question that states no oxygen: the median O2 (and pressure) of the retrieved rows.

    Only for the picture: it is flagged ``estimated`` and drawn hollow / dashed with its own label. Nothing is
    computed from it and the engine never sees it.
    """
    o2s = sorted(r["o2"] for r in topk if r.get("o2") is not None)
    if not o2s:
        return None
    ps = sorted(r["p"] for r in topk if r.get("o2") is not None and r.get("p") is not None)

    def median(v):
        m = len(v) // 2
        return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2

    return {"o2": _num(median(o2s), 1), "p": _num(median(ps), 2) if ps else None, "estimated": True, "n": len(o2s)}


def build_animation_payload(
    question: str,
    df: pd.DataFrame,
    result,
    lang: str | None = None,
    colors: dict[str, str] | None = None,
    auto_seconds: float | None = None,
) -> dict:
    """Everything the stage-2 animation draws, as one JSON-safe dict (see the module docstring)."""
    lang = normalize_lang(lang or _get(result, "lang"))
    colors = dict(colors or config.PHASE_COLORS)
    state = result_state(result)
    hits = _hits(result) if state != "out_of_scope" else pd.DataFrame()
    detected = _detected(result, state, lang)

    segments = question_segments(
        question, oxygen=detected["o2"], pressure_text=detected["pressure_text"],
        fuel=detected["fuel"] or detected["material"], agents=detected["agents"],
        detection=detected["detection"], keywords=detected["keywords"],
    )

    topk = topk_of(hits, state)
    verdict = verdict_of(topk, state, hits, _get(_get(result, "conditions"), "comparison_metric"))
    phase = state if state in config.PHASES else None
    in_subset, subset = subset_of(df, hits, detected["fuel"], phase)
    qpoint = {"o2": detected["o2"], "p": detected["pressure_atm"]} if detected["o2"] is not None else None
    if qpoint is None and state != "out_of_scope":
        qpoint = estimated_qpoint(topk)
    cloud = cloud_of(
        df, in_subset,
        extra_x=[r["o2"] for r in topk] + ([qpoint["o2"]] if qpoint else []),
        extra_y=[r["p"] for r in topk] + ([qpoint["p"]] if qpoint else []),
    )

    if state == "out_of_scope":
        mode = "scope"
    elif not topk:
        mode = "empty"
    elif any(r["o2"] is not None for r in topk):
        mode = "scatter"
    else:
        mode = "bars"

    funnel = [
        {"n": cloud["n_total"], "label": t("viz.funnel_total", lang, n="{n}")},
        {"n": subset["n"], "label": _subset_label(subset, lang)},
        {"n": len(topk), "label": t("viz.funnel_topk", lang, n="{n}")},
    ]
    if subset["kind"] == "all":
        funnel.pop(1)

    payload = {
        "version": VERSION,
        "lang": lang,
        "state": state,
        "mode": mode,
        "question": {"text": _short(question), "segments": segments},
        "detected": detected,
        "phases": _phase_counts(df, lang, colors),
        "cloud": cloud,
        "funnel": funnel,
        "subset": subset,
        "topk": topk,
        "verdict": verdict,
        "bars": bars_of(hits, lang) if mode == "bars" else [],
        "qpoint": qpoint,
        "colors": {"phases": [colors[p] for p in config.PHASES], "status": dict(STATUS_COLORS), **UI_COLORS},
        "labels": _labels(lang, cloud, verdict, detected),
        "auto_seconds": float(config.ANIMATION_SECONDS if auto_seconds is None else auto_seconds),
    }
    return _clean(payload)


# ---------------------------------------------------------------------------
# Stage 3: the one-screen dashboard
# ---------------------------------------------------------------------------

def doi_of(source: str) -> str:
    """The DOI written in a source cell, or ""."""
    m = _DOI.search(str(source or ""))
    return m.group(0).rstrip(".") if m else ""


def _default_url(source: str) -> str:
    try:
        from .data import source_url  # the app's own rule for turning a source into a link

        return source_url(source) or ""
    except Exception:
        doi = doi_of(source)
        return f"https://doi.org/{doi}" if doi else ""


def first_url(url) -> str:
    """Some source cells hold two links ("https://doi.org/... | https://psi.nasa.gov/..."); a pill opens the first."""
    parts = re.split(r"\s*[|;,]\s*|\s+", str(url or "").strip())
    return parts[0] if parts and parts[0] else ""


def source_links(source, lang: str = "en") -> list[dict]:
    """A source cell as separate clean links: "https://doi.org/X | https://psi.nasa.gov/…" ->
    [{"label": "DOI X", "url": …}, {"label": "PSI page", "url": …}]. Text that is not a link is kept as a label."""
    links = []
    for part in re.split(r"\s+\|\s+|\s*;\s*", str(source or "").strip()):
        part = part.strip()
        if not part:
            continue
        doi = doi_of(part)
        if part.lower().startswith(("http://", "https://")):
            if doi and "doi.org" in part.lower():
                links.append({"label": f"DOI {doi}", "url": f"https://doi.org/{doi}"})
            elif "psi.nasa.gov" in part.lower():
                links.append({"label": t("res.link_psi", lang), "url": part})
            else:
                links.append({"label": part if len(part) <= 60 else part[:59] + "…", "url": part})
        elif doi:
            links.append({"label": f"DOI {doi}", "url": f"https://doi.org/{doi}"})
        else:
            links.append({"label": part, "url": ""})
    return links


def source_pill(source: str, experiment: str = "", url_for=None) -> dict:
    """``{"label", "url"}`` for a source cell: "<experiment> <DOI>" when a DOI is written, else the text."""
    source = str(source or "").strip()
    doi = doi_of(source)
    if doi:
        label = f"{experiment} {doi}".strip() if experiment and experiment not in doi else doi
    else:
        label = source if len(source) <= 44 else source[:43].rstrip() + "…"
    return {"label": label, "url": first_url((url_for or _default_url)(source) if source else "")}


def split_action(text: str) -> tuple[str, str]:
    """An action sentence as (title, body): the title is the lead clause, up to the first ", ", ": " or ". ".

    The words are the engine's; only the first letter of the body is capitalised.
    """
    text = str(text or "").strip()
    cut = min((i for i in (text.find(", ", 12), text.find(": ", 4), text.find(". ", 4)) if i > 0), default=-1)
    if cut < 0 or cut > 90:
        return text, ""
    body = text[cut + 2:].strip()
    return text[:cut].strip(), body[:1].upper() + body[1:]


def action_cards(actions, df: pd.DataFrame, url_for=None) -> list[dict]:
    """Recommended actions as cards. The pills are the sources of the rows each action cites."""
    cards = []
    by_id = df.drop_duplicates("row_id").set_index("row_id") if "row_id" in df.columns else pd.DataFrame()
    for text in actions or []:
        title, body = split_action(text)
        pills, seen = [], set()
        for rid in dict.fromkeys(_ROW_REF.findall(str(text))):
            if rid not in by_id.index:
                continue
            row = by_id.loc[rid]
            source = str(row.get("fuente", "") or "")
            if not source or source in seen:
                continue
            seen.add(source)
            pills.append(source_pill(source, str(row.get("experimento", "") or ""), url_for))
        cards.append({"title": title, "body": body, "pills": pills[:3]})
    return cards


def diluent_bars(diluent) -> list[dict]:
    """``physics.diluent`` as bars: one per diluent gas plus the N2-only baseline it was compared with."""
    bars: list[dict] = []
    baselines: list[dict] = []
    for gas, block in (diluent or {}).items():
        if not block:
            continue
        w, wo = block.get("with") or {}, block.get("without") or {}
        for name, side, store in ((str(gas), w, bars), ("N2", wo, baselines)):
            rows = int(side.get("rows") or 0)
            if rows <= 0:
                continue
            ext = int(side.get("extinguished") or 0)
            store.append({
                "gas": name, "extinguished": ext, "rows": rows, "fraction": round(ext / rows, 4),
                "o2_median": _num(side.get("o2_median"), 2), "comparable": bool(block.get("comparable")),
                "baseline": name == "N2" and store is baselines, "versus": str(gas),
            })
    unique = {(b["extinguished"], b["rows"], b["o2_median"]) for b in baselines}
    if len(unique) == 1 and baselines:
        baselines = [dict(baselines[0], versus="")]
    return bars + baselines


def oxygen_scale(result, lang: str) -> dict | None:
    """The 0–40 % oxygen line: where flames are recorded for the fuel, the asked O2, reference atmospheres."""
    cond = _get(result, "conditions")
    asked = _num(_get(cond, "oxygen"))
    bracket = _get(_get(result, "calculations"), "bracket") or {}
    low = _get(bracket, "lowest_flame")
    under = _get(bracket, "highest_nonburn_below")
    if asked is None and not low:
        return None
    top = float(config.O2_SCALE_MAX)
    if any(v is not None and v > top for v in (asked, _num(_get(low, "o2")))):
        top = 100.0
    refs = []
    for ref in config.REFERENCE_ATMOSPHERES:
        o2 = float(ref["oxygen"])
        refs.append({"key": ref.get("key", ""), "label": t(f"refshort.{ref.get('key', '')}", lang),
                     "o2": o2, "off_scale": o2 > top})
    return {
        "max": top,
        "asked": asked,
        "fuel": _get(cond, "fuel") or None,
        "flame_from": ({"o2": _num(_get(low, "o2")), "row_id": str(_get(low, "row_id", ""))}
                       if low and _num(_get(low, "o2")) is not None else None),
        "no_flame_at": ({"o2": _num(_get(under, "o2")), "row_id": str(_get(under, "row_id", "")),
                         "kind": term(str(_get(under, "kind", "")), lang)}
                        if under and _num(_get(under, "o2")) is not None else None),
        "refs": refs,
    }


def build_dashboard_view(result, df: pd.DataFrame, url_for=None) -> dict:
    """What the stage-3 dashboard draws, as one JSON-safe dict. Text written by the engine is passed through."""
    lang = normalize_lang(_get(result, "lang"))
    state = result_state(result)
    hits = _hits(result) if state != "out_of_scope" else pd.DataFrame()
    detected = _detected(result, state, lang)
    topk = topk_of(hits, state)
    verdict = verdict_of(topk, state, hits, _get(_get(result, "conditions"), "comparison_metric"))
    tied = int(_get(_get(result, "retrieval"), "tied") or 0)
    experiments = list(dict.fromkeys(r["experiment"] for r in topk if r["experiment"]))

    context = []
    if detected["o2"] is not None:
        context.append(f"{detected['o2']:g} % O2")
    if detected["fuel"]:
        context.append(term(detected["fuel"], lang))
    if experiments:
        context.append(_experiments_label(experiments))

    ring_order = ("reading", "none") if state == "detect" else ("extinguished", "burned", "other")
    ring = [{"key": key, "n": verdict["counts"][key], "color": STATUS_COLORS[key], "label": t(f"viz.status_{key}", lang)}
            for key in ring_order if verdict["counts"][key]]

    draft = _get(result, "draft")
    sources = []
    for s in _get(result, "sources") or []:
        first_exp = str(s.get("experiments", "")).split(",")[0].strip()
        pill = source_pill(s.get("source", ""), first_exp, url_for)
        if s.get("url"):
            pill["url"] = first_url(s["url"])
        sources.append(pill)

    return _clean({
        "lang": lang,
        "state": state,
        "question": str(_get(result, "question") or ""),
        "detected": detected,
        "insufficient": bool(_get(result, "insufficient")),
        "missing": [str(m) for m in (_get(result, "missing") or [])],
        "verdict": dict(verdict, headline=t(f"dash.verdict_{verdict['kind']}", lang), context=context,
                        sample=t("dash.verdict_sample", lang, k=verdict["k"], n=tied) if tied else "",
                        ids=[r["id"] for r in topk], answer=str(_get(draft, "answer") or "")),
        "ring": ring,
        "o2_scale": oxygen_scale(result, lang) if state != "out_of_scope" else None,
        "diluent": diluent_bars(_get(_get(result, "calculations"), "diluent")),
        "actions": action_cards(_get(result, "actions"), df, url_for),
        "sources": sources[:3],
        "mode": str(_get(result, "mode") or "offline"),
    })
