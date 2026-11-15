"""v7b: two-model roles (flash gathers, hydrogen interprets) with a fake Gemini client. No network."""

from __future__ import annotations

import os

os.environ.setdefault("FLAME_DATA_PATH", str(__import__("pathlib").Path(__file__).resolve().parents[1]
                                             / "data" / "experiments_simulated.csv"))

import pytest  # noqa: E402
from google.genai import errors  # noqa: E402

from flame import agent, config  # noqa: E402
from flame.agent import engine_gather, reset_cooldowns, run_ai, run_hybrid, trace_dot  # noqa: E402
from test_agent import (DF, FLASH, HYDROGEN, Q_EN, Q_ES, FakeClient, call, en_answer, es_answer,  # noqa: E402
                        json_turn, text_turn, tool_turn)

FLASH36 = "gemini-3.6-flash"
GATHER = [FLASH, FLASH36, config.ENGINE_GATHER]
INTERP = [HYDROGEN, FLASH, FLASH36]


def hybrid_es(**over):
    """Spanish answer valid against the hybrid ledger: E1 = engine search (46 / 42), E3 = flash's PMMA bracket."""
    claims = [
        {"text": "De 46 filas de metanol cerca del 21 % de oxígeno, 42 registran extinción [E1].",
         "phase": "extinguish", "kind": "computed", "row_ids": [], "evidence_ids": ["E1"]},
        {"text": "La llama más baja de PMMA se registró con 15 % de oxígeno [E3] [R716].",
         "phase": "prevent", "kind": "observed", "row_ids": ["R716"], "evidence_ids": ["E3"]},
    ]
    return es_answer(claims=claims, **over)


FLASH_GATHER = [tool_turn(call("oxygen_bracket", fuel="PMMA")), text_turn("done")]


@pytest.fixture(autouse=True)
def _fresh_cooldowns():
    reset_cooldowns()
    yield
    reset_cooldowns()


@pytest.fixture(scope="module")
def res_es():
    from flame.pipeline import answer_question
    return answer_question(Q_ES, DF, None, "es")


@pytest.fixture(scope="module")
def res_en():
    from flame.pipeline import answer_question
    return answer_question(Q_EN, DF, None, "en")


def hyb(script, res, q=Q_ES, lang="es", gather=GATHER, interp=INTERP):
    client = FakeClient(script)
    return run_hybrid(q, DF, res, client, lang, gather_models=list(gather), interpret_models=list(interp)), client


def requests(client, model=None, step=None):
    return [e for e in client.models.log if (model is None or e["model"] == model) and (step is None or e["step"] == step)]


def err429():
    return errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                              "message": "Generate content requests per day limit exceeded"}})


def err503():
    return errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE",
                                              "message": "This model is currently experiencing high demand."}})


# ---------------------------------------------------------------------------
# Engine baseline
# ---------------------------------------------------------------------------

def test_engine_baseline_needs_no_model_and_matches_engine(res_es):
    led = engine_gather(DF, res_es)
    tools = [c["tool"] for c in led.calls]
    assert tools[0] == "search_experiments" and {"oxygen_bracket", "compare_diluents", "metric_trend"} <= set(tools)
    assert all(c["by"] == config.ENGINE_GATHER for c in led.calls)
    v = led.facts["E1"]["values"]
    assert (v["matching_rows"], v["matching_rows_extinguished"]) == (46, 42)


def test_engine_baseline_widens_an_empty_search():
    from flame.pipeline import answer_question
    res = answer_question("Is a 30% oxygen cabin at 0.7 atm riskier for silicone than Earth air?", DF, None, "en")
    led = engine_gather(DF, res)
    searches = [led.facts[c["evidence_id"]]["values"]["matching_rows"] for c in led.calls
                if c["tool"] == "search_experiments"]
    assert searches[0] == 0 and searches[-1] > 0  # the empty exact search is kept as evidence, then widened
    assert "atmosphere" in [c["tool"] for c in led.calls]


