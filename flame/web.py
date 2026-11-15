"""JSON + HTML-fragment presenter for the HTML version (server.py). No Streamlit import.

Everything here mirrors what app.py draws, but returns plain data:
    ask_payload()     the engine answer: dashboard view, animation document, written answer, calculations,
                      ranked rows, metric chart (Vega-Lite spec), warnings, and optionally the AI interpretation
    ai_payload()      the v7b agent outcome as JSON (badge, claims with safe citation links, chart spec, trace)
    explorer_rows()   the table for the Explorer tab
    chart_specs()     the two Vega-Lite charts of the Charts tab
Numbers come from the same functions as the Streamlit app (pipeline, viz_payload, dashboard), so both UIs agree.
Gemini text is untrusted: it is HTML-escaped and only our own R#/E# links are added.
"""

from __future__ import annotations

import html
import re
import time

import altair as alt
import pandas as pd

from . import config
from .agent import ENGINE_MODE, AIOutcome, run_ai
from .ai_view import build_chart, cited_ids, row_urls
from .animation import MISSION_HEIGHT, build_mission_html
from .dashboard import dashboard_html, strip_html
from .data import load_dataset, source_url, to_number
from .enrich import display_gas
from .lead import CATEGORIES, MEASUREMENTS, lead_payload, measurement_category, missing_material
from .i18n import STRINGS, detect_language, normalize_lang, phase_name, ref_label, t, term
from .pipeline import Result, answer_question
from .retrieval import filter_by_oxygen, metric_rows
from .theme import BG, brand_html, footer_html, hero_html
from .viz_payload import build_animation_payload, build_dashboard_view, doi_of, first_url, source_links

SEE_RESULTS_KEY = "see_results"
MUTED = "#c3c2b7"
_ID = re.compile(r"\b([RE])(\d+)\b")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CHART_TITLES = {"oxigeno": "col.oxygen", "presion": "col.pressure", "combustible": "col.fuel",
                 "experimento": "col.experiment", "fase": "col.phase", "diluente": "col.diluent"}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def link_of(source) -> str:
    """One clickable URL for a source cell (the source may list several, separated by "|")."""
    return first_url(source_url(str(source or ""))) or ""


def esc(text) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def num(x) -> str:
    return "?" if x is None or pd.isna(x) else f"{round(float(x), 4):g}"


def rich(text, urls: dict[str, str] | None = None, bold_ids: bool = False) -> str:
    """Escaped text; **bold** kept; R# linked to its source when a URL is known; E# in bold if asked."""
    out = esc(text)
    out = _BOLD.sub(r"<b>\1</b>", out)
    urls = urls or {}

    def repl(m: re.Match) -> str:
        rid = f"{m.group(1)}{m.group(2)}"
        if m.group(1) == "R" and urls.get(rid.upper()):
            return (f'<a class="ff-cite" href="{esc(urls[rid.upper()])}" target="_blank" '
                    f'rel="noopener noreferrer">{rid}</a>')
        return f'<b class="ff-cite-e">{rid}</b>' if (bold_ids or m.group(1) == "E") else rid

    return _ID.sub(repl, out)


def untrusted(text, urls: dict[str, str]) -> str:
    """Model text: drop brackets (no markdown links), escape everything, then add only our own citations."""
    text = re.sub(r"[\[\]]", "", str(text or ""))
    return rich(text.replace("**", ""), urls, bold_ids=True)


def _ids_in(*texts) -> list[str]:
    ids: list[str] = []
    for tx in texts:
        ids += [f"R{n}" for k, n in _ID.findall(str(tx or "")) if k == "R"]
    return list(dict.fromkeys(ids))


def jsonable(value):
    """pandas / numpy values -> plain JSON values (NaN -> None)."""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return value.item()
        except Exception:
            return str(value)
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def hud(chart) -> dict:
    """Mission-control look (same as app.hud) and a responsive width, as a Vega-Lite dict."""
    spec = (
        chart.configure(background="transparent")
        .configure_view(stroke="rgba(79,209,232,0.22)")
        .configure_axis(gridColor="rgba(255,255,255,0.08)", domainColor="rgba(255,255,255,0.25)",
                        tickColor="rgba(255,255,255,0.25)", labelColor="#aab2c5", titleColor="#aab2c5")
        .configure_legend(labelColor="#c9cfdc", titleColor="#aab2c5")
        .configure_title(color="#e8ecf4")
    ).to_dict()
    spec["width"] = "container"
    spec["autosize"] = {"type": "fit-x", "contains": "padding"}
    return jsonable(spec)


# ---------------------------------------------------------------------------
# Page chrome and i18n
# ---------------------------------------------------------------------------

def meta_payload(df: pd.DataFrame, lang: str, ai_enabled: bool, dataset=None) -> dict:
    L = normalize_lang(lang)
    return {
        "lang": L,
        "langs": ["en", "es"],
        "strings": {"en": STRINGS["en"], "es": STRINGS["es"]},
        "rows": int(len(df)),
        "experiments": int(df["experimento"].nunique()),
        "ai_enabled": ai_enabled,
        "gather_models": list(config.GATHER_MODELS),
        "interpret_models": list(config.INTERPRET_MODELS),
        "animation_seconds": float(config.ANIMATION_SECONDS),
        "mission_height": MISSION_HEIGHT,
        "phases": list(config.PHASES),
        "phase_colors": dict(config.PHASE_COLORS),
        "simulated_rows": int(df["simulated"].sum()) if "simulated" in df.columns else 0,
        "html": {
            "brand": {code: brand_html(code, rows=len(df), experiments=int(df["experimento"].nunique()),
                                       gemini=ai_enabled) for code in ("en", "es")},
            "hero": {code: hero_html(code) for code in ("en", "es")},
            "footer": {code: footer_html(code) for code in ("en", "es")},
        },
    }


# ---------------------------------------------------------------------------
# Engine answer
# ---------------------------------------------------------------------------

