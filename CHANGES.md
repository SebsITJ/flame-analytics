# HTML version — the app moves from Streamlit to a plain web page (2026-11-15)

Same engine, same v7b agent, same numbers; the page is now HTML/CSS/JS served by a small FastAPI server.

## v7c — la IA concluye y recomienda (2026-11-15)

- **Causa del "no concluye":** (1) no había `.env` con la clave, así que respondía solo el motor; (2) con clave, la
  cadena empezaba por `gemini-4-hydrogen` (~65 s por petición, 20/día) y `gemini-3.8-flash` (504), y el presupuesto
  de 60 s se agotaba antes de llegar a un modelo que sí responde; (3) el prompt prohibía concluir y recomendar.
- **Cadena nueva** (`flame/config.py`): `gemini-3.6-flash, gemini-3.5-flash, gemini-3.8-flash, gemini-4-hydrogen,
  gemini-3.5-flash-lite, gemini-3.1-flash-lite`. Cada petición tiene 25 s como máximo (`INTERPRET_REQUEST_TIMEOUT`)
  y el total 90 s. Un modelo sin cupo diario se salta hasta que Google lo renueva.
- **Respuesta nueva:** campos `conclusion` (veredicto directo con los números que mandan) y `recommendation`
  (qué respalda la evidencia). Siguen pasando por el verificador: ningún número ni cita fuera del paquete del motor.
- **Más evidencia para concluir** (`engine_gather`): niveles de O2 ensayados más cercanos cuando el pedido no existe,
  límite de O2 con llama, comparación de diluyentes y tiempos/tasas. `metric_trend(at_o2=...)`: el MOTOR evalúa el
  ajuste en el O2 preguntado y lo marca como interpolación o extrapolación; la IA solo lo cita.

## What changed
- `server.py` (new): FastAPI + uvicorn on `127.0.0.1:8600` (`FLAME_HOST`, `FLAME_PORT`). Serves `web/` and a JSON API:
  `GET /api/health`, `GET /api/meta?lang=`, `POST /api/ask {question, lang?, ai?}`, `POST /api/interpret`,
  `GET /api/explorer`, `GET /api/charts?lang=`, `POST /api/ask_v2` (alternative page), gzip on.
- The Gemini key is read on the server only (env `GEMINI_API_KEY`/`GOOGLE_API_KEY` → `.env` → `.streamlit/secrets.toml`)
  and never sent to the browser (tested).
- Web defaults: `GATHER_MODELS=engine` (0 flash requests) and `INTERPRET_MODELS=gemini-4-hydrogen,gemini-3.8-flash,gemini-3.6-flash`.
- `flame/web.py` (new): presenter without Streamlit. Reuses the existing HTML generators (`dashboard_html`, `strip_html`,
  `build_mission_html`) and the Altair charts as Vega-Lite specs, so the page shows exactly what the Streamlit app showed.
- `web/index.html`, `web/app.js`, `web/app.css` (main page): ask → mission animation (same iframe, auto-advance or
  "See results") → dashboard; AI panel with badge, cited summary/claims, chart, limitations, cited rows and
  "How the AI reasoned" (flow diagram in HTML/CSS + tool-call and attempt tables); metric chart; calculations,
  full written answer, ranked rows; Explorer (search, phase, fuel, O2/pressure ranges, CSV download) and Charts tabs;
  EN/ES; mobile layout. The page asks the engine first (~0.2 s) and runs the AI while the animation plays.
- `web/panel.html` (alternative view at `/panel`): single-page design, wired to the
  real engine through `/api/ask_v2`. Its built-in MOCK data is no longer shown: without the server it shows an empty
  answer and a "server offline" banner. Platform claims ("ISS and Cygnus") replaced with the real source
  (NASA PSI, 19 experiments); columns without data (d0, t_ext) removed.
- `web/vendor/`: Vega, Vega-Lite, Vega-Embed (BSD-3, see `LICENSES.txt`), so the page works offline.
- Launchers: `INICIAR_WEB_WINDOWS.bat` (CRLF) and `INICIAR_WEB_MAC_LINUX.command`. The Streamlit launchers stay as
  `RESPALDO_STREAMLIT_*` and `app.py` is unchanged.
