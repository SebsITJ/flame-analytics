"""Flame in Freefall — Streamlit app. Run with:  uv run streamlit run app.py

Assistant tab flow (st.session_state["stage"]):
    "ask"         hero + question box + chips (EN/ES toggle)
    "classifying" the mission-control animation: the question is read, drops into its PREVENT / DETECT /
                  EXTINGUISH bin, is placed on the map of every experiment, the map narrows to the rows the
                  engine retrieved and they are counted. It is drawn from the real Result, so the pipeline
                  runs first (after the other tabs are drawn); "View results" or the timer moves on.
    "results"     a one-screen dashboard in the language of the question, plus a "New question" button
The language of the whole interface follows st.session_state["lang"]: the toggle sets it, and submitting a
question sets it to the language detected in that question.

Look: flame/theme.py (page CSS), flame/animation.py (stage 2), flame/dashboard.py (stage 3). The numbers
come from flame/viz_payload.py, which only reads the table and the pipeline Result.
"""

from __future__ import annotations

import sys
import inspect
import time

import altair as alt
import pandas as pd
import streamlit as st

from flame import config
from flame.animation import HEIGHT as LEGACY_ANIMATION_HEIGHT
from flame.animation import MISSION_HEIGHT, build_animation_html, build_mission_html
from flame.dashboard import dashboard_html, strip_html
from flame.data import DataError, load_dataset, source_url, to_number
from flame.enrich import display_gas
from flame.i18n import LANGS, STRINGS, detect_language, localize_issue, phase_name, ref_label, t
from flame.agent import ENGINE_MODE, AIOutcome, make_client, run_ai
from flame.ai_view import build_chart, cited_ids, linkify, row_urls
from flame.llm import get_api_key
from flame.pipeline import Result, answer_question
from flame.retrieval import filter_by_oxygen, metric_rows
from flame.theme import BG, THEME_CSS, brand_html, esc, footer_html, hero_html, loader_html
from flame.viz_payload import build_animation_payload, build_dashboard_view, source_links

# The sidebar (data upload, Gemini status) starts collapsed so the console has the whole screen; "»" opens it.
st.set_page_config(page_title="Flame in Freefall · Fire Safety Evidence", page_icon="🔥", layout="wide",
                   initial_sidebar_state="collapsed")

SURFACE = BG  # page background, used for the ring around chart marks
MUTED = "#c3c2b7"
SEE_RESULTS_KEY = "see_results"  # the animation's "View results" control presses the button with this key
# Arguments that changed across Streamlit versions; use whichever this one has.
_STRETCH = {"width": "stretch"} if "width" in inspect.signature(st.button).parameters else {"use_container_width": True}
_VCENTER = {"vertical_alignment": "center"} if "vertical_alignment" in inspect.signature(st.columns).parameters else {}

for _key, _default in (("lang", "en"), ("stage", "ask"), ("result", None), ("pending_question", ""), ("error", None),
                       ("ai", None)):
    st.session_state.setdefault(_key, _default)
lang = st.session_state["lang"] if st.session_state["lang"] in LANGS else "en"


def T(key: str, **kwargs) -> str:
    """Text in the current interface language."""
    return t(key, lang, **kwargs)


def show_html(page: str, height: int) -> None:
    """Embed a self-contained HTML document: st.iframe on current Streamlit, components.html on older ones."""
    if hasattr(st, "iframe"):
        st.iframe(page, height=height)
    else:
        import streamlit.components.v1 as components

        components.html(page, height=height)


def markup(fragment: str) -> None:
    """Draw trusted, already-escaped HTML built by flame.theme / flame.dashboard."""
    st.markdown(fragment, unsafe_allow_html=True)


def md(text: str) -> str:
    """Stop '$' in model text from being rendered as LaTeX."""
    return str(text).replace("$", "\\$")


def num(x) -> str:
    return "?" if pd.isna(x) else f"{round(float(x), 4):g}"


# ---------------------------------------------------------------------------
# Data and model
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_from_path(path: str, mtime: float):
    return load_dataset(path)


@st.cache_data(show_spinner=False)
def load_from_bytes(raw: bytes):
    return load_dataset(raw)


@st.cache_resource(show_spinner=False)
def get_ai_client(api_key: str):
    """google-genai client for the AI interpreter (flame/agent.py). The key comes from env or st.secrets only."""
    return make_client(api_key)


markup(THEME_CSS)

