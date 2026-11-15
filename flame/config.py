"""Settings for the whole app. Most values can be overridden with environment variables."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Replace this file with the real data (same columns) and nothing else has to change.
DATA_PATH = Path(os.environ.get("FLAME_DATA_PATH", ROOT / "data" / "experiments.csv"))

# --- Gemini (optional) ------------------------------------------------------
# Model chain for the AI interpreter (flame/agent.py): each model is tried in order; if all fail (no key,
# error, 429 quota, timeout or the verifier rejects the answer) the deterministic engine answers alone.
# Override with GEMINI_MODELS="model-a,model-b". Names checked against ai.google.dev/gemini-api/docs/models
# on 2026-11-15 ("gemini-3.7-flash", the v6 default, is retired and only redirects to gemini-3.8-flash).
GEMINI_MODELS = [m.strip() for m in os.environ.get("GEMINI_MODELS", "gemini-4-hydrogen,gemini-3.8-flash").split(",")
                 if m.strip()]
# Kept for the v6 text writer (flame/llm.py) and the sidebar: the first model of the chain.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", GEMINI_MODELS[0] if GEMINI_MODELS else "gemini-3.8-flash")
# Gemini 4 and 3.6+ ignore temperature/top_p/top_k; reasoning effort is set with thinking_level instead.
# "low" is accepted by gemini-4-hydrogen (low/medium/high/xhigh) and gemini-3.8-flash (low/medium/high).
GEMINI_THINKING_LEVEL = os.environ.get("GEMINI_THINKING_LEVEL", "low")
# v7b: two roles. GATHER = models that plan extra tool calls on top of the engine's own baseline evidence
# ("engine" = no LLM, the deterministic baseline only). INTERPRET = models that write the cited answer
# (hydrogen first: 1 request per question; flash models repair or replace it). Override with env vars.
def _models_env(name: str, default: str) -> list[str]:
    raw = os.environ.get(name) or os.environ.get("GEMINI_MODELS") or default
    return [m.strip() for m in raw.split(",") if m.strip()]


ENGINE_GATHER = "engine"
GATHER_MODELS = _models_env("GATHER_MODELS", "gemini-3.8-flash,gemini-3.6-flash")
if ENGINE_GATHER not in GATHER_MODELS:
    GATHER_MODELS.append(ENGINE_GATHER)  # the baseline is always there; this marks "no LLM planner"
# Order measured on 2026-11-15 with a free-tier key: the flash models answer the interpret request in 1-5 s;
# gemini-4-hydrogen took ~65 s and gemini-3.8-flash returned 504, so with them first the whole time budget was
# spent before a model that answers got its turn ("Engine without AI" on every question). Each free-tier model
# has its own 20 requests/day, so a longer chain also means more questions per day.
DEFAULT_INTERPRET_MODELS = "gemini-3.6-flash,gemini-3.5-flash,gemini-3.8-flash,gemini-4-hydrogen,gemini-3.5-flash-lite,gemini-3.1-flash-lite"
INTERPRET_MODELS = [m for m in _models_env("INTERPRET_MODELS", DEFAULT_INTERPRET_MODELS) if m != ENGINE_GATHER]
GATHER_THINKING_LEVEL = os.environ.get("GATHER_THINKING_LEVEL", "low")
INTERPRET_THINKING_LEVEL = os.environ.get("INTERPRET_THINKING_LEVEL", os.environ.get("GEMINI_THINKING_LEVEL", "low"))
GATHER_MAX_ROUNDS = int(os.environ.get("GATHER_MAX_ROUNDS", "1"))  # flash planner requests per question
GATHER_REQUEST_TIMEOUT_S = float(os.environ.get("GATHER_REQUEST_TIMEOUT", "15"))  # a slow planner is skipped sooner
COOLDOWN_QUOTA_S = float(os.environ.get("FLAME_COOLDOWN_QUOTA", "900"))  # skip a model after a 429 for 15 min
COOLDOWN_BUSY_S = float(os.environ.get("FLAME_COOLDOWN_BUSY", "180"))  # ... after a 503/504/timeout for 3 min
AGENT_MAX_ROUNDS = int(os.environ.get("FLAME_AGENT_MAX_ROUNDS", "4"))  # gather rounds with tool calls
AGENT_MAX_CALLS_PER_ROUND = 3  # tool calls executed per round; extra calls are refused
AGENT_MAX_TOOL_CALLS = 8  # tool calls executed in total per model
AGENT_MAX_ROWS_PER_CALL = 12  # rows a tool returns at most
AGENT_REQUEST_TIMEOUT_S = float(os.environ.get("FLAME_AGENT_REQUEST_TIMEOUT", "30"))  # per HTTP request
AGENT_TOTAL_TIMEOUT_S = float(os.environ.get("FLAME_AGENT_TIMEOUT", "90"))  # whole chain; then the engine answers
# One interpret request may take this long at most; a slower model hands over to the next one in the chain.
INTERPRET_REQUEST_TIMEOUT_S = float(os.environ.get("INTERPRET_REQUEST_TIMEOUT", "25"))
AGENT_MAX_OUTPUT_TOKENS = 4096
AGENT_MAX_CLAIMS = 8

# --- Dataset contract -------------------------------------------------------
REQUIRED_COLUMNS = [
    "experimento",
    "combustible",
    "oxigeno",
    "presion",
    "resultado",
    "fase",
    "fuente",
]
PHASES = ("prevent", "detect", "extinguish")

# Comparison metrics a question can ask about (ported from the teammate's version, OCEANPIXELS).
# Each maps to the result_metric_name values and unit stored in the CSV.
COMPARISON_METRICS = {
    "flame_spread_rate": {"names": ("spread rate",), "unit": "mm/s"},
    "flame_duration": {"names": ("flame duration", "burn time"), "unit": "s"},
    "fuel_consumption_rate": {"names": ("fuel rate",), "unit": "mg/s"},
    # Droplet burning rate (FLEX): written only in the result text, e.g. "burning rate 0.52 (source unit
    # label 'mm')". Read from the text for display; the unit is reported exactly as the source labels it.
    "burning_rate": {"names": ("burning rate",), "unit": None, "from_text": True},
    "mass_loss_rate": {"names": ("mass loss rate",), "unit": "mg/min"},
}
METRIC_CHART_MAX_ROWS = 25  # bars drawn at most in the metric comparison chart
METRIC_CHART_O2_TOLERANCE = 1.5  # percentage points around the O2 asked in the question (chart filter only)

OXYGEN_UNIT = "%"  # O2 concentration, percent by volume
PRESSURE_UNIT = "atm"  # pressure column in the CSV is in atm

# Factors to convert a pressure written in a question into atm.
TO_ATM = {
    "atm": 1.0,
    "kpa": 1 / 101.325,
    "pa": 1 / 101_325,
    "psi": 1 / 14.6959,
    "psia": 1 / 14.6959,
    "bar": 1 / 1.01325,
    "mbar": 1 / 1013.25,
    "torr": 1 / 760,
    "mmhg": 1 / 760,
}

# --- Retrieval --------------------------------------------------------------
OXYGEN_TOLERANCE = 5.0  # percentage points; full match at 0, no match beyond this
PRESSURE_TOLERANCE = 0.25  # relative difference (25 %)
WEIGHTS = {"oxygen": 0.35, "pressure": 0.20, "fuel": 0.20, "phase": 0.15, "keywords": 0.10, "subject": 0.25}
# Free-text keywords are matched against the English result text, so a Spanish question never scored on
# them and the same question gave different rows in EN and ES (review #1). Their useful signals
# (fuel, gases, agents, detection variables, phase) have language-neutral components, so keywords are kept
# for display and Gemini but no longer scored. Set True to restore the v5 behaviour.
KEYWORDS_IN_RELEVANCE = False
MIN_SCORE = 0.30  # rows below this relevance are not sent to Gemini
TOP_K = 8  # max rows sent to Gemini
TIE_BAND = 0.05  # rows this close to the best score count as tied
DILUENT_MIN_ROWS = 5  # "more often with gas X" needs >= 5 rows per group (review #4, its judgment call)
DILUENT_MIN_GAIN = 0.20  # ... and a share of extinctions at least 20 points higher than N2 only
MAX_PER_EXPERIMENT = 3  # among tied rows, take at most this many from one experiment first
# Rows whose gravity column does not say microgravity are left out of retrieval pools and physics
# (review #9). Today's CSV: 1,969 "microgravity (ISS)" + 13 "microgravity (Cygnus cargo vehicle)".
MICROGRAVITY_PATTERN = "microgravity"

# Rows whose result is "outcome not listed" have their relevance multiplied by this factor.
OUTCOME_MISSING_FACTOR = 0.6

RELEVANCE_HELP = (
    "Relevance is a weighted score of how closely each row matches the conditions "
    "read from the question: oxygen 35 %, pressure 20 %, fuel 20 %, phase 15 %, "
    "plus subject 25 % when the question names a detection variable or a "
    "suppression agent (does the row record that variable or agent?). Only the conditions "
    "actually stated are used, and their weights are renormalized to sum to 1. Rows whose "
    "result is “outcome not listed” are then ranked lower (score multiplied by 0.6). "
    "When more rows tie than fit, an evenly spaced sample of the tied rows is taken, spread across experiments. "
    "Free-text keywords are not scored (the source text is English only)."
)

# --- Wording that must never change -----------------------------------------
SIMULATED_TAG = "SIMULATED"
INSUFFICIENT = (
    "The available database does not contain enough evidence to answer this "
    "query with the required precision."
)

# Reference atmospheres quoted in the challenge statement.
# Context for the charts only, never treated as experimental data.
# "label" is the English name; "key" selects the translated name in flame/i18n.py (ref.<key>).
REFERENCE_ATMOSPHERES = [
    {"key": "earth", "label": "Earth, sea level", "oxygen": 21.0, "pressure_psi": 14.7},
    {"key": "moon", "label": "Planned Moon base / rover (≥30 % O2, ≤10.2 psi)", "oxygen": 30.0, "pressure_psi": 10.2},
    {"key": "suit", "label": "Spacesuit (100 % O2, 4.3 psi)", "oxygen": 100.0, "pressure_psi": 4.3},
]

# --- Interface -----------------------------------------------------------------
# Time (seconds) the stage-2 animation stays on screen before the results open by themselves.
# The sequence itself takes about 8 s; the rest is reading time. "View results" skips the wait.
# Set FLAME_ANIM_SECONDS=0 to skip the wait (used by the tests), or a large value (e.g. 120) to
# hold the animation while presenting and move on with the button.
ANIMATION_SECONDS = float(os.environ.get("FLAME_ANIM_SECONDS", "12.0"))

# Colors for the three phases (validated for color-vision deficiency on a dark background).
PHASE_COLORS = {"prevent": "#3987e5", "detect": "#d95926", "extinguish": "#199e70"}

# Mission-control theme (flame/theme.py, flame/animation.py, flame/dashboard.py).
ACCENT_COLOR = "#d95926"  # glow accent, primary buttons
TELEMETRY_COLOR = "#4fd1e8"  # cyan telemetry labels and HUD lines
QUESTION_COLOR = "#ffd27a"  # the user's question on every chart

# Upper end of the oxygen line on the result dashboard (% O2). It widens to 100 by itself when the
# question or the lowest recorded flame is above this value.
O2_SCALE_MAX = 40.0
