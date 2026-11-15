# 🔥 Flame in Freefall — OCEANPIXELS
### Cómo abrir la app en tu computadora (guía para principiantes)

> **Novedad: versión web.** La app ahora es una página web normal (HTML) que corre en tu propia computadora en `localhost:8600`. Se abre con **`INICIAR_WEB_WINDOWS`** (Windows) o **`INICIAR_WEB_MAC_LINUX.command`** (Mac/Linux). La versión anterior (Streamlit) sigue incluida como respaldo: `RESPALDO_STREAMLIT_WINDOWS.bat` / `RESPALDO_STREAMLIT_MAC_LINUX.command` (se abre en `localhost:8501`). Las dos muestran los mismos números.

Esta guía es para cualquier persona, aunque nunca haya instalado un programa. Solo sigue los pasos en orden. **Necesitas internet la primera vez.** Tiempo total: unos 10 minutos.

> La app es gratis y no instala nada raro. Usa una herramienta llamada **uv** que descarga Python y lo necesario dentro de su propia carpeta.

---

## 🪟 Si tienes WINDOWS

### Paso 1. Descarga el archivo
Te enviaron un archivo llamado **`flame-in-freefall_OCEANPIXELS_html.zip`**. Guárdalo en tu carpeta **Descargas**.

### Paso 2. Descomprime (muy importante)
Un `.zip` es como una caja cerrada: **la app no funciona si la abres sin sacarla de la caja.**

1. Abre la carpeta **Descargas**. (Puedes presionar a la vez las teclas **Windows** ⊞ y **E**, y en la izquierda hacer clic en **Descargas**.)
2. Busca el archivo `flame-in-freefall_OCEANPIXELS_html.zip`.
3. Haz clic **una vez** sobre él para seleccionarlo.
4. Arriba en la ventana aparece un botón **"Extraer todo"**. Haz clic ahí.
   - Si no lo ves: haz clic con el **botón derecho del mouse** (el botón de la derecha) sobre el archivo y elige **"Extraer todo…"**.
5. Se abre una ventanita. Haz clic en **"Extraer"**.
6. Se abrirá una carpeta nueva. Entra (doble clic) a la carpeta **`flame-in-freefall`**.

### Paso 3. Abre la app
1. Dentro de esa carpeta, busca el archivo **`INICIAR_WEB_WINDOWS`** (o `INICIAR_WEB_WINDOWS.bat`).
2. Haz **doble clic** sobre él (dos clics rápidos con el botón izquierdo).
3. Si aparece una ventana azul que dice **"Windows protegió su PC"**:
   - Haz clic en **"Más información"**.
   - Luego en **"Ejecutar de todas formas"**.
   (Aparece porque el archivo no viene de una tienda de apps; es normal.)
4. Se abre una **ventana negra** con letras. **No la cierres.** Ahí la app se está preparando.
   - **La primera vez tarda de 1 a 5 minutos** porque descarga lo necesario. Las siguientes veces tarda segundos.
5. Cuando esté lista, **tu navegador (Chrome, Edge…) se abre solo** con la app.
   - Si no se abre, abre tu navegador y escribe arriba, en la barra de direcciones: **`localhost:8600`** y presiona **Enter**.

### Paso 4. Úsala
- Escribe una pregunta en español o en inglés, por ejemplo:
  - *¿Cómo apago un fuego de metanol al 21 % de oxígeno?*
  - *¿Qué nivel de oxígeno evita que el PMMA se encienda?*
  - *¿Qué gases indican que el algodón está ardiendo?*
- Verás una animación y luego los resultados. Para otra pregunta, usa el botón **"Nueva pregunta"**.

### Paso 5. Para cerrarla
Cierra la **ventana negra** (la X de arriba a la derecha). Listo.
La próxima vez, solo repite el **Paso 3** (doble clic en `INICIAR_WEB_WINDOWS`).

---

## 🍎 Si tienes MAC

1. Haz doble clic en el `.zip` en **Descargas**: se crea la carpeta `flame-in-freefall`.
2. Abre la app **Terminal**: presiona **Cmd ⌘ + Espacio**, escribe `Terminal` y presiona **Enter**.
3. Escribe `bash ` (con un espacio al final), luego **arrastra** el archivo `INICIAR_WEB_MAC_LINUX.command` desde la carpeta hasta la ventana de Terminal y presiona **Enter**.
4. Espera (la primera vez 1 a 5 minutos). El navegador se abre solo en `localhost:8600`.
5. Para cerrar: en Terminal presiona **Control + C**, o cierra la ventana.

## 🐧 Si tienes LINUX
Abre una terminal en la carpeta `flame-in-freefall` y ejecuta:
```
bash INICIAR_WEB_MAC_LINUX.command
```

---

## ❓ Si algo sale mal