with st.sidebar:
    st.header(T("sidebar.data"))
    upload = st.file_uploader(T("sidebar.upload"), type=["csv", "txt"], key="csv_upload")
    try:
        if upload is not None:
            dataset = load_from_bytes(upload.getvalue())
            data_name = upload.name
        else:
            dataset = load_from_path(str(config.DATA_PATH), config.DATA_PATH.stat().st_mtime)
            data_name = config.DATA_PATH.name
    except (DataError, FileNotFoundError) as err:
        st.error(T("sidebar.load_error", err=err))
        st.stop()

    df = dataset.df
    st.caption(T("sidebar.dataset_caption", name=data_name, rows=len(df), experiments=df["experimento"].nunique()))
    st.caption(T("sidebar.encoding", encoding=dataset.encoding, delimiter=dataset.delimiter))
    if dataset.issues:
        with st.expander(T("sidebar.issues", n=len(dataset.issues))):
            for issue in dataset.issues:
                st.write("• " + localize_issue(issue, lang))

    api_key = get_api_key()
    client = None  # v7: the deterministic engine always answers; Gemini only interprets (run_ai)
    if api_key:
        try:
            client = get_ai_client(api_key)
        except Exception as err:  # the page never shows SDK/model details; the engine still answers
            print(f"[flame] Gemini client unavailable: {type(err).__name__}", file=sys.stderr)

markup(brand_html(lang, rows=len(df), experiments=int(df["experimento"].nunique()), gemini=client is not None))

if dataset.has_simulated:
    st.warning(T("simulated_warning", n_sim=int(df["simulated"].sum()), n_rows=len(df)), icon="⚠️")

tab_assistant, tab_explorer, tab_charts = st.tabs([T("tab.assistant"), T("tab.explorer"), T("tab.charts")])


# ---------------------------------------------------------------------------
# Assistant: ask -> classifying -> results
# ---------------------------------------------------------------------------

def set_question(text: str) -> None:
    st.session_state["question"] = text


def on_lang_change() -> None:
    st.session_state["lang"] = str(st.session_state.get("lang_widget", "EN")).lower()


def start_classification(question: str) -> None:
    """Remember the question, switch the interface to its language and move to the animation."""
    st.session_state.update(
        pending_question=question,
        lang=detect_language(question, default=lang),
        stage="classifying",
        result=None,
        error=None,
        ai=None,
    )
    st.rerun()


def go_results() -> None:  # "View results": the button under the animation, also pressed from inside it
    st.session_state["stage"] = "results"


def reset_flow() -> None:
    st.session_state.update(stage="ask", result=None, pending_question="", error=None, ai=None)
    st.session_state.pop("question", None)


def render_ask() -> None:
    markup(hero_html(lang))
    _l, mid, _r = st.columns([5, 2, 5])
    with mid:
        st.session_state["lang_widget"] = lang.upper()
        st.radio(
            T("lang.label"), ["EN", "ES"], horizontal=True, key="lang_widget",
            label_visibility="collapsed", on_change=on_lang_change,
        )
    markup(f'<div class="ff-lang-note">{esc(T("lang.note"))}</div>')

    with st.form("ask", border=True):
        question = st.text_area(
            T("ask.label"), key="question", height=70, label_visibility="collapsed", placeholder=T("ask.placeholder"),
        )
        submitted = st.form_submit_button(T("ask.button"), type="primary")

    _pad_l, c1, c2, c3, _pad_r = st.columns([1.2, 1, 1, 1, 1.2])
    for col, kind in zip((c1, c2, c3), ("prevent", "detect", "extinguish")):
        col.button(T(f"chip.{kind}"), key=f"chip_{kind}", on_click=set_question, args=(T(f"example.{kind}"),), **_STRETCH)

    if submitted:
        if question.strip():
            start_classification(question.strip())
        else:
            st.info(T("ask.empty"))


_ASK_ELEMENTS = 10  # more than the ask stage draws (hero, language, form, chips, notes)


def animation_page(question: str, res: Result | None) -> tuple[str, int]:
    """(HTML document, height) for stage 2. Falls back to the simple card: decoration never blocks an answer."""
    if res is not None:
        try:
            payload = build_animation_payload(question, df, res, lang=res.lang, colors=config.PHASE_COLORS)
            return build_mission_html(payload, button_key=SEE_RESULTS_KEY), MISSION_HEIGHT
        except Exception:
            pass
    try:
        c = res.conditions if res is not None else None
        clf = (res.classification or c.classification) if res is not None else None
        subject = c.subject.summary(lang) if c is not None and c.subject else T("none_m")
        page = build_animation_html(question, clf.phase if clf else None, None,  # the classifier's certainty is never shown
                                    subject, lang, config.PHASE_COLORS)
    except Exception:
        page = build_animation_html(question, None, 0.0, T("none_m"), lang, config.PHASE_COLORS)
    return page, LEGACY_ANIMATION_HEIGHT


def draw_animation(slot, res: Result | None) -> None:
    """Put the animation in ``slot`` and start the clock that finish_classifying() waits on."""
    global anim_started
    page, height = animation_page(st.session_state["pending_question"], res)
    with slot.container():
        show_html(page, height)
    anim_started = time.monotonic()