# ---------------------------------------------------------------------------
# Hand-off: flash gathers, hydrogen interprets
# ---------------------------------------------------------------------------

def test_flash_gathers_once_and_hydrogen_interprets_once(res_es):
    out, client = hyb({FLASH: {"gather": FLASH_GATHER}, HYDROGEN: {"interpret": [json_turn(hybrid_es())]}}, res_es)
    assert out.ok and out.mode == HYDROGEN and out.gather_model == FLASH and out.hybrid
    assert len(requests(client, FLASH, "gather")) == 1  # GATHER_MAX_ROUNDS = 1
    assert len(requests(client, HYDROGEN)) == 1  # hydrogen: exactly one request per question
    assert requests(client, HYDROGEN)[0]["step"] == "interpret"
    by = {c["by"] for c in out.ledger.calls}
    assert by == {config.ENGINE_GATHER, FLASH}
    assert [a.step for a in out.attempts] == ["baseline", "gather", "interpret", "verify"]


def test_flash_planner_config(res_es):
    out, client = hyb({FLASH: {"gather": FLASH_GATHER}, HYDROGEN: {"interpret": [json_turn(hybrid_es())]}}, res_es)
    cfg = requests(client, FLASH, "gather")[0]["config"]
    assert cfg.tool_config.function_calling_config.mode == "AUTO"  # baseline exists: may add nothing
    assert str(getattr(cfg.thinking_config.thinking_level, "value", cfg.thinking_config.thinking_level)).lower() == config.GATHER_THINKING_LEVEL
    assert cfg.http_options.timeout == int(config.GATHER_REQUEST_TIMEOUT_S * 1000)
    assert getattr(cfg, "temperature", None) is None
    prompt = requests(client, FLASH, "gather")[0]["contents"][0].parts[0].text
    assert "ALREADY gathered" in prompt and "E1" in prompt
    icfg = requests(client, HYDROGEN)[0]["config"]
    assert str(getattr(icfg.thinking_config.thinking_level, "value", icfg.thinking_config.thinking_level)).lower() == config.INTERPRET_THINKING_LEVEL


def test_busy_flash_falls_to_next_flash_then_engine(res_es):
    out, client = hyb({FLASH: {"gather": [err503()]}, FLASH36: {"gather": [TimeoutError("timed out")]},
                       HYDROGEN: {"interpret": [json_turn(es_answer(claims=es_answer()["claims"][:1]))]}}, res_es)
    assert out.ok and out.mode == HYDROGEN and out.gather_model == config.ENGINE_GATHER
    fails = [(a.model, a.reason) for a in out.attempts if a.step == "gather"]
    assert fails == [(FLASH, "busy (503)"), (FLASH36, "timeout")]
    assert len(requests(client, HYDROGEN)) == 1


def test_hydrogen_quota_hands_off_to_flash_and_cools_down(res_es):
    script = {FLASH: {"gather": [FLASH_GATHER[0], FLASH_GATHER[0]], "interpret": [json_turn(hybrid_es())] * 2},
              HYDROGEN: {"interpret": [err429(), json_turn(hybrid_es())]}}
    client = FakeClient(script)
    out = run_hybrid(Q_ES, DF, res_es, client, "es", GATHER, INTERP)
    assert out.ok and out.mode == FLASH
    assert ("interpret", False, "quota / rate limit (429)") in [(a.step, a.ok, a.reason) for a in out.attempts
                                                                if a.model == HYDROGEN]
    # Next question: hydrogen is skipped without a request (it is cooling down).
    out2 = run_hybrid(Q_ES, DF, res_es, client, "es", GATHER, INTERP)
    assert out2.ok and out2.mode == FLASH
    assert len(requests(client, HYDROGEN)) == 1
    assert any("cooling down" in a.reason for a in out2.attempts if a.model == HYDROGEN)


