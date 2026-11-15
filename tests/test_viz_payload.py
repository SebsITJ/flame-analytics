"""Tests for flame.viz_payload: the JSON behind the stage-2 animation and the stage-3 dashboard.

The Result objects are small stand-ins (SimpleNamespace) with only the attributes the builders read, so
these tests do not depend on the engine and cannot change what it computes.
"""

from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from flame import config, viz_payload
from flame.i18n import STRINGS
from flame.viz_payload import (
    action_cards,
    build_animation_payload,
    build_dashboard_view,
    diluent_bars,
    doi_of,
    fold,
    question_segments,
    result_state,
    source_pill,
    split_action,
    subset_of,
)

NAN = float("nan")
FLEX = "FLEX 10.60555/mbq8-0451"
QUESTION_ES = "¿Cómo apago un fuego de metanol al 21 % de oxígeno? ¿Sirve CO2 o helio?"


def table() -> pd.DataFrame:
    rows = [
        # row_id, experimento, combustible, oxigeno_num, presion_num, fase, fuente
        ("R1", "FLEX", "methanol", 21.0, 3.05, "extinguish", FLEX),
        ("R2", "FLEX", "methanol", 21.0, 2.03, "extinguish", FLEX),
        ("R3", "FLEX", "methanol", 21.0, 0.71, "extinguish", FLEX),
        ("R4", "FLEX", "methanol", 21.0, NAN, "extinguish", FLEX),
        ("R5", "FLEX", "methanol", 12.0, 1.0, "extinguish", FLEX),
        ("R6", "FLEX", "methanol", 30.0, 1.0, "extinguish", FLEX),
        ("R7", "FLEX", "n-heptane", 21.0, 1.0, "extinguish", FLEX),
        ("R8", "BASS", "PMMA", 18.0, 1.0, "prevent", "BASS https://example.org/bass"),
        ("R9", "BASS", "PMMA", 40.0, NAN, "prevent", "BASS https://example.org/bass"),
        ("R10", "SAME", "Kapton", NAN, NAN, "detect", "SAME 10.60555/same-0001"),
        ("R11", "SAME", "Kapton", NAN, 1.0, "detect", "SAME 10.60555/same-0001"),
        ("R12", "SAME", "silicone", NAN, NAN, "detect", ""),
    ]
    df = pd.DataFrame(rows, columns=["row_id", "experimento", "combustible", "oxigeno_num", "presion_num", "fase", "fuente"])
    df["resultado"] = "as written in the source"
    return df


def hits_of(df: pd.DataFrame, ids, **columns) -> pd.DataFrame:
    hits = df[df["row_id"].isin(ids)].copy()
    for name, values in columns.items():
        hits[name] = values
    return hits


def subject(material=None, gases=(), inhibitors=(), detection=()):
    return NS(material=material, gases=list(gases), inhibitors=list(inhibitors), detection=list(detection))


def result(hits, *, phase="extinguish", fuel="methanol", oxygen=21.0, pressure=None, pressure_text="", subj=None,
           keywords=("apago", "helio"), confidence=0.8, out_of_scope=False, lang="es", question=QUESTION_ES,
           calculations=None, actions=(), sources=(), insufficient=False, missing=()):
    subj = subj or subject()
    clf = NS(phase=phase, confidence=confidence, matched_keywords=list(keywords), out_of_scope=out_of_scope, subject=subj)
    cond = NS(oxygen=oxygen, pressure_atm=pressure, pressure_text=pressure_text, fuel=fuel, phase=phase,
              phase_confidence=confidence, matched_keywords=list(keywords), subject=subj, classification=clf)
    return NS(question=question, conditions=cond, classification=clf, retrieval=NS(hits=hits), lang=lang,
              calculations=calculations, actions=list(actions), sources=list(sources), insufficient=insufficient,
              missing=list(missing), draft=NS(answer="Answer text written by the engine."), mode="offline")


@pytest.fixture
def df():
    return table()