def render_classifying():
    """Reserve the animation slot. It is filled in finish_classifying(), once the other tabs are drawn
    and the pipeline has answered, so Explorer and Charts never wait for the engine."""
    slot = st.empty()
    if st.session_state.get("result") is not None:  # a rerun while the animation was playing
        draw_animation(slot, st.session_state["result"])
    else:
        slot.markdown(loader_html(lang), unsafe_allow_html=True)
    _l, mid, _r = st.columns([4, 2, 4])
    mid.button(T("btn.see_results"), key=SEE_RESULTS_KEY, on_click=go_results, **_STRETCH)
    # Streamlit keeps the previous run's elements on screen until the script ends, and this run stays alive
    # while the animation plays. Overwriting the leftover positions (the ask form) with empty slots removes them at once.
    for _ in range(_ASK_ELEMENTS):
        st.empty()
    return slot


def finish_classifying(slot) -> None:
    """Runs after the other tabs are drawn: answer the question, play the animation with it, move on."""
    question = st.session_state["pending_question"]
    res = st.session_state.get("result")
    if res is None:
        try:
            # The engine answers on its own (no LLM inside); its numbers never depend on Gemini.
            res = answer_question(question, df, None, lang)
        except Exception as err:
            st.session_state.update(error=f"{type(err).__name__}: {err}", stage="results")
            st.rerun()
        st.session_state["result"] = res
        draw_animation(slot, res)
    if st.session_state.get("ai") is None:
        note = st.empty()
        if client is not None:
            note.caption(t("ai.working", res.lang))
        st.session_state["ai"] = ai_outcome(question, res)
        note.empty()
    pause = config.ANIMATION_SECONDS - (time.monotonic() - anim_started)
    if pause > 0:
        time.sleep(pause)
    st.session_state.update(result=res, stage="results")
    st.rerun()


def ai_outcome(question: str, res: Result) -> AIOutcome:
    """Gemini interprets the engine's evidence; any failure gives an engine-only outcome (never an exception)."""
    try:
        return run_ai(question, df, res, client, res.lang)
    except Exception as err:  # defensive: the dashboard must always open
        out = AIOutcome(mode=ENGINE_MODE, lang=res.lang)
        out.reason = "errors"
        out.problems = [type(err).__name__]
        return out


def render_results() -> None:
    question = st.session_state.get("pending_question", "")
    if st.session_state.get("error"):
        st.button(T("btn.new_question"), key="new_question", on_click=reset_flow, type="primary")
        print(f"[flame] pipeline error: {st.session_state['error']}", file=sys.stderr)
        st.error(T("err.pipeline_user"))
        return
    res = st.session_state.get("result")
    if res is None:  # e.g. "View results" was pressed before the answer was ready
        with st.spinner(T("spinner.searching")):
            res = answer_question(question, df, None, lang)
        st.session_state["result"] = res
    if st.session_state.get("ai") is None:
        with st.spinner(t("ai.working", res.lang)):
            st.session_state["ai"] = ai_outcome(question, res)
    render_result(res, st.session_state.get("ai"))


def render_result(res: Result, ai: AIOutcome | None = None) -> None:
    """Draw one answer as the dashboard. Every text comes from res.lang, so it never mixes languages."""
    L = res.lang
    try:
        view = build_dashboard_view(res, df, url_for=source_url)
        strip, board = strip_html(view), dashboard_html(view, include_strip=False)
    except Exception:  # the dashboard is presentation; the written answer below is always available
        view = None

    left, right = st.columns([1.3, 8], **_VCENTER)
    left.button(t("btn.new_question", L), key="new_question", on_click=reset_flow, type="primary", **_STRETCH)
    if view is None:
        right.caption(f"{t('results.your_question', L)}: {md(res.question)}")
        render_written(res)
        render_metric_chart(res)
        render_calculations(res)
        render_ranked(res)
        return
    with right:
        markup(strip)
    for w in res.warnings:
        st.warning(w)
    markup(board)

    if view["state"] == "out_of_scope":
        return
    render_ai(res, ai)
    render_metric_chart(res)
    c1, c2, c3 = st.columns(3)
    with c1:
        with st.expander(t("res.calculations", L)):
            render_calculations(res)
    with c2:
        with st.expander(t("dash.full_answer", L)):
            render_written(res, show_warnings=False)
    with c3:
        render_ranked(res)
    if res.mode == "gemini":
        with st.expander(t("res.gemini_expander", L)):
            st.json(res.payload)


_CHART_TITLES = {"oxigeno": "col.oxygen", "presion": "col.pressure", "combustible": "col.fuel",
                 "experimento": "col.experiment", "fase": "col.phase", "diluente": "col.diluent"}


