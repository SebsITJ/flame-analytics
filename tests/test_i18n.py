"""Tests for the EN/ES layer: key coverage, language detection, language-following output, the animation page
and the Assistant tab flow. Self-contained: the dataset is an inline CSV, no data/ file is needed."""
from __future__ import annotations

import html
import os
import re

import pytest

from flame import config, i18n
from flame.animation import animation_state, build_animation_html
from flame.classify import OUT_OF_SCOPE_MESSAGE, classify_question
from flame.data import load_dataset
from flame.i18n import LANGS, STRINGS, detect_language, placeholders, t
from flame.llm import DraftAnswer
from flame.pipeline import answer_question

CSV = """experimento,combustible,oxigeno,presion,resultado,fase,fuente,notas
BASS-II,PMMA,16.0,1.0,No hot ignition; flash only. O2 16.0 -> 16.0 % vol,prevent,10.1016/j.proci.2016.07.005,
BASS-II,PMMA,19.0,1.0,Hot ignition. burn time 21.0 s. O2 19.0 -> 17.8 % vol; CO2 400 -> 1660 ppm,prevent,10.1016/j.proci.2016.07.005,
BASS-II,PMMA,21.0,1.0,Hot ignition. burn time 19.0 s. O2 21.0 -> 19.8 % vol; CO2 400 -> 1740 ppm,prevent,10.1016/j.proci.2016.07.005,
SOFIE,PMMA,30.0,1.0,Flame extinguished with CO2 suppression. O2 30.0 -> 24.0 % vol,extinguish,SOFIE-REF,
SOFIE,PMMA,25.0,1.0,Dilution extinguished the flame; ambient mole fractions changed,extinguish,SOFIE-REF,
ICE,heptane,35.0,0.5,Flame kept burning; no extinction observed,extinguish,ICE-REF,
CFI-G,heptane,30.0,1.0,Flame extinguished after dilution with N2,extinguish,CFI-REF,
SAFFIRE,cotton,21.0,1.0,Smoke detected by obscuration sensor at 12 s; CO 1 -> 24 ppm,detect,SAFFIRE-REF,
"""


@pytest.fixture(scope="module")
def df():
    return load_dataset(CSV.encode("utf-8")).df


EN_Q = "How do I extinguish a fire with 30% oxygen?"
ES_Q = "¿Cómo apago un incendio con 30 % de oxígeno?"


def english_template_phrases(prefixes=("tpl.", "act.", "phy.", "warn.", "gap.", "note.")):
    """Fixed English sentences of the engine (long enough to be unambiguous). Dataset text is not among them."""
    for key, value in STRINGS["en"].items():
        if key.startswith(prefixes):
            for chunk in re.split(r"\{[^}]*\}", value):
                chunk = chunk.strip(" .;:,()")
                if len(chunk) >= 18:
                    yield chunk


# ---------------------------------------------------------------- i18n tables

def test_every_key_has_both_languages():
    for lang in LANGS:
        assert set(STRINGS[lang]) == set(STRINGS["en"]), lang
    assert all(isinstance(v, str) and v.strip() for lang in LANGS for v in STRINGS[lang].values())


def test_placeholders_match_between_languages():
    for key, en in STRINGS["en"].items():
        assert placeholders(en) == placeholders(STRINGS["es"][key]), key


def test_spanish_is_translated():
    same = [k for k, v in STRINGS["en"].items() if v == STRINGS["es"][k] and any(c.isalpha() for c in v)]
    allowed = {k for k in same if len(STRINGS["en"][k]) <= 12 or k.startswith(("ref.", "term."))}
    assert not set(same) - allowed, sorted(set(same) - allowed)


def test_t_fallbacks_and_formatting():
    assert t("tab.assistant", "es") != t("tab.assistant", "en")
    assert t("tab.assistant", "fr") == t("tab.assistant", "en")  # unknown language -> English
    assert t("tab.assistant", None) == t("tab.assistant", "en")
    assert t("no.such.key", "es") == "no.such.key"  # unknown key -> the key itself
    key = next(k for k, v in STRINGS["en"].items() if placeholders(v))
    assert t(key, "es") and "{" not in t(key, "es", **{p: 1 for p in placeholders(STRINGS["en"][key])})


def test_english_text_matches_config_constants():
    assert t("insufficient", "en") == config.INSUFFICIENT
    assert t("relevance_help", "en") == config.RELEVANCE_HELP
    from flame.physics import EXTRAPOLATION, PHYSICS_NOTE

    assert EXTRAPOLATION == t("phy.extrapolation", "en") and PHYSICS_NOTE == t("phy.note", "en")
    assert OUT_OF_SCOPE_MESSAGE == t("out_of_scope.message", "en")