@pytest.fixture
def extinguish(df):
    hits = hits_of(df, ["R1", "R2", "R3", "R4"], relevance=[0.786, 0.786, 0.78, 0.7],
                   extinguished=[True, False, True, True], burned=[False, True, False, False])
    return result(hits, subj=subject("methanol", gases=["CO2", "He"]))


# ---------------------------------------------------------------------------
# Animation payload
# ---------------------------------------------------------------------------

def test_payload_is_json_safe_and_complete(df, extinguish):
    payload = build_animation_payload(QUESTION_ES, df, extinguish, auto_seconds=9)
    text = json.dumps(payload, allow_nan=False)  # raises on NaN / numpy scalars
    assert json.loads(text) == payload
    for key in ("version", "lang", "state", "mode", "question", "detected", "phases", "cloud", "funnel", "subset",
                "topk", "verdict", "bars", "qpoint", "colors", "labels", "auto_seconds"):
        assert key in payload
    assert payload["version"] == viz_payload.VERSION
    assert payload["auto_seconds"] == 9.0


def test_extinguish_question_gives_scatter_funnel_and_verdict(df, extinguish):
    payload = build_animation_payload(QUESTION_ES, df, extinguish)
    assert (payload["state"], payload["mode"], payload["lang"]) == ("extinguish", "scatter", "es")
    assert [step["n"] for step in payload["funnel"]] == [12, 6, 4]  # table -> methanol in FLEX -> top-k
    assert payload["subset"] == {"kind": "fuel_exp", "n": 6, "fuel": "methanol", "experiments": ["FLEX"], "phase": None}
    assert "metanol" in payload["funnel"][1]["label"] and "FLEX" in payload["funnel"][1]["label"]
    assert all("{n}" in step["label"] for step in payload["funnel"])
    assert payload["verdict"]["kind"] == "extinguished"
    assert (payload["verdict"]["n"], payload["verdict"]["k"]) == (3, 4)
    assert payload["verdict"]["counts"]["burned"] == 1
    assert payload["verdict"]["top_relevance"] == 0.786
    assert [r["status"] for r in payload["topk"]] == ["extinguished", "burned", "extinguished", "extinguished"]
    assert payload["qpoint"] == {"o2": 21.0, "p": None}  # no pressure stated -> the "no pressure" strip
    assert payload["bars"] == []


def test_topk_keeps_the_engine_values_and_order(df, extinguish):
    payload = build_animation_payload(QUESTION_ES, df, extinguish)
    hits = extinguish.retrieval.hits
    assert [r["id"] for r in payload["topk"]] == hits["row_id"].tolist()
    assert [r["o2"] for r in payload["topk"]] == [21.0, 21.0, 21.0, 21.0]
    assert [r["p"] for r in payload["topk"]] == [3.05, 2.03, 0.71, None]
    assert [r["relevance"] for r in payload["topk"]] == [0.786, 0.786, 0.78, 0.7]


def test_builders_do_not_modify_the_table_or_the_hits(df, extinguish):
    before_df, before_hits = df.copy(deep=True), extinguish.retrieval.hits.copy(deep=True)
    build_animation_payload(QUESTION_ES, df, extinguish)
    build_dashboard_view(extinguish, df, url_for=lambda s: "")
    pd.testing.assert_frame_equal(df, before_df)
    pd.testing.assert_frame_equal(extinguish.retrieval.hits, before_hits)


def test_cloud_has_one_point_per_row_with_numeric_oxygen(df, extinguish):
    cloud = build_animation_payload(QUESTION_ES, df, extinguish)["cloud"]
    assert cloud["n_total"] == 12
    assert cloud["n_plotted"] == len(cloud["points"]) == 9
    assert cloud["n_no_o2"] == 3
    assert cloud["n_no_pressure"] == 2  # R4 and R9 go on the strip
    assert sum(1 for p in cloud["points"] if p[1] is None) == 2
    assert sum(p[3] for p in cloud["points"]) == 6  # the methanol-in-FLEX subset
    assert {p[2] for p in cloud["points"]} == {0, 2}  # prevent and extinguish; detect rows have no O2 here
    lo, hi = cloud["x_domain"]
    assert lo <= 12 and hi >= 40 and lo % 10 == 0 and hi % 10 == 0
    assert cloud["y_domain"] == [0, 4]
    assert cloud["sampled"] is False