- Animation: on screens under 520 px only the current step label is shown (it overlapped the clock).
- Tests: `tests/test_server.py` (12 tests) — demo numbers through the API, no-key fallback, fake hydrogen answer,
  AI error fallback, out of scope, validation, explorer/charts, static assets, key never in responses.

## Demo numbers (checked through the API, identical to v6)
Methanol at 21 % O2: 7 of 8; diluents CO2 64/75, He 27/28, N2 44/54; lowest recorded flame: methanol 12 % (R83),
PMMA 15 % (R716).

# v7b — two Gemini models with roles: flash gathers, hydrogen interprets (2026-11-15)

Question from Jeanpiere: can gemini-3.8-flash do the work it can handle and hand off to gemini-4-hydrogen only for
the harder part? Yes. The v7 flow already had two separate steps (gather, interpret); v7b gives each one its own
model chain and adds an engine baseline so that no LLM is needed to collect the core evidence.

## Flow (`agent.run_hybrid`, the default of `run_ai` when no model list is passed)
1. Engine baseline (`engine_gather`, 0 requests): the tool calls implied by the engine's own reading
   (search at O2 ±1.5, widened once if empty; compare_diluents for extinguish; oxygen_bracket for prevent;
   metric_trend if a metric is named; atmosphere if O2 and pressure are given). Calls are marked `by=engine`.
2. Flash planner (`GATHER_MODELS`, default gemini-3.8-flash, gemini-3.6-flash, engine): ONE request
   (`GATHER_MAX_ROUNDS=1`, mode AUTO, thinking low, 15 s timeout). It sees the baseline and may add tool calls
   for what is missing, or nothing. If it fails, the next flash tries; if all fail, the baseline alone is used.
3. Interpreter (`INTERPRET_MODELS`, default gemini-4-hydrogen, gemini-3.8-flash, gemini-3.6-flash): ONE
   request per model with the same evidence pack and JSON schema. A 429 / 503 / timeout hands off to the next
   model. If the verifier rejects a draft, the next model gets a REPAIR prompt with the verifier's reasons.
4. Cool-downs: after a 429 a model is skipped for 15 min (`FLAME_COOLDOWN_QUOTA`); after 503/504/timeout,
   3 min (`FLAME_COOLDOWN_BUSY`), so a dead model does not cost its timeout on every question.