def render_ai(res: Result, ai: AIOutcome | None) -> None:
    """The AI panel: mode badge, interpretation with clickable citations, chart from engine rows, trace."""
    L = res.lang
    st.markdown(f"#### {t('ai.title', L)}")
    if ai is None or not ai.ok:
        # why the AI did not answer (no key, quota, verifier...) stays out of the page
        markup(f'<span class="ff-ai-badge ff-ai-engine">{esc(t("ai.badge_engine", L))}</span>')
        st.caption(t("ai.engine_user_note", L))
        return
    a = ai.answer
    badge = t("ai.badge_hybrid" if getattr(ai, "hybrid", False) else "ai.badge_model", L)  # no model names or timings
    markup(f'<span class="ff-ai-badge">✦ {esc(badge)}</span>')
    urls = row_urls(df, cited_ids(a))
    if not a.enough_evidence:
        st.warning(t("ai.insufficient", L) + " " + t("insufficient", L))
    st.markdown(linkify(a.summary, urls))
    if a.conclusion.strip():
        st.markdown(f"**{t('ai.conclusion', L)}:** {linkify(a.conclusion, urls)}")
    if a.recommendation.strip():
        st.markdown(f"**{t('ai.recommendation', L)}:** {linkify(a.recommendation, urls)}")
    if a.agents:
        st.markdown(f"**{t('ai.agents_title', L)}**")
        for f in a.agents:
            st.markdown(f"- **{t('ai.agent.' + f.agent, L)}** — {linkify(f.finding, urls)}")
    if a.claims:
        st.markdown(f"**{t('ai.claims', L)}**")
        for c in a.claims:
            phase = phase_name(c.phase, L).capitalize() if c.phase in config.PHASES else t("ai.phase.general", L)
            st.markdown(f"- **{phase}** · _{t('ai.kind.' + c.kind, L)}_ — {linkify(c.text, urls)}")
    if a.chart is not None:
        titles = {k: t(v, L) for k, v in _CHART_TITLES.items()}
        titles.update({k: t(f"ai.field.{k}", L) for k in ("metric_value", "extinguished", "flame_recorded",
                                                           "did_not_ignite")})
        try:
            chart = build_chart(a.chart, ai.ledger, titles)
        except Exception:
            chart = None
        if chart is not None:
            st.altair_chart(hud(chart), use_container_width=True)
            st.caption(t("ai.chart_caption", L, kind=a.chart.type, eid=a.chart.evidence_id))
    if a.limitations.strip():
        st.markdown(f"**{t('ai.limitations', L)}:** {linkify(a.limitations, urls)}")
    if a.missing.strip():
        st.markdown(f"**{t('ai.missing', L)}:** {linkify(a.missing, urls)}")
    rows = [ai.ledger.rows[i] for i in cited_ids(a) if i in ai.ledger.rows]
    if rows:
        with st.expander(f"{t('ai.cited_rows', L)} ({len(rows)})"):
            table = pd.DataFrame(rows)[["row_id", "experimento", "combustible", "oxigeno", "presion", "resultado"]]
            table["fuente"] = table["row_id"].map(lambda r: urls.get(r.upper(), ""))
            st.dataframe(table, hide_index=True, column_config={
                "row_id": t("col.row", L), "experimento": t("col.experiment", L), "combustible": t("col.fuel", L),
                "oxigeno": st.column_config.NumberColumn(t("col.oxygen", L)),
                "presion": st.column_config.NumberColumn(t("col.pressure", L)),
                "resultado": t("col.result", L), "fuente": st.column_config.LinkColumn(t("col.source", L))})


def render_metric_chart(res: Result) -> None:
    """Bar chart of the metric the question compares (spread rate, duration...). Teammate's idea, bilingual.

    Only drawn when the question names a metric; one bar per recorded row, capped, highest first.
    """
    c = res.conditions
    metric_key = getattr(c, "comparison_metric", None)
    if not metric_key:
        return
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
    st.markdown(f"**{t('chart.metric_title', L, metric=metric[:1].upper() + metric[1:], o2=o2_label)}**")
    if rows.empty:
        st.info(t("chart.metric_none", L))
        return
    if o2_mode == "nearest":
        st.warning(o2_note)
    cap = config.METRIC_CHART_MAX_ROWS
    rows = rows.sort_values("result_metric", ascending=False).head(cap).copy()
    unit = str(rows["result_metric_unit"].iloc[0])
    rows["chart_label"] = (rows["row_id"].astype(str) + " | " + rows["experimento"].astype(str) + " | "
                           + rows["combustible"].astype(str) + " | " + rows["flujo"].astype(str) + " | "
                           + pd.to_numeric(rows["oxigeno_num"], errors="coerce").map(
                               lambda v: "O₂ ?" if pd.isna(v) else f"{v:g} % O₂"))
    base = alt.Chart(rows).encode(
        x=alt.X("result_metric:Q", title=f"{metric} ({unit})", scale=alt.Scale(zero=True, nice=True)),
        y=alt.Y("chart_label:N", title=None, sort="-x", axis=alt.Axis(labelLimit=320, labelFontSize=11)),
        tooltip=[alt.Tooltip("row_id:N", title=t("col.row", L)), alt.Tooltip("experimento:N", title=t("col.experiment", L)),
                 alt.Tooltip("combustible:N", title=t("col.fuel", L)), alt.Tooltip("oxigeno_num:Q", title=t("col.oxygen", L)),
                 alt.Tooltip("result_metric:Q", title=f"{metric} ({unit})")],
    )
    bars = base.mark_bar(cornerRadiusEnd=6, size=22, color=config.TELEMETRY_COLOR)
    values = base.mark_text(align="left", baseline="middle", dx=6, fontSize=12, color="#e8ecf4").encode(
        text=alt.Text("result_metric:Q", format=".2f"))
    st.altair_chart(hud((bars + values).properties(height=max(140, len(rows) * 32))), use_container_width=True)
    st.caption(t("chart.metric_caption", L, n=len(rows)) + " " + o2_note)