def test_large_tables_are_thinned_but_keep_the_subset(df, extinguish, monkeypatch):
    monkeypatch.setattr(viz_payload, "MAX_POINTS", 4)
    cloud = build_animation_payload(QUESTION_ES, df, extinguish)["cloud"]
    assert cloud["sampled"] is True
    assert len(cloud["points"]) < 9
    assert sum(p[3] for p in cloud["points"]) == 6
    assert cloud["n_plotted"] == 9  # the counts still describe the whole table


def test_question_segments_rebuild_the_question_and_tag_what_was_read(df, extinguish):
    segments = build_animation_payload(QUESTION_ES, df, extinguish)["question"]["segments"]
    assert "".join(s["t"] for s in segments) == QUESTION_ES
    tagged = [(s["t"], s["k"]) for s in segments if s["k"]]
    assert tagged == [("apago", "phase"), ("metanol", "fuel"), ("21 %", "o2"), ("CO2", "agent"), ("helio", "agent")]
    assert all(s["k"] in viz_payload.SEGMENT_KINDS for s in segments if s["k"])


def test_question_segments_english_pressure_and_detection():
    q = "Does smoke appear before a PMMA flame at 30% oxygen and 10.2 psi?"
    segments = question_segments(q, oxygen=30.0, pressure_text="10.2 psi", fuel="PMMA", detection=["smoke"], keywords=["smoke"])
    assert "".join(s["t"] for s in segments) == q
    assert [(s["t"], s["k"]) for s in segments if s["k"]] == [
        ("smoke", "detection"), ("PMMA", "fuel"), ("30%", "o2"), ("10.2 psi", "pressure"),
    ]


def test_question_segments_survive_long_and_empty_text():
    assert question_segments("") == []
    long = "fire " * 200
    segments = question_segments(long, keywords=["fire"])
    joined = "".join(s["t"] for s in segments)
    assert len(joined) <= viz_payload.MAX_QUESTION_CHARS and joined.endswith("…")


def test_fold_keeps_length_and_drops_accents():
    text = "¿Oxígeno ñandú CO₂?"
    assert len(fold(text)) == len(text)
    assert fold("Oxígeno") == "oxigeno"


def test_detect_rows_without_oxygen_fall_back_to_bars(df):
    hits = hits_of(df, ["R10", "R11", "R12"], relevance=[0.9, 0.8, 0.7], match_phase=[1.0, 1.0, 1.0],
                   match_subject=[1.0, 0.5, 0.0], o2_delta_pct=[-0.4, NAN, NAN], co2_delta_ppm=[900.0, 300.0, NAN],
                   co_delta_ppm=[12.0, NAN, NAN])
    res = result(hits, phase="detect", fuel=None, oxygen=None, subj=subject(detection=["smoke"]), keywords=["detecting"],
                 lang="en", question="What does the database say about detecting smoke?")
    payload = build_animation_payload(res.question, df, res)
    assert (payload["state"], payload["mode"]) == ("detect", "bars")
    assert payload["qpoint"] is None
    assert [step["n"] for step in payload["funnel"]] == [12, 3, 3]  # table -> detect rows -> top-k
    assert payload["subset"]["kind"] == "phase"
    assert payload["verdict"] == {"kind": "reading", "n": 2, "k": 3, "top_relevance": 0.9,
                                  "counts": {"extinguished": 0, "burned": 0, "other": 0, "reading": 2, "none": 1}}
    bars = {(b["group"], b["label"]): b for b in payload["bars"]}
    assert bars[("match", "subject")]["value"] == 0.5 and bars[("match", "subject")]["max"] == 1
    assert bars[("readings", "CO2 change over the test")]["text"] == "2/3"
    assert bars[("readings", "CO change over the test")]["value"] == 1
    json.dumps(payload, allow_nan=False)