5. UI: the badge says who did what ("Data: gemini-3.8-flash → interpretation: gemini-4-hydrogen · checked by the
   engine"); the trace shows the engine baseline node, the flash node, each interpret/repair attempt and the
   hand-off edge; the tool-call table has a "Called by" column.

## Requests per question and daily capacity (free tier: 20 requests/day per model per project)
- v7: hydrogen did gather (2-4 requests) + interpret (1) = 3-5 hydrogen requests per question → 4-6 per day.
- v7b: 1 flash + 1 hydrogen → about 20 hydrogen answers per day; the flash planner allows 20 (3.8) + 20 (3.6).
  With `GATHER_MODELS=engine` no flash request is used and the flash quota is kept for interpret fallback
  (up to ~60 verified answers per day across the three models, 20 of them by hydrogen).

## Files
- `flame/config.py`: GATHER_MODELS, INTERPRET_MODELS, ENGINE_GATHER, GATHER/INTERPRET_THINKING_LEVEL,
  GATHER_MAX_ROUNDS, GATHER_REQUEST_TIMEOUT_S, COOLDOWN_QUOTA_S, COOLDOWN_BUSY_S (env overrides; GEMINI_MODELS
  still works as a fallback for both roles).
- `flame/agent.py`: engine_gather, baseline_summary, run_hybrid, cool-downs, interpret(repair=...),
  gather(ledger=..., max_rounds=..., thinking_level=..., timeout_s=...), 503 classified as "busy (503)",
  trace_dot shows the hand-off. The v7 single-chain path is kept (`run_ai(..., models=[...])`).
- `app.py`, `flame/i18n.py`: roles in the sidebar, hybrid badge, "Called by" column, new trace labels (EN/ES).
- `tests/test_hybrid.py`: 15 tests with the fake client (hand-off, 1 hydrogen request per question, 503/timeout
  fallback to the next flash and to the engine baseline, 429 hand-off and cool-down, repair with reasons,
  everything fails → engine, language check, roles from env, trace). Full suite: 238 passed.
- Engine files unchanged; every engine number is the same as v6/v7.

# v7 — Gemini as interpreter over the engine (2026-11-15)

Goal (Jeanpiere): the AI writes complex answers and diagrams, but never "thinks from scratch": it may only ask
our engine and the NASA PSI table, and uses its reasoning only to interpret. Engine files (retrieval.py,
physics.py, classify.py, enrich.py, data.py) are unchanged; every v6 number is the same.

## How it works
1. The engine answers first, alone (`answer_question(..., llm=None)`): classification, top rows, physics, N/8.
2. GATHER: Gemini receives the question plus the engine's reading and may only call 6 whitelisted tools
   (`flame/tools.py`): `search_experiments`, `get_rows`, `oxygen_bracket`, `compare_diluents`, `metric_trend`,
   `atmosphere`. They are thin wrappers over `rank()`, `flammability_bracket()`, `_diluent_effect()`, `_trend()`,
   `metric_rows()`, `atmosphere_indices()`. Manual loop: first round must call a tool (mode ANY), max 4 rounds,
   3 calls per round, 8 calls in total, 12 rows per call. Every result is logged in a Ledger: rows keep their
   id (R#), each tool result gets a fact id (E#).
3. INTERPRET: a second call with no tools returns JSON in a fixed schema (`flame/ai_schema.py`): summary,
   claims (each with phase, kind observed/computed/extrapolation and R#/E# citations), limitations, missing,
   optional chart spec (type bar/scatter/strip, an E# table, whitelisted columns; never data values).
4. VERIFY (`verify.verify_interpretation`): rejects numbers that are not in the ledger (decimal comma,
   thousands separators and rounding handled; small integers must match exactly), ids not in the ledger,
   claims without a valid citation, chart fields not in the chosen table, and an answer in the wrong language.
5. Model chain (`config.GEMINI_MODELS`, env `GEMINI_MODELS`): gemini-4-hydrogen -> gemini-3.8-flash ->
   deterministic engine. No key, error, 429, 503/504, timeout (30 s per request, 60 s total) or verifier
   rejection moves to the next step. If the gather step worked, the next model reuses the same evidence.
   Free tier measured live: gemini-4-hydrogen allows 20 requests/day per project (each question uses 3-5),
   so for the demo set `GEMINI_MODELS=gemini-4-hydrogen,gemini-3.6-flash,gemini-3.8-flash`.

## Files
- New: `flame/tools.py`, `flame/agent.py`, `flame/ai_schema.py`, `flame/ai_view.py`, `tests/test_agent.py`
  (34 tests with a fake Gemini client, no network), `.gitignore`.
- Changed: `flame/verify.py` (v7 checks added; old functions untouched), `flame/config.py` (model chain,
  thinking level, caps; retired default `gemini-3.7-flash` removed), `flame/llm.py` (temperature removed, it is
  ignored by Gemini 4 / 3.6+; thinking_level instead), `flame/i18n.py` (ai.* strings EN/ES), `flame/theme.py`
  (badge styles, brand text), `app.py` (AI panel on the results screen, trace expander, AI-use footer),
  `.streamlit/secrets.toml.example`, `COMO_CORRER.txt`, `LEEME_PRIMERO.md/.pdf`, `README.md`.

## On screen (results stage)
- Badge: "Respondió gemini-4-hydrogen · verificado por el motor" or "Motor sin IA" with the reason.
- Summary and claims with clickable R# links (to the row's DOI / PSI page) and E# facts in bold.
- Chart chosen by the AI, drawn by the app with Altair from the engine rows of that E# table.
- "Cómo razonó la IA": Graphviz flow (question -> engine -> tool calls -> evidence pack -> interpret ->
  verifier -> screen), table of tool calls and table of attempts per model.
- Footer: AI-use declaration. The API key is read only from `GEMINI_API_KEY` or `.streamlit/secrets.toml`.

# Mission-control UI — change list

Drop these files over the repo (same paths). The engine (`flame/pipeline.py`, classify, retrieval, physics,
data, enrich, llm, verify) is not touched and no number is computed differently.

## New files
- `flame/viz_payload.py` — builds the JSON for stage 2 (`build_animation_payload`) and the view for stage 3
  (`build_dashboard_view`) from the table and the pipeline `Result`. Only reads and counts rows.
- `flame/theme.py` — page CSS (starfield and HUD grid as CSS gradients, glass panels, monospace telemetry
  labels, #d95926 glow + cyan), brand bar, hero, footer. No images, fonts or CDNs; no agency logo.
- `flame/dashboard.py` — stage-3 markup: verdict card, outcome ring, diluent bars, oxygen line 0–40 %
  (asked level, recorded flame bound, Earth / Moon base / spacesuit), action cards with DOI pills.
- `tests/test_viz_payload.py`, `tests/test_mission_ui.py` — 41 tests (payload contents and JSON safety,
  all phases and fallbacks, engine values passed through unchanged, HTML is self-contained and cannot be
  broken by the question text, EN/ES parity of the new strings).

## Changed files
- `app.py` — same three stages and the same session/widget keys. Stage 2 now runs the pipeline first
  (after Explorer and Charts are drawn) and plays the animation from the real result; stage 3 is the
  dashboard. The previous text answer is kept in the "Written answer and evidence" expander and is also the
  fallback if the dashboard cannot be built. Sidebar starts collapsed.
- `flame/animation.py` — adds `build_mission_html(payload)` and `MISSION_HEIGHT`. The old
  `build_animation_html` is unchanged and is the fallback.
- `flame/i18n.py` — 81 new keys (`hud.*`, `viz.*`, `dash.*`, `refshort.*`) in EN and ES. One existing
  English string changed: `btn.see_results` "See results ▸" -> "View results ▸".
- `flame/config.py` — `ANIMATION_SECONDS` default 3 -> 12 (the sequence takes about 8 s), plus
  `ACCENT_COLOR`, `TELEMETRY_COLOR`, `QUESTION_COLOR`, `O2_SCALE_MAX`.
- `.streamlit/config.toml` — dark theme colours, `toolbarMode = "minimal"`.

## Stage 2 at a glance
tokens light up and drop into the bin -> cloud of every row with numeric O2 (x = O2 %, y = pressure atm,
colour = phase, rows without pressure on a strip) -> narrows total -> fuel/experiment subset -> top-k with a
counter -> the question lands as a glowing point -> the top-k rings take their outcome colour and count up
to N/K -> "View results". Detect questions (no numeric O2 in the top rows) show the table by phase and bars
of what matched; out-of-scope questions stop at the bins with a stamp; "no row qualified" says so.

## Presenting
- `FLAME_ANIM_SECONDS=120 uv run streamlit run app.py` holds the animation until you press "View results".
- "Replay" and "Skip" are in the animation's top bar. `FLAME_ANIM_SECONDS=0` skips the wait (tests).

## v4 integration polish (OCEANPIXELS, after merging into the real project)
- One "View results" control: the console's button presses the hidden Streamlit button; if the console cannot
  reach the page, the Streamlit button stays visible. Auto-advance (~12 s) unchanged.
- Questions without an O2 value get an estimated point on the map: median O2 (and pressure) of the retrieved
  rows, drawn hollow/dashed with the label "estimated from the nearest experiments" (EN/ES). Picture only.
- Funnel middle step uses the engine's fuel_matches (e.g. "PMMA" -> "100 micron PMMA film").
- Source cells "DOI | PSI page" are split into separate clean links (dashboard pills and written answer).
- Engine (classify, retrieval, physics, pipeline, data, enrich, llm, verify) unchanged.

## v5 candidate — ported from the teammate's version (based on the pre-bilingual OCEANPIXELS zip)
- `flame/config.py`: `COMPARISON_METRICS` (spread rate mm/s, flame duration/burn time s, fuel rate mg/s,
  mass loss rate mg/min) and `METRIC_CHART_MAX_ROWS = 25`.
- `flame/retrieval.py`: `Conditions.material_category` and `Conditions.comparison_metric` (appended at the end),
  `detect_comparison()` with EN + ES patterns, `metric_rows()` (numeric, microgravity, optional fuel filter);
  `merge_conditions` carries both fields. Ranking, weights, hits unchanged.
- `flame/pipeline.py`: offline answer lists the recorded values of the asked metric (top 6, cited by row id);
  "related context" wording when retrieval already reported gaps; material-ranking question on spread rate
  with < 2 materials -> insufficient + explicit "missing" line. Physics / calculations untouched.
- `flame/i18n.py`: 16 new EN/ES keys (`metric.*`, `tpl.metric_*`, `tpl.answer_head_gap`, `tpl.prevent_gap`,
  `gap.metric_ranking`, `chart.metric_*`).
- `app.py`: `render_metric_chart()` under the dashboard (HUD-styled Altair bars, top 25, bilingual caption).
- `tests/test_teammate_port.py`: 17 tests.
- NOT ported: the "fuel never tested in this phase" gap (downgraded the cotton DETECT and PMMA+CO demos to
  insufficient), the "Found N experimental records" rewording (cosmetic), the unused `spread_data` locals.

## v5 — chart O₂ filter (requested by Jeanpiere)
- `flame/retrieval.py`: `filter_by_oxygen()` (display only): rows within ±`METRIC_CHART_O2_TOLERANCE`
  (1.5 pts, `flame/config.py`) of the O₂ in the question; if none, the nearest tested O₂ level (± 1.5) with a
  warning; no O₂ in the question -> all levels. Values pass through unchanged; engine answer/numbers unchanged.
- `app.py`: chart title shows the O₂ filter, caption explains it, bar labels show each row's O₂.
- `flame/i18n.py`: `chart.o2_*` keys (EN/ES); `chart.metric_title` now has an `{o2}` slot.
- `tests/test_teammate_port.py`: +7 tests (band, nearest fallback, no-O₂, strings, 3 app runs). Suite: 154.

## v6 — fixes from an external code review of v5 (all findings applied, implemented by OCEANPIXELS on the real CSV)
Credit: findings from an external code review (critical, important and minor). The reviewer's patch was not used; every fix
was re-implemented here and checked on the real 1,982-row table. Physics (NIST-JANAF Cp at 298 K), EN/ES
parity, the 3-stage flow and offline mode are unchanged.
- **#1 N/8 biased by the question / EN≠ES** (`retrieval.py`, `config.py`): keywords are accent-folded and
  phase/outcome roots (extinguish, apag, burn, quem, arde, ignit…) are excluded; tied rows are an evenly spaced
  sample spread across experiments (`_top`, `tied_count`, `Retrieval.tied`); the card and the answer say
  "sample of 8 from N equally relevant rows". Beyond the review: free-text keywords no longer score at all
  (`KEYWORDS_IN_RELEVANCE = False`), because the source text is English only and was the remaining EN/ES gap.
  The first-named fuel is used in both languages (`classify.extract_subject`).
- **#2a** neutral verdict ("N/N rows retrieved") when the question asks for a metric (`viz_payload.verdict_of`).
- **#2b** "kept burning" -> "flame, no extinction noted" / "llama sin extinción anotada" (viz, dash, tpl).
- **#3** `act.cut_oxygen` adds "a failed ignition is not an extinction limit"; O2 line says "No ignition at X %".
- **#4** diluent action needs >= 5 rows per group and >= 20 points more extinctions (`DILUENT_MIN_ROWS`,
  `DILUENT_MIN_GAIN`, the reviewer's judgment thresholds) and reads "In this table the flame went out more often with…".
- **#5** "burning rate" / "tasa de combustión" -> new `burning_rate` metric read from the result text with the
  source unit label ('mm'); "¿Cuánto tiempo arde…?" -> flame duration.
- **#6** written metric list uses the chart's O2 filter; the answer says "match = within ±5 pts of the O2 asked".
- **#7** with Gemini, the rules' confidence is shown only when both phases agree; Gemini keywords are cleaned too.
- **#8** O2 is no longer shown as an "Agent"; the signal readout reads `detection_vars`.
- **#9** `gravedad`: 1,969 "microgravity (ISS)" + 13 "microgravity (Cygnus cargo vehicle)", no other values.
  Physics pools and metric rows share one microgravity filter (no-op on today's data); texts mention Cygnus.
- **#10** Charts tab: Y axis is the outcome (went out / no extinction noted / no ignition / other / not listed)
  instead of ~800 distinct result texts (was ~30,000 px tall, now ~280 px).
- **#11** trend fitted within one unit too (group by `result_metric_unit`).
- Minor: "paper/papel" aliases removed (no paper rows); hero subtitle without "NASA ISS"; warning when a question
  names two fuels; "(balance N2)/(resto N2)" in the atmosphere line; "pts" everywhere in ES; "consultado X %".
- Tests: `tests/test_review_fixes.py` (+35, incl. 10 EN/ES verdict pairs on the real CSV); adjusted
  `test_mission_ui.py` ("pedido" -> "consultado") and `test_teammate_port.py` (methanol 8/8 -> unbiased sample).
- Demo numbers: methanol at 21 % is now **7/8** extinctions (sample of 46 equally relevant rows, 42 of them
  extinguished); the methanol "Prefer CO2 / He" actions no longer appear (+4 and +15 points < 20). Diluent bars
  (CO2 64/75, He 27/28, N2 44/54), lowest flame PMMA 15 % and methanol 12 % are unchanged.

---
# Earlier changes

# Merged changes (Flame in Freefall)

Each item is tagged **review**, **ours**, or **both**. “Ours” includes the
pre-review engine and the post-review corrections made after checking the reviewer’s
patch against the real 1,982-row NASA table.

## Kept from the reviewer (A1–A8 and section B/C)

- **A1 (review, cp values corrected by us).** pO2 is a breathing metric, not a flammability yardstick. Added inert gas per mole of O2 and its heat capacity; removed `margin_po2_atm`. Moon base and Earth have almost the same pO2; the Moon-base mix has less inert gas per mole of O2 and is therefore more flammable.
- **A2 (review, flags tightened by us).** Three outcomes: `no_ignition`, `ignited`, `extinguished`. The oxygen bound is a per-fuel bracket. “No test below X” is missing data, not safety.
- **A3 (review).** “Lower oxygen below the lowest extinguished O2” was dropped. An oxygen action appears only when a no-flame test sits below the lowest flame for that fuel. Cool-flame caveat kept.
- **A4 (review).** Renamed to “lowest O2 with a recorded flame”, with the LOI / NASA-STD-6001 / microgravity-flow caveat.
- **A5 (review).** Diluent comparison uses an N2-only baseline, keeps CO2 and He apart, and shows median O2. A “Prefer X” action needs medians within 2 points and at least 3 rows each.
- **A6 (review, span guard was already ours).** Trend is fitted inside one fuel, one experiment and one metric, with R², and only when O2 values span at least 2 points. Units come from the source or “unit not stated in source”.
- **A7 (review).** “How effective is CO2 at 15%?” is no longer read as 15 % oxygen (look-behind plus a guard for percentages that belong to another gas).
- **A8 (review).** A named material with no rows (for example ethanol) is reported as a gap, not answered with other fuels.
- **B (review, small agent-matching fixes by us).** Broader EN/ES stems, conjugation coverage, first-named phase on a tie, roles (CO2 is a product in detect questions and an agent in extinguish questions), fuel families (SIBAL / cotton / algodón, candle / Japan wax, acrílico / PMMA), “He visto humo” is not helium, extra agents and detection variables.
- **C (review, cp values corrected by us).** Atmosphere indices, oxygen bracket, rate vs O2, and gas-change (ΔCO2, ΔCO, ΔO2) indicators. Subject-aware ranking (25 % “subject” weight), tie-breaking by recorded values and experiment spread, “Monitor CO/CO2” actions, “pressure not listed” instead of “? atm”.

## Rejected or corrected

- **High-temperature cp (rejected the reviewer’s 54 / 33; replaced by us).** The reviewer labelled MEAN_CP as “rounded means over ~300–1800 K from NIST-JANAF” (CO2 54, N2 33, air ballast ~124, Moon ~77). Those are high-temperature means, not the 298 K table values, and were supplied from memory. We use NIST-JANAF Cp° at **298.15 K**: N2 29.1, O2 29.4, CO2 37.1, He 20.8, Ar 20.8 J/mol·K (Chase, 4th ed., 1998). Air at 21 % O2 / 79 % N2 then has 109.5 J/K of inert heat capacity per mole of O2; the Moon-base mix has 67.9 J/K (still ~38 % less, because that ratio depends on the O2 fraction, not on the N2 Cp). The comment, the physics note and the Calculations caption all cite NIST-JANAF and say these are not flame-temperature values.
- **BASS-II final O2 as a no-flame bound (rejected).** The reviewer treated `o2_end_pct` of an extinguished test as no-flame evidence. On the real table that is unsafe: in BASS-II the median O2 drop on extinguished rows is only 0.5 points, several “ext” / blow-off rows have essentially no drop, and at least two end values are physically inconsistent (e.g. 20.0 → 39.1 % and 20.7 → 40.4 %). Final O2 is shown as the amount left at the end of the test and is **not** used to bracket the limit.
- **False `no_ignition` from notas (fixed by us).** CFI-G row R390 has “hot ignition; burn time 43 s” in `resultado` and “No ignition.” in the comments (a failed igniter attempt). Outcome flags now follow `resultado` first; a comment cannot override a stated ignition.
- **Flame-run language and metric misuse (fixed by us).** “Spherical diffusion flame run”, “laminar jet flame run” and “cool-flame droplet test run” are now marked ignited (a flame was operated). “Fuel rate” and “mass loss rate” were removed from the “flame existed” metrics: a planned flow or a pyrolysis loss is not proof of a flame (this had marked heated-material smoke tests as ignited).
- **Over-broad agent matching (fixed by us).** “Ventilation shutdown” no longer matches every FLEX “quiescent / no flow” row. “O2 cutoff” no longer matches every row that merely has a final O2 reading.

## Kept from our pre-review version (the reviewed patch already carried these forward)

- Fuel-first retrieval: when a fuel is named, hits are restricted to that fuel; O2 and pressure gaps are scoped to those rows.
- Diluent / agent actions only when the question is about extinguishing or names a diluent.
- Deterministic offline template with citations; out-of-scope refusal; relevance breakdown and “outcome not listed” penalty; gas columns (CO2/CO/O2 start–end) and the “source does not specify compound/units” disclaimer.
- Tests default to `data/experiments_simulated.csv` via `FLAME_DATA_PATH`.

## Tests added by us on top of the reviewed suite

- NIST-JANAF 298.15 K ballast for 21 % O2 / 79 % N2 equals 109.5 J/K.
- A “No ignition” comment cannot override a stated hot ignition.
- Final O2 after flame-out is not a no-flame bracket.

## Flag counts on the real 1,982-row table (after the regex fixes)

| ignited | no_ignition | extinguished | n |
|--------:|------------:|-------------:|--:|
| True | False | False | 1131 |
| True | False | True | 407 |
| False | False | False | 374 |
| False | True | False | 70 |

No contradictory combinations. The 374 unflagged rows are mostly BASS/BASS-II “outcome not listed” or gas-only lines, plus smoke-aerosol runs, where the source does not say whether a flame existed.
