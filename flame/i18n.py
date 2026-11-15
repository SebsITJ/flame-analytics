"""English / Spanish strings and the deterministic language detector.

* ``t(key, lang, **kwargs)`` returns the text for ``key`` in ``lang`` ("en" or "es"). A missing
  key falls back to English, then to the key itself, so the UI never crashes on a typo.
* ``detect_language(text, default)`` guesses the language of a question with plain rules
  (accents, ñ, ¿ ¡ and stopword counts). No model, no network.
* Each entry is declared once with both languages next to each other (``_add``), so a key can
  not exist in one language only. ``tests/test_i18n.py`` still checks parity, placeholders and
  that nothing was left untranslated.

Data values (experiment names, fuels, sources, the ``resultado`` text, units, chemical symbols)
are never translated; only the words the application writes around them are.
Placeholders use ``str.format`` syntax. Literal braces are not used in any string.
"""

from __future__ import annotations

import re
from string import Formatter

from . import config

LANGS = ("en", "es")
DEFAULT_LANG = "en"
LANG_NAMES = {"en": "English", "es": "Español"}

_ENTRIES: list[tuple[str, str, str]] = []


def _add(key: str, en: str, es: str) -> None:
    if any(k == key for k, _, _ in _ENTRIES):
        raise KeyError(f"duplicate i18n key: {key}")
    _ENTRIES.append((key, en, es))


# ---------------------------------------------------------------------------
# Sidebar, tabs, page chrome
# ---------------------------------------------------------------------------
_add("sidebar.data", "Data", "Datos")
_add("sidebar.upload", "Try another CSV (same columns)", "Probar otro CSV (mismas columnas)")
_add("sidebar.load_error", "Cannot load the data: {err}", "No se pueden cargar los datos: {err}")
_add("sidebar.dataset_caption", "**{name}** · {rows} rows · {experiments} experiments",
     "**{name}** · {rows} filas · {experiments} experimentos")
_add("sidebar.encoding", "Encoding {encoding} · separator `{delimiter}`",
     "Codificación {encoding} · separador `{delimiter}`")
_add("sidebar.issues", "{n} data issue(s)", "{n} problema(s) en los datos")
_add("sidebar.ai", "AI", "IA")
_add("sidebar.gemini_on", "Gemini on · model `{model}`", "Gemini activo · modelo `{model}`")
_add("sidebar.gemini_error", "Gemini could not start: {err}", "Gemini no pudo iniciar: {err}")
_add("sidebar.gemini_off",
     "Gemini off (no GEMINI_API_KEY). A deterministic template is written from the ranked rows and "
     "the calculations; no language model is used.",
     "Gemini desactivado (no hay GEMINI_API_KEY). Se redacta una plantilla determinista a partir de "
     "las filas ordenadas y de los cálculos; no se usa ningún modelo de lenguaje.")
_add("simulated_warning",
     "{n_sim} of {n_rows} rows are marked SIMULATED. They are test values for development, "
     "not NASA measurements. Replace data/experiments.csv with the real file before drawing conclusions.",
     "Hay {n_sim} de {n_rows} filas marcadas como SIMULATED. Son valores de prueba para desarrollo, "
     "no mediciones de la NASA. Reemplaza data/experiments.csv por el archivo real antes de sacar conclusiones.")
_add("tab.assistant", "Assistant", "Asistente")
_add("tab.explorer", "Explorer", "Explorador")
_add("tab.charts", "Charts", "Gráficos")

# ---------------------------------------------------------------------------
# Ask stage (hero, input, chips, language toggle)
# ---------------------------------------------------------------------------
_add("hero.title", "Where should we start, explorer?", "¿Por dónde empezamos, explorador?")
_add("hero.subtitle",
     "Evidence-based decision-support tool built on NASA PSI data. "
     "Ask how to prevent, detect or extinguish a fire in microgravity: "
     "answers come only from public data of NASA microgravity combustion experiments.",
     "Herramienta de apoyo a la toma de decisiones basada en evidencia de NASA PSI. "
     "Pregunta cómo prevenir, detectar o apagar un incendio en microgravedad: "
     "las respuestas provienen únicamente de datos públicos de experimentos de combustión en microgravedad de la NASA.")
_add("res.evidence_fold", "View evidence (charts, oxygen line, diluents, rows, calculations)",
     "Ver evidencia (gráficos, línea de oxígeno, diluyentes, filas, cálculos)")
_add("col.measure", "Sensor / measurement type", "Sensor / tipo de medición")
_add("ai.legend", "R… = cited test (opens its source) · E… = calculation made with those tests",
     "R… = ensayo citado (abre su fuente) · E… = cálculo hecho con esos ensayos")
_add("ai.why", "Why", "Por qué")
_add("ai.engine_reason.no_data",
     "The material in the question is not in the data, so the AI is not called (it would only describe other fuels).",
     "El material de la pregunta no está en los datos, así que no se llama a la IA (solo describiría otros combustibles).")
_add("lang.label", "Language", "Idioma")
_add("lang.note", "Answers follow the language of your question.",
     "Las respuestas siguen el idioma de tu pregunta.")
_add("ask.placeholder", "Ask Flame in Freefall… e.g. How do I extinguish a fire at 30% oxygen?",
     "Pregunta a Flame in Freefall… p. ej. ¿Cómo apago un incendio con 30 % de oxígeno?")
_add("ask.label", "Question", "Pregunta")
_add("ask.button", "Ask  ➤", "Preguntar  ➤")
_add("ask.empty", "Write a question first.", "Escribe una pregunta primero.")
_add("chip.prevent", "🛡️ Prevent", "🛡️ Prevenir")
_add("chip.detect", "🔎 Detect", "🔎 Detectar")
_add("chip.extinguish", "🧯 Extinguish", "🧯 Apagar")
_add("example.prevent", "Which cabin materials burn fastest in microgravity?",
     "¿Qué materiales de la cabina se queman más rápido en microgravedad?")
_add("example.detect", "What does the database say about detecting smoke before a flame is visible?",
     "¿Qué dice la base de datos sobre detectar humo antes de que la llama sea visible?")
_add("example.extinguish", "How do I extinguish a fire in a spacecraft at 30% oxygen?",
     "¿Cómo apago un incendio en una nave espacial con 30 % de oxígeno?")

# ---------------------------------------------------------------------------
# Classifying stage and animation
# ---------------------------------------------------------------------------
_add("btn.see_results", "View results ▸", "Ver resultados ▸")
_add("btn.new_question", "New question", "Nueva pregunta")
_add("spinner.searching", "Searching the experiments…", "Buscando en los experimentos…")
_add("results.your_question", "Your question", "Tu pregunta")
_add("err.pipeline_user", "The answer could not be prepared right now. Please try again.",
     "No se pudo preparar la respuesta en este momento. Intenta de nuevo.")
_add("err.pipeline", "Something went wrong while answering: {err}",
     "Algo salió mal al responder: {err}")
_add("anim.classifying", "Reading your question…", "Leyendo tu pregunta…")
_add("anim.verdict", "Detected phase: {phase}", "Fase detectada: {phase}")
_add("anim.confidence", "Phase certainty {value}", "Certeza de fase {value}")
_add("anim.subject", "Subject: {subject}", "Tema: {subject}")
_add("anim.out_of_scope", "OUT OF SCOPE", "FUERA DE ALCANCE")
_add("anim.out_of_scope_hint", "Not about fire safety in spacecraft",
     "No trata de seguridad contra incendios en naves")
_add("anim.unclear", "NO CLEAR PHASE", "FASE NO IDENTIFICADA")
_add("anim.unclear_hint", "Fire-safety question without a clear prevent / detect / extinguish wording",
     "Pregunta de seguridad contra incendios sin una redacción clara de prevenir / detectar / apagar")

# ---------------------------------------------------------------------------
# Phase names, small words
# ---------------------------------------------------------------------------
_add("phase.prevent", "prevent", "prevenir")
_add("phase.detect", "detect", "detectar")
_add("phase.extinguish", "extinguish", "apagar")
_add("phase.out_of_scope", "out of scope", "fuera de alcance")
_add("phase.none", "not identified", "no identificada")
_add("word.and", "and", "y")
_add("word.less", "less", "menos")
_add("word.more", "more", "más")
_add("word.above", "above", "por encima de")
_add("word.below", "below", "por debajo de")
_add("word.oxygen", "oxygen", "oxígeno")
_add("word.pressure", "pressure", "presión")
_add("word.confidence", "phase certainty", "certeza de fase")
_add("word.keywords", "keywords", "palabras clave")
_add("none_m", "none", "ninguno")
_add("none_f", "none", "ninguna")
_add("unspecified", "source does not specify compound/units", "la fuente no especifica compuesto/unidades")

# ---------------------------------------------------------------------------
# Result view
# ---------------------------------------------------------------------------
_add("res.conditions", "Conditions read", "Condiciones leídas")
_add("label.phase", "Phase", "Fase")
_add("label.subject", "Subject", "Tema")
_add("label.stated", "Stated conditions", "Condiciones indicadas")
_add("cond.o2", "O2 {value} %", "O2 {value} %")
_add("cond.pressure", "pressure {text} = {atm} atm", "presión {text} = {atm} atm")
_add("cond.fuel", "fuel {fuel}", "combustible {fuel}")
_add("res.answer", "Answer", "Respuesta")
_add("res.missing_title", "**What is missing**", "**Qué falta**")
_add("res.closest",
     "Closest evidence in the database is shown below. It does not match every requested condition, "
     "so read it as context, not as an answer.",
     "A continuación se muestra la evidencia más cercana de la base de datos. No coincide con todas "
     "las condiciones solicitadas, así que léela como contexto, no como respuesta.")