def test_prevent_counts_rows_that_kept_burning(df):
    hits = hits_of(df, ["R8", "R9"], relevance=[0.6, 0.5], extinguished=[False, False], burned=[True, False])
    res = result(hits, phase="prevent", fuel="PMMA", oxygen=None, keywords=["burn"], lang="en", question="Does PMMA burn?")
    payload = build_animation_payload(res.question, df, res)
    assert (payload["state"], payload["mode"]) == ("prevent", "scatter")
    assert (payload["verdict"]["kind"], payload["verdict"]["n"], payload["verdict"]["k"]) == ("burned", 1, 2)
    assert [r["status"] for r in payload["topk"]] == ["burned", "other"]
    # v4: no oxygen stated -> the point is estimated from the retrieved rows (median O2) and flagged as such
    o2s = sorted(r["o2"] for r in payload["topk"] if r["o2"] is not None)
    if o2s:
        assert payload["qpoint"]["estimated"] is True and payload["qpoint"]["n"] == len(o2s)
        assert o2s[0] <= payload["qpoint"]["o2"] <= o2s[-1]
    else:
        assert payload["qpoint"] is None


def test_out_of_scope_has_no_data_scene(df):
    res = result(pd.DataFrame(columns=df.columns), phase="out_of_scope", fuel=None, oxygen=None, keywords=[],
                 confidence=0.0, out_of_scope=True, lang="en", question="What is the capital of France?")
    payload = build_animation_payload(res.question, df, res)
    assert (payload["state"], payload["mode"]) == ("out_of_scope", "scope")
    assert payload["topk"] == [] and payload["qpoint"] is None and payload["bars"] == []
    assert payload["verdict"]["k"] == 0
    assert [s["k"] for s in payload["question"]["segments"]] == [None]
    json.dumps(payload, allow_nan=False)


def test_in_scope_question_without_hits_is_empty_mode(df):
    res = result(pd.DataFrame(columns=df.columns), phase=None, fuel=None, oxygen=None, keywords=[], confidence=0.0,
                 lang="en", question="Tell me about fire in a spacecraft")
    payload = build_animation_payload(res.question, df, res)
    assert (payload["state"], payload["mode"]) == ("unclear", "empty")
    assert [step["n"] for step in payload["funnel"]] == [12, 0]  # nothing to narrow by
    assert payload["labels"]["viz.empty"]


def test_result_state_values():
    assert result_state(NS(conditions=NS(phase="detect", classification=None), classification=None)) == "detect"
    assert result_state(NS(conditions=NS(phase=None, classification=None), classification=None)) == "unclear"
    oos = NS(phase="out_of_scope", out_of_scope=True)
    assert result_state(NS(conditions=NS(phase="out_of_scope", classification=oos), classification=oos)) == "out_of_scope"


def test_subset_falls_back_when_the_fuel_is_not_in_the_hit_experiments(df):
    hits = hits_of(df, ["R8"], relevance=[0.4])
    mask, info = subset_of(df, hits, "methanol", "prevent")
    assert info["kind"] == "fuel" and info["n"] == int(mask.sum()) == 6
    mask, info = subset_of(df, hits, "unobtainium", None)
    assert info["kind"] == "exp" and info["experiments"] == ["BASS"] and int(mask.sum()) == 2
    mask, info = subset_of(df, df.head(0), None, None)
    assert info["kind"] == "all" and bool(mask.all())