def written_html(res: Result, df: pd.DataFrame) -> str:
    """Port of app.render_written: conditions read, answer, actions, P / D / E, evidence, limitations, sources."""
    L = res.lang
    c = res.conditions
    clf = res.classification or c.classification
    urls = row_urls(df, _ids_in(res.draft.answer, *(e.row_id for e in res.draft.evidence)))
    out: list[str] = []
    if clf and clf.out_of_scope:
        bits = f"<b>{esc(t('label.phase', L))}:</b> {esc(phase_name('out_of_scope', L))}"
        out.append(f"<h4>{esc(t('res.conditions', L))}</h4><div class='ff-w-info'>{bits}</div>")
        if c.subject and not c.subject.is_empty():
            out.append(f"<p class='ff-w-cap'>{esc(t('label.subject', L))}: {esc(c.subject.summary(L))}</p>")
        out.append(f"<div class='ff-w-warn'>{rich(res.draft.answer)}</div>")
        return "".join(out)

    found = [
        t("cond.o2", L, value=f"{c.oxygen:g}") if c.oxygen is not None else None,
        t("cond.pressure", L, text=c.pressure_text, atm=f"{c.pressure_atm:.3g}") if c.pressure_atm is not None else None,
        t("cond.fuel", L, fuel=term(c.fuel, L)) if c.fuel else None,
    ]
    found = [f for f in found if f]
    # the classifier's certainty, matched keywords and how the conditions were read are never shown
    phase_txt = phase_name(c.phase, L) if c.phase else t("phase.none", L)
    subject_txt = c.subject.summary(L) if c.subject else t("none_m", L)
    out.append(f"<h4>{esc(t('res.conditions', L))}</h4><ul>"
               f"<li><b>{esc(t('label.phase', L))}:</b> {esc(phase_txt)}</li>"
               f"<li><b>{esc(t('label.subject', L))}:</b> {esc(subject_txt)}</li>"
               f"<li><b>{esc(t('label.stated', L))}:</b> {esc(' · '.join(found) if found else t('none_f', L))}"
               "</li></ul>")
    d = res.draft
    out.append(f"<h4>{esc(t('res.answer', L))}</h4>")
    if res.insufficient:
        out.append(f"<div class='ff-w-err'>{esc(t('insufficient', L))}</div>")
        if res.missing:
            out.append(f"<p>{esc(t('res.missing_title', L))}</p><ul>"
                       + "".join(f"<li>{rich(m)}</li>" for m in res.missing) + "</ul>")
        if not res.retrieval.hits.empty:
            out.append(f"<div class='ff-w-info'>{esc(t('res.closest', L))}</div>")
    if not res.retrieval.hits.empty:
        out.append(f"<p>{rich(d.answer, urls)}</p>")
        out.append(f"<h4>{esc(t('res.actions', L))}</h4>")
        if res.actions:
            out.append("<ul>" + "".join(f"<li>{rich(a, urls)}</li>" for a in res.actions) + "</ul>")
        else:
            out.append(f"<p>{esc(t('res.no_actions', L))}</p>")
        out.append(f"<h4>{esc(t('res.pde', L))}</h4><ul class='ff-w-pde'>")
        for kind, text_ in (("prevent", d.prevent), ("detect", d.detect), ("extinguish", d.extinguish)):
            body = rich(text_, urls) if str(text_).strip() else esc(t("no_evidence", L))
            out.append(f"<li class='ff-w-{kind}'><b>{esc(phase_name(kind, L).capitalize())}:</b> {body}</li>")
        out.append("</ul>")
        out.append(f"<h4>{esc(t('res.evidence', L))}</h4><ul>")
        hits = res.retrieval.hits.set_index("row_id")
        for e in d.evidence:
            rid = e.row_id.strip().upper()
            if rid in hits.index:
                r = hits.loc[rid]
                flag = f" · <b>{esc(t('res.outcome_not_listed', L))}</b>" if bool(r.get("outcome_not_listed")) else ""
                o2 = t("res.o2_not_listed", L) if pd.isna(r.oxigeno_num) else f"{num(r.oxigeno_num)} % O2"
                p = t("res.p_not_listed", L) if pd.isna(r.presion_num) else f"{num(r.presion_num)} atm"
                out.append(f"<li>{rich(rid, urls, True)} · {esc(r.experimento)} · {esc(r.combustible)} · "
                           f"{esc(o2)} · {esc(p)}{flag} — {rich(e.how_used, urls)}</li>")
        out.append("</ul>")
        out.append(f"<h4>{esc(t('res.limitations', L))}</h4><p>{rich(d.limitations) or esc(t('res.none_stated', L))}</p>")
    out.append(f"<h4>{esc(t('res.sources', L))}</h4>")
    if res.sources:
        items = []
        for s in res.sources:
            links = source_links(s["source"], L)
            ref = " · ".join(
                (f'<a href="{esc(k["url"])}" target="_blank" rel="noopener noreferrer">{esc(k["label"])}</a>'
                 if k["url"] else esc(k["label"])) for k in links) or esc(s["source"])
            items.append(f"<li>{esc(s['rows'])} · {esc(s['experiments'])} — {ref}</li>")
        out.append("<ul>" + "".join(items) + "</ul>")
    else:
        out.append(f"<p>{esc(t('res.no_sources', L))}</p>")
    return "".join(out)


def calculations_payload(res: Result) -> dict:
    L = res.lang
    if res.calculations and res.calculations.lines:
        return {"lines": [rich(line) for line in res.calculations.lines], "caption": t("res.nist_caption", L)}
    return {"lines": [], "caption": t("phy.no_o2", L)}