def render_calculations(res: Result) -> None:
    L = res.lang
    if res.calculations and res.calculations.lines:
        for line in res.calculations.lines:
            st.markdown("- " + md(line))
        st.caption(t("res.nist_caption", L))
    else:
        st.caption(t("phy.no_o2", L))


def render_written(res: Result, show_warnings: bool = True) -> None:
    """The full written answer: conditions read, answer, actions, P / D / E, evidence, limitations, sources."""
    L = res.lang
    c = res.conditions
    clf = res.classification or c.classification

    if clf and clf.out_of_scope:
        st.markdown(f"**{t('res.conditions', L)}**")
        st.info(
            f"**{t('label.phase', L)}:** {phase_name('out_of_scope', L)}"
        )
        if c.subject and not c.subject.is_empty():
            st.caption(f"{t('label.subject', L)}: " + c.subject.summary(L))
        st.warning(md(res.draft.answer))
        return

    found = [
        t("cond.o2", L, value=f"{c.oxygen:g}") if c.oxygen is not None else None,
        t("cond.pressure", L, text=c.pressure_text, atm=f"{c.pressure_atm:.3g}") if c.pressure_atm is not None else None,
        t("cond.fuel", L, fuel=c.fuel) if c.fuel else None,
    ]
    found = [f for f in found if f]
    phase_txt = phase_name(c.phase, L) if c.phase else t("phase.none", L)  # no certainty or keywords
    subject_txt = c.subject.summary(L) if c.subject else t("none_m", L)

    st.markdown(f"**{t('res.conditions', L)}**")
    st.markdown(
        f"- **{t('label.phase', L)}:** {phase_txt}\n"
        f"- **{t('label.subject', L)}:** {subject_txt}\n"
        f"- **{t('label.stated', L)}:** " + (" · ".join(found) if found else t("none_f", L))
    )

    if show_warnings:
        for w in res.warnings:
            st.warning(w)

    d = res.draft
    st.markdown(f"**{t('res.answer', L)}**")
    if res.insufficient:
        st.error(t("insufficient", L))
        if res.missing:
            st.markdown(t("res.missing_title", L) + "\n" + "\n".join(f"- {md(m)}" for m in res.missing))
        if not res.retrieval.hits.empty:
            st.info(t("res.closest", L))
    if not res.retrieval.hits.empty:
        st.markdown(md(d.answer))

        st.markdown(f"**{t('res.actions', L)}**")
        if res.actions:
            for a in res.actions:
                st.markdown("- " + md(a))
        else:
            st.markdown(t("res.no_actions", L))

        st.markdown(f"**{t('res.pde', L)}**")
        for kind, text_ in (("prevent", d.prevent), ("detect", d.detect), ("extinguish", d.extinguish)):
            body = md(text_) if text_.strip() else t("no_evidence", L)
            st.markdown(f"**{phase_name(kind, L).capitalize()}:** {body}")

        st.markdown(f"**{t('res.evidence', L)}**")
        hits = res.retrieval.hits.set_index("row_id")
        for e in d.evidence:
            rid = e.row_id.strip().upper()
            if rid in hits.index:
                r = hits.loc[rid]
                flag = f" · **{t('res.outcome_not_listed', L)}**" if bool(r.get("outcome_not_listed")) else ""
                st.markdown(
                    f"- **{rid}** · {md(r.experimento)} · {md(r.combustible)} · "
                    + (t("res.o2_not_listed", L) if pd.isna(r.oxigeno_num) else f"{num(r.oxigeno_num)} % O2") + " · "
                    + (t("res.p_not_listed", L) if pd.isna(r.presion_num) else f"{num(r.presion_num)} atm")
                    + f"{flag} — {md(e.how_used)}"
                )

        st.markdown(f"**{t('res.limitations', L)}**")
        st.markdown(md(d.limitations) or t("res.none_stated", L))

    st.markdown(f"**{t('res.sources', L)}**")
    if res.sources:
        for s in res.sources:
            links = source_links(s["source"], L)  # "DOI | PSI page" cells become two clean links
            ref = " · ".join(f"[{md(k['label'])}]({k['url']})" if k["url"] else md(k["label"]) for k in links) \
                or md(s["source"])
            st.markdown(f"- {s['rows']} · {md(s['experiments'])} — {ref}")
    else:
        st.markdown(t("res.no_sources", L))


