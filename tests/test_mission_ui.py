"""Tests for the stage-2 animation document (flame.animation.build_mission_html) and the stage-3
dashboard markup (flame.dashboard). Both are plain string builders, so no browser is needed."""

from __future__ import annotations

import json
import re

import pandas as pd
import pytest

from flame import config
from flame.animation import (
    MISSION_HEIGHT,
    build_animation_html,
    build_mission_html,
    json_for_script,
    mission_summary,
)
from flame.dashboard import dashboard_html, oxygen_html, pill, strip_html
from flame.i18n import LANGS, STRINGS, placeholders
from flame.theme import THEME_CSS, brand_html, esc, footer_html, hero_html
from flame.viz_payload import build_animation_payload, build_dashboard_view

try:  # tests/ on sys.path (pytest default) or tests as a package
    from test_viz_payload import ACTIONS, QUESTION_ES, hits_of, physics, result, subject, table
except ImportError:  # pragma: no cover
    from tests.test_viz_payload import ACTIONS, QUESTION_ES, hits_of, physics, result, subject, table

PAYLOAD_RE = re.compile(r'<script id="payload" type="application/json">(.*?)</script>', re.S)
NETWORK_MARKERS = ("<script src", "<link", "@import", "<img", "<iframe", "fetch(", "XMLHttpRequest", "//cdn", "googleapis")
EXTERNAL_URL = re.compile(r"url\((?!#)")  # url(#id) is an in-document SVG reference, anything else would be a fetch


@pytest.fixture
def df():
    return table()


@pytest.fixture
def extinguish(df):
    hits = hits_of(df, ["R1", "R2", "R3", "R4"], relevance=[0.786, 0.786, 0.78, 0.7],
                   extinguished=[True, False, True, True], burned=[False, True, False, False])
    res = result(hits, subj=subject("methanol", gases=["CO2", "He"]))
    res.calculations = physics()
    res.actions = ACTIONS
    res.sources = [{"rows": "R1", "experiments": "FLEX", "source": "FLEX 10.60555/mbq8-0451", "url": "https://doi.org/10.60555/mbq8-0451"}]
    return res


def embedded(page: str) -> dict:
    return json.loads(PAYLOAD_RE.search(page).group(1))


# ---------------------------------------------------------------------------
# Animation document
# ---------------------------------------------------------------------------

def test_mission_html_is_self_contained(df, extinguish):
    page = build_mission_html(build_animation_payload(QUESTION_ES, df, extinguish))
    assert page.startswith("<!doctype html>") and page.rstrip().endswith("</html>")
    assert 'lang="es"' in page and "state-extinguish" in page and "mode-scatter" in page
    for marker in NETWORK_MARKERS:  # inline CSS / JS / SVG only: nothing is fetched
        assert marker not in page, marker
    assert not EXTERNAL_URL.search(page)
    assert page.count("<script") == 2 and page.count("</script>") == 2
    assert isinstance(MISSION_HEIGHT, int) and MISSION_HEIGHT >= 500


def test_mission_html_embeds_the_payload_unchanged(df, extinguish):
    payload = build_animation_payload(QUESTION_ES, df, extinguish)
    data = embedded(build_mission_html(payload, button_key="see_results"))
    assert data.pop("cta_key") == "see_results"
    # the classifier's certainty and matched keywords never reach the browser; everything else is unchanged
    assert "confidence" not in data["detected"] and "keywords" not in data["detected"]
    assert "word.confidence" not in data["labels"] and "word.keywords" not in data["labels"]
    expected = dict(payload)
    expected["detected"] = {k: v for k, v in payload["detected"].items() if k not in ("confidence", "keywords")}
    expected["labels"] = {k: v for k, v in payload["labels"].items() if k not in ("word.confidence", "word.keywords")}
    assert data == expected