_add("res.calculations", "Calculations", "Cálculos")
_add("res.nist_caption",
     "Inert heat capacities in the atmosphere figures are molar Cp° at 298.15 K from the "
     "NIST-JANAF thermochemical tables (N2 29.1, O2 29.4, CO2 37.1, He 20.8, Ar 20.8 J/mol·K). "
     "They are not flame-temperature values.",
     "Las capacidades caloríficas de los inertes en las cifras de atmósfera son Cp° molares a 298.15 K "
     "de las tablas termoquímicas NIST-JANAF (N2 29.1, O2 29.4, CO2 37.1, He 20.8, Ar 20.8 J/mol·K). "
     "No son valores a temperatura de llama.")
_add("res.actions", "Recommended actions", "Acciones recomendadas")
_add("res.no_actions",
     "No recommended action is offered: the retrieved rows do not record a suppression "
     "method or an extinction threshold that can be cited.",
     "No se ofrece ninguna acción recomendada: las filas recuperadas no registran un método de "
     "supresión ni un umbral de extinción que se pueda citar.")
_add("res.pde", "Prevent / Detect / Extinguish", "Prevenir / Detectar / Apagar")
_add("res.evidence", "Evidence", "Evidencia")
_add("res.o2_not_listed", "O2 not listed", "O2 no indicado")
_add("res.p_not_listed", "pressure not listed", "presión no indicada")
_add("res.outcome_not_listed", "outcome not listed", "resultado no indicado")
_add("res.limitations", "Limitations", "Limitaciones")
_add("res.none_stated", "None stated.", "No se indican.")
_add("res.sources", "Sources", "Fuentes")
_add("res.link_psi", "PSI data page", "página de datos PSI")
_add("res.no_sources", "No rows were used, so there are no sources.",
     "No se usaron filas, por lo que no hay fuentes.")
_add("res.ranked_expander", "Ranked rows used as evidence", "Filas ordenadas usadas como evidencia")
_add("res.gas_caption",
     "CO2 ppm is taken from the source when it is already in ppm, or converted from % by volume "
     "(1 % vol = 10,000 ppm) when the source used % vol. {unspecified} "
     "when the source table does not name the compound or the unit.",
     "Los ppm de CO2 se toman de la fuente cuando ya están en ppm, o se convierten desde % en volumen "
     "(1 % vol = 10 000 ppm) cuando la fuente usó % vol. {unspecified} "
     "cuando la tabla fuente no nombra el compuesto ni la unidad.")
_add("res.gemini_expander", "Exactly what was sent to Gemini", "Exactamente lo que se envió a Gemini")
_add("insufficient", config.INSUFFICIENT,
     "La base de datos disponible no contiene evidencia suficiente para responder esta "
     "consulta con la precisión requerida.")
_add("relevance_help", config.RELEVANCE_HELP,
     "La relevancia es un puntaje ponderado de qué tan bien coincide cada fila con las condiciones "
     "leídas de la pregunta: oxígeno 35 %, presión 20 %, combustible 20 %, fase 15 %, "
     "más tema 25 % cuando la pregunta nombra una variable de detección o un "
     "agente de supresión (¿la fila registra esa variable o ese agente?). Solo se usan las condiciones "
     "realmente indicadas, y sus pesos se renormalizan para que sumen 1. Las filas cuyo resultado es "
     "«outcome not listed» se ordenan más abajo (puntaje multiplicado por 0.6). "
     "Cuando empatan más filas de las que caben, se toma una muestra espaciada de las empatadas, repartida "
     "entre experimentos. Los términos libres de la pregunta no puntúan (el texto fuente está solo en inglés).")

# Table columns (ranked rows, Explorer, tooltips)
_add("col.row", "Row", "Fila")
_add("col.relevance", "Relevance", "Relevancia")
_add("col.relevance_breakdown", "Relevance breakdown", "Desglose de relevancia")
_add("col.experiment", "Experiment", "Experimento")
_add("col.fuel", "Fuel", "Combustible")
_add("col.oxygen", "Oxygen (%)", "Oxígeno (%)")
_add("col.pressure", "Pressure (atm)", "Presión (atm)")
_add("col.pressure_psi", "Pressure (psi)", "Presión (psi)")
_add("col.phase", "Phase", "Fase")
_add("col.result", "Result", "Resultado")
_add("col.source", "Source", "Fuente")
_add("col.link", "Link", "Enlace")
_add("col.diluent", "Diluent", "Diluyente")
_add("col.outcome_not_listed", "Outcome not listed", "Resultado no indicado")
_add("col.o2_start", "O2 start", "O2 inicial")
_add("col.o2_end", "O2 end", "O2 final")
_add("col.co2_start", "CO2 start", "CO2 inicial")
_add("col.co2_end", "CO2 end", "CO2 final")
_add("col.co_start", "CO start", "CO inicial")
_add("col.co_end", "CO end", "CO final")
_add("col.o2_start_pct", "O2 start (%)", "O2 inicial (%)")
_add("col.o2_end_pct", "O2 end (%)", "O2 final (%)")
_add("col.co2_start_ppm", "CO2 start (ppm)", "CO2 inicial (ppm)")
_add("col.co2_end_ppm", "CO2 end (ppm)", "CO2 final (ppm)")
_add("col.co_start_ppm", "CO start (ppm)", "CO inicial (ppm)")
_add("col.co_end_ppm", "CO end (ppm)", "CO final (ppm)")
_add("col.match", "Match", "Coincidencia")
_add("col.score", "Score", "Puntaje")
_add("component.oxygen", "oxygen", "oxígeno")
_add("component.pressure", "pressure", "presión")
_add("component.fuel", "fuel", "combustible")
_add("component.phase", "phase", "fase")
_add("component.keywords", "keywords", "palabras clave")
_add("component.subject", "subject", "tema")
_add("breakdown.outcome", " × {factor} (outcome not listed) → {value}",
     " × {factor} (resultado no indicado) → {value}")

# Explorer and charts
_add("exp.search", "Search (experiment, fuel, result)", "Buscar (experimento, combustible, resultado)")
_add("exp.rows_caption", "{n} of {total} rows", "{n} de {total} filas")
_add("exp.download", "Download these rows (CSV)", "Descargar estas filas (CSV)")
_add("chart.oxygen_vs_result", "Oxygen vs result", "Oxígeno vs resultado")
_add("chart.no_oxygen", "No row has a numeric oxygen value to plot.",
     "Ninguna fila tiene un valor numérico de oxígeno para graficar.")
_add("chart.axis_oxygen", "Oxygen (% by volume)", "Oxígeno (% en volumen)")
_add("chart.axis_result_value", "Result (value as written in the CSV)",
     "Resultado (valor tal como está escrito en el CSV)")
_add("chart.dots_note", "Each dot is one row of the table. Hover for the full result and source.",
     "Cada punto es una fila de la tabla. Pasa el cursor para ver el resultado completo y la fuente.")
_add("chart.skipped", " {n} row(s) without a numeric oxygen value are not shown.",
     " Filas sin valor numérico de oxígeno que no se muestran: {n}.")
_add("chart.conditions_vs", "Tested conditions vs the atmospheres crews will breathe",
     "Condiciones ensayadas vs las atmósferas que respirarán las tripulaciones")
_add("chart.no_both", "No row has both numeric oxygen and pressure.",
     "Ninguna fila tiene a la vez oxígeno y presión numéricos.")
_add("chart.conditions_note",
     "Dots are experiments from the table. Diamonds are reference atmospheres quoted in the "
     "challenge statement (Earth, planned Moon base and rovers, spacesuit); they are context, not data. "
     "Empty space near a diamond means no tested evidence for that atmosphere.",
     "Los puntos son experimentos de la tabla. Los rombos son atmósferas de referencia citadas en el "
     "enunciado del desafío (Tierra, base lunar y rovers previstos, traje espacial); son contexto, no datos. "
     "Un espacio vacío cerca de un rombo significa que no hay evidencia ensayada para esa atmósfera.")
_add("chart.reference", "Reference", "Referencia")
_add("ref.earth", "Earth, sea level", "Tierra, nivel del mar")
_add("ref.moon", "Planned Moon base / rover (≥30 % O2, ≤10.2 psi)",
     "Base lunar / rover previstos (≥30 % O2, ≤10.2 psi)")
_add("ref.suit", "Spacesuit (100 % O2, 4.3 psi)", "Traje espacial (100 % O2, 4.3 psi)")

# ---------------------------------------------------------------------------
# Classifier (reasons, subject summary, out-of-scope message)
# ---------------------------------------------------------------------------
_add("out_of_scope.message",
     "This assistant only answers questions about preventing, detecting or extinguishing "
     "fires in spacecraft and habitats, using NASA microgravity combustion experiments. "
     "Please rephrase the question around one of those topics, and name a fuel, oxygen "
     "level or detection variable when you can.",
     "Este asistente solo responde preguntas sobre prevenir, detectar o apagar incendios en naves "
     "espaciales y hábitats, usando experimentos de combustión en microgravedad de la NASA. "
     "Reformula la pregunta en torno a alguno de esos temas y, cuando puedas, indica un combustible, "
     "un nivel de oxígeno o una variable de detección.")