def test_phase_names_and_colours():
    for phase in ("prevent", "detect", "extinguish"):
        assert i18n.phase_name(phase, "es") != i18n.phase_name(phase, "en")
        assert phase in config.PHASE_COLORS
    assert i18n.phase_name("extinguish", "es").lower() == "apagar"


# ---------------------------------------------------------------- language detection

@pytest.mark.parametrize("text, expected", [
    ("How do I extinguish a fire with 30% oxygen?", "en"),
    ("¿Cómo apago un incendio con 30 % de oxígeno?", "es"),
    ("Qué combustible se usó en los ensayos con heptano", "es"),
    ("which tests used n-heptane at 1 atm", "en"),
    ("detección de humo en la estación", "es"),
    ("¿Qué pasa con la llama?", "es"),
    ("¡Apaga el fuego!", "es"),
    ("¿Cómo prevenir un incendio?", "es"),
])
def test_detect_language(text, expected):
    assert detect_language(text) == expected


def test_detect_language_defaults():
    assert detect_language("") == "en"
    assert detect_language("   ", default="es") == "es"
    assert detect_language("PMMA 30", default="es") == "es"  # nothing to go on -> UI language
    assert detect_language("PMMA 30", default="en") == "en"
    assert detect_language("¿PMMA?") == "es"


def test_detect_language_is_deterministic():
    assert {detect_language(ES_Q) for _ in range(5)} == {"es"}


# ---------------------------------------------------------------- pipeline output follows the language

def _texts(res):
    d = res.draft
    out = [d.answer, d.prevent, d.detect, d.extinguish, d.limitations, d.missing, *res.warnings, *res.actions]
    if res.calculations is not None:
        out += [str(x) for x in res.calculations.notes] if hasattr(res.calculations, "notes") else []
    return " ".join(str(x) for x in out)


def test_result_language_defaults_to_the_question(df):
    assert answer_question(ES_Q, df).lang == "es"
    assert answer_question(EN_Q, df).lang == "en"


def test_language_can_be_forced(df):
    assert answer_question(EN_Q, df, lang="es").lang == "es"
    assert answer_question(ES_Q, df, lang="en").lang == "en"


def test_spanish_answer_is_spanish(df):
    res = answer_question(ES_Q, df)
    text = _texts(res)
    assert re.search(r"[áéíóúñ]|apagar|filas|oxígeno", text, re.I)
    leaked = [p for p in english_template_phrases() if p in text]
    assert not leaked, leaked  # (dataset outcome text such as "Flame extinguished" is data and stays in English)
    assert t("no_evidence", "en") not in text
    assert res.conditions.phase == "extinguish"


def test_english_answer_is_english(df):
    text = _texts(answer_question(EN_Q, df))
    spanish = [p for p in (c for k, v in STRINGS["es"].items() if k.startswith(("tpl.", "act.", "phy.", "warn.", "gap.", "note."))
               for c in re.split(r"\{[^}]*\}", v) if len(c.strip(" .;:,()")) >= 18) if p.strip(" .;:,()") in text]
    assert not spanish, spanish
    assert not re.search(r"\b(filas|fase|apagar|oxígeno)\b", text, re.I)


def test_same_numbers_in_both_languages(df):
    en, es = answer_question(EN_Q, df, lang="en"), answer_question(EN_Q, df, lang="es")
    assert en.retrieval.ranked["row_id"].tolist() == es.retrieval.ranked["row_id"].tolist()
    assert en.retrieval.facts == es.retrieval.facts
    assert en.conditions.phase == es.conditions.phase


def test_out_of_scope_refusal_follows_language(df):
    es = answer_question("¿Cuál es el clima hoy?", df)
    en = answer_question("What is the weather like today?", df)
    assert es.conditions.phase == en.conditions.phase == "out_of_scope"
    assert es.draft.answer == t("out_of_scope.message", "es")
    assert en.draft.answer == OUT_OF_SCOPE_MESSAGE
    assert es.draft.answer != en.draft.answer


def test_insufficient_data_case_is_flagged_in_both_languages(df):
    es = answer_question("¿Cómo apago un incendio de metanol con 99 % de oxígeno a 50 atm?", df)
    en = answer_question("How do I extinguish a methanol fire with 99% oxygen at 50 atm?", df)
    assert es.insufficient and en.insufficient
    assert es.draft.answer != en.draft.answer
    assert not any(p in es.draft.answer + es.draft.limitations for p in english_template_phrases())