def ranked_payload(res: Result) -> dict:
    """Port of app.render_ranked: the retrieved rows with their score columns (table data, labels in L)."""
    L = res.lang
    hits = res.retrieval.hits.copy()
    for col, unit in (("co2_start_ppm", "ppm"), ("co2_end_ppm", "ppm"), ("co_start_ppm", "ppm"),
                      ("co_end_ppm", "ppm"), ("o2_start_pct", "% vol"), ("o2_end_pct", "% vol")):
        if col in hits.columns:
            hits[col + "_display"] = hits[col].map(lambda v, u=unit: display_gas(v, u, L))
    if "fase" in hits.columns:
        hits["fase"] = hits["fase"].map(lambda p: phase_name(p, L) if p else p)
    cols = ["row_id", "relevance", "relevance_breakdown"]
    cols += [c_ for c_ in hits.columns if c_.startswith("match_") or c_.startswith("score_")]
    if "experimento" in hits.columns:
        hits["medicion"] = hits["experimento"].map(lambda e: measurement_category(e, L))
    cols += ["experimento", "medicion", "combustible", "oxigeno_num", "presion_num", "fase"]
    for extra in ("o2_start_pct_display", "o2_end_pct_display", "co2_start_ppm_display", "co2_end_ppm_display",
                  "co_start_ppm_display", "co_end_ppm_display", "diluent", "outcome_not_listed", "resultado", "fuente"):
        if extra in hits.columns:
            cols.append(extra)
    cols = [c_ for c_ in cols if c_ in hits.columns]
    labels = {"row_id": t("col.row", L), "relevance": t("col.relevance", L), "experimento": t("col.experiment", L),
              "combustible": t("col.fuel", L), "fase": t("col.phase", L), "resultado": t("col.result", L),
              "fuente": t("col.source", L), "oxigeno_num": t("col.oxygen", L), "presion_num": t("col.pressure", L),
              "relevance_breakdown": t("col.relevance_breakdown", L), "o2_start_pct_display": t("col.o2_start", L),
              "o2_end_pct_display": t("col.o2_end", L), "co2_start_ppm_display": t("col.co2_start", L),
              "co2_end_ppm_display": t("col.co2_end", L), "co_start_ppm_display": t("col.co_start", L),
              "co_end_ppm_display": t("col.co_end", L), "outcome_not_listed": t("col.outcome_not_listed", L),
              "diluent": t("col.diluent", L), "medicion": t("col.measure", L)}
    for col in cols:
        kind, _, comp = col.partition("_")
        if kind in ("match", "score") and comp:
            name = t(f"component.{comp}", L) if f"component.{comp}" in STRINGS["en"] else comp
            labels[col] = f"{t('col.' + kind, L)} · {name}"
    rows = [{c_: jsonable(r[c_]) for c_ in cols} for _, r in hits[cols].iterrows()]
    for r in rows:
        r["_url"] = link_of(r.get("fuente") or "") if "fuente" in r else ""
    return {"title": t("res.ranked_expander", L), "help": t("relevance_help", L),
            "columns": [{"key": c_, "label": labels.get(c_, c_)} for c_ in cols], "rows": rows,
            "caption": t("res.gas_caption", L, unspecified=t("unspecified", L).capitalize())}


def metric_chart_payload(res: Result, df: pd.DataFrame) -> dict | None:
    """Port of app.render_metric_chart: bars of the metric the question names, O2-filtered (± tolerance)."""
    c = res.conditions
    metric_key = getattr(c, "comparison_metric", None)
    if not metric_key:
        return None
    L = res.lang
    rows = metric_rows(df, metric_key, c.fuel)
    metric = t(f"metric.{metric_key}", L)
    tol = f"{config.METRIC_CHART_O2_TOLERANCE:g}"
    asked = None if c.oxygen is None else f"{c.oxygen:g}"
    rows, o2_mode, level = filter_by_oxygen(rows, c.oxygen)
    level_txt = None if level is None else f"{level:g}"
    o2_label = {"all": t("chart.o2_all", L), "band": t("chart.o2_band", L, o2=asked, tol=tol),
                "nearest": t("chart.o2_nearest", L, level=level_txt, tol=tol)}[o2_mode]
    o2_note = {"all": t("chart.o2_note_all", L), "band": t("chart.o2_note_band", L, o2=asked, tol=tol),
               "nearest": t("chart.o2_note_nearest", L, o2=asked, level=level_txt, tol=tol)}[o2_mode]
    out = {"title": t("chart.metric_title", L, metric=metric[:1].upper() + metric[1:], o2=o2_label),
           "o2_mode": o2_mode, "warning": o2_note if o2_mode == "nearest" else "", "spec": None,
           "empty": "", "caption": ""}
    if rows.empty:
        out["empty"] = t("chart.metric_none", L)
        return out
    rows = rows.sort_values("result_metric", ascending=False).head(config.METRIC_CHART_MAX_ROWS).copy()
    unit = str(rows["result_metric_unit"].iloc[0])
    rows["chart_label"] = (rows["row_id"].astype(str) + " | " + rows["experimento"].astype(str) + " | "
                           + rows["combustible"].astype(str) + " | " + rows["flujo"].astype(str) + " | "
                           + pd.to_numeric(rows["oxigeno_num"], errors="coerce").map(
                               lambda v: "O₂ ?" if pd.isna(v) else f"{v:g} % O₂"))
    data = rows[["row_id", "experimento", "combustible", "oxigeno_num", "result_metric", "chart_label"]].copy()
    base = alt.Chart(data).encode(
        x=alt.X("result_metric:Q", title=f"{metric} ({unit})", scale=alt.Scale(zero=True, nice=True)),
        y=alt.Y("chart_label:N", title=None, sort="-x", axis=alt.Axis(labelLimit=320, labelFontSize=11)),
        tooltip=[alt.Tooltip("row_id:N", title=t("col.row", L)), alt.Tooltip("experimento:N", title=t("col.experiment", L)),
                 alt.Tooltip("combustible:N", title=t("col.fuel", L)), alt.Tooltip("oxigeno_num:Q", title=t("col.oxygen", L)),
                 alt.Tooltip("result_metric:Q", title=f"{metric} ({unit})")],
    )
    bars = base.mark_bar(cornerRadiusEnd=6, size=22, color=config.TELEMETRY_COLOR)
    values = base.mark_text(align="left", baseline="middle", dx=6, fontSize=12, color="#e8ecf4").encode(
        text=alt.Text("result_metric:Q", format=".2f"))
    out["spec"] = hud((bars + values).properties(height=max(140, len(rows) * 32)))
    out["caption"] = t("chart.metric_caption", L, n=len(rows)) + " " + o2_note
    out["rows"] = [jsonable(r) for r in data.drop(columns=["chart_label"]).to_dict("records")]
    out["unit"] = unit
    return out