_add("out_of_scope.limitations",
     "The question was classified as out of scope; no rows were retrieved and no actions are suggested.",
     "La pregunta se clasificó como fuera de alcance; no se recuperó ninguna fila ni se sugiere ninguna acción.")
_add("clf.oos_offtopic",
     "The question is not about spacecraft fire prevention, detection or extinction.",
     "La pregunta no trata sobre la prevención, detección o extinción de incendios en naves espaciales.")
_add("clf.no_phase",
     "Fire-safety question, but no prevent / detect / extinguish wording was found.",
     "Pregunta de seguridad contra incendios, pero no se encontró ninguna redacción de prevenir / detectar / apagar.")
_add("clf.oos_nofire",
     "The question does not mention fire, combustion, fuels, oxygen or spacecraft safety.",
     "La pregunta no menciona fuego, combustión, combustibles, oxígeno ni seguridad en naves espaciales.")
_add("clf.tie", "Tie between {phases}; the phase named first in the question was used.",
     "Empate entre {phases}; se usó la fase mencionada primero en la pregunta.")
_add("clf.matched", "Matched {phase} wording.", "Coincidió con la redacción de {phase}.")
_add("subj.material", "material/fuel {value}", "material/combustible {value}")
_add("subj.gases", "gas/diluent {value}", "gas/diluyente {value}")
_add("subj.inhibitors", "inhibitor/suppressant {value}", "inhibidor/supresor {value}")
_add("subj.detection", "detection variable {value}", "variable de detección {value}")

# ---------------------------------------------------------------------------
# Retrieval (coverage gaps, notes)
# ---------------------------------------------------------------------------
_add("gap.no_o2_values", "No experiment in the database has a numeric oxygen value.",
     "Ningún experimento de la base de datos tiene un valor numérico de oxígeno.")
_add("gap.o2",
     "No experiment within ±{tol} percentage points of {o2} % O2. Oxygen tested in the database: "
     "{span} % (closest: {closest} %).",
     "Ningún experimento a ±{tol} puntos porcentuales de {o2} % de O2. Oxígeno ensayado en la base de "
     "datos: {span} % (el más cercano: {closest} %).")
_add("gap.pressure",
     "No experiment within ±{tol} of {asked}. Pressure tested in the database: {span}.",
     "Ningún experimento a ±{tol} de {asked}. Presión ensayada en la base de datos: {span}.")
_add("gap.no_numeric", "no numeric values", "sin valores numéricos")
_add("gap.fuel", "No experiment with fuel '{fuel}'. Fuels in the database: {fuels}.",
     "Ningún experimento con el combustible '{fuel}'. Combustibles en la base de datos: {fuels}.")
_add("gap.material",
     "No experiment with the material '{material}' named in the question; "
     "the rows shown are other fuels and do not describe it.",
     "Ningún experimento con el material '{material}' mencionado en la pregunta; "
     "las filas mostradas son de otros combustibles y no lo describen.")
_add("gap.subject", "No row in the database records: {items}.",
     "Ninguna fila de la base de datos registra: {items}.")
_add("gap.min_relevance_fuel",
     "No row with fuel '{fuel}' reached the minimum relevance of {min}; "
     "the closest fuel-matching rows are shown as context.",
     "Ninguna fila con el combustible '{fuel}' alcanzó la relevancia mínima de {min}; "
     "se muestran como contexto las filas más cercanas de ese combustible.")
_add("gap.metric_ranking",
     "The database does not have {metric} measurements for enough different materials to rank them in microgravity.",
     "La base de datos no tiene mediciones de {metric} para suficientes materiales distintos como para ordenarlos en microgravedad.")
_add("gap.min_relevance", "No row reached the minimum relevance of {min}.",
     "Ninguna fila alcanzó la relevancia mínima de {min}.")
_add("gap.empty",
     "The question names no condition (oxygen, pressure, fuel or phase) and no searchable term.",
     "La pregunta no menciona ninguna condición (oxígeno, presión, combustible o fase) ni ningún término de búsqueda.")
_add("note.llm_number", "Gemini proposed {value} but that number is not in the question; ignored.",
     "Gemini propuso {value}, pero ese número no está en la pregunta; se ignoró.")
_add("note.pressure_unit", "Pressure {value} has no recognised unit; ignored.",
     "La presión {value} no tiene una unidad reconocida; se ignoró.")

# ---------------------------------------------------------------------------
# Physics ("Calculations")
# ---------------------------------------------------------------------------
_add("phy.extrapolation",
     "All rows in this database were obtained in microgravity (on the ISS, and Saffire on the Cygnus cargo vehicle). "
     "There is no partial-gravity data, so any statement about a lunar or Martian surface "
     "habitat is an extrapolation and must be read as such.",
     "Todas las filas de esta base de datos se obtuvieron en microgravedad (en la ISS, y Saffire en el carguero Cygnus). "
     "No hay datos de gravedad parcial, por lo que cualquier afirmación sobre un hábitat en la "
     "superficie lunar o marciana es una extrapolación y debe leerse como tal.")
_add("phy.note",
     "How to read these numbers (physics note, not a result from the database): pO2 tells whether the "
     "crew can breathe (sea-level air is about 21.2 kPa). Flammability follows the oxygen fraction more "
     "than pO2, because with less inert gas per mole of O2 the flame is hotter. An atmosphere with an "
     "Earth-like pO2 and a higher O2 % is therefore more flammable than sea-level air, not equally flammable. "
     "Inert heat capacities are molar Cp° at 298.15 K from the NIST-JANAF tables "
     "(N2 29.1, O2 29.4, CO2 37.1, He 20.8, Ar 20.8 J/mol·K), not flame-temperature values.",
     "Cómo leer estos números (nota de física, no es un resultado de la base de datos): la pO2 indica si la "
     "tripulación puede respirar (el aire a nivel del mar tiene unos 21.2 kPa). La inflamabilidad sigue más "
     "a la fracción de oxígeno que a la pO2, porque con menos gas inerte por mol de O2 la llama es más caliente. "
     "Por tanto, una atmósfera con una pO2 similar a la terrestre y un % de O2 mayor es más inflamable que el "
     "aire a nivel del mar, no igual de inflamable. "
     "Las capacidades caloríficas de los inertes son Cp° molares a 298.15 K de las tablas NIST-JANAF "
     "(N2 29.1, O2 29.4, CO2 37.1, He 20.8, Ar 20.8 J/mol·K), no valores a temperatura de llama.")
_add("phy.stated_atm",
     "Stated atmosphere: {o2} % O2 at {p} atm. "
     "pO2 = (O2 % / 100) × P = {atm} atm ({kpa} kPa, {psi} psi). "
     "Inert gas per mole of O2 (balance N2) = (100 − O2 %) / O2 % = {inert} mol, "
     "with a heat capacity of about {ballast} J/K per mole of O2.",
     "Atmósfera indicada: {o2} % de O2 a {p} atm. "
     "pO2 = (O2 % / 100) × P = {atm} atm ({kpa} kPa, {psi} psi). "
     "Gas inerte por mol de O2 (resto N2) = (100 − O2 %) / O2 % = {inert} mol, "
     "con una capacidad calorífica de unos {ballast} J/K por mol de O2.")
_add("phy.normoxic", "At this pressure, sea-level pO2 ({sea} kPa) needs {pct} % O2.",
     "A esta presión, la pO2 del nivel del mar ({sea} kPa) requiere {pct} % de O2.")
_add("phy.stated_o2_only",
     "Stated oxygen: {o2} % by volume. Inert gas per mole of O2 (balance N2) = "
     "{inert} mol (about {ballast} J/K per mole of O2). "
     "No pressure was given, so pO2 is not computed.",
     "Oxígeno indicado: {o2} % en volumen. Gas inerte por mol de O2 (resto N2) = "
     "{inert} mol (unos {ballast} J/K por mol de O2). "
     "No se indicó la presión, por lo que no se calcula la pO2.")
_add("phy.no_o2", "No oxygen level was stated in the question, so no atmosphere figures are computed for it.",
     "La pregunta no indica ningún nivel de oxígeno, por lo que no se calculan cifras de atmósfera para ella.")
_add("phy.refs_header",
     "Reference atmospheres quoted in the challenge (context only, not experimental data):",
     "Atmósferas de referencia citadas en el desafío (solo contexto, no son datos experimentales):")
_add("phy.ref_line",
     "– {label}: {o2} % O2 at {psi} psi → pO2 {atm} atm ({kpa} kPa); "
     "{inert} mol inert per mol O2 (about {ballast} J/K).",
     "– {label}: {o2} % de O2 a {psi} psi → pO2 {atm} atm ({kpa} kPa); "
     "{inert} mol de inerte por mol de O2 (unos {ballast} J/K).")
_add("phy.vs_air",
     "Against {label}, the stated atmosphere has {pct} % "
     "{less_more} inert heat capacity per mole of O2, so it should be "
     "{more_less} flammable. The size of that effect is not predicted here.",
     "Frente a {label}, la atmósfera indicada tiene {pct} % "
     "{less_more} de capacidad calorífica inerte por mol de O2, por lo que debería ser "
     "{more_less} inflamable. Aquí no se predice la magnitud de ese efecto.")
_add("phy.no_fuel",
     "No fuel or material from the database was identified, so no oxygen bound is computed: "
     "a bound across mixed fuels would mean nothing.",
     "No se identificó ningún combustible ni material de la base de datos, por lo que no se calcula un "
     "límite de oxígeno: un límite entre combustibles mezclados no significaría nada.")