def test_mission_html_cannot_be_broken_by_the_question(df, extinguish):
    nasty = '</script><script>alert(1)</script> <img src=x onerror=alert(2)> & "quotes" <!-- 21 %'
    extinguish.question = nasty
    page = build_mission_html(build_animation_payload(nasty, df, extinguish))
    assert page.count("<script") == 2 and page.count("</script>") == 2
    assert "alert(1)</script>" not in page and "<img" not in page and "<!--" not in page
    assert embedded(page)["question"]["text"] == nasty  # the text itself survives, as data
    assert "".join(s["t"] for s in embedded(page)["question"]["segments"]) == nasty


def test_json_for_script_escapes_markup_characters():
    text = json_for_script({"a": "</script>&<b> "})
    assert "<" not in text and ">" not in text and "&" not in text and " " not in text
    assert json.loads(text) == {"a": "</script>&<b> "}
    with pytest.raises(ValueError):
        json_for_script({"a": float("nan")})


def test_button_key_is_sanitised(df, extinguish):
    page = build_mission_html(build_animation_payload(QUESTION_ES, df, extinguish), button_key='see" results<x>')
    assert embedded(page)["cta_key"] == "seeresultsx"


@pytest.mark.parametrize("lang", LANGS)
def test_mission_html_for_other_states(df, lang):
    empty = pd.DataFrame(columns=df.columns)
    oos = result(empty, phase="out_of_scope", fuel=None, oxygen=None, keywords=[], confidence=0.0, out_of_scope=True,
                 lang=lang, question="What is the capital of France?")
    page = build_mission_html(build_animation_payload(oos.question, df, oos))
    assert "state-out_of_scope" in page and "mode-scope" in page
    assert STRINGS[lang]["anim.out_of_scope"] in mission_summary(embedded(page))

    unclear = result(empty, phase=None, fuel=None, oxygen=None, keywords=[], confidence=0.0, lang=lang, question="fire?")
    page = build_mission_html(build_animation_payload(unclear.question, df, unclear))
    assert "state-unclear" in page and "mode-empty" in page

    hits = hits_of(df, ["R10", "R11"], relevance=[0.9, 0.8], co2_delta_ppm=[900.0, float("nan")])
    detect = result(hits, phase="detect", fuel=None, oxygen=None, keywords=["smoke"], lang=lang, question="smoke?")
    page = build_mission_html(build_animation_payload(detect.question, df, detect))
    assert "state-detect" in page and "mode-bars" in page
    assert "1/2" in mission_summary(embedded(page))


def test_mission_summary_reads_like_the_animation(df, extinguish):
    summary = mission_summary(build_animation_payload(QUESTION_ES, df, extinguish))
    assert "APAGAR" in summary and "12 filas en la tabla" in summary and "6 filas de metanol en FLEX" in summary  # Spanish display name of the fuel
    assert "3/4 de las filas más parecidas registran extinción" in summary


def test_legacy_card_is_still_available_as_fallback():
    page = build_animation_html("How do I extinguish a fire?", "extinguish", 0.8, "none", "en", config.PHASE_COLORS)
    assert "<script" not in page and "state-extinguish" in page


# ---------------------------------------------------------------------------
# Dashboard markup and page chrome
# ---------------------------------------------------------------------------

def test_dashboard_html_shows_the_engine_numbers(df, extinguish):
    view = build_dashboard_view(extinguish, df, url_for=lambda s: "https://example.org/src")
    page = dashboard_html(view)
    assert "<b>3<small>/4</small></b>" in page and "3 / 4" in page
    assert "extinciones · 21 % O2 · metanol · FLEX" in page  # Spanish display name of the fuel
    assert "Answer text written by the engine." in page
    assert "64 / 75" in page and "27 / 28" in page and "44 / 54" in page
    assert "consultado 21 %" in page and "Tierra 21 %" in page and "Base lunar 30 %" in page
    assert "Llama registrada desde 12 % hacia arriba [R5]" in page
    assert 'href="https://doi.org/10.60555/mbq8-0451"' in page and "FLEX 10.60555/mbq8-0451" in page
    assert "Prefer CO2 to nitrogen as the diluting gas" in page
    assert "\n" not in page  # one line: safe inside st.markdown
    assert strip_html(view) in page and strip_html(view) not in dashboard_html(view, include_strip=False)