def ask_payload(question: str, lang: str | None, df: pd.DataFrame) -> tuple[dict, Result]:
    """The engine's answer (no Gemini). Always returns a dict; presentation errors become empty parts."""
    t0 = time.monotonic()
    L = detect_language(question, default=normalize_lang(lang))
    res = answer_question(question, df, None, L)
    L = res.lang
    out: dict = {"question": res.question, "lang": L, "mode": res.mode, "warnings": list(res.warnings),
                 "insufficient": bool(res.insufficient)}
    try:
        view = build_dashboard_view(res, df, url_for=source_url)
        try:  # C3 / C4: "not enough data" first, and the Moon / Mars notice (flame/lead.py)
            lead = lead_payload(res, view, df)
            if view["state"] == "out_of_scope":
                lead = dict(lead, html="", state="out_of_scope")
            elif lead["state"] == "nodata":
                view["nodata"] = " ".join(x for x in (lead["sentence"], lead["reason"]) if x)
            elif lead.get("hide_count") or (view["state"] == "detect" and not view["verdict"]["counts"].get("reading")):
                view["nodata"] = lead["sentence"]  # the measure is not in these rows: never a big 0/N
            out["lead_html"] = lead["html"]  # C1: the answer comes first, the evidence is folded below it
            out["lead"] = {k: lead[k] for k in ("state", "sentence", "reason", "notices", "confidence", "action",
                                                "measurements", "phase_label", "hide_count")}
        except Exception:
            out["lead_html"], out["lead"] = "", None
        out["view"] = jsonable(view)
        out["html"] = {"strip": strip_html(view), "board": dashboard_html(view, include_strip=False)}
        out["state"] = view.get("state")
    except Exception as err:  # presentation only: the written answer is still there
        out["view"], out["html"], out["state"] = None, None, None
        out["view_error"] = type(err).__name__
    try:
        payload = build_animation_payload(res.question, df, res, lang=L, colors=config.PHASE_COLORS)
        ld = out.get("lead") or {}
        if (ld.get("state") == "nodata" or ld.get("hide_count")) and isinstance(payload.get("verdict"), dict):
            # the material is not in the data: the animation counts rows found, not "N of 8 extinguished"
            payload["verdict"].update(kind="rows", n=payload["verdict"].get("k", 0))
        out["animation"] = {"html": build_mission_html(payload, button_key=SEE_RESULTS_KEY),
                            "height": MISSION_HEIGHT, "auto_seconds": jsonable(payload.get("auto_seconds"))}
    except Exception:
        out["animation"] = None
    out["written_html"] = written_html(res, df)
    out["calculations"] = calculations_payload(res)
    out["ranked"] = ranked_payload(res)
    cond = getattr(res, "conditions", None)
    out["out_of_scope"] = out.get("state") == "out_of_scope" or getattr(cond, "phase", None) == "out_of_scope"
    out["metric_chart"] = None if out["out_of_scope"] else metric_chart_payload(res, df)
    out["engine_seconds"] = round(time.monotonic() - t0, 2)
    return out, res


# ---------------------------------------------------------------------------
# AI interpretation (v7b agent)
# ---------------------------------------------------------------------------

def _attempt(a) -> dict:
    return {"model": a.model, "step": a.step, "ok": bool(a.ok), "detail": str(a.reason)[:240],
            "seconds": round(float(a.seconds), 1)}


def trace_steps(ai: AIOutcome, L: str) -> list[dict]:
    """The model trace as an ordered list of nodes (the HTML draws it as a vertical flow; no Graphviz needed)."""
    calls = ai.ledger.calls if ai.ledger else []
    steps = [{"kind": "question", "label": t("ai.dot.question", L)},
             {"kind": "engine", "label": t("ai.dot.engine", L)}]
    engine_calls = [c for c in calls if c.get("by") == config.ENGINE_GATHER]
    llm_calls = [c for c in calls if c.get("by") != config.ENGINE_GATHER]

    def call_item(c):
        args = ", ".join(f"{k}={v}" for k, v in (c.get("args") or {}).items() if v not in (None, ""))
        return {"tool": c.get("tool"), "args": args, "ok": bool(c.get("ok")),
                "result": (f"{c.get('evidence_id')} · {c.get('n_rows')} R#" if c.get("ok") else str(c.get("error") or ""))}

    if engine_calls:
        steps.append({"kind": "baseline", "label": t("ai.dot.baseline", L), "calls": [call_item(c) for c in engine_calls]})
    planners = [a for a in ai.attempts if a.step == "gather"]
    for a in planners:
        steps.append({"kind": "gather", "label": t("ai.dot.gather", L), "model": a.model, "ok": a.ok,
                      "detail": a.reason, "calls": [call_item(c) for c in llm_calls if c.get("by") == a.model]})
    if calls:
        steps.append({"kind": "pack", "label": t("ai.dot.pack", L),
                      "detail": f"{len(ai.ledger.rows)} R# · {len(ai.ledger.facts)} E#"})
    first = True
    for a in ai.attempts:
        if a.step in ("interpret", "repair"):
            verdicts = [v for v in ai.attempts if v.step == "verify" and v.model == a.model]
            rejected = a.ok and verdicts and not verdicts[-1].ok
            steps.append({"kind": a.step, "label": t("ai.dot.interpret", L), "model": a.model, "ok": bool(a.ok),
                          "rejected": bool(rejected), "detail": (verdicts[-1].reason if rejected else a.reason)[:200],
                          "handoff": t("ai.dot.handoff", L) if first else "", "seconds": round(a.seconds, 1)})
            first = False
    steps.append({"kind": "verify", "ok": ai.ok,
                  "label": t("ai.dot.verify_ok", L) if ai.ok else t("ai.dot.verify_fail", L)})
    steps.append({"kind": "ui", "label": t("ai.dot.ui_ai", L) if ai.ok else t("ai.dot.ui_engine", L)})
    return steps