def render_ranked(res: Result) -> None:
    L = res.lang
    with st.expander(t("res.ranked_expander", L)):
        st.caption(t("relevance_help", L))
        hits = res.retrieval.hits.copy()
        # Human-readable gas cells; keep numeric columns too.
        for col, unit in (
            ("co2_start_ppm", "ppm"),
            ("co2_end_ppm", "ppm"),
            ("co_start_ppm", "ppm"),
            ("co_end_ppm", "ppm"),
            ("o2_start_pct", "% vol"),
            ("o2_end_pct", "% vol"),
        ):
            if col in hits.columns:
                hits[col + "_display"] = hits[col].map(lambda v, u=unit: display_gas(v, u, L))
        hits["fase"] = hits["fase"].map(lambda p: phase_name(p, L) if p else p)
        cols = ["row_id", "relevance", "relevance_breakdown"]
        cols += [c_ for c_ in hits.columns if c_.startswith("match_") or c_.startswith("score_")]
        cols += ["experimento", "combustible", "oxigeno_num", "presion_num", "fase"]
        for extra in (
            "o2_start_pct_display", "o2_end_pct_display",
            "co2_start_ppm_display", "co2_end_ppm_display",
            "co_start_ppm_display", "co_end_ppm_display",
            "diluent", "outcome_not_listed", "resultado", "fuente",
        ):
            if extra in hits.columns:
                cols.append(extra)
        labels = {
            "row_id": t("col.row", L),
            "relevance": t("col.relevance", L),
            "experimento": t("col.experiment", L),
            "combustible": t("col.fuel", L),
            "fase": t("col.phase", L),
            "resultado": t("col.result", L),
            "fuente": t("col.source", L),
            "oxigeno_num": st.column_config.NumberColumn(t("col.oxygen", L)),
            "presion_num": st.column_config.NumberColumn(t("col.pressure", L)),
            "relevance_breakdown": st.column_config.TextColumn(t("col.relevance_breakdown", L)),
            "o2_start_pct_display": t("col.o2_start", L),
            "o2_end_pct_display": t("col.o2_end", L),
            "co2_start_ppm_display": t("col.co2_start", L),
            "co2_end_ppm_display": t("col.co2_end", L),
            "co_start_ppm_display": t("col.co_start", L),
            "co_end_ppm_display": t("col.co_end", L),
            "outcome_not_listed": t("col.outcome_not_listed", L),
            "diluent": t("col.diluent", L),
        }
        for col in cols:  # match_<component> / score_<component>
            kind, _, comp = col.partition("_")
            if kind in ("match", "score") and comp:
                name = t(f"component.{comp}", L) if f"component.{comp}" in STRINGS["en"] else comp
                labels[col] = st.column_config.NumberColumn(f"{t('col.' + kind, L)} · {name}")
        st.dataframe(hits[cols], hide_index=True, column_config=labels)
        st.caption(t("res.gas_caption", L, unspecified=t("unspecified", L).capitalize()))


# ---------------------------------------------------------------------------
# Explorer
# ---------------------------------------------------------------------------

def range_filter(container, label: str, series: pd.Series, key: str):
    values = series.dropna()
    if values.empty or values.min() == values.max():
        return None
    lo, hi = float(values.min()), float(values.max())
    picked = container.slider(label, lo, hi, (lo, hi), key=key)
    return picked if picked != (lo, hi) else None


def local_phase(p) -> str:
    return phase_name(p, lang) if p else p


