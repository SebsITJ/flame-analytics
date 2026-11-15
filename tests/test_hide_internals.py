"""One page for everyone (Jeanpiere, 15 nov 2026): the web page shows exactly what the jury sees.

No debug switch, no query parameter, no stored flag and no endpoint can make the page show model names, the
AI trace, timings, the technical reason for an engine-only answer or the classifier's certainty. Those stay in the
backend (ai_payload, server log). Engine only, no network.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from flame import web  # noqa: E402
from flame.agent import ENGINE_MODE, AIOutcome  # noqa: E402
from flame.data import load_dataset  # noqa: E402
from flame.i18n import STRINGS, t  # noqa: E402
from flame.theme import THEME_CSS, brand_html  # noqa: E402

DF = load_dataset(ROOT / "data" / "experiments.csv").df
WEB = ROOT / "web"

# Words a decision maker never reads. "Gemini" is allowed only in the AI-use declaration.
BANNED = re.compile(
    r"gemini|\bmotor\b|determinist|sin ia|\bno ai\b|\bclave\b|\bkey\b|\bapi\b|latenc|\bms\b|\bmodel|\bmodelo|"
    r"router|enrutador|verific|verifier|quota|cuota|traza|\btrace\b|confianza|confidence|certeza|fallback|"
    r"\bjson\b|token|\bengine\b|pipeline|plantilla|template",
    re.I,
)
USER_KEYS = [
    "ai.badge_engine", "ai.badge_model", "ai.badge_hybrid", "ai.title_engine", "ai.engine_user_note", "ai.working",
    "ai.legend", "ai.kind.computed", "ai.chart_caption", "hud.engine_rules", "hud.engine_ai", "anim.classifying",
    "viz.step_classify", "viz.step_locate", "viz.step_narrow", "viz.step_verdict", "tpl.lim_template",
    "err.pipeline_user",
]
QUESTIONS = ["¿Cómo apago un incendio de metanol con 21 % de oxígeno?", "¿Cómo detecto un incendio?",
             "¿Cómo apago un incendio de litio en la Luna?", "How do I put out a methanol fire at 21% oxygen?",
             "How do I detect a fire?", "How do I put out a lithium fire on the Moon?"]
PRIVATE_AI = ("mode", "reason", "note", "tech_badge", "gather_model", "attempts", "calls", "trace", "problems",
              "agents", "seconds", "seconds_label", "labels", "how")


def text_of(html_text: str) -> str:
    return re.sub(r"<[^>]+>", " ", html_text or "")


@pytest.fixture()
def client(monkeypatch):
    st = server.State()
    st.dataset, st.client, st.loaded = load_dataset(ROOT / "data" / "experiments.csv"), None, True
    monkeypatch.setattr(server, "STATE", st)
    return TestClient(server.app, raise_server_exceptions=False)


@pytest.mark.parametrize("lang", ["en", "es"])
@pytest.mark.parametrize("key", USER_KEYS)
def test_user_strings_have_no_internal_words(key, lang):
    assert not BANNED.search(STRINGS[lang][key]), (key, lang, STRINGS[lang][key])


@pytest.mark.parametrize("lang", ["en", "es"])
def test_ai_footer_declares_runtime_and_development_ai_use(lang):
    footer = STRINGS[lang]["ai.footer"]
    assert "Google Gemini" in footer and "OCEANPIXELS" in footer
    assert not BANNED.search(footer.replace("Google Gemini", ""))


@pytest.mark.parametrize("reason", ["no_key", "errors", "verifier", "no_data", "out_of_scope", None])
@pytest.mark.parametrize("q", [QUESTIONS[0], QUESTIONS[3]])
def test_engine_only_answer_reads_seamlessly_and_keeps_the_reason_private(reason, q):
    out, res = web.ask_payload(q, None, DF)
    outcome = None
    if reason:
        outcome = AIOutcome(mode=ENGINE_MODE, lang=res.lang)
        outcome.reason = reason
    ai = web.ai_payload(outcome, res, DF)  # backend: the reason is still there for the team
    assert ai["ok"] is False and ai["note"]
    pub = web.public_ai(ai)  # what the browser receives
    assert pub["badge"] == t("ai.badge_engine", res.lang) and pub["title"] == t("ai.title_engine", res.lang)
    assert not any(k in pub for k in PRIVATE_AI)
    assert not BANNED.search(json.dumps(pub, ensure_ascii=False))
    panel = web.public_panel(web.panel_payload(out, res, ai, DF, 0.2))
    assert panel["model_trace"] == {"answered_by": t("ai.badge_engine", res.lang), "fallback_used": True}
    assert not BANNED.search(panel["interpretation"]), panel["interpretation"]


@pytest.mark.parametrize("q", QUESTIONS)
def test_answer_html_has_no_internal_words(q):
    out, _ = web.ask_payload(q, None, DF)
    for part in (out.get("lead_html"), (out.get("html") or {}).get("board"), out.get("written_html")):
        text = text_of(part)
        assert not BANNED.search(text), BANNED.search(text).group(0) + " in: " + text[:400]
    assert "ff-tech" not in json.dumps(out)


def test_animation_never_carries_certainty_keywords_or_clock():
    out, _ = web.ask_payload(QUESTIONS[0], None, DF)
    page = out["animation"]["html"]
    assert "T+" not in page and "R.clock" not in page and ".tech" not in page
    assert '"confidence"' not in page and '"keywords"' not in page and "certeza" not in page


def test_demo_numbers_and_spanish_fuel_name():
    out, _ = web.ask_payload(QUESTIONS[0], None, DF)
    assert out["lead"]["sentence"] == "Con 21 % de oxígeno, la llama de metanol se apagó en 7 de 8 ensayos parecidos."
    dil = {d["gas"]: (d["extinguished"], d["rows"]) for d in out["view"]["diluent"]}
    assert dil["CO2"] == (64, 75) and dil["He"] == (27, 28) and dil["N2"] == (44, 54)
    en, _ = web.ask_payload(QUESTIONS[3], None, DF)
    assert "7 of 8" in en["lead"]["sentence"]


@pytest.mark.parametrize("lang", ["en", "es"])
def test_brand_bar_has_no_internal_label(lang):
    for gemini in (False, True):
        bar = brand_html(lang, rows=1982, experiments=19, gemini=gemini)
        assert not BANNED.search(text_of(bar)) and "ff-tech" not in bar
    assert "ff-tech" not in THEME_CSS


def test_no_debug_switch_anywhere_in_the_frontend():
    assert not (WEB / "debug.js").exists()
    for name in ("index.html", "panel.html", "app.js", "skin.js"):
        src = (WEB / name).read_text(encoding="utf-8")
        for word in ("debug", "DEBUG", "ff-tech", "sessionStorage", "FF_withDebug", "renderTrace", "traceKv",
                     "tech_badge", "answered_by_tech", "buildMock"):
            assert word not in src, (name, word)
    app = (WEB / "app.js").read_text(encoding="utf-8")
    for gone in ("ai.how", "agents_title", "seconds_label", "sidebar.ai_roles", "sidebar.ai_off", "traceHTML"):
        assert gone not in app, gone


@pytest.mark.parametrize("path", ["/?debug=1", "/panel?debug=1", "/?debug=1&tech=1", "/panel"])
def test_query_parameters_change_nothing(client, path):
    base = path.split("?")[0]
    assert client.get(path).text == client.get(base).text


def test_api_responses_carry_no_internals(client):
    meta = client.get("/api/meta?lang=es").json()
    assert "gather_models" not in meta and "interpret_models" not in meta
    for L in ("en", "es"):
        assert not any(k.startswith(("ai.tech_", "ai.engine_reason.", "ai.dot.", "sidebar.", "ai.how"))
                       for k in meta["strings"][L])
    q = {"question": QUESTIONS[0], "lang": "es"}
    ask = client.post("/api/ask", json=dict(q, ai=True)).json()
    assert ask["lead"]["sentence"].endswith("7 de 8 ensayos parecidos.")
    assert "mode" not in ask and "engine_seconds" not in ask and not any(k in ask["ai"] for k in PRIVATE_AI)
    inter = client.post("/api/interpret", json=q).json()["ai"]
    assert not any(k in inter for k in PRIVATE_AI)
    panel = client.post("/api/ask_v2", json=q).json()
    assert set(panel["model_trace"]) == {"answered_by", "fallback_used"}
    assert (panel["verdict"]["numerator"], panel["verdict"]["denominator"]) == (7, 8)
    for body in (ask, inter, panel):
        dumped = json.dumps(body, ensure_ascii=False).lower()
        for word in ("no hay clave", "motor determinista", "verificador", "latency_ms", "attempts"):
            assert word not in dumped, word


def test_server_errors_are_generic(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr(web, "ask_payload", boom)
    r = client.post("/api/ask", json={"question": "hola"})
    assert r.status_code == 500 and r.json() == {"error": "internal error"}