| Lo que ves | Qué hacer |
|---|---|
| El doble clic abre una lista de archivos y no pasa nada | No descomprimiste. Vuelve al **Paso 2** ("Extraer todo"). |
| "Windows protegió su PC" | "Más información" → "Ejecutar de todas formas". |
| La ventana negra se cierra sola de inmediato | Revisa tu internet y vuelve a hacer doble clic. |
| Dice "address already in use" o "8600" con un error | La app ya está abierta en otra ventana negra. Abre el navegador en `localhost:8600`, o cierra la otra ventana y prueba otra vez. |
| El navegador muestra "No se puede acceder a este sitio" | Aún se está preparando. Espera 1 minuto y presiona **F5** para recargar. |
| Sale **"Respuesta del motor (sin IA): mismos números"** | La app sigue funcionando con el motor solo (mismos números). Causas: sin clave, sin internet o cupo gratis de Gemini agotado (cada modelo: 20 peticiones al día; v7b usa 1 de gemini-4-hydrogen por pregunta, unas 20 preguntas; se renueva a las 03:00 hora Colombia). Ver `COMO_CORRER.txt`. |
| Nada funciona | Toma una foto de la ventana negra y envíala al equipo OCEANPIXELS. |

---

## ℹ️ Datos útiles
- **Funciona sin internet** después de la primera vez (las respuestas salen de los datos, sin IA externa).
- **Opcional: IA que interpreta (Gemini).** Con una clave gratis de Google Gemini, debajo del tablero aparece "Interpretación de la IA": Gemini solo puede consultar el motor y los datos de la NASA, cada frase cita sus filas y un verificador revisa todos los números. Sin clave, sin internet o si Google está saturado, responde el motor solo con los mismos números ("Motor sin IA").
  - **Cómo poner la clave en 4 pasos:** (1) sácala en `aistudio.google.com/apikey`; (2) entra a la carpeta `.streamlit` (en Windows, si no la ves: Vista → Mostrar → Elementos ocultos); (3) copia `secrets.toml.example` y renombra la copia a `secrets.toml`; (4) ábrelo con el Bloc de notas, cambia `paste-your-key-here` por tu clave entre comillas, guarda y vuelve a abrir la app. La clave se queda en tu computadora: la versión web la lee solo en el servidor local y **nunca** la envía al navegador. Detalles en `COMO_CORRER.txt`.
  - Nunca compartas ni subas tu clave a internet (los archivos `secrets.toml` y `.env` ya están excluidos de GitHub).
- **Datos:** 1,982 registros públicos de experimentos de combustión en microgravedad (NASA Physical Sciences Informatics). Proyecto de estudiantes para NASA Space Apps Challenge 2026; **no está afiliado ni respaldado por la NASA**.
- **Uso de IA:** en ejecución, cuando hay clave, Google Gemini redacta la interpretación opcional y cada número se comprueba con los datos de la NASA; los gráficos los dibuja la app con filas de la NASA (no son imágenes generadas por IA). Desarrollo: Herramientas de IA apoyaron en: la interfaz de usuario (UI), los conectores, el subagente y el esquema de IA, y la preparación de la base de datos; el resto lo desarrolló el equipo OCEANPIXELS.
- **AI use (EN):** at runtime, when a key is set, Google Gemini writes the optional interpretation and every number is checked against the NASA data; charts are drawn from NASA rows (not AI-generated images). Development: AI tools assisted with: the user interface (UI), the connectors, the subagent and the AI schema, and the database preparation; the rest was developed by the OCEANPIXELS team.

*Equipo OCEANPIXELS — Guayaquil, Ecuador.*

---

## 🛠️ Para el equipo técnico (versión web)

- `server.py`: FastAPI + uvicorn. Sirve `web/` (HTML/CSS/JS puros, sin paso de compilación; Vega/Vega-Lite/Vega-Embed copiados en `web/vendor/`) y una API JSON sobre el mismo motor y el mismo agente v7b que `app.py`.
- Correr a mano: `uv run python server.py` (puerto con `FLAME_PORT`, host con `FLAME_HOST`, por defecto `127.0.0.1:8600`; `--open` abre el navegador).
- Endpoints: `GET /api/health`, `GET /api/meta?lang=`, `POST /api/ask {question, lang?, ai?}`, `POST /api/interpret {question, lang?}`, `GET /api/explorer`, `GET /api/charts?lang=`.
- Clave Gemini: solo en el servidor (variable `GEMINI_API_KEY`/`GOOGLE_API_KEY`, luego `.env`, luego `.streamlit/secrets.toml`). Nunca llega al JavaScript.
- IA por defecto en la versión web: `GATHER_MODELS=engine` (el motor junta la evidencia, 0 peticiones flash) e `INTERPRET_MODELS=gemini-4-hydrogen,gemini-3.8-flash,gemini-3.6-flash`. Se cambian con variables de entorno.
- Flujo: la página llama `/api/ask` con `ai:false` (≈0,2 s) para arrancar la animación y, en paralelo, `/api/interpret`; si la IA falla o no hay clave, se muestra "Motor sin IA" con los mismos números.
- Pruebas: `uv run --with pytest python -m pytest -q tests`.
- `app.py` (Streamlit) se mantiene como respaldo: `uv run streamlit run app.py`.

## Para qué sirve (nuestra interpretación del reto)