def render_explorer() -> None:
    f1, f2, f3 = st.columns([2, 1, 1])
    text = f1.text_input(T("exp.search"), key="exp_text")
    phases = f2.multiselect(T("col.phase"), list(config.PHASES), format_func=local_phase, key="exp_phases")
    fuels = f3.multiselect(T("col.fuel"), sorted(df["combustible"].unique()), key="exp_fuels")
    s1, s2 = st.columns(2)
    o2_range = range_filter(s1, T("col.oxygen"), df["oxigeno_num"], "exp_o2")
    p_range = range_filter(s2, T("col.pressure"), df["presion_num"], "exp_p")

    view = df
    if text:
        blob = (view["experimento"] + " " + view["combustible"] + " " + view["resultado"]).str.lower()
        view = view[blob.str.contains(text.lower(), regex=False)]
    if phases:
        view = view[view["fase"].isin(phases)]
    if fuels:
        view = view[view["combustible"].isin(fuels)]
    if o2_range:
        view = view[view["oxigeno_num"].between(*o2_range)]
    if p_range:
        view = view[view["presion_num"].between(*p_range)]

    st.caption(T("exp.rows_caption", n=len(view), total=len(df)))
    table = view.assign(link=view["fuente"].map(source_url), fase=view["fase"].map(local_phase))
    show = ["row_id", "experimento", "combustible", "oxigeno_num", "presion_num"]
    for extra in ("o2_start_pct", "o2_end_pct", "co2_start_ppm", "co2_end_ppm", "co_start_ppm", "co_end_ppm", "diluent", "outcome_not_listed"):
        if extra in table.columns:
            show.append(extra)
    show += ["resultado", "fase", "fuente", "link"]
    st.dataframe(
        table[show],
        hide_index=True,
        column_config={
            "row_id": T("col.row"),
            "experimento": T("col.experiment"),
            "combustible": T("col.fuel"),
            "oxigeno_num": st.column_config.NumberColumn(T("col.oxygen")),
            "presion_num": st.column_config.NumberColumn(T("col.pressure")),
            "o2_start_pct": st.column_config.NumberColumn(T("col.o2_start_pct")),
            "o2_end_pct": st.column_config.NumberColumn(T("col.o2_end_pct")),
            "co2_start_ppm": st.column_config.NumberColumn(T("col.co2_start_ppm")),
            "co2_end_ppm": st.column_config.NumberColumn(T("col.co2_end_ppm")),
            "co_start_ppm": st.column_config.NumberColumn(T("col.co_start_ppm")),
            "co_end_ppm": st.column_config.NumberColumn(T("col.co_end_ppm")),
            "diluent": T("col.diluent"),
            "outcome_not_listed": T("col.outcome_not_listed"),
            "resultado": T("col.result"),
            "fase": T("col.phase"),
            "fuente": T("col.source"),
            "link": st.column_config.LinkColumn(T("col.link")),
        },
    )
    st.download_button(
        T("exp.download"),
        view[config.REQUIRED_COLUMNS].to_csv(index=False).encode("utf-8"),
        file_name="flame_experiments_filtered.csv",
        mime="text/csv",
        key="exp_download",
    )


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def hud(chart):
    """Mission-control look for an Altair chart: transparent background, thin HUD grid and frame."""
    return (
        chart.configure(background="transparent")
        .configure_view(stroke="rgba(79,209,232,0.22)")
        .configure_axis(gridColor="rgba(255,255,255,0.08)", domainColor="rgba(255,255,255,0.25)",
                        tickColor="rgba(255,255,255,0.25)", labelColor="#aab2c5", titleColor="#aab2c5")
        .configure_legend(labelColor="#c9cfdc", titleColor="#aab2c5")
    )


def phase_color() -> alt.Color:
    return alt.Color(
        "fase_label:N",
        title=T("col.phase"),
        scale=alt.Scale(
            domain=[phase_name(p, lang) for p in config.PHASES],
            range=[config.PHASE_COLORS[p] for p in config.PHASES],
        ),
    )


def tooltip() -> list:
    return [
        alt.Tooltip("row_id:N", title=T("col.row")),
        alt.Tooltip("experimento:N", title=T("col.experiment")),
        alt.Tooltip("combustible:N", title=T("col.fuel")),
        alt.Tooltip("oxigeno_num:Q", title=T("col.oxygen")),
        alt.Tooltip("presion_num:Q", title=T("col.pressure")),
        alt.Tooltip("resultado:N", title=T("col.result")),
        alt.Tooltip("fase_label:N", title=T("col.phase")),
        alt.Tooltip("fuente:N", title=T("col.source")),
    ]


def outcome_label(r: pd.Series) -> str:
    """Outcome bucket of one row, from the enrich flags (same meaning as the dashboard ring)."""
    if bool(r.get("extinguished")):
        return T("outcome.extinguished")
    if bool(r.get("no_ignition")):
        return T("outcome.no_ignition")
    if bool(r.get("burned")):
        return T("outcome.burned")
    if bool(r.get("outcome_not_listed")):
        return T("outcome.not_listed")
    return T("outcome.other")


