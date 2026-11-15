"""Changes ported from the teammate's version (comparison metrics, phase gap, gap-aware wording, metric chart).

Run against the real NASA CSV (data/experiments.csv), because the metric rows only exist there.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flame import config  # noqa: E402
from flame.data import load_dataset  # noqa: E402
from flame.i18n import STRINGS, t  # noqa: E402
from flame.pipeline import answer_question  # noqa: E402
from flame.retrieval import detect_comparison, filter_by_oxygen, metric_rows  # noqa: E402

REAL = ROOT / "data" / "experiments.csv"
pytestmark = pytest.mark.skipif(not REAL.exists(), reason="real NASA CSV not present")
DF = load_dataset(REAL).df if REAL.exists() else None


@pytest.mark.parametrize("q,material,metric", [
    ("Which cabin materials burn fastest in microgravity?", "cabin materials", "flame_spread_rate"),
    ("¿Qué materiales de cabina se queman más rápido?", "cabin materials", "flame_spread_rate"),
    ("What is the flame spread rate of silicone?", None, "flame_spread_rate"),
    ("How long does methanol burn in 21% oxygen?", None, "flame_duration"),
    ("¿Cuánto dura la llama de metanol?", None, "flame_duration"),
    ("Fuel consumption rate of heptane droplets", None, "fuel_consumption_rate"),
    ("¿Cuál es la tasa de pérdida de masa del PMMA?", None, "mass_loss_rate"),
    ("Will methanol flames extinguish at 21% oxygen?", None, None),
])
def test_detect_comparison(q, material, metric):
    assert detect_comparison(q) == (material, metric)


def test_metric_rows_are_numeric_microgravity_and_fuel_filtered():
    spread = metric_rows(DF, "flame_spread_rate")
    assert len(spread) >= 1 and (spread["result_metric_unit"] == "mm/s").all()
    assert spread["gravedad"].str.contains("microgravity", case=False).all()
    meth = metric_rows(DF, "flame_duration", "Methanol")
    assert not meth.empty and meth["combustible"].str.contains("ethanol", case=False).all()
    assert metric_rows(DF, None).empty and metric_rows(DF, "nope").empty


@pytest.mark.parametrize("lang", ["en", "es"])
def test_material_ranking_question_is_honest(lang):
    q = {"en": "Which cabin materials burn fastest in microgravity?",
         "es": "¿Qué materiales de cabina se queman más rápido en microgravedad?"}[lang]
    res = answer_question(q, DF)
    assert res.lang == lang
    k = metric_rows(DF, "flame_spread_rate")["combustible"].nunique()
    if k < 2:  # today's CSV: only Silicone has spread rates
        assert res.insufficient
        assert t("gap.metric_ranking", lang, metric=t("metric.flame_spread_rate", lang)) in res.missing
    for rid in metric_rows(DF, "flame_spread_rate")["row_id"].head(6):
        assert f"[{rid}]" in res.draft.answer  # recorded values are cited, nothing invented


def test_detect_demo_not_downgraded_by_phase_labels():
    # The teammate's "fuel never tested in this phase" gap was NOT ported: the fase column is coarse and it
    # flipped the cotton DETECT demo (rows with gas readings) to "insufficient".
    res = answer_question("Which sensors detect cotton smoldering early?", DF)
    assert not res.insufficient


def test_duration_question_lists_recorded_values():
    res = answer_question("How long does methanol burn in 21% oxygen at 1 atm?", DF)
    assert res.conditions.comparison_metric == "flame_duration" and not res.insufficient
    top = metric_rows(DF, "flame_duration", "Methanol").sort_values("result_metric", ascending=False).iloc[0]
    assert f"[{top.row_id}]" in res.draft.answer


def test_demo_methanol_extinguish_is_an_unbiased_sample():
    # v5 said 8/8: the word "extinguish" was a keyword matched inside `resultado`, so extinction rows were
    # pulled up (review #1). Now the 8 rows are a spaced sample of the equally relevant rows.
    res = answer_question("Will methanol flames extinguish at 21% oxygen?", DF)
    assert not res.retrieval.gaps and not res.insufficient
    assert "extinguish" not in res.conditions.keywords
    assert res.retrieval.tied >= len(res.retrieval.hits)
    assert "record extinction" in res.draft.answer


def test_new_strings_have_both_languages():
    keys = [k for k in STRINGS["en"] if k.startswith(("metric.", "tpl.metric", "chart.metric", "gap.metric_ranking", "tpl.answer_head_gap", "tpl.prevent_gap"))]
    assert len(keys) >= 13
    for k in keys:
        assert STRINGS["en"][k] and STRINGS["es"].get(k) and STRINGS["en"][k] != STRINGS["es"][k]


@pytest.fixture()
def app(monkeypatch):
    pytest.importorskip("streamlit.testing.v1")
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(config, "DATA_PATH", REAL)
    monkeypatch.setattr(config, "ANIMATION_SECONDS", 0.0)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.chdir(ROOT)
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=90)
    at.run()
    return at


@pytest.mark.parametrize("q,lang", [("How long does methanol burn in 21% oxygen at 1 atm?", "en"),
                                    ("¿Qué materiales de cabina se queman más rápido?", "es")])
def test_metric_chart_in_results(app, q, lang):
    app.text_area(key="question").input(q)
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state["stage"] == "results"
    page = " ".join(m.value for m in app.markdown)
    assert t("chart.metric_title", lang, metric="", o2="").split("—")[-1].strip(" ·") in page
    assert any(t("chart.metric_caption", lang, n=0).split("(")[0] in c.value for c in app.caption)


# ---------------------------------------------------------------- chart O2 filter (display only)

def test_o2_filter_band_keeps_only_rows_near_the_asked_level():
    rows = metric_rows(DF, "flame_duration", "Methanol")
    out, mode, level = filter_by_oxygen(rows, 21.0)
    assert mode == "band" and level == 21.0 and not out.empty
    assert (out["oxigeno_num"].sub(21).abs() <= config.METRIC_CHART_O2_TOLERANCE).all()
    assert len(out) < len(rows)
    # values are passed through untouched
    assert out["result_metric"].equals(rows.loc[out.index, "result_metric"])


def test_o2_filter_falls_back_to_nearest_level():
    rows = metric_rows(DF, "flame_duration", "Methanol")
    top = float(rows["oxigeno_num"].max())
    out, mode, level = filter_by_oxygen(rows, top + 20)
    assert mode == "nearest" and level == top and not out.empty
    assert (out["oxigeno_num"].sub(top).abs() <= config.METRIC_CHART_O2_TOLERANCE).all()


def test_o2_filter_without_o2_keeps_everything():
    rows = metric_rows(DF, "flame_duration", "Methanol")
    out, mode, level = filter_by_oxygen(rows, None)
    assert mode == "all" and level is None and len(out) == len(rows)


def test_o2_filter_strings_bilingual():
    for k in ("chart.o2_all", "chart.o2_band", "chart.o2_nearest", "chart.o2_note_all", "chart.o2_note_band",
              "chart.o2_note_nearest"):
        assert STRINGS["en"][k] and STRINGS["es"][k]
    assert t("chart.o2_all", "es") == "todos los niveles de O₂" and t("chart.o2_all", "en") == "all O₂ levels"


@pytest.mark.parametrize("q,lang,key", [
    ("¿Cuánto dura la llama de metanol al 21% de oxígeno?", "es", "band"),
    ("How long does methanol burn?", "en", "all"),
    ("How long does methanol burn at 60% oxygen?", "en", "nearest"),
])
def test_chart_shows_the_o2_filter(app, q, lang, key):
    app.text_area(key="question").input(q)
    app.button[0].click().run()
    assert not app.exception and app.session_state["stage"] == "results"
    page = " ".join(m.value for m in app.markdown)
    captions = " ".join(c.value for c in app.caption)
    if key == "all":
        assert t("chart.o2_all", lang) in page and t("chart.o2_note_all", lang) in captions
    elif key == "band":
        assert t("chart.o2_band", lang, o2="21", tol="1.5") in page
        assert t("chart.o2_note_band", lang, o2="21", tol="1.5") in captions
    else:
        assert any("60" in w.value for w in app.warning)