**Herramienta de apoyo a la toma de decisiones basada en evidencia de NASA PSI** (EN: *Evidence-based decision-support tool built on NASA PSI data*). Es nuestra lectura del uso que sugiere el reto: destacar investigación de combustión en microgravedad que sea útil para controles de seguridad y equipos. No reemplaza procedimientos de vuelo ni el juicio de ingenieros; muestra qué dicen los ensayos y cuán sólido es. Proyecto estudiantil, sin afiliación ni respaldo de la NASA.

- **Respuesta primero:** tras la animación se muestra una frase clara, la confianza (N de K, de cuántas filas y experimentos), la acción y la interpretación de la IA. La evidencia (tablero, línea de O2, diluyentes, filas, cálculos) queda plegada en "Ver evidencia".
- **Datos insuficientes:** si el material no está en los datos (ejemplo: litio) o la medida no existe en esas filas, la primera frase es "Los datos no alcanzan para responder esto" y no se muestra un N/K grande.
- **Luna y Marte:** todos los ensayos de PSI son en microgravedad (ISS y Cygnus). Si la pregunta menciona Luna, Marte o gravedad parcial, aparece un aviso de extrapolación.

## Sensores y tipos de medición por experimento

Generado desde el CSV de PSI (1.982 filas). "Instrumento" solo cuando el CSV lo nombra (P-Trak y DustTrak, únicamente en DAFT). Lo que no está aquí (modelos de detector, lecturas de partículas de SAME / SAME-R) no está incluido en los datos. En el Explorador se puede filtrar por esta categoría.

| Experimento | Filas · fase | Categoría | Qué se ensayó · tipo de medición |
|---|---|---|---|
| SAME | 8 · detectar | Humo / aerosol | humo de materiales calentados (Teflon, Kapton, caucho de silicona, mecha, ftalato de dibutilo) · medición: tasa de pérdida de masa (mg/min), tiempo de envejecimiento |
| SAME-R | 109 · detectar | Humo / aerosol | corridas de aerosol de humo · se registran la relación del calentador Rt/R0, el tiempo de envejecimiento del humo y la velocidad de entrada; los datos de PSI no incluyen las lecturas de partículas |
| SPICE | 469 · detectar | Hollín (punto de humo) | llama de chorro laminar para punto de humo (hollín) · se registran el caudal de combustible y la duración de la llama |
| DAFT | 2 · detectar | Polvo | aerosol de polvo (Arizona Road Dust) en aire de la ISS · instrumentos nombrados en los datos: P-Trak modificado, DustTrak |
| BASS-II | 129 · prevenir | Gases (inicio → fin) | llama sobre sólidos con flujo de aire · medición: O2 y CO2 (% vol) y CO (ppm), inicio → fin del ensayo |
| BASS | 122 · prevenir | Sin resultado en PSI | muestras de material · sin resultado en la tabla de PSI |
| CFI-G | 333 · apagar | Gases (inicio → fin) | llamas esféricas normales e inversas de gas · medición: tiempo de combustión (s), fracción molar de O2 antes / después, flujo de combustible |
| CFI | 87 · apagar | Combustión de gotas | gotas con llama fría · composición y presión del ambiente; sin resultado |
| FLEX | 274 · apagar | Combustión de gotas | combustión de gotas · medición: diámetro de extinción, tasa de combustión, tiempo de combustión; composición del ambiente |
| FLEX-2 | 8 · apagar | Combustión de gotas | matriz de ensayos · solo condiciones ensayadas |
| ACME Flame Design | 327 · prevenir | Llamas de gas | llamas esféricas de difusión · XO2 inicial / final, temperatura adiabática calculada, flujo total |
| ACME BRE | 18 · prevenir | Llamas de gas | llamas de quemador por día de ensayo · llamas encendidas, % de O2 y combustible |
| ACME CLD Flame | 32 · prevenir | Llamas de gas | llamas de quemador por día de ensayo · llamas encendidas, % de O2 y combustible |
| ACME E-FIELD Flames | 21 · prevenir | Llamas de gas | llamas de quemador por día de ensayo · llamas encendidas, % de O2 y combustible |
| ACME s-Flame | 18 · apagar | Llamas de gas | llamas de quemador por día de ensayo · llamas encendidas, % de O2 y combustible |
| SLICE | 12 · prevenir | Sin resultado en PSI | llama de chorro levantada / adherida · día de ensayo; sin resultado |
| SAFFIRE-I | 2 · prevenir | Propagación (sólidos) | combustión a gran escala en Cygnus · tiempo de combustión, velocidad de propagación (mm/s), longitud quemada |
| SAFFIRE-II | 9 · prevenir | Propagación (sólidos) | combustión a gran escala en Cygnus · tiempo de combustión, velocidad de propagación (mm/s), longitud quemada; O2 derivado de la producción de CO2 |
| SAFFIRE-III | 2 · prevenir | Propagación (sólidos) | combustión a gran escala en Cygnus · tiempo de combustión, velocidad de propagación (mm/s), longitud quemada |