def test_cooldown_expires(res_es, monkeypatch):
    monkeypatch.setattr(config, "COOLDOWN_QUOTA_S", 0.0)
    script = {FLASH: {"interpret": [json_turn(hybrid_es())]},
              HYDROGEN: {"interpret": [err429(), json_turn(es_answer(claims=es_answer()["claims"][:1]))]}}
    client = FakeClient(script)
    run_hybrid(Q_ES, DF, res_es, client, "es", [config.ENGINE_GATHER], INTERP)
    out = run_hybrid(Q_ES, DF, res_es, client, "es", [config.ENGINE_GATHER], INTERP)
    assert out.mode == HYDROGEN and len(requests(client, HYDROGEN)) == 2


def test_verifier_rejection_is_repaired_by_flash_with_reasons(res_es):
    bad = hybrid_es(summary="En los experimentos FLEX con metanol la llama se apagó en 77 de 46 filas [E1].")
    out, client = hyb({FLASH: {"gather": FLASH_GATHER, "interpret": [json_turn(hybrid_es())]},
                       HYDROGEN: {"interpret": [json_turn(bad)]}}, res_es)
    assert out.ok and out.mode == FLASH
    steps = [(a.model, a.step, a.ok) for a in out.attempts]
    assert (HYDROGEN, "verify", False) in steps and (FLASH, "repair", True) in steps
    repair_prompt = requests(client, FLASH, "interpret")[0]["contents"][0].parts[0].text
    assert "REJECTED" in repair_prompt and "77" in repair_prompt
    assert len(requests(client, FLASH, "gather")) == 1  # the pack is not gathered again


def test_everything_fails_engine_answers_with_the_baseline_kept(res_es):
    out, client = hyb({FLASH: {"gather": [err503()], "interpret": [err503()]},
                       FLASH36: {"gather": [err429()], "interpret": [err429()]},
                       HYDROGEN: {"interpret": [err429()]}}, res_es)
    assert not out.ok and out.mode == agent.ENGINE_MODE and out.reason == "errors"
    assert out.answer is None and out.ledger.facts  # the trace still shows what the engine gathered


def test_english_hybrid_and_language_check(res_en):
    out, _ = hyb({FLASH: {"gather": [text_turn("done")]}, HYDROGEN: {"interpret": [json_turn(en_answer())]}},
                 res_en, q=Q_EN, lang="en")
    assert out.ok and out.mode == HYDROGEN and out.gather_model == FLASH
    wrong, _ = hyb({FLASH: {"gather": [text_turn("done")]}, HYDROGEN: {"interpret": [json_turn(es_answer())]},
                    FLASH36: {}}, res_en, q=Q_EN, lang="en", interp=[HYDROGEN])
    assert not wrong.ok and wrong.reason == "verifier"


def test_no_key_and_out_of_scope_skip_the_models(res_es):
    assert run_hybrid(Q_ES, DF, res_es, None, "es").reason == "no_key"
    from flame.pipeline import answer_question
    res = answer_question("What is the capital of France?", DF, None, "en")
    if res.conditions.phase == "out_of_scope":
        client = FakeClient({})
        assert run_hybrid("What is the capital of France?", DF, res, client, "en").reason == "out_of_scope"
        assert client.models.log == []


def test_run_ai_default_is_hybrid_and_explicit_models_stay_legacy(res_es, monkeypatch):
    monkeypatch.setattr(config, "GATHER_MODELS", [FLASH, config.ENGINE_GATHER])
    monkeypatch.setattr(config, "INTERPRET_MODELS", [HYDROGEN])
    client = FakeClient({FLASH: {"gather": FLASH_GATHER}, HYDROGEN: {"interpret": [json_turn(hybrid_es())]}})
    out = run_ai(Q_ES, DF, res_es, client, "es")
    assert out.hybrid and out.mode == HYDROGEN
    legacy = run_ai(Q_ES, DF, res_es, FakeClient({HYDROGEN: {"gather": [text_turn()]}}), "es", models=[HYDROGEN])
    assert not legacy.hybrid


