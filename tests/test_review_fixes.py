"""Fixes from the code review of v5 (findings 1-11 and the minor items), on the real CSV."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flame import config  # noqa: E402
from flame.classify import FUEL_SYNONYMS, extract_subject  # noqa: E402
from flame.data import load_dataset, source_url  # noqa: E402
from flame.i18n import STRINGS, t  # noqa: E402
from flame.physics import _trend  # noqa: E402
from flame.pipeline import answer_question  # noqa: E402
from flame.retrieval import (_top, clean_keywords, detect_comparison, merge_conditions, metric_rows,  # noqa: E402
                             parse_rules)
from flame.viz_payload import build_dashboard_view, verdict_of  # noqa: E402

REAL = ROOT / "data" / "experiments.csv"
pytestmark = pytest.mark.skipif(not REAL.exists(), reason="real NASA CSV not present")
DF = load_dataset(REAL).df if REAL.exists() else None
FUELS = DF["combustible"].unique().tolist() if DF is not None else []

PAIRS = [
    ("Will methanol flames extinguish at 21% oxygen?", "¿Se apaga la llama de metanol al 21% de oxígeno?"),
    ("How long does methanol burn in microgravity?", "¿Cuánto tiempo arde el metanol en microgravedad?"),
    ("How do I prevent PMMA from igniting?", "¿Cómo evito que el PMMA se encienda?"),
    ("Does helium extinguish heptane flames better than nitrogen?",
     "¿El helio apaga las llamas de heptano mejor que el nitrógeno?"),
    ("How do I put out a methanol fire in microgravity?", "¿Cómo apago un fuego de metanol en microgravedad?"),
    ("Which sensors detect cotton smoldering early?", "¿Qué sensores detectan temprano la combustión lenta del algodón?"),
    ("What is the burning rate of heptane droplets?", "¿Cuál es la tasa de combustión de las gotas de heptano?"),
    ("What role does oxygen play in flame spread in microgravity?",
     "¿Qué papel juega el oxígeno en la propagación de la llama en microgravedad?"),
    ("Do methanol and heptane flames extinguish at 21% oxygen?",
     "¿Se apagan las llamas de metanol y heptano al 21% de oxígeno?"),
    ("Which cabin materials burn fastest in microgravity?", "¿Qué materiales de cabina se queman más rápido en microgravedad?"),
]


def _verdict(q):
    r = answer_question(q, DF)
    v = build_dashboard_view(r, DF, url_for=source_url)["verdict"]
    return r, v


# ---- 1. keywords and tie sampling ------------------------------------------------------------------------
@pytest.mark.parametrize("en,es", PAIRS)
def test_en_and_es_give_the_same_verdict(en, es):
    r_en, v_en = _verdict(en)
    r_es, v_es = _verdict(es)
    assert (v_en["kind"], v_en["n"], v_en["k"]) == (v_es["kind"], v_es["n"], v_es["k"])
    assert r_en.lang == "en" and r_es.lang == "es"
    assert r_en.retrieval.hits["row_id"].tolist() == r_es.retrieval.hits["row_id"].tolist()


def test_keywords_are_not_scored():
    assert config.KEYWORDS_IN_RELEVANCE is False
    r = answer_question("Will methanol flames extinguish at 21% oxygen?", DF)
    assert "match_keywords" not in r.retrieval.ranked.columns


def test_first_named_fuel_is_used_in_both_languages():
    assert extract_subject("Do methanol and heptane flames go out?", FUELS).fuel.lower() == "methanol"
    assert extract_subject("¿Se apagan el metanol y el heptano?", FUELS).fuel.lower() == "methanol"
    assert extract_subject("¿Se apagan el heptano y el metanol?", FUELS).fuel.lower() in ("heptane", "n-heptane")


def test_outcome_words_are_not_keywords_and_accents_fold():
    assert clean_keywords(["extinguish", "apaga", "burn", "oxígeno", "geno", "methanol", "nitrógeno"]) == \
        ["geno", "methanol", "nitrogeno"]
    kw = parse_rules("¿Se apaga la llama de metanol al 21% de oxígeno?", FUELS, "es").keywords
    assert "geno" not in kw and not any(k.startswith("apag") for k in kw)


def test_ties_are_sampled_across_the_band_not_file_order():
    frame = pd.DataFrame({"relevance": [0.9] * 20, "info": [1] * 20, "experimento": ["X"] * 20,
                          "row_id": [f"R{i}" for i in range(20)]})
    picked = _top(frame)["row_id"].tolist()
    assert len(picked) == config.TOP_K and "R0" in picked and "R19" in picked
    assert picked != [f"R{i}" for i in range(config.TOP_K)]


def test_dashboard_says_when_the_rows_are_a_sample():
    r, v = _verdict("Will methanol flames extinguish at 21% oxygen?")
    assert r.retrieval.tied > config.TOP_K
    assert v["sample"] == t("dash.verdict_sample", "en", k=v["k"], n=r.retrieval.tied)


# ---- 2a / 2b. neutral verdict for metric questions; honest label ------------------------------------------
def test_metric_question_has_neutral_verdict():
    r, v = _verdict("How long does methanol burn in microgravity?")
    assert r.conditions.comparison_metric == "flame_duration"
    assert v["kind"] == "rows" and v["n"] == v["k"]


def test_verdict_of_metric_param():
    topk = [{"status": "extinguished", "relevance": 1.0}] * 3
    hits = pd.DataFrame({"extinguished": [True] * 3, "burned": [False] * 3})
    assert verdict_of(topk, "prevent", hits)["kind"] == "burned"
    assert verdict_of(topk, "prevent", hits, "flame_duration")["kind"] == "rows"


def test_burned_label_does_not_claim_kept_burning():
    for lang in ("en", "es"):
        for key in ("viz.status_burned", "dash.verdict_burned", "viz.verdict_burned", "tpl.extinguish"):
            text = STRINGS[lang][key].lower()
            assert "kept burning" not in text and "siguió ardiendo" not in text and "siguieron" not in text


# ---- 3. failed ignition is not an extinction limit -------------------------------------------------------
def test_cut_oxygen_warns_about_failed_ignition():
    assert "failed ignition is not an extinction limit" in STRINGS["en"]["act.cut_oxygen"]
    assert "ignición fallida no es un límite de extinción" in STRINGS["es"]["act.cut_oxygen"]
    assert STRINGS["es"]["dash.o2_noflame"].startswith("Sin ignición a")


# ---- 4. diluent action needs >= 5 rows and >= 0.2 gain -----------------------------------------------------
def test_diluent_action_thresholds():
    assert config.DILUENT_MIN_ROWS == 5 and config.DILUENT_MIN_GAIN == 0.20
    meth = answer_question("How do I put out a methanol fire in microgravity?", DF)
    # CO2 64/75 vs N2 44/54 (+4 pts) and He 27/28 vs 44/54 (+15 pts): below the 20-point gain
    assert not any("more often with" in a for a in meth.actions)
    hept = answer_question("Does CO2 extinguish heptane flames better than nitrogen?", DF)
    # CO2 38/48 vs N2 23/47 (+30 pts)
    assert any("more often with CO2" in a for a in hept.actions)
    assert not any(a.startswith("Prefer") for a in hept.actions)


# ---- 5. metric detection -----------------------------------------------------------------------------------
@pytest.mark.parametrize("q,metric", [
    ("What is the burning rate of heptane droplets?", "burning_rate"),
    ("¿Cuál es la tasa de combustión de las gotas de heptano?", "burning_rate"),
    ("¿Cuánto tiempo arde el metanol?", "flame_duration"),
    ("What is the fuel consumption rate of propane?", "fuel_consumption_rate"),
])
def test_metric_detection(q, metric):
    assert detect_comparison(q)[1] == metric


def test_burning_rate_rows_come_from_the_text_with_the_source_unit():
    rows = metric_rows(DF, "burning_rate", "Heptane")
    assert len(rows) >= 50
    assert set(rows["result_metric_unit"]) == {"source unit label 'mm'"}
    # value is the number written after "burning rate" in the row text
    r = rows.iloc[0]
    assert f"burning rate {r.result_metric:g}" in r.resultado.replace(f"{r.result_metric}", f"{r.result_metric:g}")


# ---- 6. text and chart use the same O2 filter; ±5 pts wording ----------------------------------------------
def test_metric_text_uses_the_chart_filter():
    r = answer_question("How long does methanol burn at 21% oxygen?", DF)
    assert t("chart.o2_note_band", "en", o2="21", tol="1.5") in r.draft.answer
    cited = [i for i in metric_rows(DF, "flame_duration", "Methanol").query("abs(oxigeno_num - 21) > 1.5")["row_id"]]
    assert not any(f"[{c}]" in r.draft.answer for c in cited)
    assert "±5 percentage points" in r.draft.answer


# ---- 7. Gemini phase vs rules confidence -------------------------------------------------------------------
def test_confidence_hidden_when_gemini_changes_the_phase():
    q = "How do I prevent PMMA from igniting?"
    rules = parse_rules(q, FUELS)
    same = merge_conditions(q, rules, {"phase": rules.phase, "keywords": ["burn", "pmma"]})
    other = merge_conditions(q, rules, {"phase": "extinguish", "keywords": ["burn"]})
    assert same.phase_confidence == rules.phase_confidence > 0
    assert other.phase == "extinguish" and other.phase_confidence == 0.0
    assert "burn" not in other.keywords


# ---- 8. O2 is not an agent; detection_vars feed the signal readout -----------------------------------------
def test_oxygen_is_not_shown_as_agent_and_smoke_is_a_signal():
    r = answer_question("How do I put out a methanol fire at 21% oxygen?", DF)
    d = build_dashboard_view(r, DF, url_for=source_url)["detected"]
    assert "O2" not in d["agents"]
    r2 = answer_question("Which sensors detect smoke from cotton early?", DF)
    d2 = build_dashboard_view(r2, DF, url_for=source_url)["detected"]
    assert "smoke" in d2["detection"]


# ---- 9. gravity column --------------------------------------------------------------------------------------
def test_every_row_is_microgravity():
    counts = DF["gravedad"].value_counts().to_dict()
    assert all("microgravity" in k for k in counts)
    assert counts == {"microgravity (ISS)": 1969, "microgravity (Cygnus cargo vehicle)": 13}


# ---- 10. charts tab height ------------------------------------------------------------------------------------
def test_outcome_axis_keeps_the_chart_small():
    import ast
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "38 * plot[\"resultado\"].nunique()" not in src
    assert "outcome_label" in src
    ast.parse(src)


# ---- 11. trend is fitted within one unit --------------------------------------------------------------------
def test_trend_never_mixes_units():
    pool = pd.DataFrame({
        "oxigeno_num": [18, 20, 22, 24, 18, 20, 22, 24, 26],
        "result_metric": [1, 2, 3, 4, 10, 20, 30, 40, 50],
        "result_metric_name": ["burning rate"] * 9,
        "result_metric_unit": ["mm2/s"] * 4 + ["mg/s"] * 5,
        "combustible": ["X"] * 9, "experimento": ["E"] * 9, "row_id": [f"R{i}" for i in range(9)],
    })
    tr = _trend(pool)
    assert tr["unit"] == "mg/s" and tr["n"] == 5


# ---- minor items -----------------------------------------------------------------------------------------------
def test_papel_is_not_a_material_when_there_are_no_paper_rows():
    assert not DF["combustible"].str.contains("paper|papel", case=False).any()
    assert "paper" not in FUEL_SYNONYMS
    subj = extract_subject("¿Qué papel juega el oxígeno en la propagación de la llama?", FUELS)
    assert subj.material is None


def test_two_fuels_warn():
    r = answer_question("Do methanol and heptane flames extinguish at 21% oxygen?", DF)
    assert any("more than one fuel" in w for w in r.warnings)
    r_es = answer_question("¿Se apagan las llamas de metanol y heptano al 21% de oxígeno?", DF)
    assert any("más de un combustible" in w for w in r_es.warnings)
    assert not answer_question("Will methanol flames extinguish at 21% oxygen?", DF).warnings


def test_hero_and_wording_minor_items():
    for lang in ("en", "es"):
        assert "ISS" not in STRINGS[lang]["hero.subtitle"]
    assert "(balance N2)" in STRINGS["en"]["phy.stated_atm"] and "(resto N2)" in STRINGS["es"]["phy.stated_atm"]
    assert "(resto N2)" in STRINGS["es"]["phy.stated_o2_only"]
    assert all("ptos" not in v for k, v in STRINGS["es"].items() if k.startswith("chart.o2"))
    assert STRINGS["es"]["dash.o2_asked"].startswith("consultado")


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


def test_burning_rate_chart_renders(app):
    app.text_area(key="question").input("What is the burning rate of heptane droplets?")
    app.button[0].click().run()
    assert not app.exception and app.session_state["stage"] == "results"
    assert not any(i.value == t("chart.metric_none", "en") for i in app.info)