def test_labels_follow_the_language_and_exist_in_both(df, extinguish):
    es = build_animation_payload(QUESTION_ES, df, extinguish, lang="es")["labels"]
    en = build_animation_payload(QUESTION_ES, df, extinguish, lang="en")["labels"]
    assert es["viz.cta"] == "Ver resultados" and en["viz.cta"] == "View results"
    assert es["viz.credit"] == "Datos: NASA PSI" and en["viz.credit"] == "Data: NASA PSI"
    assert es["viz.kind_phase"] == "APAGAR" and en["viz.kind_phase"] == "EXTINGUISH"
    assert set(es) == set(en)
    assert all(isinstance(v, str) for v in es.values())
    for key in viz_payload._LABEL_KEYS:
        assert key in STRINGS["en"] and key in STRINGS["es"], key
    for labels in (es, en):  # the only placeholder left for the browser is the countdown number
        assert [k for k, v in labels.items() if "{" in v] == ["viz.auto"]


def test_colors_come_from_config(df, extinguish):
    colors = build_animation_payload(QUESTION_ES, df, extinguish)["colors"]
    assert colors["phases"] == [config.PHASE_COLORS[p] for p in config.PHASES]
    assert colors["accent"] == "#d95926"
    assert colors["status"]["extinguished"] == config.PHASE_COLORS["extinguish"]


# ---------------------------------------------------------------------------
# Dashboard view
# ---------------------------------------------------------------------------

def physics():
    baseline = {"rows": 54, "extinguished": 44, "o2_median": 20.0, "row_ids": ["R2"]}
    return NS(
        bracket={"lowest_flame": {"o2": 12.0, "row_id": "R5"}, "highest_nonburn_below": None},
        diluent={
            "CO2": {"comparable": True, "with": {"rows": 75, "extinguished": 64, "o2_median": 20.0, "row_ids": ["R1"]}, "without": baseline},
            "He": {"comparable": True, "with": {"rows": 28, "extinguished": 27, "o2_median": 18.0, "row_ids": ["R3"]}, "without": dict(baseline)},
            "Ar": None,
        },
        lines=["a calculation line"],
    )


ACTIONS = [
    "Prefer CO2 to nitrogen as the diluting gas, on this evidence only: at similar oxygen levels the flame went out in "
    "64 of 75 rows with CO2 [R1] and in 44 of 54 N2-only rows [R8].",
    "Keep monitoring after the visible flame is gone: 1 retrieved row(s) mention a cool flame [R3].",
]


def test_dashboard_view_for_an_extinguish_answer(df, extinguish):
    extinguish.calculations = physics()
    extinguish.actions = ACTIONS
    extinguish.sources = [{"rows": "R1, R2", "experiments": "FLEX", "source": FLEX, "url": "https://doi.org/10.60555/mbq8-0451"}]
    view = build_dashboard_view(extinguish, df, url_for=lambda s: "https://example.org/x")
    json.dumps(view, allow_nan=False)
    v = view["verdict"]
    assert (v["kind"], v["n"], v["k"]) == ("extinguished", 3, 4)
    assert v["headline"] == "extinciones" and v["context"] == ["21 % O2", "metanol", "FLEX"]  # Spanish display name of the fuel
    assert v["answer"] == "Answer text written by the engine."  # engine text is passed through untouched
    assert [(seg["key"], seg["n"]) for seg in view["ring"]] == [("extinguished", 3), ("burned", 1)]
    scale = view["o2_scale"]
    assert scale["max"] == 40.0 and scale["asked"] == 21.0
    assert scale["flame_from"] == {"o2": 12.0, "row_id": "R5"} and scale["no_flame_at"] is None
    assert [(r["key"], r["off_scale"]) for r in scale["refs"]] == [("earth", False), ("moon", False), ("suit", True)]
    assert view["sources"] == [{"label": "FLEX 10.60555/mbq8-0451", "url": "https://doi.org/10.60555/mbq8-0451"}]
    assert view["state"] == "extinguish" and view["insufficient"] is False