def test_trace_shows_baseline_and_handoff(res_es):
    bad = hybrid_es(summary="En los experimentos FLEX con metanol la llama se apagó en 77 de 46 filas [E1].")
    out, _ = hyb({FLASH: {"gather": FLASH_GATHER, "interpret": [json_turn(hybrid_es())]},
                  HYDROGEN: {"interpret": [json_turn(bad)]}}, res_es)
    labels = {k: k for k in ("question", "engine", "gather", "pack", "interpret", "verify_ok", "verify_fail",
                             "ui_ai", "ui_engine", "baseline", "handoff", "rejected")}
    dot = trace_dot(out, labels)
    assert dot.startswith("digraph") and dot.rstrip().endswith("}")
    assert "b [label=" in dot and "g [label=" in dot and "handoff" in dot
    assert HYDROGEN in dot and FLASH in dot and "rejected" in dot and "repair" in dot


def test_model_roles_from_env(monkeypatch):
    monkeypatch.setenv("GATHER_MODELS", "gemini-3.6-flash")
    monkeypatch.setenv("INTERPRET_MODELS", "gemini-4-hydrogen,engine,gemini-3.6-flash")
    assert config._models_env("GATHER_MODELS", "x") == ["gemini-3.6-flash"]
    import importlib
    cfg = importlib.reload(config)
    try:
        assert cfg.GATHER_MODELS == ["gemini-3.6-flash", "engine"]
        assert cfg.INTERPRET_MODELS == ["gemini-4-hydrogen", "gemini-3.6-flash"]
    finally:
        monkeypatch.delenv("GATHER_MODELS")
        monkeypatch.delenv("INTERPRET_MODELS")
        importlib.reload(config)


def test_default_roles():
    # Fast flash models first (hydrogen needs ~1 min per request and used up the whole time budget).
    assert config.INTERPRET_MODELS[0] == "gemini-3.6-flash" and "gemini-4-hydrogen" in config.INTERPRET_MODELS
    assert config.GATHER_MODELS[0] == "gemini-3.8-flash" and config.GATHER_MODELS[-1] == config.ENGINE_GATHER
    assert config.GATHER_MAX_ROUNDS == 1


# ---------------------------------------------------------------------------
# v8: router + specialist agents (each agent walks its own path; 0 model requests)
# ---------------------------------------------------------------------------

def test_router_activates_agents_and_every_fact_has_an_owner(res_es):
    from flame.agent import AGENTS, route
    lead, active = route(DF, res_es)
    assert lead == "extinction" and {"extinction", "prevention", "timing"} <= set(active)
    led = engine_gather(DF, res_es)
    assert led.agents and set(led.agents) <= set(AGENTS)
    assert all(c.get("agent") in AGENTS for c in led.calls)
    assert all(f.get("agent") in led.agents for f in led.facts.values())
    pack = led.as_pack()
    assert pack["active_agents"] == led.agents and all("agent" in f for f in pack["facts"])
    by_agent = {a: [c["tool"] for c in led.calls if c["agent"] == a] for a in led.agents}
    assert "compare_diluents" in by_agent["extinction"] and "oxygen_bracket" in by_agent["prevention"]
    assert by_agent["timing"] == ["metric_trend"]


def test_detection_agent_reports_gas_readings():
    from flame.pipeline import answer_question
    res = answer_question("Which gas signal detects a PMMA fire first, CO or CO2?", DF, None, "en")
    led = engine_gather(DF, res)
    assert "detection" in led.agents
    facts = [f for f in led.facts.values() if f.get("agent") == "detection"]
    assert any("rows_with_CO_reading" in f["values"] for f in facts)


def test_verifier_rejects_a_finding_from_an_inactive_agent(res_es):
    from flame.ai_schema import AgentFinding, InterpretedAnswer
    from flame.verify import verify_interpretation
    led = engine_gather(DF, res_es)
    idle = next(a for a in ("detection", "timing", "prevention", "extinction") if a not in led.agents)
    ans = InterpretedAnswer(enough_evidence=False, summary="Resumen de la evidencia del metanol [E1].",
                            agents=[AgentFinding(agent=idle, finding="Nada [E1].")])
    assert any("not active" in p for p in verify_interpretation(ans, led, res_es.question, "es"))
