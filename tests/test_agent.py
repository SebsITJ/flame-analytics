"""v7 AI interpreter: tool loop, caps, schema, verifier, model chain, bilingual. No network: a fake Gemini
client replays scripted responses through the same google-genai types the real SDK uses."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
# Same default as test_core.py (config reads it at import); this file loads the NASA CSV explicitly below.
os.environ.setdefault("FLAME_DATA_PATH", str(ROOT / "data" / "experiments_simulated.csv"))
sys.path.insert(0, str(ROOT))

from google.genai import types  # noqa: E402

from flame import agent, config  # noqa: E402
from flame.agent import ENGINE_MODE, run_ai, trace_dot  # noqa: E402
from flame.ai_schema import InterpretedAnswer, response_schema  # noqa: E402
from flame.ai_view import build_chart, linkify, safe_text  # noqa: E402
from flame.data import load_dataset  # noqa: E402
from flame.pipeline import answer_question  # noqa: E402
from flame.tools import TOOL_SCHEMAS, Ledger, dispatch  # noqa: E402
from flame.verify import unsupported_numbers_loose, verify_interpretation  # noqa: E402

DF = load_dataset(ROOT / "data" / "experiments.csv").df
HYDROGEN, FLASH = "gemini-4-hydrogen", "gemini-3.8-flash"
Q_ES = "¿Cómo apago un fuego de metanol al 21 % de oxígeno?"
Q_EN = "How do I put out a methanol fire at 21% oxygen?"


# ---------------------------------------------------------------------------
# Fake client
# ---------------------------------------------------------------------------

def call(name, **args):
    return types.FunctionCall(name=name, args=args)


def tool_turn(*calls):
    content = types.Content(role="model", parts=[types.Part(function_call=c) for c in calls])
    return SimpleNamespace(function_calls=list(calls), candidates=[SimpleNamespace(content=content)],
                           text=None, parsed=None)


def text_turn(text="done"):
    content = types.Content(role="model", parts=[types.Part.from_text(text=text)])
    return SimpleNamespace(function_calls=None, candidates=[SimpleNamespace(content=content)], text=text, parsed=None)


def json_turn(obj):
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return SimpleNamespace(function_calls=None, candidates=[], text=text, parsed=None)


class FakeModels:
    def __init__(self, script):
        # script: {model: {"gather": [responses or Exception], "interpret": [...]}}; callables get the ledger later
        self.script = {m: {k: list(v) for k, v in steps.items()} for m, steps in script.items()}
        self.log = []

    def generate_content(self, model, contents, config):
        step = "interpret" if getattr(config, "response_mime_type", None) == "application/json" else "gather"
        self.log.append({"model": model, "step": step, "config": config, "contents": contents})
        queue = self.script.get(model, {}).get(step, [])
        item = queue.pop(0) if queue else (text_turn() if step == "gather" else json_turn("{}"))
        if isinstance(item, Exception):
            raise item
        if callable(item):
            item = item(contents)
        return item


class FakeClient:
    def __init__(self, script):
        self.models = FakeModels(script)


def es_answer(**over):
    a = {
        "enough_evidence": True,
        "summary": "En los experimentos FLEX con metanol la llama se apagó en 42 de 46 filas [E1], por ejemplo [R2].",
        "claims": [
            {"text": "De 46 filas de metanol cerca del 21 % de oxígeno, 42 registran extinción [E1].",
             "phase": "extinguish", "kind": "computed", "row_ids": [], "evidence_ids": ["E1"]},
            {"text": "La llama más baja de PMMA se registró con 15 % de oxígeno [E2] [R716].",
             "phase": "prevent", "kind": "observed", "row_ids": ["R716"], "evidence_ids": ["E2"]},
        ],
        "chart": {"type": "scatter", "evidence_id": "E1", "x": "oxigeno", "y": "presion", "color": "experimento",
                  "title": "Filas de metanol por oxígeno y presión"},
        "limitations": "Solo experimentos de gotas en microgravedad; no hay agentes extintores activos.",
        "missing": "",
    }
    a.update(over)
    return a


def en_answer(**over):
    a = es_answer(
        summary="In the FLEX methanol tests the flame went out in 42 of 46 rows [E1], for example [R2].",
        claims=[{"text": "Of 46 methanol rows near 21 % oxygen, 42 record extinction [E1].",
                 "phase": "extinguish", "kind": "computed", "row_ids": [], "evidence_ids": ["E1"]}],
        chart=None, limitations="Only droplet tests in microgravity; no active suppression agents.")
    a.update(over)
    return a


GOOD_GATHER = [
    tool_turn(call("search_experiments", fuel="metanol", o2_min=19.5, o2_max=22.5, phase="extinguish")),
    tool_turn(call("oxygen_bracket", fuel="PMMA")),
    text_turn("done"),
]


@pytest.fixture(scope="module")
def res_es():
    return answer_question(Q_ES, DF, None, "es")


@pytest.fixture(scope="module")
def res_en():
    return answer_question(Q_EN, DF, None, "en")


def run(script, res, q=Q_ES, lang="es", models=(HYDROGEN, FLASH)):
    client = FakeClient(script)
    return run_ai(q, DF, res, client, lang, models=list(models)), client


# ---------------------------------------------------------------------------
# Tools and ledger
# ---------------------------------------------------------------------------

def test_tools_are_a_whitelist_of_six():
    assert set(TOOL_SCHEMAS) == {"search_experiments", "get_rows", "oxygen_bracket", "compare_diluents",
                                 "metric_trend", "atmosphere"}


def test_search_tool_matches_the_engine_numbers():
    led = Ledger()
    out = dispatch("search_experiments", {"fuel": "metanol", "o2_min": 19.5, "o2_max": 22.5,
                                          "phase": "extinguish"}, DF, led)
    assert out["evidence_id"] == "E1"
    assert (out["matching_rows"], out["matching_rows_extinguished"]) == (46, 42)  # v6: 42 of 46 (91 %)
    assert all(r["row_id"] in led.rows for r in out["rows"])
    assert led.facts["E1"]["table"] and set(led.facts["E1"]["table"][0]) >= {"oxigeno", "extinguished"}


def test_atmosphere_tool_reuses_nist_index():
    out = dispatch("atmosphere", {"o2_pct": 30, "pressure_atm": 0.694}, DF, Ledger())
    assert out["inert_heat_capacity_J_per_K_per_mol_O2"] == 67.9  # Moon-base value used since v3


def test_unknown_tool_and_bad_args_become_errors_not_crashes():
    led = Ledger()
    assert "error" in dispatch("delete_everything", {}, DF, led)
    assert "error" in dispatch("search_experiments", {"o2_min": 500}, DF, led)
    assert [c["ok"] for c in led.calls] == [False, False]
    assert not led.facts


# ---------------------------------------------------------------------------
# Tool loop and caps
# ---------------------------------------------------------------------------

def test_happy_path_hydrogen_answers_in_spanish(res_es):
    out, client = run({HYDROGEN: {"gather": list(GOOD_GATHER), "interpret": [json_turn(es_answer())]}}, res_es)
    assert out.ok and out.mode == HYDROGEN, out.attempts
    assert [c["tool"] for c in out.ledger.calls] == ["search_experiments", "oxygen_bracket"]
    assert set(out.ledger.facts) == {"E1", "E2"}
    gather_cfgs = [e["config"] for e in client.models.log if e["step"] == "gather"]
    modes = [c.tool_config.function_calling_config.mode for c in gather_cfgs]
    assert str(modes[0]).endswith("ANY") and all(str(m).endswith("AUTO") for m in modes[1:])
    assert all(c.thinking_config.thinking_level for c in gather_cfgs)
    names = {d.name for d in gather_cfgs[0].tools[0].function_declarations}
    assert names == set(TOOL_SCHEMAS)
    interp = [e for e in client.models.log if e["step"] == "interpret"][0]
    assert interp["config"].tools is None  # interpret step cannot call anything
    assert interp["config"].response_json_schema == response_schema()
    assert "Spanish" in interp["contents"][0].parts[0].text


def test_no_temperature_is_sent(res_es):
    _, client = run({HYDROGEN: {"gather": list(GOOD_GATHER), "interpret": [json_turn(es_answer())]}}, res_es)
    assert all(getattr(e["config"], "temperature", None) is None for e in client.models.log)


def test_calls_per_round_are_capped(res_es):
    five = tool_turn(*[call("search_experiments", fuel="metanol", limit=2) for _ in range(5)])
    out, _ = run({HYDROGEN: {"gather": [five, text_turn()], "interpret": [json_turn("{}")]}}, res_es,
                 models=(HYDROGEN,))
    ok = [c for c in out.ledger.calls if c["ok"]]
    refused = [c for c in out.ledger.calls if c["error"] == "refused (limit)"]
    assert len(ok) == config.AGENT_MAX_CALLS_PER_ROUND and len(refused) == 5 - config.AGENT_MAX_CALLS_PER_ROUND


def test_rounds_and_total_calls_are_capped(res_es):
    forever = [tool_turn(call("search_experiments", fuel="heptano", limit=1)) for _ in range(20)]
    out, client = run({HYDROGEN: {"gather": forever, "interpret": [json_turn("{}")]}}, res_es, models=(HYDROGEN,))
    n_gather = sum(1 for e in client.models.log if e["step"] == "gather")
    assert n_gather == config.AGENT_MAX_ROUNDS
    assert len([c for c in out.ledger.calls if c["ok"]]) <= config.AGENT_MAX_TOOL_CALLS


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_schema_whitelists_chart_types_and_fields():
    s = json.dumps(response_schema())
    for word in ("bar", "scatter", "strip", "oxigeno", "metric_value", "evidence_id", "row_ids"):
        assert word in s
    with pytest.raises(Exception):
        InterpretedAnswer.model_validate(es_answer(chart={"type": "pie", "evidence_id": "E1", "x": "oxigeno",
                                                          "y": "presion", "title": "x"}))
    with pytest.raises(Exception):
        InterpretedAnswer.model_validate(es_answer(chart={"type": "bar", "evidence_id": "E1", "x": "password",
                                                          "y": "presion", "title": "x"}))


def test_broken_json_moves_to_next_model(res_es):
    out, _ = run({HYDROGEN: {"gather": list(GOOD_GATHER), "interpret": [json_turn("not json {")]},
                  FLASH: {"interpret": [json_turn(es_answer())]}}, res_es)
    assert out.mode == FLASH and out.gather_model == HYDROGEN  # evidence reused, not gathered again


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------

def _ledger_with_two_facts():
    led = Ledger()
    dispatch("search_experiments", {"fuel": "metanol", "o2_min": 19.5, "o2_max": 22.5, "phase": "extinguish"}, DF, led)
    dispatch("oxygen_bracket", {"fuel": "PMMA"}, DF, led)
    return led


def test_verifier_accepts_the_good_answer():
    led = _ledger_with_two_facts()
    assert verify_interpretation(InterpretedAnswer.model_validate(es_answer()), led, Q_ES, "es") == []


@pytest.mark.parametrize("change, expected", [
    ({"summary": "La llama se apagó en 7 de 8 pruebas [E1]."}, "numbers not in the tool outputs"),
    ({"summary": "Se apagó en 42 de 46 filas [R999999]."}, "ids not in the evidence pack"),
    ({"claims": [{"text": "El metanol se apaga solo.", "phase": "extinguish", "kind": "observed",
                  "row_ids": [], "evidence_ids": []}]}, "claim without a valid citation"),
    ({"claims": [{"text": "Dato [E9].", "phase": "general", "kind": "computed",
                  "row_ids": [], "evidence_ids": ["E9"]}]}, "ids not in the evidence pack"),
    ({"chart": {"type": "bar", "evidence_id": "E1", "x": "diluente", "y": "extinguished", "title": "t"}},
     "chart field not in E1"),
    ({"chart": {"type": "bar", "evidence_id": "E7", "x": "combustible", "y": "extinguished", "title": "t"}},
     "has no table"),
    ({"summary": "In the FLEX methanol tests the flame went out in 42 of 46 rows [E1] and the data shows it."},
     "answer language"),
])
def test_verifier_rejections(change, expected):
    led = _ledger_with_two_facts()
    problems = verify_interpretation(InterpretedAnswer.model_validate(es_answer(**change)), led, Q_ES, "es")
    assert any(expected in p for p in problems), problems


def test_number_tolerance_rules():
    allowed = ["91.3 0.52 1982 0.997 3.0597"]
    assert unsupported_numbers_loose(["91 % · 0,52 mm · 1.982 filas · 1,982 rows · 3.06 psi · 0.997 atm"], allowed) == []
    assert unsupported_numbers_loose(["1 atm"], allowed) == ["1"]  # 0.997 is not "1" (small integers exact)
    assert unsupported_numbers_loose(["CO2, O₂, PSI-69, BASS-II, FLEX2, R12, E3"], allowed) == []


# ---------------------------------------------------------------------------
# Model chain and fallback
# ---------------------------------------------------------------------------

def test_no_key_means_engine_only(res_es):
    out = run_ai(Q_ES, DF, res_es, None, "es")
    assert out.mode == ENGINE_MODE and out.reason == "no_key" and not out.attempts


def test_429_on_hydrogen_falls_to_flash(res_es):
    err = RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")
    out, _ = run({HYDROGEN: {"gather": [err]},
                  FLASH: {"gather": list(GOOD_GATHER), "interpret": [json_turn(es_answer())]}}, res_es)
    assert out.mode == FLASH
    assert out.attempts[0].model == HYDROGEN and out.attempts[0].reason == "quota / rate limit (429)"


def test_both_models_fail_engine_answers(res_es):
    out, _ = run({HYDROGEN: {"gather": [TimeoutError("timed out")]},
                  FLASH: {"gather": [RuntimeError("503 unavailable")]}}, res_es)
    assert out.mode == ENGINE_MODE and out.answer is None and out.reason == "errors"
    assert [a.ok for a in out.attempts] == [False, False]


def test_verifier_rejects_both_engine_answers(res_es):
    bad = es_answer(summary="Se apagó en 7 de 8 pruebas [E1].")
    out, _ = run({HYDROGEN: {"gather": list(GOOD_GATHER), "interpret": [json_turn(bad)]},
                  FLASH: {"interpret": [json_turn(bad)]}}, res_es)
    assert out.mode == ENGINE_MODE and out.reason == "verifier" and out.problems


def test_total_time_budget(res_es, monkeypatch):
    monkeypatch.setattr(config, "AGENT_TOTAL_TIMEOUT_S", -1.0)
    out, client = run({HYDROGEN: {"gather": list(GOOD_GATHER)}}, res_es)
    assert out.mode == ENGINE_MODE and not client.models.log


def test_out_of_scope_does_not_call_gemini():
    res = answer_question("What is the best pizza in Guayaquil?", DF, None, "en")
    if res.conditions.phase != "out_of_scope":
        pytest.skip("classifier did not mark it out of scope")
    out, client = run({HYDROGEN: {"gather": list(GOOD_GATHER)}}, res, q="pizza", lang="en")
    assert out.mode == ENGINE_MODE and not client.models.log


def test_engine_result_is_identical_with_or_without_ai(res_es):
    again = answer_question(Q_ES, DF, None, "es")
    assert again.retrieval.hits["row_id"].tolist() == res_es.retrieval.hits["row_id"].tolist()
    assert again.retrieval.facts == res_es.retrieval.facts


# ---------------------------------------------------------------------------
# Bilingual
# ---------------------------------------------------------------------------

def test_english_question_english_answer(res_en):
    out, client = run({HYDROGEN: {"gather": list(GOOD_GATHER), "interpret": [json_turn(en_answer())]}},
                      res_en, q=Q_EN, lang="en")
    assert out.ok and out.lang == "en"
    assert "English" in [e for e in client.models.log if e["step"] == "interpret"][0]["contents"][0].parts[0].text


def test_spanish_reply_to_english_question_is_rejected(res_en):
    out, _ = run({HYDROGEN: {"gather": list(GOOD_GATHER), "interpret": [json_turn(es_answer())]},
                  FLASH: {"interpret": [json_turn(es_answer())]}}, res_en, q=Q_EN, lang="en")
    assert out.mode == ENGINE_MODE and any("language" in p for p in out.problems)


# ---------------------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------------------

def test_links_cannot_be_injected_and_ids_become_links():
    evil = "Mira [aquí](https://evil.example) <script>x</script> $x$ y [R2]."
    out = linkify(evil, {"R2": "https://doi.org/10.60555/mbq8-0451"})
    assert "evil.example)" not in out.replace("(https://evil.example)", "")  # no markdown link survives
    assert "](https://evil" not in out and "<script>" not in out
    assert "[R2](https://doi.org/10.60555/mbq8-0451)" in out
    assert "\\$" in safe_text("$5")


def test_chart_is_built_from_engine_rows_only(res_es):
    out, _ = run({HYDROGEN: {"gather": list(GOOD_GATHER), "interpret": [json_turn(es_answer())]}}, res_es)
    chart = build_chart(out.answer.chart, out.ledger)
    assert chart is not None
    spec = chart.to_dict()
    values = spec.get("data", {}).get("values") or next(iter(spec.get("datasets", {}).values()))
    rows = {r["row_id"] for r in out.ledger.facts["E1"]["table"]}
    assert values and {v["row_id"] for v in values} <= rows


def test_trace_diagram_lists_tool_calls(res_es):
    out, _ = run({HYDROGEN: {"gather": list(GOOD_GATHER), "interpret": [json_turn(es_answer())]}}, res_es)
    labels = {k: k for k in ("question", "engine", "gather", "pack", "interpret", "verify_ok", "verify_fail",
                             "ui_ai", "ui_engine")}
    dot = trace_dot(out, labels)
    assert dot.startswith("digraph") and "search_experiments" in dot and "oxygen_bracket" in dot and "verify_ok" in dot


# ---------------------------------------------------------------------------
# Key hygiene
# ---------------------------------------------------------------------------

def test_no_api_key_in_the_code_and_secrets_are_ignored():
    import re

    pattern = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")
    for path in list(ROOT.glob("*.py")) + list((ROOT / "flame").glob("*.py")) + list((ROOT / ".streamlit").glob("*")):
        assert not pattern.search(path.read_text(encoding="utf-8", errors="ignore")), path
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".streamlit/secrets.toml" in ignore and ".env" in ignore


def test_default_models_are_current():
    assert config.GEMINI_MODELS[:2] == [HYDROGEN, FLASH] or "GEMINI_MODELS" in __import__("os").environ
    assert "gemini-3.7-flash" not in (ROOT / "flame" / "config.py").read_text().split("GEMINI_MODELS =")[1][:200]


def test_bar_of_a_flag_shows_the_share_of_rows(res_es):
    out, _ = run({HYDROGEN: {"gather": list(GOOD_GATHER), "interpret": [json_turn(es_answer())]}}, res_es)
    from flame.ai_schema import ChartSpec

    spec = ChartSpec(type="bar", evidence_id="E1", x="experimento", y="extinguished", title="t")
    enc = build_chart(spec, out.ledger).to_dict()["encoding"]
    assert enc["y"]["aggregate"] == "mean" and enc["y"]["axis"]["format"] == "%"
