"""Offline checks for the deterministic engine. No API key or network needed.

Run:  uv run pytest tests/test_core.py
  or: uv run python tests/test_core.py

Sample-based tests use data/experiments_simulated.csv via FLAME_DATA_PATH.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Point at the 5-row simulated sample so these tests stay independent of the NASA CSV.
os.environ.setdefault("FLAME_DATA_PATH", str(ROOT / "data" / "experiments_simulated.csv"))

sys.path.insert(0, str(ROOT))

from flame import config  # noqa: E402
from flame.classify import classify_question  # noqa: E402
from flame.data import DataError, load_dataset, source_url  # noqa: E402
from flame.enrich import UNSPECIFIED, display_gas, parse_row_text  # noqa: E402
from flame.llm import DraftAnswer, EvidenceItem  # noqa: E402
from flame.physics import compute_physics, po2  # noqa: E402
from flame.pipeline import answer_question  # noqa: E402
from flame.retrieval import merge_conditions, parse_rules, rank  # noqa: E402
from flame.verify import unsupported_numbers  # noqa: E402

SAMPLE = load_dataset(config.DATA_PATH)
DF = SAMPLE.df
FUELS = DF["combustible"].tolist()


def test_sample_loads_and_is_flagged_simulated():
    assert len(DF) == 5
    assert DF["simulated"].all()
    assert DF["oxigeno_num"].tolist() == [21.0, 30.0, 21.0, 40.0, 21.0]
    assert set(DF["fase"]) == {"prevent", "detect", "extinguish"}
    assert not SAMPLE.issues


def test_cp1252_semicolon_decimal_comma_accented_headers():
    text = (
        "Experimento;Combustible;Oxígeno;Presión;Resultado;Fase;Fuente\n"
        "Prueba Ñ;n-heptano;21 %;0,7;Extinción después de 5 s;Extinción;10.60555/abcd-1234\n"
        "Prueba 2;metanol;treinta;1;Sin extinción;detección;\n"
    )
    ds = load_dataset(text.encode("cp1252"))
    assert ds.encoding == "cp1252" and ds.delimiter == ";"
    assert ds.df.loc[0, "oxigeno_num"] == 21.0 and ds.df.loc[0, "presion_num"] == 0.7
    assert ds.df.loc[0, "oxigeno"] == "21 %"  # original text kept
    assert ds.df.loc[0, "fase"] == "extinguish" and ds.df.loc[1, "fase"] == "detect"
    assert any("treinta" in i for i in ds.issues)
    assert any("no source" in i for i in ds.issues)


def test_missing_columns_raise():
    try:
        load_dataset(b"a,b\n1,2\n")
    except DataError as err:
        assert "Missing columns" in str(err)
    else:
        raise AssertionError("expected DataError")


def test_rule_parser():
    c = parse_rules("How do I extinguish a fire in a spacecraft at 30% oxygen and 10.2 psi?", FUELS)
    assert c.oxygen == 30.0
    assert abs(c.pressure_atm - 10.2 / 14.6959) < 1e-9
    assert c.phase == "extinguish"
    c2 = parse_rules("oxygen concentration of 21 % with methanol", FUELS)
    assert c2.oxygen == 21.0 and c2.fuel == "methanol"
    c3 = parse_rules("Does ethanol burn?", FUELS)
    assert c3.fuel is None  # 'ethanol' must not match 'methanol'


def test_gemini_numbers_not_in_question_are_dropped():
    q = "How do I put out a fire in the Moon base?"
    rules = parse_rules(q, [])
    merged = merge_conditions(q, rules, {"oxygen_percent": 30, "phase": "extinguish", "keywords": ["moon"]})
    assert merged.oxygen is None
    assert merged.phase == "extinguish"
    assert merged.notes


def test_ranking_and_gaps():
    c = parse_rules("extinguish at 30% oxygen", [])
    r = rank(DF, c)
    assert r.hits.iloc[0]["row_id"] == "R2"
    assert not r.gaps
    c50 = parse_rules("extinguish at 60% oxygen", [])
    r50 = rank(DF, c50)
    assert any("60 % O2" in g and "21–40" in g for g in r50.gaps)


def test_number_verifier():
    allowed = ["R1 n-heptane 21 1.0 time to extinction 12 s", '{"requested_pressure_atm": "0.694"}']
    assert unsupported_numbers(["Extinction took 12 s at 21 % O2 [R1]"], allowed) == []
    assert unsupported_numbers(["about 0.69 atm"], allowed) == []
    assert unsupported_numbers(["extinction took 15 s at 1 atm"], allowed) == ["15"]
    assert unsupported_numbers(["CO2 and O2 at 21 %"], allowed) == []


def test_source_url():
    assert source_url("10.60555/80qf-vj95") == "https://doi.org/10.60555/80qf-vj95"
    assert source_url("doi:10.1016/j.pecs.2019.100787") == "https://doi.org/10.1016/j.pecs.2019.100787"
    assert source_url("https://psi.nasa.gov/x") == "https://psi.nasa.gov/x"
    assert source_url("SIMULATED - not a NASA source") is None


def test_pipeline_offline_unknown_fuel_is_insufficient():
    res = answer_question("How does kerosene burn at 21% oxygen?", DF, llm=None)
    # 'kerosene' is not a known fuel to the rule parser, so this is about oxygen only
    assert res.mode == "offline"
    res2 = answer_question("extinguish at 60% oxygen", DF, llm=None)
    assert res2.insufficient
    assert any("60 % O2" in m for m in res2.missing)


class FakeGemini:
    """Stands in for Gemini to test the checks around it."""

    def extract_conditions(self, question):
        return {"oxygen_percent": 30, "pressure_value": None, "pressure_unit": None,
                "fuel": "n-heptane", "phase": "extinguish", "keywords": ["extinction"]}

    def draft_answer(self, payload):
        ids = [r["row_id"] for r in payload["rows"]]
        return DraftAnswer(
            enough_evidence=True,
            answer=f"At 30 % O2 the flame was not extinguished [{ids[0]}]; extinction took 99 s elsewhere [R42].",
            prevent="No evidence in the retrieved rows.",
            detect="No evidence in the retrieved rows.",
            extinguish=f"See [{ids[0]}].",
            evidence=[EvidenceItem(row_id=ids[0], how_used="main row"), EvidenceItem(row_id="R42", how_used="invented")],
            limitations="Rows are SIMULATED.",
            missing="",
        )


def test_pipeline_with_fake_gemini_flags_invented_numbers_and_rows():
    res = answer_question("How do I extinguish an n-heptane fire at 30% oxygen?", DF, llm=FakeGemini())
    assert res.mode == "gemini"
    assert res.retrieval.hits.iloc[0]["row_id"] == "R2"
    assert any("99" in w for w in res.warnings)
    assert any("R42" in w for w in res.warnings)
    assert all(e.row_id != "R42" for e in res.draft.evidence)
    assert [s["rows"] for s in res.sources] == ["R2"]


# ---------------------------------------------------------------------------
# Classifier, physics, relevance breakdown, gas columns, offline template
# ---------------------------------------------------------------------------

def test_classifier_phases_english_and_spanish():
    fuels = ["n-heptane", "PMMA", "methanol", "Cotton-Fiberglass (SIBAL)"]
    ext_en = classify_question("How do I extinguish a fire at 30% oxygen?", fuels)
    ext_es = classify_question("¿Cómo apago un fuego de n-heptano al 30% de oxígeno?", fuels)
    det_en = classify_question("What does the database say about detecting smoke before a flame is visible?", fuels)
    det_es = classify_question("¿Cómo se detecta el humo en microgravedad?", fuels)
    prev_en = classify_question("Is PMMA flammable at 21% oxygen?", fuels)
    prev_es = classify_question("¿El PMMA es inflamable al 21% de oxígeno?", fuels)
    assert ext_en.phase == "extinguish" and ext_en.confidence >= 0.7
    assert ext_es.phase == "extinguish" and "n-heptane" in (ext_es.subject.fuel or ext_es.subject.material or "")
    assert det_en.phase == "detect" and "smoke" in det_en.subject.detection_vars
    assert det_es.phase == "detect" and "smoke" in det_es.subject.detection_vars
    assert prev_en.phase == "prevent" and prev_en.subject.fuel == "PMMA"
    assert prev_es.phase == "prevent" and prev_es.subject.material == "PMMA"
    assert "apago" in ext_es.matched_keywords or "apagar" in ext_es.matched_keywords or any("apag" in k for k in ext_es.matched_keywords)


def test_classifier_subject_diluent_and_synonyms():
    fuels = ["n-heptane", "PMMA", "methanol", "Cotton-Fiberglass (SIBAL)", "SIBAL 2 cm"]
    q = classify_question("Can a cotton-fiberglass fire be suppressed with CO2 or helium water mist?", fuels)
    assert q.phase == "extinguish"
    assert q.subject.fuel in {"Cotton-Fiberglass (SIBAL)", "SIBAL 2 cm"} or "SIBAL" in (q.subject.material or "")
    assert "CO2" in q.subject.gases
    assert "He" in q.subject.gases or "He" in q.subject.inhibitors
    assert "water mist" in q.subject.inhibitors
    # Synonym must not collapse ethanol into methanol
    eth = classify_question("Does ethanol burn in the cabin?", ["methanol", "n-heptane"])
    assert eth.subject.material == "ethanol"
    assert eth.subject.fuel is None


def test_classifier_out_of_scope():
    clf = classify_question("Who won the world cup last year?", [])
    assert clf.out_of_scope and clf.confidence >= 0.8
    res = answer_question("¿Quién ganó el mundial de fútbol?", DF, llm=None)
    assert res.conditions.phase == "out_of_scope"
    assert res.retrieval.hits.empty
    # Spanish question -> Spanish refusal; English question stays in English.
    ans = res.draft.answer.lower()
    assert "naves espaciales" in ans or "microgravedad" in ans or "hábitats" in ans
    en = answer_question("Who won the world cup last year?", DF, llm=None)
    assert en.conditions.phase == "out_of_scope"
    assert "spacecraft" in en.draft.answer.lower() or "microgravity" in en.draft.answer.lower()
    assert res.actions == []


def test_partial_pressure_and_reference_comparison():
    p = po2(30.0, 10.2 / 14.6959)
    # pO2 = 0.30 * (10.2/14.6959) atm
    expected = 0.30 * (10.2 / 14.6959)
    assert abs(p["atm"] - expected) < 1e-6
    assert abs(p["psi"] - expected * 14.6959) < 1e-3
    assert abs(p["kpa"] - expected * 101.325) < 1e-3
    c = parse_rules("How do I extinguish a fire at 30% oxygen and 10.2 psi?", FUELS)
    report = compute_physics(DF, DF, c)
    assert report.query_po2 is not None
    assert abs(report.query_po2["atm"] - expected) < 1e-5
    assert any("Moon" in line or "Earth" in line for line in report.lines)
    assert any("microgravity" in w.lower() for w in report.warnings)


def test_flammability_bound_uses_every_row_with_a_flame():
    c = parse_rules("How do I extinguish an n-heptane fire at 30% oxygen?", FUELS)
    report = compute_physics(DF, DF, c)
    # R1 (21 % O2) ignited and later went out; R2 (30 % O2) kept burning.
    # A flame existed at 21 %, so 21 % is the lowest O2 with a recorded flame, not 30 %.
    assert report.lowest_o2_burned == 21.0
    assert report.margin_o2 == 9.0
    assert report.bracket["highest_nonburn_below"] is None
    assert any("not bracketed from below" in line for line in report.lines)
    # No fuel named: no bound across mixed fuels.
    mixed = compute_physics(DF, DF, parse_rules("extinguish at 30% oxygen", FUELS))
    assert mixed.lowest_o2_burned is None and mixed.bracket is None


def _frame(rows: str):
    return load_dataset(("experimento,combustible,oxigeno,presion,resultado,fase,fuente,notas\n" + rows).encode("utf-8")).df


def test_bracket_action_needs_a_no_flame_test_below_the_lowest_flame():
    df = _frame(
        "X,PMMA,17,1.0,flame spread; spread rate 0.4 mm/s,prevent,SIMULATED,\n"
        "X,PMMA,21,1.0,flame spread; spread rate 0.9 mm/s,prevent,SIMULATED,\n"
        "X,PMMA,25,1.0,flame spread; spread rate 1.5 mm/s,prevent,SIMULATED,\n"
        "X,PMMA,15,1.0,did not ignite,extinguish,SIMULATED,\n"
        "X,PMMA,19,1.0,no flame spread observed,prevent,SIMULATED,\n"
    )
    assert df["ignited"].tolist() == [True, True, True, False, False]
    assert df["no_ignition"].tolist() == [False, False, False, True, False]
    res = answer_question("How do I extinguish a PMMA fire at 21% oxygen?", df, llm=None)
    b = res.calculations.bracket
    assert b["lowest_flame"]["o2"] == 17.0 and b["highest_nonburn_below"]["o2"] == 15.0
    assert any("[R4]" in a and "15 % O2" in a for a in res.actions)
    t = res.calculations.trend
    assert t["n"] == 3 and t["metric"] == "spread rate" and t["exponent"] is not None


def test_atmosphere_indices_same_po2_is_not_same_flammability():
    from flame.physics import atmosphere_indices
    earth = atmosphere_indices(21.0, 1.0)
    moon = atmosphere_indices(30.0, 10.2 / 14.6959)
    assert abs(earth["po2"]["atm"] - moon["po2"]["atm"]) < 0.005  # same breathing oxygen
    assert moon["ballast"] < 0.65 * earth["ballast"]  # much less inert gas per mole of O2
    assert abs(moon["normoxic_o2_pct"] - 30.2) < 0.1
    assert atmosphere_indices(21.0, None, x_co2=0.3)["ballast"] > atmosphere_indices(21.0)["ballast"]


def test_classifier_conjugations_roles_and_oxygen_reading():
    fuels = ["n-heptane", "SIBAL Fabric", "Japan wax"]
    for q in (
        "What CO2 concentration extinguishes a heptane flame?",
        "¿Qué concentración de CO2 apaga una llama de heptano?",
        "Which diluents work best against a methanol droplet flame?",
        "¿Se debe cortar la ventilación durante un incendio?",
    ):
        assert classify_question(q, fuels).phase == "extinguish", q
    made = classify_question("¿Cuánto CO2 genera la combustión de algodón?", fuels)
    assert made.phase == "detect" and made.subject.detection_vars == ["CO2"] and made.subject.inhibitors == []
    assert made.subject.fuel == "Cotton-Fiberglass (SIBAL)"  # reaches the "SIBAL Fabric" rows
    assert classify_question("How fast does a candle burn?", fuels).subject.fuel == "candle"
    assert "He" not in classify_question("He visto humo en la cabina", fuels).subject.gases
    assert classify_question("Which cabin atmosphere is safest?", fuels).phase == "prevent"
    assert parse_rules("How effective is CO2 at 15%?", fuels).oxygen is None
    assert parse_rules("CO2 al 20% y O2 al 18%", fuels).oxygen == 18.0


def test_subject_scoring_and_gas_change_in_detection():
    df = _frame(
        'A,PMMA,22.2,1.0,"O2 22.2 -> 21.8 % vol (initial -> final); CO2 0.44 -> 0.49 % vol (initial -> final); CO 12 -> 19 ppm (initial -> final)",detect,SIMULATED,\n'
        "B,Teflon,21,1.0,smoke particles observed,detect,SIMULATED,\n"
        "C,Kapton,21,1.0,outcome not listed,detect,SIMULATED,\n"
    )
    res = answer_question("Which sensor detects CO first?", df, llm=None)
    assert res.retrieval.hits.iloc[0]["row_id"] == "R1"  # the only row that records CO
    assert "subject" in res.retrieval.hits.iloc[0]["relevance_breakdown"]
    assert "CO +7 ppm" in res.draft.detect and "CO2 +500 ppm" in res.draft.detect
    assert any(a.startswith("Monitor CO:") for a in res.actions)
    none = answer_question("Can an HCl sensor detect a Kapton fire?", df, llm=None)
    assert none.insufficient and any("HCl" in m for m in none.missing)


def test_linear_trend_requires_three_points():
    c = parse_rules("extinguish methanol at 21% oxygen", FUELS)
    report = compute_physics(DF, DF, c)
    assert report.trend is None
    # Build a tiny numeric series
    extra = DF.iloc[[0, 0, 0]].copy().reset_index(drop=True)
    extra["oxigeno_num"] = [15.0, 20.0, 25.0]
    extra["result_metric"] = [10.0, 12.0, 14.0]
    extra["result_metric_name"] = "burn time"
    extra["result_metric_unit"] = "s"
    extra["row_id"] = ["T1", "T2", "T3"]
    report2 = compute_physics(extra, extra, c)
    assert report2.trend is not None and report2.trend["n"] >= 3
    assert abs(report2.trend["slope"] - 0.4) < 1e-6


def test_relevance_breakdown_and_outcome_penalty():
    c = parse_rules("extinguish at 30% oxygen", [])
    r = rank(DF, c)
    top = r.hits.iloc[0]
    assert "relevance_breakdown" in r.hits.columns
    assert "oxygen" in top["relevance_breakdown"]
    assert "0.35" in config.RELEVANCE_HELP or "35 %" in config.RELEVANCE_HELP
    # Inject an "outcome not listed" copy of the top row and confirm it ranks lower
    tagged = DF.copy()
    tagged.loc[tagged["row_id"] == "R2", "resultado"] = "outcome not listed in PSI table"
    tagged = load_dataset(
        (
            "experimento,combustible,oxigeno,presion,resultado,fase,fuente\n"
            + "\n".join(
                f"{row.experimento},{row.combustible},{row.oxigeno},{row.presion},"
                f"{'outcome not listed in PSI table' if row.row_id=='R2' else row.resultado},"
                f"{row.fase},{row.fuente}"
                for row in DF.itertuples()
            )
            + "\n"
        ).encode("utf-8")
    ).df
    r2 = rank(tagged, c)
    # R2 is still the closest in oxygen but must be penalised
    r2_row = r2.ranked[r2.ranked["row_id"] == "R2"].iloc[0]
    assert bool(r2_row["outcome_not_listed"])
    assert r2_row["relevance"] < r2_row["relevance_raw"]
    assert r2_row["relevance"] == round(float(r2_row["relevance_raw"]) * config.OUTCOME_MISSING_FACTOR, 3)


def test_gas_columns_from_resultado_and_notas():
    raw = parse_row_text(
        "O2 22.2 -> 21.8 % vol (initial -> final); CO2 0.44 -> 0.49 % vol (initial -> final); CO 12 -> 19 ppm (initial -> final)",
        "ambient mole fractions O2=0.21, N2=0.79, CO2=0.0, He=0.15",
    )
    assert raw["o2_start_pct"] == 22.2 and raw["o2_end_pct"] == 21.8
    assert raw["co2_start_pct"] == 0.44 and raw["co2_end_pct"] == 0.49
    assert raw["co2_start_ppm"] == 4400 and raw["co2_end_ppm"] == 4900
    assert raw["co_start_ppm"] == 12 and raw["co_end_ppm"] == 19
    assert raw["x_he"] == 0.15 and "He" in raw["diluent"]
    assert display_gas(None) == UNSPECIFIED
    csv = (
        "experimento,combustible,oxigeno,presion,resultado,fase,fuente,notas\n"
        "BASS-II,PMMA,22.2,1.0,"
        "\"O2 22.2 -> 21.8 % vol (initial -> final); CO2 0.44 -> 0.49 % vol (initial -> final); CO 12 -> 19 ppm (initial -> final)\","
        "detect,https://doi.org/10.60555/example,"
        "\"test B3; ambient mole fractions O2=0.222, N2=0.778, CO2=0.0, He=0.0\"\n"
        "SAFFIRE-I,SIBAL Fabric,21.5,1.0,large-scale burn; burn time 70.0 s,prevent,https://doi.org/10.60555/example,sample S2; O2 as reported: ~ 21.5 %\n"
    )
    ds = load_dataset(csv.encode("utf-8"))
    bass = ds.df.iloc[0]
    assert bass["co_start_ppm"] == 12
    assert bass["co2_start_ppm"] == 4400
    saff = ds.df.iloc[1]
    assert display_gas(saff["co_start_ppm"]) == UNSPECIFIED
    assert display_gas(saff["co2_start_ppm"]) == UNSPECIFIED
    assert "source does not specify" in display_gas(saff["co2_end_ppm"])


def test_offline_template_has_citations_and_no_unsupported_action():
    res = answer_question("How do I extinguish an n-heptane fire at 21% oxygen?", DF, llm=None)
    assert res.mode == "offline"
    assert res.calculations is not None and res.calculations.lines
    # A droplet that burned in air and went out later does not show that "below 21 % O2" extinguishes.
    assert res.actions == []
    assert "[R1]" in res.draft.answer or any(e.row_id == "R1" for e in res.draft.evidence)
    assert "microgravity" in res.draft.limitations.lower()
    assert res.sources  # fuente carried onto the answer


def test_nist_janaf_cp_at_298k_and_notas_cannot_override_resultado():
    from flame.physics import CP_298K, atmosphere_indices
    assert CP_298K == {"N2": 29.1, "O2": 29.4, "CO2": 37.1, "He": 20.8, "Ar": 20.8}
    earth = atmosphere_indices(21.0, 1.0)
    # 79 % N2 / 21 % O2 at 298.15 K: 0.79 × 29.1 / 0.21 = 109.5 J/K per mole of O2
    assert abs(earth["ballast"] - 109.5) < 0.05
    # A "No ignition" comment must not override a stated hot ignition in resultado.
    row = parse_row_text(
        "hot ignition; burn time 43.0 s; flow terminated (fuel flow stopped)",
        "comments: Igniter voltage: 2.25V. No ignition.",
    )
    assert row["ignited"] is True and row["no_ignition"] is False
    # Final O2 after flame-out is not a no-flame bound.
    df = _frame(
        "X,n-heptane,21,1.0,flame extinguished (extinction) before droplet burned out; O2 21.0 -> 16.0 % vol (initial -> final),extinguish,SIMULATED,\n"
        "X,n-heptane,18,1.0,flame extinguished (extinction) before droplet burned out,extinguish,SIMULATED,\n"
        "X,n-heptane,25,1.0,burned to completion,extinguish,SIMULATED,\n"
    )
    report = compute_physics(df, df, parse_rules("How do I extinguish an n-heptane fire at 21% oxygen?", ["n-heptane"]))
    assert report.lowest_o2_burned == 18.0
    assert report.bracket["highest_nonburn_below"] is None




if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok    {name}")
        except Exception as err:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}: {type(err).__name__}: {err}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