def test_sources_keep_dataset_names(df):
    res = answer_question(ES_Q, df)
    names = {s.get("experiment") or s.get("experimento") for s in res.sources}
    assert names <= {"SOFIE", "ICE", "CFI-G", "BASS-II", "SAFFIRE", None}


# ---------------------------------------------------------------- LLM compatibility

class OneArgLLM:
    """A client written before the language option existed."""

    def __init__(self):
        self.calls = []

    def extract_conditions(self, question):
        return None

    def draft_answer(self, payload):
        self.calls.append("old")
        return DraftAnswer(enough_evidence=True, answer="ok", prevent="p", detect="d", extinguish="e", limitations="l")


class LangLLM(OneArgLLM):
    def draft_answer(self, payload, lang="en"):
        self.calls.append(lang)
        return DraftAnswer(enough_evidence=True, answer="ok", prevent="p", detect="d", extinguish="e", limitations="l")


def test_llm_without_lang_argument_still_works(df):
    llm = OneArgLLM()
    res = answer_question(ES_Q, df, llm)
    assert llm.calls == ["old"] and res.mode == "gemini"


def test_llm_is_told_the_language(df):
    llm = LangLLM()
    answer_question(ES_Q, df, llm)
    answer_question(EN_Q, df, llm)
    assert llm.calls == ["es", "en"]


def test_gemini_prompt_names_the_language():
    from flame.llm import ANSWER_SYSTEM, answer_system

    assert answer_system("en") == ANSWER_SYSTEM
    assert "Spanish" in answer_system("es") and answer_system("es").startswith(ANSWER_SYSTEM[:40])
    assert t("insufficient", "es") in answer_system("es") and t("no_evidence", "es") in answer_system("es")


# ---------------------------------------------------------------- classifier text

def test_classifier_reason_and_subject_follow_language(df):
    fuels = df["combustible"].unique().tolist()
    es = classify_question(ES_Q, fuels, "es")
    en = classify_question(EN_Q, fuels, "en")
    assert es.phase == en.phase == "extinguish"
    assert es.reason != en.reason
    assert "keyword" not in es.reason.lower()
    assert es.subject.summary("es") != en.subject.summary("en") or es.subject.summary("es") == t("none_m", "es")


@pytest.mark.parametrize("lang", LANGS)
def test_example_chips_classify_to_their_phase(df, lang):
    fuels = df["combustible"].unique().tolist()
    for kind in ("prevent", "detect", "extinguish"):
        example = t(f"example.{kind}", lang)
        assert classify_question(example, fuels, lang).phase == kind, (lang, kind, example)
        assert detect_language(example) == lang


# ---------------------------------------------------------------- animation page

@pytest.mark.parametrize("phase, state", [
    ("prevent", "prevent"), ("detect", "detect"), ("extinguish", "extinguish"),
    ("out_of_scope", "out_of_scope"), (None, "unclear"), ("something-else", "unclear"),
])
def test_animation_state(phase, state):
    assert animation_state(phase) == state


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("phase", ["prevent", "detect", "extinguish", "out_of_scope", None])
def test_animation_html_builds(lang, phase):
    page = build_animation_html("¿Cómo apago un incendio?", phase, 0.8, "O2", lang, config.PHASE_COLORS)
    assert page.lstrip().lower().startswith("<!doctype html") or "<html" in page.lower()
    assert "<script" not in page.lower()  # pure CSS
    for p in ("prevent", "detect", "extinguish"):
        assert i18n.phase_name(p, lang).upper() in page
    assert "prefers-reduced-motion" in page
    if phase in config.PHASE_COLORS:
        assert config.PHASE_COLORS[phase].lower() in page.lower()


def test_animation_escapes_the_question():
    nasty = '<img src=x onerror=alert(1)> & "quotes" </style><script>alert(2)</script>'
    page = build_animation_html(nasty, "detect", 0.7, "<b>subject</b>", "en", config.PHASE_COLORS)
    assert "<img src=x" not in page and "<script>alert" not in page and "<b>subject</b>" not in page
    assert html.escape("<b>subject</b>") in page or "&lt;b&gt;subject" in page


def test_animation_text_follows_language():
    es = build_animation_html("q", "extinguish", 0.8, "gas", "es", config.PHASE_COLORS)
    en = build_animation_html("q", "extinguish", 0.8, "gas", "en", config.PHASE_COLORS)
    assert "APAGAR" in es and "EXTINGUISH" not in es
    assert "EXTINGUISH" in en and "APAGAR" not in en


