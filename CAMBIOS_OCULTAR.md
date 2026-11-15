# Una sola página para el jurado: qué se quitó (15 nov 2026)

**Regla:** la página web es exactamente lo que ve el jurado. No existe modo técnico: ni `?debug=1`, ni botón oculto,
ni marca en el navegador (localStorage/sessionStorage), ni parámetro en la dirección, ni ruta que devuelva la traza
para mostrarla. Los detalles internos siguen en el código del servidor y en su registro (consola), solo para el equipo.

## 1. Código borrado (no solo oculto con CSS)

- `web/debug.js` eliminado, con todas sus referencias (`index.html`, `panel.html`, `app.js`). Ya no existen la clase
  `ff-tech` / `ff-tech-only` ni la regla CSS que las ocultaba.
- `web/app.js`: borrados el desplegable «Cómo razonó la IA» (agentes, enrutador, herramientas, modelos, intentos,
  segundos), la nota con el motivo técnico de la respuesta sin IA, el texto técnico de espera y la pista bajo la caja.
- `web/panel.html`: borrada la tarjeta «Traza del modelo» (modelo, respaldo, filas, latencia,
  fuente, intentos) y los datos de demostración internos (MOCK).
- Animación (`flame/animation.py`, `flame/viz_payload.py`): borrados el reloj «T+5.0 s», la píldora de certeza y las
  palabras clave; esos campos ya no se envían al navegador.
- «Condiciones leídas» (`flame/web.py`): ya no muestra certeza, palabras clave ni «(reglas)» / «(gemini + reglas)».
- Barra superior (`flame/theme.py`): una sola etiqueta sencilla («Basado en datos de NASA PSI»).
- Respaldo Streamlit (`app.py`): mismo criterio — sin traza, sin nombres de modelo ni segundos, sin motivo técnico,
  sin certeza/palabras clave, sin estado de modelos en la barra lateral; error genérico en pantalla.

## 2. Datos que ya no salen del servidor

`server.py` filtra todas las respuestas (`web.public_meta`, `public_ask`, `public_ai`, `public_panel`):
- Fuera: `mode`, `reason`, `note`, `tech_badge`, `gather_model`, `attempts`, `calls`, `trace`, `agents`, `seconds`,
  `engine_seconds`, `gather_models` / `interpret_models` y los textos técnicos (`ai.tech_*`, `ai.engine_reason.*`,
  `ai.dot.*`, `sidebar.*`, `ai.how*`).
- `/api/ask_v2` → `model_trace` solo lleva `{answered_by: insignia sencilla, fallback_used}`.
- Errores: el navegador recibe solo `{"error": "internal error"}`; el detalle va al registro del servidor.

## 3. Textos reescritos (ES / EN)

| Antes | Ahora |
|---|---|
| «Respondió {modelo} · verificado por el motor» | «Interpretación con IA · comprobada con los datos» |
| «Respuesta del motor (sin IA): mismos números» | «Respuesta basada en los datos» |
| «🛰️ Gemini está consultando el motor…» | «🛰️ Analizando la evidencia…» |
| «Motor determinista» / «Gemini interpreta, el motor verifica» | «Basado en datos de NASA PSI» / «Datos NASA PSI · interpretación con IA» |
| Pasos «Clasificar · Ubicar · Acotar · Contar» | «Entender la pregunta · Buscar ensayos · Elegir los más parecidos · Resultado» |
| «R = fila del dataset · E = cálculo del motor» | «R… = ensayo citado · E… = cálculo hecho con esos ensayos» |
| «Esta respuesta es una plantilla determinista…» | «Esta respuesta se redactó directamente a partir de las filas ordenadas y de los cálculos.» |
| Nombre del combustible «methanol» en español | «metanol» (y el resto de combustibles en `_TERMS_ES`) |

La IA recibe la instrucción de no hablar del funcionamiento interno (motor, modelo, herramienta, verificador…).

## 4. Vista alternativa renombrada

La vista alternativa ahora está en **`/panel`** (`web/panel.html`), con un nombre neutro; enlaces, lanzadores, pruebas y
documentación actualizados.

## 5. Declaración de uso de IA

- **En ejecución (se mantiene):** Google Gemini redacta la interpretación opcional; cada número y cita se comprueba con
  los datos de la NASA; los gráficos los dibuja la app con datos de NASA PSI.
- **En el desarrollo (nueva, ES):** «Herramientas de IA apoyaron en: la interfaz de usuario (UI), los conectores, el
  subagente y el esquema de IA, y la preparación de la base de datos; el resto lo desarrolló el equipo OCEANPIXELS.»
- **(EN):** «AI tools assisted with: the user interface (UI), the connectors, the subagent and the AI schema, and the
  database preparation; the rest was developed by the OCEANPIXELS team.»
- Está en el pie de la página principal, en «Declaración de uso de IA» de `/panel`, en README.md y LEEME_PRIMERO.md/.pdf.

## 6. Pruebas

- `tests/test_hide_internals.py`: `?debug=1` (y otros parámetros) devuelve exactamente la misma página; `debug.js` no
  existe; ningún archivo del navegador contiene código de depuración; las respuestas de la API no traen campos
  internos; los textos visibles no tienen términos internos; números de la demo intactos.
- Suite completa: ver el resumen de entrega. Revisión en navegador (Chrome sin ventana) de `/` y `/panel`, ES y EN,
  con y sin `?debug=1`: texto visible idéntico y sin términos internos.
- Números verificados: metanol 21 % → 7 de 8; CO2 64/75, He 27/28, solo N2 44/54; «detectar» sin 0/8; litio en la Luna
  → «Los datos no alcanzan…» sin número grande.
