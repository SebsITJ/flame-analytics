"""HTML version: FastAPI server + JSON API over the real engine. No network, no real key."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from flame import config, web  # noqa: E402
from flame.agent import reset_cooldowns  # noqa: E402
from flame.data import load_dataset  # noqa: E402
from test_agent import FLASH, HYDROGEN, Q_EN, Q_ES, FakeClient, es_answer, json_turn  # noqa: E402

FAKE_KEY = "fake-gemini-key-for-tests-0123456789abcdef"
DATASET = load_dataset(ROOT / "data" / "experiments.csv")


@pytest.fixture()
def api(monkeypatch):
    """A client over the real dataset with no Gemini client (engine only)."""
    st = server.State()
    st.dataset, st.client, st.loaded = DATASET, None, True
    monkeypatch.setattr(server, "STATE", st)
    reset_cooldowns()
    yield TestClient(server.app), st
    reset_cooldowns()


def ask(client, q, lang=None, ai=True):
    r = client.post("/api/ask", json={"question": q, "lang": lang, "ai": ai})
    assert r.status_code == 200, r.text
    return r.json()


def test_health_and_meta(api):
    c, _ = api
    h = c.get("/api/health").json()
    assert h == {"ok": True, "rows": len(DATASET.df), "ai_enabled": False}
    m = c.get("/api/meta?lang=es").json()
    assert m["lang"] == "es" and set(m["strings"]) == {"en", "es"}
    assert m["strings"]["es"]["tab.assistant"] == "Asistente"
    assert m["phases"] == list(config.PHASES) and m["animation_seconds"] > 0
    for code in ("en", "es"):
        assert "ff-brand" in m["html"]["brand"][code] and m["html"]["footer"][code]


def test_demo_numbers_spanish(api):
    c, _ = api
    d = ask(c, Q_ES, "es", ai=False)
    v = d["view"]
    assert d["lang"] == "es" and d["out_of_scope"] is False
    assert (v["verdict"]["n"], v["verdict"]["k"]) == (7, 8)
    dil = {x["gas"]: (x["extinguished"], x["rows"]) for x in v["diluent"]}
    assert dil == {"CO2": (64, 75), "He": (27, 28), "N2": (44, 54)}
    assert v["o2_scale"]["flame_from"] == {"o2": 12.0, "row_id": "R83"}
    assert "7" in d["html"]["board"] and d["animation"]["html"].startswith("<")
    assert "ai" not in d


def test_lowest_flame_pmma_english(api):
    c, _ = api
    d = ask(c, "At what oxygen level does PMMA stop burning?", "en", ai=False)
    assert d["lang"] == "en"
    assert d["view"]["o2_scale"]["flame_from"]["o2"] == 15.0


def test_no_key_falls_back_to_engine(api):
    c, _ = api
    d = ask(c, Q_EN)
    assert d["ai"]["ok"] is False and d["ai"]["badge"] and d["ai"]["user_note"]
    for private in ("mode", "reason", "note", "tech_badge", "attempts", "trace", "calls", "seconds"):
        assert private not in d["ai"], private  # the reason (no key) stays on the server
    i = c.post("/api/interpret", json={"question": Q_ES}).json()
    assert i["lang"] == "es" and i["ai"]["ok"] is False and "reason" not in i["ai"]


def test_ai_answer_with_fake_hydrogen(api, monkeypatch):
    c, st = api
    monkeypatch.setattr(config, "GATHER_MODELS", [config.ENGINE_GATHER])
    monkeypatch.setattr(config, "INTERPRET_MODELS", [HYDROGEN, FLASH])
    st.client = FakeClient({HYDROGEN: {"interpret": [json_turn(es_answer(claims=es_answer()["claims"][:1]))]}})
    ai = c.post("/api/interpret", json={"question": Q_ES, "lang": "es"}).json()["ai"]
    assert ai["ok"] is True and ai["claims"] and "ff-cite" in ai["summary_html"]
    assert ai["chart"] and ai["chart"]["spec"]["$schema"].startswith("https://vega.github.io")
    for private in ("mode", "gather_model", "trace", "calls", "attempts", "agents", "seconds", "tech_badge", "labels"):
        assert private not in ai, private  # the page never receives model names, trace or timings
    assert HYDROGEN not in json.dumps(ai)
    assert len(st.client.models.log) == 1  # engine gathers: hydrogen is the only request
    # the internal trace still exists in the backend for the team
    st.client = FakeClient({HYDROGEN: {"interpret": [json_turn(es_answer(claims=es_answer()["claims"][:1]))]}})
    res = web.answer_question(Q_ES, DATASET.df, None, "es")
    full = web.ai_payload(web.run_ai_safe(Q_ES, res, DATASET.df, st.client), res, DATASET.df)
    assert full["mode"] == HYDROGEN and [s["kind"] for s in full["trace"]][:2] == ["question", "engine"]
    assert any(s["kind"] == "interpret" and s["model"] == HYDROGEN for s in full["trace"]) and full["calls"]


def test_ai_errors_fall_back(api, monkeypatch):
    c, st = api
    monkeypatch.setattr(config, "GATHER_MODELS", [config.ENGINE_GATHER])
    monkeypatch.setattr(config, "INTERPRET_MODELS", [HYDROGEN])
    st.client = FakeClient({HYDROGEN: {"interpret": [RuntimeError("boom")]}})
    d = ask(c, Q_ES, "es")
    assert d["ai"]["ok"] is False and d["ai"]["badge"] and "mode" not in d["ai"]
    assert d["view"]["verdict"]["n"] == 7  # the engine answer is unaffected


def test_out_of_scope_and_validation(api):
    c, _ = api
    d = ask(c, "What is the capital of France?", "en")
    assert d["out_of_scope"] is True and d["state"] == "out_of_scope" and d["metric_chart"] is None
    assert d["ai"]["ok"] is False
    assert c.post("/api/ask", json={"question": ""}).status_code == 422
    assert c.post("/api/ask", json={"question": "   "}).status_code == 422
    assert c.post("/api/ask", json={"question": "x" * 1001}).status_code == 422


def test_explorer_and_charts(api):
    c, _ = api
    x = c.get("/api/explorer").json()
    assert len(x["rows"]) == len(DATASET.df) and "row_id" in x["columns"]
    assert set(x["required"]) <= set(x["rows"][0]) and x["rows"][0]["link"].startswith("http")
    ch = c.get("/api/charts?lang=es").json()
    assert ch["oxygen"]["spec"] and ch["conditions"]["spec"]
    assert ch["oxygen"]["spec"]["width"] == "container"


def test_static_page_and_assets(api):
    c, _ = api
    page = c.get("/")
    assert page.status_code == 200 and "app.js" in page.text and "vega-embed" in page.text
    for path in ("/static/app.js", "/static/app.css", "/theme.css", "/static/vendor/vega.min.js",
                 "/static/vendor/vega-lite.min.js", "/static/vendor/vega-embed.min.js"):
        assert c.get(path).status_code == 200, path
    assert "NASA" not in page.text or "endorse" not in page.text.lower()


def test_key_never_leaves_the_server(api, monkeypatch, tmp_path):
    c, st = api
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    assert server.read_api_key() == FAKE_KEY
    st.client = FakeClient({})
    bodies = [c.get(p).text for p in ("/", "/static/app.js", "/api/meta?lang=en", "/api/health")]
    bodies.append(c.post("/api/ask", json={"question": Q_EN}).text)
    for b in bodies:
        assert FAKE_KEY not in b and "AIza" not in b
    real = os.environ.get("GOOGLE_API_KEY", "")
    if real:
        assert all(real not in b for b in bodies)


def test_read_key_from_files(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(server, "ROOT", tmp_path)
    assert server.read_api_key() is None
    (tmp_path / ".streamlit").mkdir()
    (tmp_path / ".streamlit" / "secrets.toml").write_text('GEMINI_API_KEY = "paste-your-key-here"\n')
    assert server.read_api_key() is None
    (tmp_path / ".streamlit" / "secrets.toml").write_text(f'GEMINI_API_KEY = "{FAKE_KEY}"\n')
    assert server.read_api_key() == FAKE_KEY
    (tmp_path / ".env").write_text("GEMINI_API_KEY='from-env-file'\n")
    assert server.read_api_key() == "from-env-file"


def test_alternative_page_contract_matches_engine(api):
    """web/panel.html's JSON shape, filled from the real engine: the same demo numbers as the main page."""
    c, _ = api
    assert c.get("/panel").status_code == 200
    page = c.get("/panel").text
    assert "/api/ask_v2" in page and "buildMock(question, lang), source" not in page
    d = c.post("/api/ask_v2", json={"question": Q_ES, "lang": "es"}).json()
    assert d["phase"] == "EXTINGUISH" and d["lang"] == "es"
    assert (d["verdict"]["numerator"], d["verdict"]["denominator"]) == (7, 8)
    assert {x["name"]: (x["extinguished"], x["total"]) for x in d["diluents"]} == \
        {"CO2": (64, 75), "He": (27, 28), "N2": (44, 54)}
    assert len(d["evidence"]) == 8 and all(e["id"].startswith("R") for e in d["evidence"])
    assert sum(e["outcome"] == "extinguished" for e in d["evidence"]) == 7
    assert d["model_trace"] == {"answered_by": "Respuesta basada en los datos", "fallback_used": True}
    assert d["oxygen"]["query_o2_pct"] == 21.0 and d["oxygen"]["bins"]
    assert "[R1]" in d["interpretation"]