_add("phy.no_outcome",
     "No ignition or extinction outcome with an oxygen value is recorded for '{fuel}'.",
     "No hay registrado ningún resultado de ignición o extinción con valor de oxígeno para '{fuel}'.")
_add("phy.no_flame",
     "No row records a flame for '{fuel}'. Highest O2 without one: {o2} % "
     "({kind}) [{row}].",
     "Ninguna fila registra llama para '{fuel}'. O2 más alto sin ella: {o2} % "
     "({kind}) [{row}].")
_add("phy.lowest_flame",
     "Lowest O2 with a recorded flame for '{fuel}': {o2} % "
     "[{row}] ({where}); {n} row(s) record a flame. The flammability limit "
     "in that configuration is at or below this value. It is an observed bound in microgravity, "
     "not an oxygen index (LOI is a normal-gravity test).",
     "O2 más bajo con llama registrada para '{fuel}': {o2} % "
     "[{row}] ({where}); filas con llama registrada: {n}. El límite de inflamabilidad "
     "en esa configuración está en este valor o por debajo. Es un límite observado en microgravedad, "
     "no un índice de oxígeno (el LOI es un ensayo en gravedad normal).")
_add("phy.highest_nonburn",
     "Highest O2 without a flame below it: {o2} % ({kind}) "
     "[{row}]. For the tested configurations the limit lies between "
     "{a} % and {b} %; it is not interpolated.",
     "O2 más alto sin llama por debajo de ese valor: {o2} % ({kind}) "
     "[{row}]. Para las configuraciones ensayadas el límite se sitúa entre "
     "{a} % y {b} %; no se interpola.")
_add("phy.no_below",
     "No test below {b} % records a failed ignition, "
     "so the limit is not bracketed from below. Missing data below that value "
     "is not evidence that the fuel will not burn there.",
     "Ningún ensayo por debajo de {b} % registra una ignición fallida, "
     "por lo que el límite no queda acotado por debajo. La falta de datos por debajo de ese valor "
     "no es evidencia de que el combustible no arda allí.")
_add("phy.overlap",
     "{n} row(s) record no ignition or a flame going out at or above "
     "{o2} % O2: oxygen alone does not decide the outcome "
     "(flow speed, sample or droplet size, pressure and diluent also do).",
     "Filas sin ignición o con una llama que se apaga con "
     "{o2} % de O2 o más: {n}. El oxígeno por sí solo no decide el resultado "
     "(también influyen la velocidad del flujo, el tamaño de la muestra o de la gota, la presión y el diluyente).")
_add("phy.margin",
     "The stated {o2} % O2 is {m} points "
     "{dir} that lowest recorded flame: {verdict}.",
     "El {o2} % de O2 indicado está {m} puntos "
     "{dir} esa llama registrada más baja: {verdict}.")
_add("phy.verdict_inside", "inside the range where this fuel burned in the tests",
     "dentro del rango en el que este combustible ardió en los ensayos")
_add("phy.verdict_below_nonburn",
     "at or below the highest O2 where no flame was recorded, for those test configurations only",
     "igual o inferior al O2 más alto en el que no se registró llama, solo para esas configuraciones de ensayo")
_add("phy.verdict_untested", "in a range with no test, which is not evidence of safety",
     "en un rango sin ensayos, lo que no es evidencia de seguridad")
_add("phy.ext_final",
     "In {n} extinguished row(s) a final O2 is recorded "
     "(range {lo}–{hi} %). That is the O2 left at the end of the test, "
     "not a demonstrated limiting concentration, so it is not used to bracket the bound.",
     "En {n} fila(s) con llama extinguida se registra un O2 final "
     "(rango {lo}–{hi} %). Es el O2 que queda al final del ensayo, "
     "no una concentración límite demostrada, por lo que no se usa para acotar el límite.")
_add("phy.in_unit", " in {unit}", " en {unit}")
_add("phy.trend",
     "Trend inside one experiment ({experiment}, {fuel}; {n} rows; {metric}{unit} "
     "vs O2 % over {range}): {metric} ≈ {a} + {b} × O2%{r2}.",
     "Tendencia dentro de un experimento ({experiment}, {fuel}; {n} filas; {metric}{unit} "
     "vs O2 % en {range}): {metric} ≈ {a} + {b} × O2%{r2}.")
_add("phy.power", " Power-law form: {metric} ∝ (O2 %)^{e}.",
     " Forma de ley de potencias: {metric} ∝ (O2 %)^{e}.")
_add("phy.trend_caveat",
     " Descriptive fit of these rows only: pressure, flow and sample size are not held constant, "
     "and it must not be extended outside that oxygen range.",
     " Ajuste descriptivo solo de estas filas: la presión, el flujo y el tamaño de la muestra no se mantienen "
     "constantes, y no debe extenderse fuera de ese rango de oxígeno.")
_add("phy.no_trend",
     "No trend was fitted: it needs at least 3 rows of one fuel in one experiment, with the same "
     "numeric metric and oxygen values at least 2 points apart.",
     "No se ajustó ninguna tendencia: se necesitan al menos 3 filas de un mismo combustible en un mismo "
     "experimento, con la misma métrica numérica y valores de oxígeno separados al menos 2 puntos.")
_add("phy.diluent",
     "Diluent {gas}: in {n} row(s) with {gas} (median O2 {med} %, "
     "about {ballast} J/K inert heat capacity per mole of O2) the flame went out in "
     "{ext}{ids}; in {n2} N2-only row(s) (median O2 "
     "{med2} %, about {ballast2} J/K) it went out in "
     "{ext2}{ids2}. ",
     "Diluyente {gas}: en {n} fila(s) con {gas} (O2 mediano {med} %, "
     "unos {ballast} J/K de capacidad calorífica inerte por mol de O2) la llama se apagó en "
     "{ext}{ids}; en {n2} fila(s) solo con N2 (O2 mediano "
     "{med2} %, unos {ballast2} J/K) se apagó en "
     "{ext2}{ids2}. ")
_add("phy.diluent_comparable",
     "The two groups have similar oxygen levels, but droplet or sample size and pressure are not "
     "matched: an observation, not a causal claim.",
     "Los dos grupos tienen niveles de oxígeno similares, pero el tamaño de la gota o de la muestra y la "
     "presión no están igualados: es una observación, no una afirmación causal.")
_add("phy.diluent_not_comparable",
     "The two groups differ in oxygen level, so these counts are not a like-for-like comparison.",
     "Los dos grupos difieren en el nivel de oxígeno, por lo que estos recuentos no son una comparación equivalente.")
_add("phy.diluent_cool",
     " {n} of these rows mention a cool flame: "
     "the visible flame going out did not end the reaction.",
     " Entre estas filas, las que mencionan una llama fría son {n}: "
     "que la llama visible se apagara no puso fin a la reacción.")
_add("phy.no_diluent",
     "No rows with CO2 or He next to an N2-only baseline were available for the matching rows.",
     "No había filas con CO2 o He junto a una referencia solo con N2 entre las filas coincidentes.")

# ---------------------------------------------------------------------------
# Pipeline (templated answer, actions, warnings)
# ---------------------------------------------------------------------------
_add("no_evidence", "No evidence in the retrieved rows.", "No hay evidencia en las filas recuperadas.")
_add("empty.answer", "No row in the database matches the question at the required relevance.",
     "Ninguna fila de la base de datos coincide con la pregunta con la relevancia requerida.")
_add("empty.limit_1", "No written interpretation beyond the absence of matching rows.",
     "No se ofrece ninguna interpretación más allá de la ausencia de filas coincidentes.")
_add("source.none", "(no source in the database)", "(sin fuente en la base de datos)")
_add("row.change", " (change over the test: {change})", " (cambio durante el ensayo: {change})")
_add("row.ratio", "; CO produced per CO2 produced {ratio} mol/mol",
     "; CO producido por CO2 producido {ratio} mol/mol")
_add("phase_summary.more", "({extra} more {phase} row(s) in the ranked list.)",
     "({extra} fila(s) más de la fase «{phase}» en la lista ordenada.)")
_add("tpl.answer_head",
     "{n} row(s) from {experiments} match the question for {focus}, "
     "covering {span} {ids}. ",
     "Filas de {experiments} que coinciden con la pregunta para {focus}: {n}, "
     "que cubren {span} {ids}. ")
_add("tpl.answer_head_gap",
     "{n} row(s) from {experiments} were retrieved as related context for {focus}, covering {span} {ids}. "
     "They do not meet every requested condition, so do not read them as a direct answer. ",
     "Se recuperaron {n} fila(s) de {experiments} como contexto relacionado para {focus}, que cubren {span} {ids}. "
     "No cumplen todas las condiciones pedidas, así que no deben leerse como respuesta directa. ")
_add("tpl.prevent_gap",
     "The retrieved experiments do not directly establish prevention evidence under the requested conditions. ",
     "Los experimentos recuperados no establecen directamente evidencia de prevención en las condiciones pedidas. ")
_add("tpl.metric_few",
     "The data do not contain enough comparable {metric} measurements to rank different materials. ",
     "Los datos no contienen suficientes mediciones comparables de {metric} para ordenar materiales distintos. ")
_add("tpl.metric_many",
     "The data contain {metric} measurements for {k} materials; their test conditions differ, so check them before ranking. ",
     "Los datos contienen mediciones de {metric} para {k} materiales; sus condiciones de ensayo difieren, así que revísalas antes de ordenarlos. ")
_add("tpl.metric_fuel", "Recorded {metric} for {fuel} ({n} row(s), highest first): ",
     "{metric} registrada para {fuel} ({n} fila(s), de mayor a menor): ")