def agents_payload(ai: AIOutcome, L: str, urls: dict[str, str] | None = None) -> list[dict]:
    """One card per specialist agent: the question it answers, its path (engine calls) and its finding."""
    ledger = ai.ledger
    active = list(getattr(ledger, "agents", []) or [])
    if not active:
        return []
    findings = {f.agent: f.finding for f in (ai.answer.agents if ai.ok and ai.answer else [])}
    lead = next((c.get("agent") for c in ledger.calls if c.get("agent")), None)
    out = []
    for name in active:
        path = []
        for c in ledger.calls:
            if c.get("agent") != name:
                continue
            args = ", ".join(f"{k}={v}" for k, v in (c.get("args") or {}).items() if v not in (None, ""))
            path.append({"tool": c.get("tool"), "args": args, "ok": bool(c.get("ok")),
                         "result": (f"{c.get('evidence_id')} · {c.get('n_rows')} R#" if c.get("ok") else str(c.get("error") or ""))})
        text = findings.get(name, "")
        out.append({"key": name, "label": t(f"ai.agent.{name}", L), "question": t(f"ai.agent_q.{name}", L),
                    "lead": name == lead, "path": path,
                    "finding_html": untrusted(text, urls or {}) if text.strip() else ""})
    return out


def ai_payload(ai: AIOutcome | None, res: Result, df: pd.DataFrame) -> dict:
    L = res.lang
    out: dict = {"title": t("ai.title", L), "how": t("ai.how", L), "footer": t("ai.footer", L)}
    if ai is None or not ai.ok:
        reason = (ai.reason if ai is not None else "no_key") or "errors"
        key = f"ai.engine_reason.{reason}" if f"ai.engine_reason.{reason}" in STRINGS["en"] else "ai.engine_reason.errors"
        # badge / title / user_note are what a decision maker sees; tech_badge and note (why the AI did not
        # answer: no key, quota, verifier...) are internal and only shown with ?debug=1.
        out.update(ok=False, mode=ENGINE_MODE, reason=reason, title=t("ai.title_engine", L),
                   badge=t("ai.badge_engine", L), tech_badge=t("ai.tech_badge_engine", L), note=t(key, L),
                   user_note="" if reason in ("no_data", "out_of_scope") else t("ai.engine_user_note", L))
    else:
        a = ai.answer
        if getattr(ai, "hybrid", False):
            gather = ai.gather_model if ai.gather_model != config.ENGINE_GATHER else t("ai.engine_name", L)
            badge = t("ai.badge_hybrid", L)
            tech_badge = t("ai.tech_badge_hybrid", L, gather=gather, model=ai.mode)
        else:
            badge = t("ai.badge_model", L)
            tech_badge = t("ai.tech_badge_model", L, model=ai.mode)
        urls = row_urls(df, cited_ids(a))
        claims = []
        for c in a.claims:
            phase = phase_name(c.phase, L).capitalize() if c.phase in config.PHASES else t("ai.phase.general", L)
            claims.append({"phase": c.phase, "phase_label": phase, "kind": c.kind, "kind_label": t("ai.kind." + c.kind, L),
                           "text": c.text, "html": untrusted(c.text, urls), "row_ids": list(c.row_ids),
                           "evidence_ids": list(c.evidence_ids)})
        chart = None
        if a.chart is not None:
            titles = {k: t(v, L) for k, v in _CHART_TITLES.items()}
            titles.update({k: t(f"ai.field.{k}", L) for k in ("metric_value", "extinguished", "flame_recorded",
                                                               "did_not_ignite")})
            try:
                built = build_chart(a.chart, ai.ledger, titles)
                if built is not None:
                    chart = {"spec": hud(built), "caption": t("ai.chart_caption", L, kind=a.chart.type,
                                                                eid=a.chart.evidence_id)}
            except Exception:
                chart = None
        cited = [ai.ledger.rows[i] for i in cited_ids(a) if i in ai.ledger.rows]
        out.update(ok=True, mode=ai.mode, gather_model=ai.gather_model, badge=badge, tech_badge=tech_badge,
                   seconds=ai.seconds, seconds_label=t("ai.seconds", L, s=ai.seconds),
                   enough_evidence=bool(a.enough_evidence),
                   insufficient_note=(t("ai.insufficient", L) + " " + t("insufficient", L)) if not a.enough_evidence else "",
                   summary=a.summary, summary_html=untrusted(a.summary, urls),
                   conclusion_label=t("ai.conclusion", L),
                   conclusion_html=untrusted(a.conclusion, urls) if a.conclusion.strip() else "",
                   recommendation_label=t("ai.recommendation", L),
                   recommendation_html=untrusted(a.recommendation, urls) if a.recommendation.strip() else "",
                   claims_title=t("ai.claims", L), claims=claims, chart=chart,
                   limitations_label=t("ai.limitations", L), limitations_html=untrusted(a.limitations, urls) if a.limitations.strip() else "",
                   missing_label=t("ai.missing", L), missing_html=untrusted(a.missing, urls) if a.missing.strip() else "",
                   cited_rows=jsonable(cited), row_urls=urls)
    if ai is not None:
        out["agents"] = agents_payload(ai, L, out.get("row_urls"))
        out["agents_title"], out["agents_intro"] = t("ai.agents_title", L), t("ai.agents_intro", L)
        out["agent_path_label"], out["agent_lead_label"] = t("ai.agent_path", L), t("ai.agent_lead", L)
        out["attempts"] = [_attempt(a) for a in ai.attempts]
        out["calls"] = [{"by": ((t("ai.engine_name", L) + (" · " + t("ai.agent." + c["agent"], L) if c.get("agent") else ""))
                                if c.get("by") == config.ENGINE_GATHER else c.get("by") or ai.gather_model or ""),
                         "tool": c.get("tool"),
                         "args": ", ".join(f"{k}={v}" for k, v in (c.get("args") or {}).items() if v not in (None, "")),
                         "result": (f"{c.get('evidence_id')} · {c.get('n_rows')} R#" if c.get("ok") else str(c.get("error") or "")),
                         "ok": bool(c.get("ok"))} for c in (ai.ledger.calls if ai.ledger else [])]
        out["trace"] = trace_steps(ai, L) if ai.attempts else []
        out["problems"] = list(ai.problems)
    else:
        out["attempts"], out["calls"], out["trace"], out["problems"] = [], [], [], []
    out["labels"] = {k: t(f"ai.col.{k}", L) for k in ("by", "tool", "args", "result", "model", "step", "status",
                                                       "detail", "seconds")}
    out["labels"].update(ok=t("ai.ok", L), fail=t("ai.fail", L), intro=t("ai.how_intro", L),
                         engine_note=t("ai.how_engine", L))
    return out


