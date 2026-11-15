"""Flame in Freefall — HTML version. Run with:  uv run python server.py   (then open http://localhost:8600)

FastAPI serves the static page in web/ and a small JSON API over the same engine and v7b agent as app.py
(the Streamlit app stays in the project as a backup). The Gemini key is read on the server only:
environment (GEMINI_API_KEY / GOOGLE_API_KEY), then .env, then .streamlit/secrets.toml. It is never sent to
the browser. Without a key the deterministic engine answers alone ("Engine without AI").

Endpoints
    GET  /                 the page (web/index.html)
    GET  /api/health       {"ok": true, ...}
    GET  /api/meta         strings EN/ES, dataset size, AI roles, page chrome (brand, hero, footer HTML)
    POST /api/ask          {"question", "lang"?, "ai"?: true}  -> engine answer (+ "ai" when ai is true)
    POST /api/ask_v2       same answer in the JSON shape of the alternative page /panel (web/panel.html)
    POST /api/interpret    {"question", "lang"?}               -> {"ai": ...} (the AI step alone)
    GET  /api/explorer     table rows for the Explorer tab
    GET  /api/charts?lang= Vega-Lite specs for the Charts tab
"""

from __future__ import annotations

import os
import sys
import threading
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# HTML defaults (set before flame.config is imported): the engine gathers the evidence itself (0 flash requests)
# and the interpret chain of flame/config.py (fast flash models first) writes the answer. Override with env vars.
os.environ.setdefault("GATHER_MODELS", "engine")

from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from flame import config  # noqa: E402
from flame.data import load_dataset  # noqa: E402
from flame.i18n import normalize_lang  # noqa: E402
from flame.theme import THEME_CSS  # noqa: E402
from flame import web  # noqa: E402

WEB = ROOT / "web"
PORT = int(os.environ.get("FLAME_PORT", "8600"))
HOST = os.environ.get("FLAME_HOST", "127.0.0.1")
MAX_QUESTION = 1000


def read_api_key() -> str | None:
    """Server-side only. Order: environment, .env, .streamlit/secrets.toml. Never logged or returned."""
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    env_file = ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key.strip() in ("GEMINI_API_KEY", "GOOGLE_API_KEY") and value.strip().strip('"\''):
                return value.strip().strip('"\'')
    secrets = ROOT / ".streamlit" / "secrets.toml"
    if secrets.is_file():
        try:
            data = tomllib.loads(secrets.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            return None
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            value = str(data.get(name, "")).strip()
            if value and value != "paste-your-key-here":
                return value
    return None


class State:
    """Dataset and Gemini client, loaded once (lazily, so tests can swap them)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.dataset = None
        self.client = None
        self.client_error = None
        self.loaded = False

    def load(self) -> "State":
        with self._lock:
            if not self.loaded:
                self.dataset = load_dataset(config.DATA_PATH)
                key = read_api_key()
                if key:
                    try:
                        from flame.agent import make_client
                        self.client = make_client(key)
                    except Exception as err:  # bad SDK install etc.: the engine still answers
                        self.client_error = type(err).__name__
                self.loaded = True
        return self

    @property
    def df(self):
        return self.load().dataset.df


STATE = State()
app = FastAPI(title="Flame in Freefall", docs_url=None, redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=2000)


class AskIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION)
    lang: str | None = None
    ai: bool = True


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/theme.css", include_in_schema=False)
def theme_css():
    css = THEME_CSS.replace("<style>", "").replace("</style>", "")
    return PlainTextResponse(css, media_type="text/css")


@app.get("/api/health")
def health():
    st = STATE.load()
    return {"ok": True, "rows": int(len(st.df)), "ai_enabled": st.client is not None}


@app.get("/api/meta")
def meta(lang: str = "en"):
    st = STATE.load()
    out = web.meta_payload(st.df, lang, ai_enabled=st.client is not None, dataset=st.dataset)
    out["simulated_warning"] = bool(getattr(st.dataset, "has_simulated", False))
    return JSONResponse(web.public_meta(out))


def _log_ai(question: str, ai: dict) -> None:
    """Internal details for the team go to the server console / log only, never to the page."""
    try:
        print(f"[ai] ok={ai.get('ok')} mode={ai.get('mode')} reason={ai.get('reason', '')} "
              f"seconds={ai.get('seconds', '')} attempts={len(ai.get('attempts') or [])} q={question[:80]!r}",
              file=sys.stderr, flush=True)
    except Exception:
        pass


def _error(err: Exception) -> JSONResponse:
    print(f"[error] {type(err).__name__}: {err}"[:500], file=sys.stderr, flush=True)
    return JSONResponse({"error": "internal error"}, status_code=500)


def _question(body: AskIn) -> str:
    q = body.question.strip()
    if not q:
        raise HTTPException(status_code=422, detail="empty question")
    return q


@app.post("/api/ask")
def ask(body: AskIn):
    st = STATE.load()
    q = _question(body)
    try:
        out, res = web.ask_payload(q, body.lang, st.df)
    except Exception as err:
        return _error(err)
    if body.ai:
        outcome = web.run_ai_safe(q, res, st.df, st.client)
        out["ai"] = web.ai_payload(outcome, res, st.df)
        _log_ai(q, out["ai"])
    return JSONResponse(web.public_ask(out))


@app.post("/api/ask_v2")
def ask_v2(body: AskIn):
    """The same answer in the JSON shape of the alternative page web/panel.html (engine + AI in one call)."""
    import time
    st = STATE.load()
    q = _question(body)
    t0 = time.monotonic()
    try:
        out, res = web.ask_payload(q, body.lang, st.df)
    except Exception as err:
        return _error(err)
    outcome = web.run_ai_safe(q, res, st.df, st.client) if body.ai else None
    ai = web.ai_payload(outcome, res, st.df)
    _log_ai(q, ai)
    return JSONResponse(web.public_panel(web.panel_payload(out, res, ai, st.df, time.monotonic() - t0)))


@app.get("/panel", include_in_schema=False)
def panel_page():
    return FileResponse(WEB / "panel.html", headers={"Cache-Control": "no-store"})


@app.post("/api/interpret")
def interpret(body: AskIn):
    st = STATE.load()
    q = _question(body)
    try:
        lang = web.detect_language(q, default=normalize_lang(body.lang))
        res = web.answer_question(q, st.df, None, lang)
    except Exception as err:
        return _error(err)
    outcome = web.run_ai_safe(q, res, st.df, st.client)
    ai = web.ai_payload(outcome, res, st.df)
    _log_ai(q, ai)
    return JSONResponse({"question": q, "lang": res.lang, "ai": web.public_ai(ai)})


@app.get("/api/explorer")
def explorer():
    return JSONResponse(web.explorer_rows(STATE.df))


@app.get("/api/charts")
def charts(lang: str = "en"):
    return JSONResponse(web.chart_specs(STATE.df, lang))


app.mount("/static", StaticFiles(directory=WEB), name="static")


def main() -> None:
    import uvicorn

    url = f"http://localhost:{PORT}"
    print(f"\n  Flame in Freefall (HTML) -> {url}\n  Ctrl+C para detener / to stop.\n", flush=True)
    if "--open" in sys.argv:
        import webbrowser
        threading.Timer(2.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