_add("tpl.metric_row", "{fuel}: {value} {unit} (flow: {flow}; {o2}) [{row}]. ",
     "{fuel}: {value} {unit} (flujo: {flow}; {o2}) [{row}]. ")
_add("tpl.metric_more", "{n} more row(s) in the chart. ", "{n} fila(s) más en el gráfico. ")
_add("metric.flame_spread_rate", "flame spread rate", "velocidad de propagación de llama")
_add("metric.flame_duration", "flame duration", "duración de la llama")
_add("metric.fuel_consumption_rate", "fuel consumption rate", "tasa de consumo de combustible")
_add("metric.mass_loss_rate", "mass loss rate", "tasa de pérdida de masa")
_add("chart.metric_title", "{metric} — recorded values · {o2}", "{metric} — valores registrados · {o2}")
_add("chart.metric_caption",
     "Each bar is one experimental record (top {n} by value). Test conditions differ, so this is not a direct material ranking.",
     "Cada barra es un registro experimental (los {n} mayores). Las condiciones de ensayo difieren, así que no es un ranking directo de materiales.")
_add("chart.o2_all", "all O₂ levels", "todos los niveles de O₂")
_add("chart.o2_band", "O₂ {o2} % ± {tol} pts", "O₂ al {o2} % ± {tol} pts")
_add("chart.o2_nearest", "nearest tested O₂: {level} % ± {tol} pts", "O₂ ensayado más cercano: {level} % ± {tol} pts")
_add("chart.o2_note_all", "The question does not state an O₂ level, so rows from all O₂ levels are shown.",
     "La pregunta no indica un nivel de O₂, así que se muestran filas de todos los niveles de O₂.")
_add("chart.o2_note_band", "Only rows within ± {tol} percentage points of the {o2} % O₂ in the question.",
     "Solo filas a ± {tol} puntos porcentuales del {o2} % de O₂ de la pregunta.")
_add("chart.o2_note_nearest",
     "No row was recorded near {o2} % O₂; showing the nearest tested level instead ({level} % ± {tol} pts). Read it as context, not as data at {o2} %.",
     "No hay filas registradas cerca del {o2} % de O₂; se muestra el nivel ensayado más cercano ({level} % ± {tol} pts). Léelo como contexto, no como datos al {o2} %.")
_add("chart.metric_none", "No compatible measurements of this metric in the data.",
     "No hay mediciones compatibles de esta métrica en los datos.")
_add("tpl.o2_window", "Here “match” means within ±{tol} percentage points of the {o2} % O2 asked. ",
     "Aquí «coinciden» significa a ±{tol} puntos porcentuales del {o2} % de O2 consultado. ")
_add("tpl.tied_sample",
     "{n} rows were equally relevant; these {k} are an evenly spaced sample of them, not a selection. ",
     "{n} filas eran igual de relevantes; estas {k} son una muestra espaciada de ellas, no una selección. ")
_add("dash.verdict_sample", "sample of {k} from {n} equally relevant rows",
     "muestra de {k} entre {n} filas igual de relevantes")
_add("metric.burning_rate", "droplet burning rate", "tasa de combustión de la gota")
_add("warn.two_fuels",
     "The question names more than one fuel; only {used} is used. Ask about {others} separately.",
     "La pregunta nombra más de un combustible; solo se usa {used}. Pregunta por {others} por separado.")
_add("chart.outcome_axis", "Outcome", "Resultado")
_add("outcome.extinguished", "flame went out", "la llama se apagó")
_add("outcome.burned", "flame, no extinction noted", "llama sin extinción anotada")
_add("outcome.no_ignition", "no ignition", "sin ignición")
_add("outcome.not_listed", "outcome not listed", "resultado no indicado")
_add("outcome.other", "other", "otro")
_add("tpl.focus_default", "the stated conditions", "las condiciones indicadas")
_add("tpl.no_o2", "no numeric oxygen", "sin oxígeno numérico")
_add("tpl.extinguish",
     "Of those rows, {ext} record extinction and {burn} record a flame with no extinction noted. ",
     "Entre esas filas: con extinción, {ext}; con llama sin extinción anotada, {burn}. ")
_add("tpl.detect",
     "{n} of them record gas readings at the start and end of the test (O2 in % vol, CO2 and CO "
     "in ppm); the change is shown with each row under Detect. ",
     "Filas con lecturas de gases al inicio y al final del ensayo (O2 en % vol, CO2 y CO "
     "en ppm): {n}; el cambio se muestra con cada fila en Detectar. ")
_add("tpl.detect_vars", "Variables named in the question: {vars}. ",
     "Variables mencionadas en la pregunta: {vars}. ")
_add("tpl.detect_nosensor", "No sensor performance is inferred beyond what the rows state. ",
     "No se infiere el desempeño de ningún sensor más allá de lo que indican las filas. ")
_add("tpl.prevent",
     "The result text of those rows is summarised under Prevent; flammability claims are limited to the tested conditions. ",
     "El texto de resultado de esas filas se resume en Prevenir; las afirmaciones sobre inflamabilidad "
     "se limitan a las condiciones ensayadas. ")
_add("tpl.missing",
     "{n} of the ranked rows are marked “outcome not listed” and are ranked lower; "
     "they do not support a result claim. ",
     "Filas ordenadas marcadas como «outcome not listed»: {n}; "
     "quedan más abajo y no respaldan ninguna afirmación sobre el resultado. ")
_add("tpl.numbers", "Numbers not written in the rows or in Calculations are not stated here.",
     "Aquí no se afirman números que no estén escritos en las filas o en Cálculos.")
_add("tpl.lim_template",
     "This answer is written directly from the ranked rows and the calculations.",
     "Esta respuesta se redactó directamente a partir de las filas ordenadas y de los cálculos.")
_add("tpl.lim_micro", "All evidence is from microgravity tests; there is no partial-gravity data.",
     "Toda la evidencia proviene de ensayos en microgravedad; no hay datos de gravedad parcial.")
_add("tpl.lim_sim", "Some rows are marked SIMULATED: test values, not NASA measurements.",
     "Algunas filas están marcadas como SIMULATED: son valores de prueba, no mediciones de la NASA.")
_add("tpl.lim_missing", "{n} ranked row(s) have no listed outcome in the source table.",
     "Filas ordenadas sin resultado indicado en la tabla fuente: {n}.")
_add("tpl.how_relevance", "relevance {value}", "relevancia {value}")
_add("tpl.how_outcome", "; outcome not listed", "; resultado no indicado")
_add("act.fuel_default", "the named fuel", "el combustible indicado")
_add("act.cut_oxygen",
     "Cut the oxygen that reaches the fuel. For {fuel}, no flame is recorded at {u_o2} % O2 "
     "({kind}) [{u_row}], and flames are recorded from {l_o2} % O2 upward "
     "[{l_row}]. Bringing the gas around the fuel to {u_o2} % O2 or lower, by flooding "
     "with inert gas or stopping the air flow that feeds the flame, is consistent with those rows. "
     "This holds for the tested configurations in microgravity; it is not a certified procedure. "
     "A failed ignition is not an extinction limit: an established flame may persist below {u_o2} %.",
     "Corta el oxígeno que llega al combustible. Para {fuel}, no se registra llama con {u_o2} % de O2 "
     "({kind}) [{u_row}], y se registran llamas desde {l_o2} % de O2 hacia arriba "
     "[{l_row}]. Llevar el gas que rodea al combustible a {u_o2} % de O2 o menos, inundándolo "
     "con gas inerte o deteniendo el flujo de aire que alimenta la llama, es coherente con esas filas. "
     "Esto vale para las configuraciones ensayadas en microgravedad; no es un procedimiento certificado. "
     "Una ignición fallida no es un límite de extinción: una llama ya encendida puede persistir por debajo de {u_o2} %.")
_add("act.diluent",
     "In this table the flame went out more often with {gas} than with nitrogen alone: at similar oxygen "
     "levels (median {w_med} % and {wo_med} %) the flame went out in "
     "{w_ext} of {w_rows} rows with {gas} {w_ids} and in "
     "{wo_ext} of {wo_rows} N2-only rows {wo_ids}. Sample or "
     "droplet size and pressure are not matched, and in droplet tests extinction is the normal end of the "
     "test, so this is an observation from the table, not a suppression result.",
     "En esta tabla la llama se apagó más a menudo con {gas} que solo con nitrógeno: con niveles de oxígeno "
     "similares (mediana {w_med} % y {wo_med} %) la llama se apagó en "
     "{w_ext} de {w_rows} filas con {gas} {w_ids} y en "
     "{wo_ext} de {wo_rows} filas solo con N2 {wo_ids}. El tamaño de la muestra o de la "
     "gota y la presión no están igualados, y en los ensayos de gotas la extinción es el final normal del "
     "ensayo, así que es una observación de la tabla, no un resultado de supresión.")
_add("act.cool",
     "Keep monitoring after the visible flame is gone: {n} retrieved row(s) mention a cool "
     "flame {ids}, where the fuel kept reacting without a visible flame.",
     "Sigue monitoreando después de que desaparezca la llama visible: las filas recuperadas que mencionan "
     "una llama fría son {n} {ids}; en ellas el combustible siguió reaccionando sin llama visible.")