def run_ai_safe(question: str, res: Result, df: pd.DataFrame, client) -> AIOutcome:
    """The agent never raises into the API: any failure is an engine-only outcome."""
    if res.conditions is not None and getattr(res.conditions, "phase", None) == "out_of_scope":
        out = AIOutcome(mode=ENGINE_MODE, lang=res.lang)
        out.reason = "out_of_scope"
        return out
    if not getattr(res.conditions, "fuel", None) and missing_material(question, df):
        # C3: the material is not in the data. No request is spent on writing about other fuels.
        out = AIOutcome(mode=ENGINE_MODE, lang=res.lang)
        out.reason = "no_data"
        return out
    try:
        return run_ai(question, df, res, client, res.lang)
    except Exception as err:
        out = AIOutcome(mode=ENGINE_MODE, lang=res.lang)
        out.reason = "errors"
        out.problems = [type(err).__name__]
        return out


# ---------------------------------------------------------------------------
# Explorer and Charts tabs
# ---------------------------------------------------------------------------

EXPLORER_COLUMNS = ["row_id", "experimento", "combustible", "oxigeno_num", "presion_num", "o2_start_pct", "o2_end_pct",
                    "co2_start_ppm", "co2_end_ppm", "co_start_ppm", "co_end_ppm", "diluent", "outcome_not_listed",
                    "resultado", "fase", "fuente"]


def explorer_rows(df: pd.DataFrame) -> dict:
    cols = [c for c in dict.fromkeys(EXPLORER_COLUMNS + list(config.REQUIRED_COLUMNS)) if c in df.columns]
    frame = df[cols].copy()
    rows = [jsonable(r) for r in frame.to_dict("records")]
    links = df["fuente"].map(link_of).tolist()
    for r, link in zip(rows, links):
        r["link"] = link
        r["medicion"] = MEASUREMENTS.get(str(r.get("experimento")), {}).get("cat", "")  # C11
    return {"columns": cols + ["medicion"], "required": list(config.REQUIRED_COLUMNS), "rows": rows,
            "measure_labels": {k: {"en": v[0], "es": v[1]} for k, v in CATEGORIES.items()},
            "fuels": sorted(map(str, df["combustible"].unique())), "phases": list(config.PHASES)}


def _phase_color(L: str) -> alt.Color:
    return alt.Color("fase_label:N", title=t("col.phase", L), scale=alt.Scale(
        domain=[phase_name(p, L) for p in config.PHASES], range=[config.PHASE_COLORS[p] for p in config.PHASES]))


def _tooltip(L: str) -> list:
    return [alt.Tooltip("row_id:N", title=t("col.row", L)), alt.Tooltip("experimento:N", title=t("col.experiment", L)),
            alt.Tooltip("combustible:N", title=t("col.fuel", L)), alt.Tooltip("oxigeno_num:Q", title=t("col.oxygen", L)),
            alt.Tooltip("presion_num:Q", title=t("col.pressure", L)), alt.Tooltip("resultado:N", title=t("col.result", L)),
            alt.Tooltip("fase_label:N", title=t("col.phase", L)), alt.Tooltip("fuente:N", title=t("col.source", L))]


def _outcome_label(r: pd.Series, L: str) -> str:
    if bool(r.get("extinguished")):
        return t("outcome.extinguished", L)
    if bool(r.get("no_ignition")):
        return t("outcome.no_ignition", L)
    if bool(r.get("burned")):
        return t("outcome.burned", L)
    if bool(r.get("outcome_not_listed")):
        return t("outcome.not_listed", L)
    return t("outcome.other", L)


_CHART_CACHE: dict[tuple[int, str], dict] = {}


