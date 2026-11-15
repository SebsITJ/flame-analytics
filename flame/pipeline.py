"""The question -> answer flow.

1. Read the question (rule-based classifier, optionally checked by Gemini).
2. Filter and rank rows with pandas.
3. Compute facts and physics with pandas.
4. Write a deterministic template, or send Gemini only the question, rows and facts.
5. Check Gemini's numbers and row citations; add sources from the CSV.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field

import pandas as pd

from . import config
from .classify import OUT_OF_SCOPE_MESSAGE, Classification  # noqa: F401  (re-exported for older imports)
from .data import source_url
from .i18n import detect_language, normalize_lang, phase_name, t, term
from .llm import DraftAnswer, EvidenceItem
from .physics import PhysicsReport, compute_physics
from .retrieval import (Conditions, Retrieval, filter_by_oxygen, merge_conditions, metric_rows, microgravity_only,
                        parse_rules, rank, subject_items)
from .verify import row_ids_in, unknown_row_ids, unsupported_numbers

NO_EVIDENCE = t("no_evidence", "en")  # English wording; every function below takes lang= for the rest


@dataclass
class Result:
    question: str
    conditions: Conditions
    retrieval: Retrieval
    draft: DraftAnswer
    insufficient: bool
    missing: list[str]
    sources: list[dict]
    mode: str  # "gemini" or "offline"
    warnings: list[str] = field(default_factory=list)
    payload: dict | None = None
    calculations: PhysicsReport | None = None
    actions: list[str] = field(default_factory=list)
    classification: Classification | None = None
    lang: str = "en"  # language of every text in this result ("en" or "es")


def _short(err: Exception) -> str:
    text = str(err).strip().splitlines()[0] if str(err).strip() else type(err).__name__
    return text[:160]


def _fmt_num(x) -> str:
    return "?" if pd.isna(x) else f"{round(float(x), 4):g}"


def gas_signature(r, lang: str = "en") -> str:
    """What changed in the gas over the test, with compound and unit. Empty when the source gives none."""
    def get(name):
        v = r.get(name) if isinstance(r, pd.Series) else getattr(r, name, None)
        return None if v is None or pd.isna(v) else float(v)

    bits = []
    for label, col, unit in (("O2", "o2_delta_pct", "% vol"), ("CO2", "co2_delta_ppm", "ppm"), ("CO", "co_delta_ppm", "ppm")):
        delta = get(col)
        if delta is not None:
            bits.append(f"{label} {delta:+g} {unit}")
    text = ", ".join(bits)
    ratio = get("co_co2_ratio")
    if ratio is not None:
        text += t("row.ratio", lang, ratio=f"{ratio:g}")
    return text


def row_label(r: pd.Series, lang: str = "en") -> str:
    o2 = f"{_fmt_num(r.oxigeno_num)} % O2" if pd.notna(r.oxigeno_num) else t("res.o2_not_listed", lang)
    pressure = (
        f"{_fmt_num(r.presion_num)} {config.PRESSURE_UNIT}" if pd.notna(r.presion_num) else t("res.p_not_listed", lang)
    )
    label = f"[{r.row_id}] {r.experimento} · {r.combustible} · {o2} · {pressure}: {r.resultado}"
    change = gas_signature(r, lang)
    return label + (t("row.change", lang, change=change) if change else "")


def _gas_payload(r) -> dict:
    def _get(name):
        return getattr(r, name, None)

    def _clean(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        if isinstance(v, (float, int)):
            return float(v)
        return v

    return {
        "o2_start_pct": _clean(_get("o2_start_pct")),
        "o2_end_pct": _clean(_get("o2_end_pct")),
        "co2_start_pct": _clean(_get("co2_start_pct")),
        "co2_end_pct": _clean(_get("co2_end_pct")),
        "co2_start_ppm": _clean(_get("co2_start_ppm")),
        "co2_end_ppm": _clean(_get("co2_end_ppm")),
        "co_start_ppm": _clean(_get("co_start_ppm")),
        "co_end_ppm": _clean(_get("co_end_ppm")),
        "diluent": _get("diluent") or "",
        "outcome_not_listed": bool(_get("outcome_not_listed")),
        "o2_delta_pct": _clean(_get("o2_delta_pct")),
        "co2_delta_ppm": _clean(_get("co2_delta_ppm")),
        "co_delta_ppm": _clean(_get("co_delta_ppm")),
        "co_co2_ratio": _clean(_get("co_co2_ratio")),
    }


def build_payload(question: str, retrieval: Retrieval, physics: PhysicsReport | None = None) -> dict:
    rows = []
    for r in retrieval.hits.itertuples():
        item = {
            "row_id": r.row_id,
            "experiment": r.experimento,
            "fuel": r.combustible,
            "oxygen_percent": r.oxigeno,  # original text, unchanged
            f"pressure_{config.PRESSURE_UNIT}": r.presion,
            "result": r.resultado,
            "phase": r.fase,
            "source": r.fuente,
            "simulated": bool(r.simulated),
            "relevance": float(r.relevance),
            "relevance_breakdown": getattr(r, "relevance_breakdown", ""),
        }
        item.update(_gas_payload(r))
        rows.append(item)
    facts = dict(retrieval.facts)
    if physics:
        facts.update(physics.as_facts())
    return {
        "question": question,
        "units": {"oxygen": "percent by volume", "pressure": config.PRESSURE_UNIT},
        "computed_facts": facts,
        "coverage_gaps": retrieval.gaps,
        "calculations": physics.lines if physics else [],
        "rows": rows,
    }


def _phase_summary(hits: pd.DataFrame, phase: str, limit: int = 3, lang: str = "en") -> str:
    rows = hits[hits["fase"] == phase]
    if rows.empty:
        return t("no_evidence", lang)
    parts = [row_label(r, lang) for _, r in rows.head(limit).iterrows()]
    extra = len(rows) - limit
    if extra > 0:
        parts.append(t("phase_summary.more", lang, extra=extra, phase=phase_name(phase, lang)))
    return " ".join(parts)


def _cite(ids) -> str:
    return ", ".join(f"[{i}]" for i in ids)


def recommended_actions(hits: pd.DataFrame, physics: PhysicsReport, cond: Conditions, lang: str = "en") -> list[str]:
    """Actions only when rows support them. Each one cites its rows and states where it stops holding."""
    actions: list[str] = []
    if hits.empty:
        return actions
    fuel = cond.fuel or t("act.fuel_default", lang)

    # 1. Oxygen threshold: only when a no-flame test sits below the lowest flame for this fuel.
    b = physics.bracket
    if cond.phase != "detect" and b and b.get("lowest_flame") and b.get("highest_nonburn_below"):
        low, under = b["lowest_flame"], b["highest_nonburn_below"]
        actions.append(t(
            "act.cut_oxygen", lang, fuel=fuel, u_o2=f"{under['o2']:g}", kind=term(under["kind"], lang),
            u_row=under["row_id"], l_o2=f"{low['o2']:g}", l_row=low["row_id"],
        ))

    # 2. Diluent gas: only when the groups have similar oxygen levels, at least DILUENT_MIN_ROWS rows each and
    #    a share of extinctions at least DILUENT_MIN_GAIN higher (review #4; thresholds are its judgment).
    named = set()
    if cond.subject:
        named = set(cond.subject.gases or []) | set(cond.subject.inhibitors or [])
    agent_asked = cond.phase == "extinguish" or bool(named & {"CO2", "He", "N2", "diluent (unspecified)"})
    if agent_asked and physics.diluent:
        for gas, block in physics.diluent.items():
            if not block or not block["comparable"]:
                continue
            w, wo = block["with"], block["without"]
            gain = w["extinguished"] / w["rows"] - wo["extinguished"] / wo["rows"]
            if min(w["rows"], wo["rows"]) >= config.DILUENT_MIN_ROWS and gain >= config.DILUENT_MIN_GAIN:
                actions.append(t(
                    "act.diluent", lang, gas=gas, w_med=f"{w['o2_median']:g}", wo_med=f"{wo['o2_median']:g}",
                    w_ext=w["extinguished"], w_rows=w["rows"], w_ids=_cite(w["row_ids"][:4]),
                    wo_ext=wo["extinguished"], wo_rows=wo["rows"], wo_ids=_cite(wo["row_ids"][:4]),
                ))

    # 3. Cool flames: the visible flame going out is not the end of the event.
    if cond.phase == "extinguish" and "cool_flame" in hits.columns:
        cool = hits[hits["cool_flame"] == True]
        if not cool.empty:
            actions.append(t("act.cool", lang, n=len(cool), ids=_cite(cool["row_id"].tolist()[:6])))

    # 4. Detection: which gas moved, and by how much, in the retrieved rows.
    if cond.phase == "detect":
        for label, col in (("CO2", "co2_delta_ppm"), ("CO", "co_delta_ppm")):
            if col not in hits.columns:
                continue
            rose = hits[hits[col] > 0]
            if not rose.empty:
                lo, hi = rose[col].min(), rose[col].max()
                span = f"{lo:g} ppm" if lo == hi else t("act.span_range", lang, lo=f"{lo:g}", hi=f"{hi:g}")
                actions.append(t("act.monitor", lang, label=label, n=len(rose), span=span,
                                 ids=_cite(rose["row_id"].tolist()[:6])))
    return actions


def _metric_text(df: pd.DataFrame | None, cond: Conditions, lang: str, limit: int = 6) -> str:
    """Recorded values of the metric the question compares (e.g. flame spread rate). Only numbers in the rows."""
    if df is None or not cond.comparison_metric:
        return ""
    rows = metric_rows(df, cond.comparison_metric, cond.fuel)
    if rows.empty:
        return ""
    # Same O2 filter as the chart (review #6), so text and chart list the same rows.
    rows, o2_mode, level = filter_by_oxygen(rows, cond.oxygen)
    if rows.empty:
        return ""
    metric = t(f"metric.{cond.comparison_metric}", lang)
    k = rows["combustible"].dropna().nunique()
    if cond.fuel:
        text = t("tpl.metric_fuel", lang, metric=metric, fuel=cond.fuel, n=len(rows))
        text = text[:1].upper() + text[1:]
    else:
        text = t("tpl.metric_many", lang, metric=metric, k=k) if k >= 2 else t("tpl.metric_few", lang, metric=metric)
    rows = rows.sort_values("result_metric", ascending=False)
    for r in rows.head(limit).itertuples():
        o2 = f"{_fmt_num(r.oxigeno_num)} % O2" if pd.notna(getattr(r, "oxigeno_num", None)) else t("tpl.no_o2", lang)
        text += t("tpl.metric_row", lang, fuel=r.combustible, value=f"{float(r.result_metric):g}",
                  unit=r.result_metric_unit, flow=r.flujo or "—", o2=o2, row=r.row_id)
    if len(rows) > limit:
        text += t("tpl.metric_more", lang, n=len(rows) - limit)
    tol = f"{config.METRIC_CHART_O2_TOLERANCE:g}"
    if o2_mode == "band":
        text += t("chart.o2_note_band", lang, o2=f"{cond.oxygen:g}", tol=tol) + " "
    elif o2_mode == "nearest":
        text += t("chart.o2_note_nearest", lang, o2=f"{cond.oxygen:g}", level=f"{level:g}", tol=tol) + " "
    return text


def templated_draft(
    retrieval: Retrieval,
    physics: PhysicsReport,
    cond: Conditions,
    actions: list[str],
    lang: str = "en",
    df: pd.DataFrame | None = None,
) -> DraftAnswer:
    """Deterministic answer used when Gemini is off or fails. No invented facts."""
    hits = retrieval.hits
    no_evidence = t("no_evidence", lang)
    if hits.empty:
        limitations = [
            t("empty.limit_1", lang),
            physics.warnings[0] if physics.warnings else "",
        ]
        return DraftAnswer(
            enough_evidence=False,
            answer=t("empty.answer", lang),
            prevent=no_evidence,
            detect=no_evidence,
            extinguish=no_evidence,
            evidence=[],
            limitations=" ".join(t for t in limitations if t),
            missing="",
        )

    phase = cond.phase if cond.phase in config.PHASES else None
    n = len(hits)
    experiments = ", ".join(dict.fromkeys(hits["experimento"].astype(str)))
    ids = hits["row_id"].tolist()
    o2 = hits["oxigeno_num"].dropna()
    o2_span = f"{_fmt_num(o2.min())}–{_fmt_num(o2.max())} % O2" if not o2.empty else t("tpl.no_o2", lang)
    missing_n = int(hits["outcome_not_listed"].sum()) if "outcome_not_listed" in hits.columns else 0

    focus = phase_name(phase, lang) if phase else t("tpl.focus_default", lang)
    first_ids = _cite(ids[:5])
    head_key = "tpl.answer_head_gap" if retrieval.gaps else "tpl.answer_head"
    answer = t(head_key, lang, n=n, experiments=experiments, focus=focus, span=o2_span, ids=first_ids)
    if cond.oxygen is not None:
        answer += t("tpl.o2_window", lang, tol=f"{config.OXYGEN_TOLERANCE:g}", o2=f"{cond.oxygen:g}")
    if retrieval.tied:
        answer += t("tpl.tied_sample", lang, k=n, n=retrieval.tied)
    if phase == "extinguish":
        ext_n = int(hits["extinguished"].sum()) if "extinguished" in hits.columns else 0
        burn_n = int(hits["burned"].sum()) if "burned" in hits.columns else 0
        answer += t("tpl.extinguish", lang, ext=ext_n, burn=burn_n)
    elif phase == "detect":
        gas_cols = [c for c in ("o2_delta_pct", "co2_delta_ppm", "co_delta_ppm") if c in hits.columns]
        gas_n = int(hits[gas_cols].notna().any(axis=1).sum()) if gas_cols else 0
        answer += t("tpl.detect", lang, n=gas_n)
        named = subject_items(cond, lang)
        if named:
            answer += t("tpl.detect_vars", lang, vars=", ".join(named))
        answer += t("tpl.detect_nosensor", lang)
    elif phase == "prevent":
        answer += t("tpl.prevent_gap" if retrieval.gaps else "tpl.prevent", lang)
    answer += _metric_text(df, cond, lang)
    if missing_n:
        answer += t("tpl.missing", lang, n=missing_n)
    answer += t("tpl.numbers", lang)

    limitations = [t("tpl.lim_template", lang), t("tpl.lim_micro", lang)]
    if not hits.empty and hits["simulated"].any():
        limitations.append(t("tpl.lim_sim", lang))
    if missing_n:
        limitations.append(t("tpl.lim_missing", lang, n=missing_n))

    evidence = []
    for r in hits.itertuples():
        how = t("tpl.how_relevance", lang, value=f"{r.relevance:g}")
        if getattr(r, "relevance_breakdown", ""):
            how += " (" + str(r.relevance_breakdown) + ")"
        if getattr(r, "outcome_not_listed", False):
            how += t("tpl.how_outcome", lang)
        evidence.append(EvidenceItem(row_id=r.row_id, how_used=how))

    return DraftAnswer(
        enough_evidence=True,
        answer=answer.strip(),
        prevent=_phase_summary(hits, "prevent", lang=lang),
        detect=_phase_summary(hits, "detect", lang=lang),
        extinguish=_phase_summary(hits, "extinguish", lang=lang),
        evidence=evidence,
        limitations=" ".join(limitations),
        missing="",
    )


def out_of_scope_result(question: str, conditions: Conditions, df: pd.DataFrame, lang: str = "en") -> Result:
    empty = pd.DataFrame(columns=df.columns)
    empty["relevance"] = pd.Series(dtype=float)
    retrieval = Retrieval(hits=empty, ranked=empty, gaps=[], facts={"rows_retrieved": 0})
    draft = DraftAnswer(
        enough_evidence=False,
        answer=t("out_of_scope.message", lang),
        prevent=t("no_evidence", lang),
        detect=t("no_evidence", lang),
        extinguish=t("no_evidence", lang),
        evidence=[],
        limitations=t("out_of_scope.limitations", lang),
        missing="",
    )
    return Result(
        question=question,
        conditions=conditions,
        retrieval=retrieval,
        draft=draft,
        insufficient=False,
        missing=[],
        sources=[],
        mode="offline",
        warnings=[],
        payload=None,
        calculations=None,
        actions=[],
        classification=conditions.classification,
        lang=lang,
    )


def offline_draft(retrieval: Retrieval) -> DraftAnswer:
    """Backward-compatible wrapper used by tests that call this directly, if any."""
    return templated_draft(retrieval, PhysicsReport(), Conditions(), [])


def collect_sources(df: pd.DataFrame, row_ids: list[str], lang: str = "en") -> list[dict]:
    rows = df[df["row_id"].isin(row_ids)]
    sources = []
    for source, group in rows.groupby("fuente", sort=False):
        sources.append(
            {
                "rows": ", ".join(group["row_id"]),
                "experiments": ", ".join(dict.fromkeys(group["experimento"])),
                "source": source or t("source.none", lang),
                "url": source_url(source),
            }
        )
    return sources


def _draft_with_llm(llm, payload: dict, lang: str) -> DraftAnswer:
    """English keeps the original call. Other languages pass lang= when the client accepts it."""
    if lang != "en":
        try:
            accepts = "lang" in inspect.signature(llm.draft_answer).parameters
        except (TypeError, ValueError):
            accepts = False
        if accepts:
            return llm.draft_answer(payload, lang=lang)
    return llm.draft_answer(payload)


def answer_question(question: str, df: pd.DataFrame, llm=None, lang: str | None = None) -> Result:
    """Answer ``question`` from ``df``. ``lang`` ("en"/"es") defaults to the language detected in the question."""
    lang = normalize_lang(lang) if lang else detect_language(question)
    warnings: list[str] = []
    rules = parse_rules(question, df["combustible"].unique().tolist(), lang)

    llm_reading = None
    if llm is not None and rules.phase != "out_of_scope":
        try:
            llm_reading = llm.extract_conditions(question)
        except Exception as err:  # quota, network, bad key...
            warnings.append(t("warn.gemini_read", lang, err=_short(err)))
    conditions = merge_conditions(question, rules, llm_reading, lang)
    warnings.extend(conditions.notes)
    others = list(getattr(conditions.subject, "also_named", []) or []) if conditions.subject else []
    if others and conditions.fuel:
        warnings.append(t("warn.two_fuels", lang, used=conditions.fuel, others=", ".join(others)))

    if conditions.phase == "out_of_scope":
        return out_of_scope_result(question, conditions, df, lang)

    retrieval = rank(df, conditions, lang)
    physics = compute_physics(df, retrieval.hits, conditions, lang)
    retrieval.facts.update(physics.as_facts())
    payload = build_payload(question, retrieval, physics)
    actions = recommended_actions(retrieval.hits, physics, conditions, lang)

    mode = "offline"
    draft = templated_draft(retrieval, physics, conditions, actions, lang, df)
    if llm is not None and not retrieval.hits.empty:
        try:
            draft = _draft_with_llm(llm, payload, lang)
            mode = "gemini"
        except Exception as err:
            warnings.append(t("warn.gemini_write", lang, err=_short(err)))

    valid_ids = retrieval.hits["row_id"].tolist()
    if mode == "gemini":
        texts = [draft.answer, draft.prevent, draft.detect, draft.extinguish, draft.limitations, draft.missing]
        texts += [e.how_used for e in draft.evidence]

        allowed = [question, json.dumps(payload, ensure_ascii=False)]
        bad_numbers = unsupported_numbers(texts, allowed)
        if bad_numbers:
            warnings.append(t("warn.numbers", lang, numbers=", ".join(bad_numbers)))

        cited = [e.row_id for e in draft.evidence] + [i for t in texts for i in row_ids_in(t)]
        unknown = list(dict.fromkeys(unknown_row_ids(cited, valid_ids)))
        if unknown:
            warnings.append(t("warn.unknown_rows", lang, rows=", ".join(unknown)))
            draft.evidence = [e for e in draft.evidence if e.row_id.strip().upper() in {v.upper() for v in valid_ids}]

    cited_ids = [e.row_id.strip().upper() for e in draft.evidence] or valid_ids
    sources = collect_sources(df, [i for i in valid_ids if i.upper() in cited_ids], lang)

    insufficient = retrieval.hits.empty or bool(retrieval.gaps) or not draft.enough_evidence
    missing = list(retrieval.gaps)
    if conditions.comparison_metric == "flame_spread_rate" and not conditions.fuel:
        # A ranking of materials needs the metric for at least two of them.
        if metric_rows(df, "flame_spread_rate")["combustible"].dropna().nunique() < 2:
            insufficient = True
            missing.append(t("gap.metric_ranking", lang, metric=t("metric.flame_spread_rate", lang)))
    if draft.missing.strip():
        missing.append(draft.missing.strip())

    return Result(
        question=question,
        conditions=conditions,
        retrieval=retrieval,
        draft=draft,
        insufficient=insufficient,
        missing=missing,
        sources=sources,
        mode=mode,
        warnings=warnings,
        payload=payload,
        calculations=physics,
        actions=actions,
        classification=conditions.classification,
        lang=lang,
    )