def render_charts() -> None:
    plot = df.dropna(subset=["oxigeno_num"]).copy()
    plot["fase_label"] = plot["fase"].map(local_phase)
    skipped = len(df) - len(plot)

    st.subheader(T("chart.oxygen_vs_result"))
    if plot.empty:
        st.info(T("chart.no_oxygen"))
    else:
        numeric_result = plot["resultado"].map(to_number)
        dots = alt.Chart(plot).mark_circle(size=120, opacity=0.95, stroke=SURFACE, strokeWidth=2)
        height = 220
        if numeric_result.notna().mean() >= 0.8:
            plot["result_value"] = numeric_result
            y = alt.Y("result_value:Q", title=T("chart.axis_result_value"))
        else:
            # One row per outcome, not per result text: the real table has ~800 distinct texts, which made this
            # chart ~30,000 px tall (review #10). The full text stays in the tooltip.
            plot["result_label"] = plot.apply(outcome_label, axis=1)
            order = [T(f"outcome.{k}") for k in ("extinguished", "burned", "no_ignition", "other", "not_listed")]
            y = alt.Y("result_label:N", title=T("chart.outcome_axis"), sort=order, axis=alt.Axis(labelLimit=260))
            dots = alt.Chart(plot).mark_circle(size=90, opacity=0.75, stroke=SURFACE, strokeWidth=1)
            height = max(220, 70 * plot["result_label"].nunique())
        chart = dots.encode(
            x=alt.X("oxigeno_num:Q", title=T("chart.axis_oxygen"), scale=alt.Scale(zero=False, padding=20)),
            y=y,
            color=phase_color(),
            tooltip=tooltip(),
        ).properties(height=height)
        st.altair_chart(hud(chart))
        note = T("chart.dots_note")
        if skipped:
            note += T("chart.skipped", n=skipped)
        st.caption(note)

    st.subheader(T("chart.conditions_vs"))
    both = plot.dropna(subset=["presion_num"])
    refs = pd.DataFrame(config.REFERENCE_ATMOSPHERES)
    refs["label"] = [ref_label(ref, lang) for ref in config.REFERENCE_ATMOSPHERES]
    refs["pressure_atm"] = refs["pressure_psi"] * config.TO_ATM["psi"]
    if both.empty:
        st.info(T("chart.no_both"))
    else:
        y_max = max(1.1, float(both["presion_num"].max()) * 1.1)
        x_scale = alt.Scale(domain=[0, 105])
        y_scale = alt.Scale(domain=[0, y_max])
        data_layer = alt.Chart(both).mark_circle(size=120, opacity=0.95, stroke=SURFACE, strokeWidth=2).encode(
            x=alt.X("oxigeno_num:Q", title=T("chart.axis_oxygen"), scale=x_scale),
            y=alt.Y("presion_num:Q", title=T("col.pressure"), scale=y_scale),
            color=phase_color(),
            tooltip=tooltip(),
        )
        ref_tooltip = [
            alt.Tooltip("label:N", title=T("chart.reference")),
            alt.Tooltip("oxygen:Q", title=T("col.oxygen")),
            alt.Tooltip("pressure_psi:Q", title=T("col.pressure_psi")),
            alt.Tooltip("pressure_atm:Q", title=T("col.pressure"), format=".3f"),
        ]
        ref_points = alt.Chart(refs).mark_point(shape="diamond", size=170, filled=False, color=MUTED, strokeWidth=2).encode(
            x=alt.X("oxygen:Q", scale=x_scale), y=alt.Y("pressure_atm:Q", scale=y_scale), tooltip=ref_tooltip
        )
        left = alt.Chart(refs[refs["oxygen"] < 80]).mark_text(align="left", dx=10, dy=-10, color=MUTED, fontSize=12).encode(
            x=alt.X("oxygen:Q", scale=x_scale), y=alt.Y("pressure_atm:Q", scale=y_scale), text="label:N"
        )
        right = alt.Chart(refs[refs["oxygen"] >= 80]).mark_text(align="right", dx=-10, dy=-10, color=MUTED, fontSize=12).encode(
            x=alt.X("oxygen:Q", scale=x_scale), y=alt.Y("pressure_atm:Q", scale=y_scale), text="label:N"
        )
        st.altair_chart(hud((data_layer + ref_points + left + right).properties(height=380)))
        st.caption(T("chart.conditions_note"))


# ---------------------------------------------------------------------------
# Page body. Order matters: the animation slot is reserved first, the other tabs are drawn, and only
# then does the pipeline run and the animation play (finish_classifying), so Explorer and Charts never wait.
# ---------------------------------------------------------------------------

stage = st.session_state["stage"]
anim_started = time.monotonic()
classifying = stage == "classifying" and bool(st.session_state["pending_question"])
animation_slot = None

with tab_assistant:
    if classifying:
        animation_slot = render_classifying()
    elif stage == "results":
        render_results()
    else:
        if stage != "ask":  # unknown or empty state: start over
            reset_flow()
        render_ask()

with tab_explorer:
    render_explorer()

with tab_charts:
    render_charts()

markup(footer_html(lang))
markup(f'<div class="ff-footer ff-ai-footer">{esc(T("ai.footer"))}</div>')

if classifying:
    finish_classifying(animation_slot)