def _chart_specs_build(df: pd.DataFrame, L: str) -> dict:
    plot = df.dropna(subset=["oxigeno_num"]).copy()
    plot["fase_label"] = plot["fase"].map(lambda p: phase_name(p, L) if p else p)
    skipped = len(df) - len(plot)
    keep = ["row_id", "experimento", "combustible", "oxigeno_num", "presion_num", "resultado", "fase_label", "fuente",
            "extinguished", "no_ignition", "burned", "outcome_not_listed"]
    out: dict = {"oxygen_title": t("chart.oxygen_vs_result", L), "conditions_title": t("chart.conditions_vs", L)}
    if plot.empty:
        out["oxygen"] = {"spec": None, "empty": t("chart.no_oxygen", L)}
    else:
        numeric_result = plot["resultado"].map(to_number)
        data = plot[[c for c in keep if c in plot.columns]].copy()
        if numeric_result.notna().mean() >= 0.8:
            data["result_value"] = numeric_result
            y = alt.Y("result_value:Q", title=t("chart.axis_result_value", L))
            dots, height = alt.Chart(data).mark_circle(size=120, opacity=0.95, stroke=BG, strokeWidth=2), 220
        else:
            data["result_label"] = data.apply(lambda r: _outcome_label(r, L), axis=1)
            order = [t(f"outcome.{k}", L) for k in ("extinguished", "burned", "no_ignition", "other", "not_listed")]
            y = alt.Y("result_label:N", title=t("chart.outcome_axis", L), sort=order, axis=alt.Axis(labelLimit=260))
            dots = alt.Chart(data).mark_circle(size=90, opacity=0.75, stroke=BG, strokeWidth=1)
            height = max(220, 70 * data["result_label"].nunique())
        chart = dots.encode(x=alt.X("oxigeno_num:Q", title=t("chart.axis_oxygen", L), scale=alt.Scale(zero=False, padding=20)),
                            y=y, color=_phase_color(L), tooltip=_tooltip(L)).properties(height=height)
        note = t("chart.dots_note", L) + (t("chart.skipped", L, n=skipped) if skipped else "")
        out["oxygen"] = {"spec": hud(chart), "caption": note}
    both = plot.dropna(subset=["presion_num"])
    refs = pd.DataFrame(config.REFERENCE_ATMOSPHERES)
    refs["label"] = [ref_label(ref, L) for ref in config.REFERENCE_ATMOSPHERES]
    refs["pressure_atm"] = refs["pressure_psi"] * config.TO_ATM["psi"]
    if both.empty:
        out["conditions"] = {"spec": None, "empty": t("chart.no_both", L)}
    else:
        both = both[[c for c in keep if c in both.columns]]
        y_max = max(1.1, float(both["presion_num"].max()) * 1.1)
        xs, ys = alt.Scale(domain=[0, 105]), alt.Scale(domain=[0, y_max])
        data_layer = alt.Chart(both).mark_circle(size=120, opacity=0.95, stroke=BG, strokeWidth=2).encode(
            x=alt.X("oxigeno_num:Q", title=t("chart.axis_oxygen", L), scale=xs),
            y=alt.Y("presion_num:Q", title=t("col.pressure", L), scale=ys), color=_phase_color(L), tooltip=_tooltip(L))
        ref_tooltip = [alt.Tooltip("label:N", title=t("chart.reference", L)), alt.Tooltip("oxygen:Q", title=t("col.oxygen", L)),
                       alt.Tooltip("pressure_psi:Q", title=t("col.pressure_psi", L)),
                       alt.Tooltip("pressure_atm:Q", title=t("col.pressure", L), format=".3f")]
        ref_points = alt.Chart(refs).mark_point(shape="diamond", size=170, filled=False, color=MUTED, strokeWidth=2).encode(
            x=alt.X("oxygen:Q", scale=xs), y=alt.Y("pressure_atm:Q", scale=ys), tooltip=ref_tooltip)
        left = alt.Chart(refs[refs["oxygen"] < 80]).mark_text(align="left", dx=10, dy=-10, color=MUTED, fontSize=12).encode(
            x=alt.X("oxygen:Q", scale=xs), y=alt.Y("pressure_atm:Q", scale=ys), text="label:N")
        right = alt.Chart(refs[refs["oxygen"] >= 80]).mark_text(align="right", dx=-10, dy=-10, color=MUTED, fontSize=12).encode(
            x=alt.X("oxygen:Q", scale=xs), y=alt.Y("pressure_atm:Q", scale=ys), text="label:N")
        out["conditions"] = {"spec": hud((data_layer + ref_points + left + right).properties(height=380)),
                             "caption": t("chart.conditions_note", L)}
    return out


def chart_specs(df: pd.DataFrame, lang: str) -> dict:
    key = (id(df), normalize_lang(lang))
    if key not in _CHART_CACHE:
        _CHART_CACHE[key] = _chart_specs_build(df, key[1])
    return _CHART_CACHE[key]


# ---------------------------------------------------------------------------
# Alternative page (web/panel.html): its documented JSON contract, filled from the real engine + agent.
# No number here is new: verdict, diluents, rows and the oxygen bins all come from the dataset / engine.
# ---------------------------------------------------------------------------

_V2_PHASE = {"prevent": "PREVENT", "detect": "DETECT", "extinguish": "EXTINGUISH"}


def _v2_outcome(r) -> str | None:
    if bool(r.get("extinguished")):
        return "extinguished"
    if bool(r.get("burned")):
        return "sustained"
    return None


def _v2_row(r, lang: str) -> dict:
    o2, p = r.get("oxigeno_num"), r.get("presion_num")
    return {"id": str(r.get("row_id")), "kind": "row", "platform": str(r.get("experimento") or ""),
            "experiment": doi_of(str(r.get("fuente") or "")), "fuel": str(r.get("combustible") or ""),
            "o2_pct": jsonable(o2), "diluent": str(r.get("diluent") or "") or None, "pressure_atm": jsonable(p),
            "d0_mm": None, "outcome": _v2_outcome(r), "t_ext_s": None,
            "note": str(r.get("resultado") or "")[:160], "url": link_of(r.get("fuente"))}


def _v2_oxygen_bins(df: pd.DataFrame, fuel: str | None, asked) -> dict | None:
    if not fuel or "combustible" not in df.columns:
        return None
    rows = df[(df["combustible"].astype(str).str.lower() == str(fuel).lower()) & df["oxigeno_num"].notna()]
    if rows.empty:
        return None
    level = rows["oxigeno_num"].round(0)
    bins = []
    for o2, grp in rows.groupby(level):
        bins.append({"o2_pct": float(o2), "extinguished": int(grp["extinguished"].astype(bool).sum()),
                     "total": int(len(grp))})
    return {"query_o2_pct": jsonable(asked), "bins": bins}