def test_oxygen_scale_widens_for_high_oxygen_and_keeps_the_no_flame_bound(df, extinguish):
    extinguish.conditions.oxygen = 95.0
    extinguish.calculations = NS(diluent=None, bracket={
        "lowest_flame": {"o2": 17.0, "row_id": "R8"},
        "highest_nonburn_below": {"o2": 15.0, "row_id": "R9", "kind": "did not ignite"},
    })
    scale = build_dashboard_view(extinguish, df, url_for=lambda s: "")["o2_scale"]
    assert scale["max"] == 100.0 and scale["asked"] == 95.0
    assert scale["no_flame_at"] == {"o2": 15.0, "row_id": "R9", "kind": "no hubo ignición"}
    assert all(r["off_scale"] is False for r in scale["refs"])


def test_dashboard_view_without_oxygen_or_bound_has_no_scale(df):
    hits = hits_of(df, ["R10"], relevance=[0.9], co2_delta_ppm=[900.0])
    res = result(hits, phase="detect", fuel=None, oxygen=None, lang="en", keywords=["detect"])
    view = build_dashboard_view(res, df, url_for=lambda s: "")
    assert view["o2_scale"] is None and view["diluent"] == [] and view["actions"] == []
    assert view["verdict"]["kind"] == "reading" and view["ring"][0]["key"] == "reading"


def test_diluent_bars_share_one_baseline_when_it_is_the_same():
    bars = diluent_bars(physics().diluent)
    assert [(b["gas"], b["extinguished"], b["rows"], b["baseline"]) for b in bars] == [
        ("CO2", 64, 75, False), ("He", 27, 28, False), ("N2", 44, 54, True),
    ]
    assert bars[0]["fraction"] == round(64 / 75, 4) and bars[2]["versus"] == ""
    different = physics().diluent
    different["He"]["without"] = {"rows": 10, "extinguished": 5, "o2_median": 30.0}
    assert [b["versus"] for b in diluent_bars(different) if b["baseline"]] == ["CO2", "He"]
    assert diluent_bars(None) == [] and diluent_bars({"CO2": None}) == []


def test_action_cards_split_text_and_cite_sources(df):
    cards = action_cards(ACTIONS, df, url_for=lambda s: "https://example.org/" + s.split()[0])
    assert cards[0]["title"] == "Prefer CO2 to nitrogen as the diluting gas"
    assert cards[0]["body"].startswith("On this evidence only: at similar oxygen levels")
    assert [p["label"] for p in cards[0]["pills"]] == ["FLEX 10.60555/mbq8-0451", "BASS https://example.org/bass"]
    assert cards[0]["pills"][0]["url"] == "https://example.org/FLEX"
    assert cards[1]["title"] == "Keep monitoring after the visible flame is gone"
    assert [p["label"] for p in cards[1]["pills"]] == ["FLEX 10.60555/mbq8-0451"]
    assert action_cards([], df) == []


def test_split_action_and_source_helpers():
    assert split_action("Monitor CO2: it rose in 3 rows.") == ("Monitor CO2", "It rose in 3 rows.")
    assert split_action("Cut the oxygen that reaches the fuel. For methanol, no flame.") == (
        "Cut the oxygen that reaches the fuel", "For methanol, no flame.")
    assert split_action("One short sentence") == ("One short sentence", "")
    assert doi_of("FLEX 10.60555/mbq8-0451.") == "10.60555/mbq8-0451"
    assert doi_of("no doi here") == ""
    assert source_pill("", "FLEX", url_for=lambda s: "x") == {"label": "", "url": ""}
    assert source_pill("x" * 80, url_for=lambda s: "")["label"].endswith("…")


# --- v4 integration checks against the real table (added when merging into the project) ---

def test_first_url_takes_the_first_link():
    from flame.viz_payload import first_url

    assert first_url("https://doi.org/10.60555/x | https://psi.nasa.gov/y") == "https://doi.org/10.60555/x"
    assert first_url("") == "" and first_url(None) == ""


