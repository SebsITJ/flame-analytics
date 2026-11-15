# 🔥 Flame in Freefall — OCEANPIXELS

**Evidence-based decision-support tool built on NASA PSI microgravity combustion data.**
Built for the NASA Space Apps Challenge 2026 by the OCEANPIXELS team.

Ask a fire-safety question in English or Spanish — for example *"How do I put out a methanol fire at 21% oxygen?"* —
and the app answers from 1,982 real test rows of 19 NASA Physical Sciences Informatics (PSI) experiments: what
happened in the most similar tests (e.g. *"the methanol flame went out in 7 of 8 similar tests"*), which diluent gases
extinguished flames more often (CO₂ 64/75, He 27/28, N₂ only 44/54), the cited rows with links to their NASA source,
charts, and clear warnings when the data do not cover the question (e.g. lithium fires on the Moon).

The numbers always come from the data. Optionally, Google Gemini writes a short interpretation; every number and
citation it uses is checked against the data before it is shown. Without a key, the app answers from the data alone
with the same numbers.

> Student project. Not affiliated with or endorsed by NASA. It does not replace flight procedures or engineering
> judgment; it shows what the tests say and how solid that is.

## Run it

Requirements: internet the first time. The launchers install [uv](https://docs.astral.sh/uv/), which downloads
Python 3.11+ and the dependencies into the project folder.

- **Windows:** double-click `INICIAR_WEB_WINDOWS.bat`
- **macOS / Linux:** run `INICIAR_WEB_MAC_LINUX.command`
- **Manual:** `uv run python server.py` → open <http://127.0.0.1:8600>

Pages: `/` (main console) and `/panel` (alternative single-page view). A Streamlit backup app is included
(`RESPALDO_STREAMLIT_*`, `uv run streamlit run app.py`, port 8501).

Optional AI interpretation: copy `.env.example` to `.env` and set `GEMINI_API_KEY=...` (never commit it; `.env` is
git-ignored).

Tests: `uv run --with pytest python -m pytest -q` (on Windows PowerShell set `$env:PYTHONUTF8=1` first).

## Project layout

| Path | What it does |
|---|---|
| `server.py` | FastAPI server (port 8600): `/api/ask`, `/api/interpret`, `/api/ask_v2`, `/api/explorer`, `/api/charts` |
| `flame/` | Question classification, retrieval and physics over `data/experiments.csv` (pandas), answer cards, AI interpreter, EN/ES strings |
| `web/` | HTML/CSS/JS front end (`index.html`, `panel.html`), offline Vega libraries in `web/vendor/` |
| `data/experiments.csv` | NASA PSI rows used by the app (1,982 rows, 19 experiments) |
| `tests/` | pytest suite |

## Data

NASA Physical Sciences Informatics (PSI) system, <https://psi.nasa.gov>. Each row in `data/experiments.csv` keeps
its PSI identifier and the DOI of its source dataset (`https://doi.org/10.60555/...`); the app links every cited row
to that source. Please cite the original PSI datasets through those DOIs. Data are used as published; derived
numeric columns are added alongside, and the original values are not modified.

## Third-party software

| Library | License |
|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | MIT |
| [Uvicorn](https://github.com/encode/uvicorn) | BSD 3-Clause |
| [pandas](https://github.com/pandas-dev/pandas) | BSD 3-Clause |
| [Streamlit](https://github.com/streamlit/streamlit) (backup app) | Apache 2.0 |
| [Google Gen AI SDK for Python](https://github.com/googleapis/python-genai) (`google-genai`) | Apache 2.0 |
| [Vega](https://github.com/vega/vega), [Vega-Lite](https://github.com/vega/vega-lite), [Vega-Embed](https://github.com/vega/vega-embed) (bundled in `web/vendor/`) | BSD 3-Clause |

Full dependency pins are in `uv.lock`.

## AI use

- **At runtime:** when a key is configured, Google Gemini writes the optional interpretation from the NASA tests;
  every number and citation is checked against the data before it is shown. Charts are drawn by the app from NASA
  PSI rows; they are not AI-generated images. Without a key the app answers from the data alone.
- **During development:** AI tools assisted with: the user interface (UI), the connectors, the subagent and the AI
  schema, and the database preparation; the rest was developed by the OCEANPIXELS team.

## Team OCEANPIXELS

| Name | Major | GitHub |
|---|---|---|
| Jeanpiere Castro | Mechanical Engineering | [@customerservicesastrotech-wq](https://github.com/customerservicesastrotech-wq) |
| Sebastián Tumbaco | Electronics and Automation Engineering | [@SebsITJ](https://github.com/SebsITJ) |
| Dylan Rosales | Mechatronics Engineering | [@dylanrosalesasc-cmd](https://github.com/dylanrosalesasc-cmd) |
| Miguel Carpio | Naval Engineering | [@Micaez](https://github.com/Micaez) |
| Jacob Gaviño | Chemical Engineering | [@JaanG-95](https://github.com/JaanG-95) |

## Documentation in Spanish

`README_ES.md` / `LEEME_PRIMERO.md` (step-by-step guide), `COMO_CORRER.txt`, `CAMBIOS_OCULTAR.md`,
`CAMBIOS_DISENO_FLAME_ANALYTICS.md`, `PENDIENTES_TECNICOS.pdf`. Change history: `CHANGES.md`.

## License

Apache License 2.0 — see `LICENSE` and `NOTICE`. Copyright 2026 OCEANPIXELS team.
