"""Team spec C3 (not enough data first, never a big 0/N) and C4 (Moon / Mars notice). Engine only, no network."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flame import config, web  # noqa: E402
from flame.data import load_dataset  # noqa: E402
from flame.lead import MEASUREMENTS, mentions_partial_gravity, missing_material  # noqa: E402

DF = load_dataset(ROOT / "data" / "experiments.csv").df  # the real table, whatever FLAME_DATA_PATH says
BIG = re.compile(r'ff-big"><b>(\d+)<small>/(\d+)')


def ask(q):
    out, _ = web.ask_payload(q, None, DF)
    return out


def test_missing_material_says_so_first_and_hides_the_big_number():
    out = ask("¿Cómo apago un incendio de litio en la Luna?")
    assert out["lead"]["state"] == "nodata"
    assert out["lead"]["sentence"].startswith("Los datos no alcanzan") and "litio" in out["lead"]["reason"]
    assert "ff-lead-nodata" in out["lead_html"] and "ff-nodata" in out["html"]["board"]
    assert not BIG.search(out["html"]["board"])
    en = ask("How do I put out a lithium fire on the Moon?")
    assert en["lead"]["sentence"].startswith("The data are not enough") and "lithium" in en["lead"]["reason"]


def test_materials_that_exist_are_not_reported_missing():
    assert missing_material("incendio de litio", DF) == ("litio", "lithium")
    assert missing_material("un fuego de metanol", DF) is None
    assert missing_material("does cotton burn?", DF) is None


def test_moon_and_mars_notice_only_when_mentioned():
    for q in ("¿Puede arder papel en Marte con 30 % de oxígeno?", "¿Cómo apago un incendio de litio en la Luna?",
              "Can PMMA burn in a lunar habitat at 30% oxygen?"):
        out = ask(q)
        assert out["lead"]["notices"] and ("gravedad parcial" in out["lead_html"] or "partial gravity" in out["lead_html"])
    assert ask("¿Cómo apago un fuego de metanol al 21 % de oxígeno?")["lead"]["notices"] == []
    assert not mentions_partial_gravity("Marsella y la lunática")


def test_detect_without_gas_readings_never_shows_zero_of_n():
    out = ask("¿Cómo detecto un incendio temprano en la nave?")
    v = out["view"]["verdict"]
    assert v["kind"] == "rows" and v["n"] == v["k"] and not BIG.search(out["html"]["board"])  # never "0 of N"
    assert "no midieron gases" in out["html"]["board"] and "no midieron gases" in out["lead_html"]
    assert [m["experiment"] for m in out["lead"]["measurements"]]  # C11: what each experiment measured
    assert "DustTrak" not in out["lead_html"] or "DAFT" in out["lead_html"]


def test_demo_numbers_are_unchanged():
    out = ask("¿Cómo apago un fuego de metanol al 21 % de oxígeno?")
    assert BIG.search(out["html"]["board"]).groups() == ("7", "8")
    assert "7 de 8" in out["lead"]["sentence"] and out["lead"]["sentence"] in out["lead_html"]  # C1: answer first
    assert "46 filas de 1 experimento (FLEX)" in out["lead"]["confidence"]
    assert "CO2 64/75" in out["lead"]["action"] and "He 27/28" in out["lead"]["action"]
    bars = {b["gas"]: (b["extinguished"], b["rows"]) for b in out["view"]["diluent"]}
    assert bars == {"CO2": (64, 75), "He": (27, 28), "N2": (44, 54)}


def test_measurement_table_covers_every_experiment_and_names_no_extra_instrument():
    assert set(DF["experimento"].unique()) <= set(MEASUREMENTS)
    named = [e for e, m in MEASUREMENTS.items() if "P-Trak" in m["en"] or "DustTrak" in m["en"]]
    assert named == ["DAFT"]


def test_gas_question_cites_where_gases_were_measured():
    out = ask("¿Qué gases indican que hay un incendio?")
    assert "BASS-II" in out["lead"]["reason"] and "CO2" in out["lead"]["reason"] and "+2.400 ppm" in out["lead"]["reason"]
    cotton = ask("¿Qué gases indican que el algodón está ardiendo?")
    assert cotton["view"]["verdict"]["kind"] == "reading" and "BASS-II" in cotton["lead"]["confidence"]


def test_explorer_has_measurement_type_and_no_ai_without_data():
    ex = web.explorer_rows(DF)
    cats = {r["experimento"]: r["medicion"] for r in ex["rows"]}
    assert cats["BASS-II"] == "gas" and cats["SPICE"] == "soot" and cats["DAFT"] == "dust" and "gas" in ex["measure_labels"]
    q = "¿Cómo apago un incendio de litio en la Luna?"
    _, res = web.ask_payload(q, None, DF)
    assert web.run_ai_safe(q, res, DF, client=object()).reason == "no_data"  # no request spent


def test_panel_payload_carries_the_same_notices():
    q = "¿Cómo apago un incendio de litio en la Luna?"
    out, res = web.ask_payload(q, None, DF)
    c = web.panel_payload(out, res, web.ai_payload(None, res, DF), DF, 0.1)
    assert c["verdict"]["numerator"] is None and "Los datos no alcanzan" in c["interpretation"]
    assert any("gravedad parcial" in w for w in c["warnings"])


def test_zero_of_n_is_hidden_when_the_rows_do_not_record_the_outcome():
    out = ask("¿Puede arder el PMMA con 18 % de oxígeno?")
    assert out["lead"]["hide_count"] and "no registran" in out["lead"]["sentence"] and "hubo llama" in out["lead"]["sentence"]
    assert not BIG.search(out["html"]["board"]) and "0 de 8" not in out["lead_html"]