_add("act.span_range", "{lo} to {hi} ppm", "{lo} a {hi} ppm")
_add("act.monitor",
     "Monitor {label}: it rose in {n} retrieved row(s), by {span} over the test "
     "{ids}. The table gives "
     "the change over the whole test, not how fast it rose, so it does not set an alarm threshold.",
     "Monitorea {label}: aumentó en {n} fila(s) recuperada(s), en {span} a lo largo del ensayo "
     "{ids}. La tabla da "
     "el cambio en todo el ensayo, no qué tan rápido subió, por lo que no fija un umbral de alarma.")
_add("warn.gemini_read", "Gemini could not read the question ({err}). Used the rule-based reading.",
     "Gemini no pudo leer la pregunta ({err}). Se usó la lectura basada en reglas.")
_add("warn.gemini_write",
     "Gemini could not write the answer ({err}). Showing the template written from the rows instead.",
     "Gemini no pudo redactar la respuesta ({err}). Se muestra en su lugar la plantilla redactada a partir de las filas.")
_add("warn.numbers",
     "These numbers in the answer are not in the question, the rows or the computed facts: "
     "{numbers}. Treat them as unverified.",
     "Estos números de la respuesta no están en la pregunta, en las filas ni en los hechos calculados: "
     "{numbers}. Trátalos como no verificados.")
_add("warn.unknown_rows", "The answer cited rows that were not retrieved: {rows}. They were removed.",
     "La respuesta citó filas que no fueron recuperadas: {rows}. Se eliminaron.")

# ---------------------------------------------------------------------------
# Mission-control interface: page chrome, stage-2 animation (viz.*), stage-3 dashboard (dash.*)
# ---------------------------------------------------------------------------
_add("hud.console", "Fire safety evidence console", "Consola de evidencia contra incendios")
_add("hud.team", "Team OCEANPIXELS · ESPOL · Space Apps Challenge 2026",
     "Equipo OCEANPIXELS · ESPOL · Space Apps Challenge 2026")
_add("hud.loaded", "{rows} rows · {experiments} experiments loaded",
     "{rows} filas · {experiments} experimentos cargados")
_add("hud.engine_rules", "Based on NASA PSI data", "Basado en datos de NASA PSI")
_add("hud.tech_engine_rules", "Deterministic engine", "Motor determinista")
_add("hud.engine_gemini", "Gemini writes, the engine checks", "Gemini redacta, el motor verifica")
_add("hud.footer",
     "Data: NASA PSI (Physical Sciences Informatics). Student project for the Space Apps Challenge; "
     "not affiliated with or endorsed by NASA. It does not replace flight procedures or the judgment of "
     "engineers; it shows what the tests say and how solid that is.",
     "Datos: NASA PSI (Physical Sciences Informatics). Proyecto estudiantil para el Space Apps Challenge; "
     "sin afiliación ni respaldo de la NASA. No reemplaza procedimientos de vuelo ni el juicio de ingenieros; "
     "muestra qué dicen los ensayos y cuán sólido es.")

_add("viz.step_classify", "Understand the question", "Entender la pregunta")
_add("viz.step_locate", "Find tests", "Buscar ensayos")
_add("viz.step_narrow", "Pick the closest", "Elegir los más parecidos")
_add("viz.step_verdict", "Result", "Resultado")
_add("viz.kind_fuel", "Fuel", "Combustible")
_add("viz.kind_agent", "Agent", "Agente")
_add("viz.kind_detection", "Signal", "Señal")
_add("viz.kind_pressure", "Pressure", "Presión")
_add("viz.axis_o2", "Oxygen (% by volume)", "Oxígeno (% en volumen)")
_add("viz.axis_pressure", "Pressure (atm)", "Presión (atm)")
_add("viz.cloud_title", "Every dot is one row of the table", "Cada punto es una fila de la tabla")
_add("viz.cloud_note",
     "{plotted} rows have a numeric O2 and are drawn. {hidden} have none and stay off the map.",
     "Se dibujan las {plotted} filas con O2 numérico. Las {hidden} que no lo tienen quedan fuera del mapa.")
_add("viz.strip", "No pressure in the table ({n} rows)", "Sin presión en la tabla ({n} filas)")
_add("viz.your_question", "Your question", "Tu pregunta")
_add("viz.your_question_est", "Your question (estimated from the nearest experiments)",
     "Tu pregunta (estimado a partir de los experimentos más cercanos)")
_add("viz.no_pressure_stated", "no pressure stated", "sin presión indicada")
_add("viz.no_o2_stated", "Your question states no oxygen level, so it has no position on this map.",
     "Tu pregunta no indica un nivel de oxígeno, así que no tiene posición en este mapa.")
_add("viz.status_extinguished", "flame went out", "la llama se apagó")
_add("viz.status_burned", "flame, no extinction noted", "llama sin extinción anotada")
_add("viz.status_other", "other outcome", "otro resultado")
_add("viz.status_reading", "gas readings recorded", "con lecturas de gases")
_add("viz.status_none", "no gas readings", "sin lecturas de gases")
_add("viz.verdict_extinguished", "of the closest rows record extinction",
     "de las filas más parecidas registran extinción")
_add("viz.verdict_burned", "of the closest rows record a flame with no extinction noted",
     "de las filas más parecidas registran llama sin extinción anotada")
_add("viz.verdict_reading", "of the closest rows record gas readings",
     "de las filas más parecidas registran lecturas de gases")
_add("viz.verdict_rows", "rows retrieved as evidence", "filas recuperadas como evidencia")
_add("viz.bars_match", "How well the closest rows match the question (0 to 1)",
     "Qué tan bien coinciden las filas más parecidas con la pregunta (0 a 1)")
_add("viz.bars_readings", "What those rows record", "Qué registran esas filas")
_add("viz.bar_reading", "{gas} change over the test", "cambio de {gas} durante el ensayo")
_add("viz.phase_strip", "Rows per phase in the whole table", "Filas por fase en toda la tabla")
_add("viz.empty", "No row reached the minimum relevance. The results explain what is missing.",
     "Ninguna fila alcanzó la relevancia mínima. Los resultados explican qué falta.")
_add("viz.cta", "View results", "Ver resultados")
_add("viz.cta_below", "Use the button below", "Usa el botón de abajo")
_add("viz.replay", "Replay", "Repetir")
_add("viz.skip", "Skip", "Saltar")
_add("viz.auto", "Results open in {n} s", "Los resultados se abren en {n} s")
_add("viz.credit", "Data: NASA PSI", "Datos: NASA PSI")
_add("viz.legend_top", "Rings: the rows closest to your question",
     "Anillos: las filas más parecidas a tu pregunta")
_add("viz.sampled", "Large table: the map shows a sample of the rows.",
     "Tabla grande: el mapa muestra una muestra de las filas.")
_add("viz.relevance", "top relevance {value}", "relevancia máxima {value}")
_add("viz.funnel_total", "{n} rows in the table", "{n} filas en la tabla")
_add("viz.funnel_topk", "{n} closest to your question", "{n} más parecidas a tu pregunta")
_add("viz.subset_fuel_exp", "{n} {fuel} rows in {experiments}", "{n} filas de {fuel} en {experiments}")
_add("viz.subset_fuel", "{n} {fuel} rows", "{n} filas de {fuel}")
_add("viz.subset_phase", "{n} rows tagged {phase}", "{n} filas de la fase {phase}")
_add("viz.subset_exp", "{n} rows in {experiments}", "{n} filas en {experiments}")
_add("viz.subset_all", "{n} rows considered", "{n} filas consideradas")

_add("refshort.earth", "Earth", "Tierra")
_add("refshort.moon", "Moon base", "Base lunar")
_add("refshort.suit", "Spacesuit", "Traje espacial")

_add("dash.verdict_title", "Verdict on the retrieved rows", "Veredicto sobre las filas recuperadas")
_add("dash.verdict_extinguished", "extinctions", "extinciones")
_add("dash.verdict_burned", "flame, no extinction noted", "con llama sin extinción anotada")
_add("dash.verdict_reading", "with gas readings", "con lecturas de gases")
_add("dash.verdict_rows", "rows retrieved", "filas recuperadas")
_add("dash.out_of_scope_title", "Outside what this console answers", "Fuera de lo que responde esta consola")
_add("dash.insufficient_title", "Not enough evidence", "Evidencia insuficiente")
_add("dash.ring_center", "closest rows", "filas más parecidas")
_add("dash.phase_pill", "{phase} · phase certainty {value}", "{phase} · certeza de fase {value}")
_add("dash.o2_title", "Oxygen line, 0 to {max} % O2", "Línea de oxígeno, 0 a {max} % de O2")
_add("dash.o2_asked", "asked {o2} %", "consultado {o2} %")
_add("dash.o2_flame_zone", "Flame recorded from {o2} % upward [{row}]",
     "Llama registrada desde {o2} % hacia arriba [{row}]")
_add("dash.o2_untested", "No test below {o2} %: limit not bracketed",
     "Sin ensayo por debajo de {o2} %: límite no acotado")
_add("dash.o2_noflame", "No ignition at {o2} % ({kind}) [{row}]",
     "Sin ignición a {o2} % ({kind}) [{row}]")
_add("dash.o2_gap", "untested", "sin ensayo")
_add("dash.o2_no_bound",
     "No oxygen bound was computed for this question. The line shows the asked level next to the reference atmospheres.",
     "No se calculó un límite de oxígeno para esta pregunta. La línea muestra el nivel pedido junto a las "
     "atmósferas de referencia.")
_add("dash.o2_note",
     "Observed in microgravity for the tested configurations; not an oxygen index. "
     "A range without tests is not evidence of safety.",
     "Observado en microgravedad para las configuraciones ensayadas; no es un índice de oxígeno. "
     "Un rango sin ensayos no es evidencia de seguridad.")