def test_dashboard_html_escapes_text(df, extinguish):
    extinguish.question = '<script>alert(1)</script> costs $5 & "more"'
    extinguish.draft.answer = "<b>bold</b> $x$"
    page = dashboard_html(build_dashboard_view(extinguish, df, url_for=lambda s: ""))
    assert "<script" not in page and "<b>bold" not in page and "$" not in page
    assert "&lt;script&gt;" in page and "&#36;" in page


def test_pill_links_only_http_urls():
    assert pill("DOI", "https://doi.org/10.1/x").startswith('<a class="ff-pill" href="https://doi.org/10.1/x"')
    assert 'rel="noopener noreferrer"' in pill("DOI", "https://doi.org/10.1/x")
    assert pill("x", "javascript:alert(1)") == '<span class="ff-pill">x</span>'
    assert pill("<x>", "") == '<span class="ff-pill">&lt;x&gt;</span>'


def test_dashboard_for_out_of_scope_and_insufficient(df):
    empty = pd.DataFrame(columns=df.columns)
    oos = result(empty, phase="out_of_scope", fuel=None, oxygen=None, keywords=[], confidence=0.0, out_of_scope=True,
                 lang="en", question="What is the capital of France?")
    oos.draft.answer = STRINGS["en"]["out_of_scope.message"]
    page = dashboard_html(build_dashboard_view(oos, df, url_for=lambda s: ""))
    assert STRINGS["en"]["dash.out_of_scope_title"] in page and "OUT OF SCOPE" in page
    assert "ff-ring" not in page and "ff-o2" not in page and "ff-actions" not in page

    none = result(empty, phase=None, fuel=None, oxygen=None, keywords=[], confidence=0.0, lang="en", question="fire?",
                  insufficient=True, missing=["The question names no condition."])
    page = dashboard_html(build_dashboard_view(none, df, url_for=lambda s: ""))
    assert config.INSUFFICIENT in page and "The question names no condition." in page  # wording unchanged


def test_oxygen_line_handles_missing_bound_and_off_scale(df, extinguish):
    extinguish.calculations = None
    view = build_dashboard_view(extinguish, df, url_for=lambda s: "")
    html_ = oxygen_html(view)
    assert STRINGS["es"]["dash.o2_no_bound"] in html_ and "ff-zone" not in html_
    assert "Traje espacial 100 % (fuera de esta escala)" in html_
    extinguish.conditions.oxygen = None
    assert oxygen_html(build_dashboard_view(extinguish, df, url_for=lambda s: "")) == ""


@pytest.mark.parametrize("lang", LANGS)
def test_page_chrome_credits_the_data_as_text_only(lang):
    chrome = brand_html(lang, rows=1982, experiments=19, gemini=False) + hero_html(lang) + footer_html(lang)
    assert "NASA PSI" in footer_html(lang)
    assert "<img" not in chrome and "url(" not in THEME_CSS and "@import" not in THEME_CSS  # no logos, nothing fetched
    assert "1982" in chrome and "OCEANPIXELS" in chrome
    assert esc("a<b>$") == "a&lt;b&gt;&#36;"


def test_new_interface_strings_exist_in_both_languages():
    new = [k for k in STRINGS["en"] if k.split(".")[0] in ("viz", "dash", "hud", "refshort")]
    assert len(new) > 60
    for key in new:
        en, es = STRINGS["en"][key], STRINGS["es"][key]
        assert en.strip() and es.strip() and en != es, key
        assert placeholders(en) == placeholders(es), key


def test_single_view_results_control_hides_the_streamlit_button():
    from flame.animation import build_mission_html

    page = build_mission_html({"lang": "es", "state": "extinguish", "mode": "scatter", "labels": {}, "funnel": [],
                               "verdict": {}, "topk": [], "cloud": {}, "qpoint": None}, button_key="see_results")
    assert "hideParentButton" in page and "data-ff-hidden" in page
    assert '"cta_key":"see_results"' in page