def panel_payload(out: dict, res: Result, ai: dict, df: pd.DataFrame, seconds: float) -> dict:
    """Map the real /api/ask answer onto the contract documented at the top of web/panel.html."""
    L = out.get("lang") or res.lang
    view = out.get("view") or {}
    v = view.get("verdict") or {}
    det = view.get("detected") or {}
    by_id = df.drop_duplicates("row_id").set_index("row_id", drop=False) if "row_id" in df.columns else None

    def rows_for(ids):
        found = []
        for rid in ids:
            if by_id is not None and rid in by_id.index:
                found.append(_v2_row(by_id.loc[rid].to_dict(), L))
        return found

    ids = list(v.get("ids") or [])
    if ai.get("ok"):
        for r in ai.get("cited_rows") or []:
            if r.get("row_id") and r["row_id"] not in ids:
                ids.append(r["row_id"])
        parts = [f"{ai.get(k + '_label')}: {strip_tags(ai[k + '_html'])}" for k in ("conclusion", "recommendation")
                 if ai.get(k + "_html")]
        parts.append(strip_tags(ai.get("summary_html", "")))
        parts += [f"{c['phase_label']} · {strip_tags(c['html'])}" for c in ai.get("claims") or []]
        if ai.get("limitations_html"):
            parts.append(strip_tags(ai["limitations_html"]))
        interpretation = "\n\n".join(p for p in parts if p)
        answered_by = ai.get("badge") or ai.get("mode")
    else:
        interpretation = str(v.get("answer") or "")  # the technical reason (ai["note"]) goes to model_trace only
        answered_by = ai.get("badge") or t("ai.badge_engine", L)

    lead = out.get("lead") or {}
    nodata = lead.get("state") == "nodata"
    if nodata:
        interpretation = " ".join(x for x in (lead.get("sentence"), lead.get("reason")) if x)
    elif lead.get("sentence"):
        interpretation = lead["sentence"] + " " + str(lead.get("confidence") or "") + "\n\n" + interpretation
    label_bits = [str(lead.get("sentence") or "")] if nodata else [str(v.get("headline") or "")]
    if det.get("o2") is not None:
        label_bits.append(f"{num(det['o2'])} % O2")
    if det.get("fuel"):
        label_bits.append(term(str(det["fuel"]), L))
    attempts = [{"name": f"{a['model']} · {a['step']}", "status": "ok" if a["ok"] else "error",
                 "detail": a.get("detail", ""), "ms": int(round(float(a.get("seconds") or 0) * 1000))}
                for a in ai.get("attempts") or []]
    attempts.append({"name": t("ai.engine_name", L), "status": "ok", "detail": "", "ms": int(out.get("engine_seconds", 0) * 1000)})
    pipeline = [s["label"] + (f" · {s['model']}" if s.get("model") else "") for s in ai.get("trace") or []]
    if not pipeline:
        pipeline = [t("ai.dot.question", L), t("ai.dot.engine", L), t("ai.dot.ui_engine", L)]
    actions = []
    for a in view.get("actions") or []:
        ph = _V2_PHASE.get(str(a.get("phase") or det.get("phase") or "").lower())
        text = ". ".join(str(a.get(k) or "") for k in ("title", "body") if a.get(k)).strip()
        actions.append({"phase": ph, "text": strip_tags(text)})
    return {
        "question": out.get("question"), "lang": L,
        "phase": _V2_PHASE.get(str(det.get("phase") or "").lower(), None),
        "out_of_scope": bool(out.get("out_of_scope")),
        "verdict": {"numerator": None if nodata else v.get("n"), "denominator": None if nodata else v.get("k"),
                    "label": " · ".join(b for b in label_bits if b),
                    "summary": str(lead.get("reason") or "") if nodata else str(v.get("sample") or "")},
        "lead": lead or None,
        "interpretation": interpretation,
        "evidence": rows_for(ids),
        "oxygen": _v2_oxygen_bins(df, det.get("fuel"), det.get("o2")),
        "diluents": [{"name": d["gas"], "extinguished": d["extinguished"], "total": d["rows"]}
                     for d in view.get("diluent") or [] if d.get("rows")],
        "model_trace": {"answered_by": answered_by, "answered_by_tech": ai.get("tech_badge") or answered_by,
                        "note": str(ai.get("note") or ""), "fallback_used": not ai.get("ok"), "attempts": attempts,
                        "rows_scanned": int(len(df)), "rows_matched": v.get("k"),
                        "latency_ms": int(round(seconds * 1000)), "pipeline": pipeline},
        "actions": actions,
        "warnings": list(lead.get("notices") or []) + list(out.get("warnings") or []),
    }


def strip_tags(html_text: str) -> str:
    return re.sub(r"<[^>]+>", "", str(html_text or "")).replace("&amp;", "&").replace("&lt;", "<") \
        .replace("&gt;", ">").replace("&quot;", '"').replace("&#x27;", "'").replace("&#39;", "'")


# ---------------------------------------------------------------------------
# What the browser receives (15 nov 2026, Jeanpiere): the page shows exactly what the jury sees and
# there is no way to show anything else. Model names, attempts, timings, the AI trace, tool calls and the
# technical reason for an engine-only answer stay in the backend (ai_payload / logs); they are not sent.
# ---------------------------------------------------------------------------

PUBLIC_AI_KEYS = (
    "ok", "title", "badge", "user_note", "enough_evidence", "insufficient_note", "summary_html",
    "conclusion_label", "conclusion_html", "recommendation_label", "recommendation_html", "claims_title", "claims",
    "chart", "limitations_label", "limitations_html", "missing_label", "missing_html", "cited_rows", "row_urls",
)
PUBLIC_CLAIM_KEYS = ("phase", "phase_label", "kind", "kind_label", "html", "row_ids", "evidence_ids")
PRIVATE_ASK_KEYS = ("mode", "engine_seconds", "view_error")
_PRIVATE_STRING_PREFIXES = (
    "ai.tech_", "hud.tech_", "ai.engine_reason.", "ai.dot.", "ai.col.", "ai.how", "ai.agent", "ai.engine_name",
    "ai.seconds", "ai.ok", "ai.fail", "sidebar.", "anim.confidence", "word.confidence", "word.keywords",
    "dash.phase_pill", "res.gemini_expander", "term.gemini + rules", "term.rules",
)


def public_ai(ai: dict) -> dict:
    """The AI panel as the page draws it: answer, citations and chart only."""
    out = {k: ai[k] for k in PUBLIC_AI_KEYS if k in ai}
    if out.get("claims"):
        out["claims"] = [{k: c[k] for k in PUBLIC_CLAIM_KEYS if k in c} for c in out["claims"]]
    return out


def public_ask(out: dict) -> dict:
    data = {k: v for k, v in out.items() if k not in PRIVATE_ASK_KEYS}
    if isinstance(data.get("ai"), dict):
        data["ai"] = public_ai(data["ai"])
    return data


def public_panel(payload: dict) -> dict:
    data = dict(payload)
    tr = payload.get("model_trace") or {}
    data["model_trace"] = {"answered_by": tr.get("answered_by", ""), "fallback_used": bool(tr.get("fallback_used"))}
    return data


def public_strings(strings: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    return {L: {k: v for k, v in table.items() if not k.startswith(_PRIVATE_STRING_PREFIXES)}
            for L, table in strings.items()}


def public_meta(meta: dict) -> dict:
    data = {k: v for k, v in meta.items() if k not in ("gather_models", "interpret_models")}
    data["strings"] = public_strings(meta.get("strings") or {})
    return data