_add("dash.o2_off", "{label} {o2} % (off this scale)", "{label} {o2} % (fuera de esta escala)")
_add("dash.diluent_title", "Diluent vs N2 only", "Diluyente vs solo N2")
_add("dash.diluent_sub", "Share of rows where the flame went out. An observation, not a cause.",
     "Proporción de filas en las que la llama se apagó. Es una observación, no una causa.")
_add("dash.diluent_value", "{ext} / {rows} · median O2 {med} %", "{ext} / {rows} · O2 mediano {med} %")
_add("dash.diluent_n2", "N2 only", "Solo N2")
_add("dash.diluent_vs", "N2 only (vs {gas})", "Solo N2 (vs {gas})")
_add("dash.diluent_differs", "O2 levels differ: not like for like", "Niveles de O2 distintos: no es equivalente")
_add("dash.full_answer", "Written answer and evidence", "Respuesta escrita y evidencia")
_add("dash.open_source", "Open the source", "Abrir la fuente")

# ---------------------------------------------------------------------------
# Data-load diagnostics shown in the sidebar (translated at display time)
# ---------------------------------------------------------------------------
_add("issue.not_number", "{row}: {label} value '{value}' is not a plain number; ignored in filters.",
     "{row}: el valor de {label} '{value}' no es un número simple; se ignora en los filtros.")
_add("issue.o2_range", "{row}: oxygen {value} is outside 0–100 %.",
     "{row}: el oxígeno {value} está fuera de 0–100 %.")
_add("issue.phase", "{row}: phase '{value}' is not prevent / detect / extinguish.",
     "{row}: la fase '{value}' no es prevent / detect / extinguish.")
_add("issue.no_source", "{row}: no source (DOI or link).", "{row}: sin fuente (DOI o enlace).")

# ---------------------------------------------------------------------------
# Canonical labels that the engine uses for matching and shows as text.
# English is the label itself; only the display changes.
# ---------------------------------------------------------------------------
_TERMS_ES = {
    # detection variables
    "smoke": "humo", "particles": "partículas", "O2 depletion": "agotamiento de O2",
    "acid gases": "gases ácidos", "temperature": "temperatura",
    "mass loss rate": "tasa de pérdida de masa", "flame radiation": "radiación de la llama",
    # suppression agents
    "water mist": "agua nebulizada", "foam": "espuma", "portable extinguisher": "extintor portátil",
    "ventilation shutdown": "corte de ventilación", "O2 cutoff": "corte de O2",
    "depressurization": "despresurización", "diluent (unspecified)": "diluyente (sin especificar)",
    # generic material names from the synonym table
    "candle": "vela", "silicone": "silicona", "paper": "papel", "nylon": "nailon",
    "polyethylene": "polietileno", "wire insulation": "aislamiento de cable",
    # result metrics parsed from the table
    "burn time": "tiempo de combustión", "time to extinction": "tiempo hasta la extinción",
    "flame duration": "duración de la llama", "burning rate": "tasa de combustión",
    "extinction diameter": "diámetro de extinción", "fuel rate": "caudal de combustible",
    "spread rate": "velocidad de propagación",
    "unit not stated in source": "unidad no indicada en la fuente",
    # outcome kinds and reading mode
    "did not ignite": "no hubo ignición", "rules": "reglas", "gemini + rules": "gemini + reglas",
    # canonical fuel names (flame/classify.py FUEL_SYNONYMS): display only, the data values are never changed
    "methanol": "metanol", "ethanol": "etanol", "n-heptane": "n-heptano", "ethylene": "etileno",
    "propane": "propano", "propylene": "propileno", "methane": "metano", "butane": "butano",
    "ethane": "etano", "decane": "decano", "octane": "octano", "hydrogen": "hidrógeno",
    "Cotton-Fiberglass (SIBAL)": "algodón-fibra de vidrio (SIBAL)", "Lampwick": "mecha",
    "Dibutyl Phthalate": "ftalato de dibutilo", "cellulose": "celulosa",
}
for _label, _es in _TERMS_ES.items():
    _add(f"term.{_label}", _label, _es)

# ---------------------------------------------------------------------------
# v7: AI interpreter (flame/agent.py) panel, badges, trace, footer declaration
# ---------------------------------------------------------------------------
_add("ai.title", "AI interpretation of the evidence", "Interpretación de la IA sobre la evidencia")
_add("ai.badge_model", "AI interpretation · checked against the data", "Interpretación con IA · comprobada con los datos")
_add("ai.tech_badge_model", "Answered by {model} · checked by the engine", "Respondió {model} · verificado por el motor")
_add("ai.badge_engine", "Answer based on the data", "Respuesta basada en los datos")
_add("ai.tech_badge_engine", "Engine answer (no AI): same numbers", "Respuesta del motor (sin IA): mismos números")
_add("ai.title_engine", "Reading of the evidence", "Lectura de la evidencia")
_add("ai.engine_user_note",
     "Every number and citation above comes straight from the tests; open \u201cView evidence\u201d to check them.",
     "Cada número y cita de arriba sale directamente de los ensayos; abre \u00abVer evidencia\u00bb para revisarlos.")
_add("ai.engine_reason.no_key",
     "No Gemini key configured: the deterministic engine answers alone (same numbers, template text).",
     "No hay clave de Gemini: responde solo el motor determinista (mismos números, texto de plantilla).")
_add("ai.engine_reason.errors",
     "Gemini did not answer (network, quota or timeout): the deterministic engine answers alone.",
     "Gemini no respondió (red, cuota o tiempo agotado): responde solo el motor determinista.")
_add("ai.engine_reason.verifier",
     "The AI answer was rejected by the verifier (a number or citation was not in the engine's output), "
     "so the deterministic engine answers alone.",
     "El verificador rechazó la respuesta de la IA (un número o una cita no estaba en la salida del motor), "
     "así que responde solo el motor determinista.")
_add("ai.engine_reason.out_of_scope",
     "Question outside the data: the AI is not called.",
     "Pregunta fuera de los datos: no se llama a la IA.")
_add("ai.claims", "What the evidence says", "Qué dice la evidencia")
_add("ai.kind.observed", "observed", "observado")
_add("ai.kind.computed", "calculation from the data", "cálculo con los datos")
_add("ai.kind.extrapolation", "extrapolation", "extrapolación")
_add("ai.phase.general", "General", "General")
_add("ai.conclusion", "Conclusion", "Conclusión")
_add("ai.agents_title", "Specialist agents and their paths", "Agentes especialistas y sus caminos")
_add("ai.agents_intro", "The router activated these agents for your question. Each one followed its own path "
     "over the NASA table (engine queries, no AI); the AI then wrote what each path found.",
     "El enrutador activó estos agentes para tu pregunta. Cada uno siguió su propio camino sobre la tabla de la "
     "NASA (consultas del motor, sin IA); luego la IA redactó lo que encontró cada camino.")
_add("ai.agent.prevention", "Prevention agent", "Agente de prevención")
_add("ai.agent.detection", "Detection agent", "Agente de detección")
_add("ai.agent.extinction", "Extinction agent", "Agente de extinción")
_add("ai.agent.timing", "Timing agent", "Agente de tiempos")
_add("ai.agent_q.prevention", "Can it burn at these conditions?", "¿Puede arder en estas condiciones?")
_add("ai.agent_q.detection", "Which measured signal changes?", "¿Qué señal medida cambia?")
_add("ai.agent_q.extinction", "What put the flame out?", "¿Qué apagó la llama?")
_add("ai.agent_q.timing", "How long or how fast?", "¿Cuánto dura o qué tan rápido?")
_add("ai.agent_path", "Path", "Camino")
_add("ai.agent_lead", "lead", "principal")
_add("ai.recommendation", "Recommendation from the evidence", "Recomendación según la evidencia")
_add("ai.limitations", "Limitations", "Limitaciones")
_add("ai.missing", "Missing data", "Datos que faltan")
_add("ai.insufficient", "The AI judged the evidence insufficient for a firm answer.",
     "La IA consideró que la evidencia no alcanza para una respuesta firme.")
_add("ai.chart_caption",
     "Chart chosen by the AI; drawn by the app from the cited tests, never with values written by the AI.",
     "Gráfico elegido por la IA; lo dibuja la app con los ensayos citados, nunca con valores escritos por la IA.")
_add("ai.cited_rows", "Rows cited by the AI", "Filas citadas por la IA")
_add("ai.how", "How the AI reasoned", "Cómo razonó la IA")
_add("ai.how_intro",
     "Gemini could only call these engine tools. Each result got an id (E#) and every row keeps its id (R#); "
     "the verifier accepted the answer only because every number and id in it is in this list.",
     "Gemini solo podía llamar a estas herramientas del motor. Cada resultado recibió un id (E#) y cada fila "
     "conserva el suyo (R#); el verificador aceptó la respuesta solo porque todos sus números e ids están en esta lista.")
_add("ai.how_engine",
     "The AI did not produce an accepted answer. Attempts:",
     "La IA no produjo una respuesta aceptada. Intentos:")