def test_animation_survives_odd_input():
    for q in ("", "x" * 5000, "🔥" * 50):
        build_animation_html(q, "prevent", None, "", "es", None)


# ---------------------------------------------------------------- Assistant tab flow (Streamlit AppTest)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture()
def app(tmp_path, monkeypatch):
    pytest.importorskip("streamlit.testing.v1")
    from streamlit.testing.v1 import AppTest

    data = tmp_path / "experiments.csv"
    data.write_text(CSV, encoding="utf-8")
    monkeypatch.setattr(config, "DATA_PATH", data)
    monkeypatch.setattr(config, "ANIMATION_SECONDS", 0.0)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.chdir(ROOT)
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=60)
    at.run()
    assert not at.exception
    return at


def _submit(at, question):
    at.text_area(key="question").input(question)
    at.button[0].click().run()  # the form's submit button comes first
    return at


def test_flow_starts_in_english_ask_stage(app):
    assert app.session_state["stage"] == "ask" and app.session_state["lang"] == "en"
    assert [t_.label for t_ in app.tabs] == [t("tab.assistant", "en"), t("tab.explorer", "en"), t("tab.charts", "en")]


def test_toggle_switches_the_whole_interface(app):
    app.radio(key="lang_widget").set_value("ES").run()
    assert not app.exception and app.session_state["lang"] == "es"
    assert [t_.label for t_ in app.tabs] == [t("tab.assistant", "es"), t("tab.explorer", "es"), t("tab.charts", "es")]
    assert app.text_area(key="question").placeholder == t("ask.placeholder", "es")


def test_spanish_question_goes_to_spanish_results_and_back(app):
    _submit(app, ES_Q)
    assert not app.exception
    assert app.session_state["stage"] == "results" and app.session_state["lang"] == "es"
    assert app.session_state["result"].lang == "es"
    assert [b.label for b in app.button] == [t("btn.new_question", "es")]
    # v4 mission-control UI: the dashboard replaces the old subheaders; the written answer (with "conditions
    # read") now sits in an expander under it.
    page = " ".join(m.value for m in app.markdown)
    assert t("dash.verdict_title", "es") in page
    assert t("res.conditions", "es") in page
    assert t("dash.full_answer", "es") in [e.label for e in app.expander]

    app.button(key="new_question").click().run()
    assert not app.exception and app.session_state["stage"] == "ask"
    assert app.session_state["lang"] == "es"  # the language sticks
    assert app.text_area(key="question").value == ""  # input cleared


def test_english_question_in_spanish_ui_switches_to_english(app):
    app.radio(key="lang_widget").set_value("ES").run()
    _submit(app, EN_Q)
    assert app.session_state["result"].lang == "en" and app.session_state["lang"] == "en"


def test_empty_question_stays_on_ask(app):
    _submit(app, "   ")
    assert app.session_state["stage"] == "ask" and not app.exception


def test_out_of_scope_ends_in_results_with_refusal(app):
    _submit(app, "¿Cuál es el clima hoy?")
    assert not app.exception and app.session_state["stage"] == "results"
    # v4: the refusal is drawn inside the dashboard card (HTML) instead of st.warning.
    page = " ".join(m.value for m in app.markdown) + " ".join(w.value for w in app.warning)
    assert t("out_of_scope.message", "es")[:40] in page


def test_insufficient_sentence_is_shown_in_the_question_language(app):
    _submit(app, "¿Cómo apago un incendio de metanol con 99 % de oxígeno a 50 atm?")
    assert not app.exception
    assert t("insufficient", "es") in [e.value for e in app.error]


def test_results_without_a_result_recomputes(app):
    app.session_state["pending_question"] = EN_Q
    app.session_state["stage"] = "results"
    app.session_state["result"] = None
    app.run()
    assert not app.exception and app.session_state["stage"] == "results"


def test_pipeline_error_is_shown_not_raised(app, monkeypatch):
    import flame.pipeline as pipeline

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(pipeline, "answer_question", boom)  # app.py imports it at the start of every run
    _submit(app, EN_Q)
    assert not app.exception
    assert app.session_state["stage"] == "results"
    # a plain message for the user; the technical error goes to the server log only
    assert [e.value for e in app.error] == [t("err.pipeline_user", "en")] and "boom" not in str(app.error)
    assert [b.label for b in app.button] == [t("btn.new_question", "en")]  # the user can always start over