def test_real_table_funnel_narrows_and_counts_match_engine():
    import os as _os

    from flame import config as _config
    from flame.data import load_dataset
    from flame.pipeline import answer_question
    from flame.viz_payload import build_animation_payload, build_dashboard_view

    if not _config.DATA_PATH.exists():
        pytest.skip("real table not present")
    _os.environ.pop("GEMINI_API_KEY", None)
    df = load_dataset(str(_config.DATA_PATH)).df
    for q in ("¿Qué nivel de oxígeno evita que el PMMA se encienda?", "How do I put out a methanol fire in microgravity?"):
        res = answer_question(q, df, None, None)
        p = build_animation_payload(q, df, res, lang=res.lang, colors=_config.PHASE_COLORS)
        ns = [step["n"] for step in p["funnel"]]
        assert ns == sorted(ns, reverse=True), ns  # every step keeps at most the rows of the one before
        hits = res.retrieval.hits
        v = build_dashboard_view(res, df)
        assert v["verdict"]["k"] == len(hits)
        if "extinguished" in hits.columns and res.conditions.phase != "detect":
            assert v["verdict"]["counts"]["extinguished"] == int(hits["extinguished"].fillna(False).astype(bool).sum())
        assert all(" " not in s["url"] for s in v["sources"])


def test_estimated_qpoint_is_the_median_of_the_retrieved_rows():
    from flame.viz_payload import estimated_qpoint

    rows = [{"o2": 21.0, "p": 1.0}, {"o2": 15.0, "p": None}, {"o2": 30.0, "p": 3.0}, {"o2": None, "p": 2.0}]
    q = estimated_qpoint(rows)
    assert q == {"o2": 21.0, "p": 2.0, "estimated": True, "n": 3}
    assert estimated_qpoint([{"o2": None, "p": 1.0}]) is None and estimated_qpoint([]) is None


def test_stated_oxygen_is_never_marked_estimated(df):
    hits = hits_of(df, ["R8", "R9"], relevance=[0.6, 0.5], extinguished=[False, False], burned=[True, False])
    res = result(hits, phase="prevent", fuel="PMMA", oxygen=21.0, keywords=["burn"], lang="en", question="Does PMMA burn at 21 % O2?")
    payload = build_animation_payload(res.question, df, res)
    assert payload["qpoint"]["o2"] == 21.0 and "estimated" not in payload["qpoint"]


def test_source_links_split_doi_and_psi():
    from flame.i18n import t as _t
    from flame.viz_payload import source_links

    cell = "https://doi.org/10.60555/mbq8-0451 | https://psi.nasa.gov/physci/repo/data/investigations/PSI-69"
    for lang in ("en", "es"):
        links = source_links(cell, lang)
        assert links == [
            {"label": "DOI 10.60555/mbq8-0451", "url": "https://doi.org/10.60555/mbq8-0451"},
            {"label": _t("res.link_psi", lang), "url": "https://psi.nasa.gov/physci/repo/data/investigations/PSI-69"},
        ]
    assert source_links("Smith et al. 2019") == [{"label": "Smith et al. 2019", "url": ""}]
    assert source_links("") == []


def test_real_table_estimated_point_for_questions_without_oxygen():
    import os as _os

    from flame import config as _config
    from flame.data import load_dataset
    from flame.pipeline import answer_question

    if not _config.DATA_PATH.exists():
        pytest.skip("real table not present")
    _os.environ.pop("GEMINI_API_KEY", None)
    df = load_dataset(str(_config.DATA_PATH)).df
    q = "¿Cómo apago un fuego de metanol en microgravedad?"
    res = answer_question(q, df, None, None)
    payload = build_animation_payload(q, df, res, lang=res.lang)
    assert payload["qpoint"] == {"o2": 21.0, "p": 1.0, "estimated": True, "n": 8} or (
        payload["qpoint"]["estimated"] and payload["qpoint"]["o2"] == 21.0)
    assert "estimado a partir de los experimentos más cercanos" in payload["labels"]["viz.your_question_est"]