_add("ai.col.step", "Step", "Paso")
_add("ai.col.tool", "Tool", "Herramienta")
_add("ai.col.args", "Arguments", "Argumentos")
_add("ai.col.result", "Result", "Resultado")
_add("ai.col.model", "Model", "Modelo")
_add("ai.col.status", "Status", "Estado")
_add("ai.col.detail", "Detail", "Detalle")
_add("ai.col.seconds", "Seconds", "Segundos")
_add("ai.ok", "ok", "ok")
_add("ai.fail", "failed", "falló")
_add("ai.dot.question", "Question", "Pregunta")
_add("ai.dot.engine", "Engine: classify + retrieve + physics", "Motor: clasificar + recuperar + física")
_add("ai.dot.gather", "Gemini plans tool calls", "Gemini planifica llamadas")
_add("ai.dot.pack", "Evidence pack", "Paquete de evidencia")
_add("ai.dot.interpret", "Gemini interprets (JSON schema)", "Gemini interpreta (esquema JSON)")
_add("ai.dot.verify_ok", "Verifier: approved", "Verificador: aprobado")
_add("ai.dot.verify_fail", "Verifier / chain: engine answers", "Verificador / cadena: responde el motor")
_add("ai.dot.ui_ai", "Answer + chart on screen", "Respuesta + gráfico en pantalla")
_add("ai.dot.ui_engine", "Deterministic answer on screen", "Respuesta determinista en pantalla")
_add("ai.working", "🛰️ Analysing the evidence…", "🛰️ Analizando la evidencia…")
_add("ai.tech_working", "🛰️ Gemini is querying the engine… (the numbers come only from the engine)",
     "🛰️ Gemini está consultando el motor… (los números salen solo del motor)")
_add("ai.seconds", "{s} s", "{s} s")
_add("ai.footer",
     "AI use: when available, Google Gemini writes the interpretation from the NASA tests; every number and citation "
     "is checked against those data before it is shown. Charts are drawn from NASA PSI data, not generated by AI. "
     "AI tools assisted with: the user interface (UI), the connectors, the subagent and the AI schema, and the database preparation; the rest was developed by the OCEANPIXELS team.",
     "Uso de IA: cuando está disponible, Google Gemini redacta la interpretación a partir de los ensayos de la NASA; "
     "cada número y cita se comprueba con esos datos antes de mostrarse. Los gráficos se dibujan con datos de NASA PSI, "
     "no los genera una IA. Herramientas de IA apoyaron en: la interfaz de usuario (UI), los conectores, el subagente y el esquema de IA, y la preparación de la base de datos; el resto lo desarrolló el equipo OCEANPIXELS.")
_add("sidebar.ai_chain", "AI chain: {chain} → engine", "Cadena de IA: {chain} → motor")
_add("sidebar.ai_roles", "AI roles: data by {gather} → interpretation by {interpret} → engine",
     "Roles de IA: datos con {gather} → interpretación con {interpret} → motor")
_add("ai.badge_hybrid", "AI interpretation · checked against the data", "Interpretación con IA · comprobada con los datos")
_add("ai.tech_badge_hybrid", "Data: {gather} → interpretation: {model} · checked by the engine",
     "Datos: {gather} → interpretación: {model} · verificado por el motor")
_add("ai.dot.baseline", "Engine baseline evidence (0 requests)", "Evidencia base del motor (0 peticiones)")
_add("ai.dot.handoff", "hand-off: same pack", "relevo: mismo paquete")
_add("ai.dot.rejected", "rejected", "rechazada")
_add("ai.engine_name", "engine", "motor")
_add("ai.col.by", "Called by", "Pedido por")
_add("sidebar.ai_off",
     "No GEMINI_API_KEY: the deterministic engine answers alone. See COMO_CORRER.txt to add a key.",
     "Sin GEMINI_API_KEY: responde solo el motor determinista. Ver COMO_CORRER.txt para agregar la clave.")
_add("ai.field.metric_value", "Metric value", "Valor de la métrica")
_add("ai.field.extinguished", "Rows with extinction", "Filas con extinción")
_add("ai.field.flame_recorded", "Rows with a recorded flame", "Filas con llama registrada")
_add("ai.field.did_not_ignite", "Rows that did not ignite", "Filas sin ignición")
_add("hud.engine_ai", "NASA PSI data · AI interpretation", "Datos de NASA PSI · interpretación con IA")
_add("hud.tech_engine_ai", "Gemini interprets, the engine verifies", "Gemini interpreta, el motor verifica")

STRINGS: dict[str, dict[str, str]] = {
    "en": {key: en for key, en, _ in _ENTRIES},
    "es": {key: es for key, _, es in _ENTRIES},
}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def normalize_lang(lang: str | None) -> str:
    code = str(lang or "").strip().lower()[:2]
    return code if code in LANGS else DEFAULT_LANG


def t(key: str, lang: str | None = DEFAULT_LANG, **kwargs) -> str:
    """Text for ``key`` in ``lang``, with ``str.format`` placeholders filled from ``kwargs``."""
    code = normalize_lang(lang)
    text = STRINGS[code].get(key)
    if text is None:
        text = STRINGS[DEFAULT_LANG].get(key)
    if text is None:
        return key
    if not kwargs:
        return text
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return text


def placeholders(text: str) -> set[str]:
    """Names of the ``{placeholders}`` in a template (used by the tests)."""
    return {name for _, name, _, _ in Formatter().parse(text) if name}


def phase_name(phase: str | None, lang: str | None = DEFAULT_LANG) -> str:
    """Lowercase phase name in ``lang``. Unknown values are returned unchanged."""
    if not phase:
        return t("phase.none", lang)
    key = f"phase.{phase}"
    return t(key, lang) if key in STRINGS[DEFAULT_LANG] else str(phase)


def term(label: str, lang: str | None = DEFAULT_LANG) -> str:
    """Display text for a canonical engine label (detection variable, agent, metric...)."""
    key = f"term.{label}"
    return t(key, lang) if key in STRINGS[DEFAULT_LANG] else str(label)


def terms(labels, lang: str | None = DEFAULT_LANG) -> list[str]:
    return [term(label, lang) for label in labels]


def ref_label(ref: dict, lang: str | None = DEFAULT_LANG) -> str:
    """Name of a reference atmosphere (config.REFERENCE_ATMOSPHERES entry)."""
    key = ref.get("key")
    if normalize_lang(lang) == DEFAULT_LANG or not key or f"ref.{key}" not in STRINGS[DEFAULT_LANG]:
        return str(ref.get("label", ""))
    return t(f"ref.{key}", lang)


_ISSUE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^(?P<row>R\d+): (?P<label>oxygen|pressure) value '(?P<value>.*)' is not a plain number; ignored in filters\.$"),
     "issue.not_number"),
    (re.compile(r"^(?P<row>R\d+): oxygen (?P<value>.*) is outside 0–100 %\.$"), "issue.o2_range"),
    (re.compile(r"^(?P<row>R\d+): phase '(?P<value>.*)' is not prevent / detect / extinguish\.$"), "issue.phase"),
    (re.compile(r"^(?P<row>R\d+): no source \(DOI or link\)\.$"), "issue.no_source"),
]


def localize_issue(issue: str, lang: str | None = DEFAULT_LANG) -> str:
    """Translate one of the data-load diagnostics produced by ``flame.data``. Unknown text is kept."""
    if normalize_lang(lang) == DEFAULT_LANG:
        return issue
    for pattern, key in _ISSUE_PATTERNS:
        m = pattern.match(issue)
        if m:
            fields = m.groupdict()
            if "label" in fields:
                fields["label"] = t(f"word.{fields['label']}", lang)
            return t(key, lang, **fields)
    return issue


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

# Words that are strongly one language. Ambiguous ones ("a", "no", "me", "he", "o", "e") are left out.
_ES_WORDS = frozenset("""
el la los las un una unos unas de del al en por para con sin sobre entre hasta desde como cómo que qué
cual cuál cuales cuáles quien quién cuando cuándo donde dónde cuanto cuánto porque por qué es son está
están ser estar fue hay se su sus mi mis tu tus lo le les nos y pero más mas muy también tambien ya
si sí cuando mientras durante antes después despues dime explica puedo puede pueden debo debe deben
fuego incendio incendios llama llamas humo oxigeno oxígeno presion presión nave naves espacial espaciales
microgravedad combustible combustibles combustion combustión apagar apago apaga extinguir extingue extintor
detectar detecta detectan detecto prevenir previene prevenir evitar materiales cabina tripulacion
tripulación experimentos experimento ensayo ensayos cuál tipo datos pruebas prueba
""".split())

_EN_WORDS = frozenset("""
the of in on at to for and or with without how what which when where why who whom is are was were be been
can could should would do does did i we you it this that these those my our your about tell please
fire fires flame flames oxygen pressure spacecraft space experiment experiments test tests used using
happen happened happens database data detect detecting extinguish extinguishing prevent preventing
smoke visible there their them than then also before after during from by as if not into over under
burn burns burning materials cabin crew
""".split())

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_ACCENTED = re.compile(r"[áéíóúü]")


def language_scores(text: str) -> tuple[int, int]:
    """(english score, spanish score) for ``text``. Deterministic."""
    raw = str(text or "")
    low = raw.lower()
    tokens = _TOKEN.findall(low)
    en = sum(1 for tok in tokens if tok in _EN_WORDS)
    es = sum(1 for tok in tokens if tok in _ES_WORDS)
    if "¿" in raw or "¡" in raw:
        es += 3
    es += 2 * low.count("ñ")
    es += min(3, len(_ACCENTED.findall(low)))
    return en, es


def detect_language(text: str, default: str | None = DEFAULT_LANG) -> str:
    """"es" or "en" for a question. Ties (or no signal at all) return ``default``."""
    en, es = language_scores(text)
    if es > en:
        return "es"
    if en > es:
        return "en"
    return normalize_lang(default)
