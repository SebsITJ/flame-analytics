"""Answer-first card of the results page (team spec C1-C4, C11).

    1 one plain sentence  2 confidence line  3 phase + action  (then the AI's "why", then folded evidence)

Everything here is read from the engine's result: no number is computed that the engine did not already
count, and no instrument is named that is not in the CSV (see MEASUREMENTS, generated from the PSI table).
"""

from __future__ import annotations

import html
import re
import unicodedata

import pandas as pd

from . import config
from .i18n import term

# ---------------------------------------------------------------------------
# C11: what each experiment measured. "instrument" only when the CSV names one.
# ---------------------------------------------------------------------------
MEASUREMENTS: dict[str, dict] = {
    "SAME": {"cat": "smoke", "en": "smoke from heated materials (Teflon, Kapton, silicone rubber, wick, dibutyl phthalate) · measurement: mass loss rate (mg/min), smoke ageing time",
             "es": "humo de materiales calentados (Teflon, Kapton, caucho de silicona, mecha, ftalato de dibutilo) · medición: tasa de pérdida de masa (mg/min), tiempo de envejecimiento"},
    "SAME-R": {"cat": "smoke", "en": "smoke aerosol runs · recorded: heater ratio Rt/R0, smoke ageing time, inlet velocity; the PSI data do not include the particle readings",
               "es": "corridas de aerosol de humo · se registran la relación del calentador Rt/R0, el tiempo de envejecimiento del humo y la velocidad de entrada; los datos de PSI no incluyen las lecturas de partículas"},
    "SPICE": {"cat": "soot", "en": "laminar jet flame for smoke point (soot) · recorded: fuel flow rate and flame duration",
              "es": "llama de chorro laminar para punto de humo (hollín) · se registran el caudal de combustible y la duración de la llama"},
    "DAFT": {"cat": "dust", "en": "dust aerosol (Arizona Road Dust) in ISS air · instruments named in the data: modified P-Trak, DustTrak",
             "es": "aerosol de polvo (Arizona Road Dust) en aire de la ISS · instrumentos nombrados en los datos: P-Trak modificado, DustTrak"},
    "BASS-II": {"cat": "gas", "en": "flames over solids in an air flow · measurement: O2 and CO2 (% vol) and CO (ppm), start → end of the test",
                "es": "llama sobre sólidos con flujo de aire · medición: O2 y CO2 (% vol) y CO (ppm), inicio → fin del ensayo"},
    "BASS": {"cat": "none", "en": "material samples · no result in the PSI table", "es": "muestras de material · sin resultado en la tabla de PSI"},
    "CFI-G": {"cat": "gas", "en": "normal and inverse spherical gas flames · measurement: burn time (s), O2 mole fraction before / after, fuel flow",
              "es": "llamas esféricas normales e inversas de gas · medición: tiempo de combustión (s), fracción molar de O2 antes / después, flujo de combustible"},
    "CFI": {"cat": "droplet", "en": "cool-flame droplets · ambient composition and pressure; no result", "es": "gotas con llama fría · composición y presión del ambiente; sin resultado"},
    "FLEX": {"cat": "droplet", "en": "droplet combustion · measurement: extinction diameter, burning rate, burn time; ambient composition",
             "es": "combustión de gotas · medición: diámetro de extinción, tasa de combustión, tiempo de combustión; composición del ambiente"},
    "FLEX-2": {"cat": "droplet", "en": "test matrix · tested conditions only", "es": "matriz de ensayos · solo condiciones ensayadas"},
    "ACME Flame Design": {"cat": "flame", "en": "spherical diffusion flames · initial / final XO2, computed adiabatic temperature, total flow",
                          "es": "llamas esféricas de difusión · XO2 inicial / final, temperatura adiabática calculada, flujo total"},
    "ACME BRE": {"cat": "flame", "en": "burner flames per test day · flames lit, % O2 and fuel", "es": "llamas de quemador por día de ensayo · llamas encendidas, % de O2 y combustible"},
    "ACME CLD Flame": {"cat": "flame", "en": "burner flames per test day · flames lit, % O2 and fuel", "es": "llamas de quemador por día de ensayo · llamas encendidas, % de O2 y combustible"},
    "ACME E-FIELD Flames": {"cat": "flame", "en": "burner flames per test day · flames lit, % O2 and fuel", "es": "llamas de quemador por día de ensayo · llamas encendidas, % de O2 y combustible"},
    "ACME s-Flame": {"cat": "flame", "en": "burner flames per test day · flames lit, % O2 and fuel", "es": "llamas de quemador por día de ensayo · llamas encendidas, % de O2 y combustible"},
    "SLICE": {"cat": "none", "en": "lifted / attached jet flame · test day; no result", "es": "llama de chorro levantada / adherida · día de ensayo; sin resultado"},
    "SAFFIRE-I": {"cat": "spread", "en": "large-scale burning in Cygnus · burn time, spread rate (mm/s), burned length", "es": "combustión a gran escala en Cygnus · tiempo de combustión, velocidad de propagación (mm/s), longitud quemada"},
    "SAFFIRE-II": {"cat": "spread", "en": "large-scale burning in Cygnus · burn time, spread rate (mm/s), burned length; O2 derived from CO2 production",
                   "es": "combustión a gran escala en Cygnus · tiempo de combustión, velocidad de propagación (mm/s), longitud quemada; O2 derivado de la producción de CO2"},
    "SAFFIRE-III": {"cat": "spread", "en": "large-scale burning in Cygnus · burn time, spread rate (mm/s), burned length", "es": "combustión a gran escala en Cygnus · tiempo de combustión, velocidad de propagación (mm/s), longitud quemada"},
}
CATEGORIES = {
    "gas": ("Gases (start → end)", "Gases (inicio → fin)"),
    "smoke": ("Smoke / aerosol", "Humo / aerosol"),
    "soot": ("Soot (smoke point)", "Hollín (punto de humo)"),
    "dust": ("Dust", "Polvo"),
    "droplet": ("Droplet combustion", "Combustión de gotas"),
    "flame": ("Gas flames", "Llamas de gas"),
    "spread": ("Flame spread (solids)", "Propagación (sólidos)"),
    "none": ("No result in PSI", "Sin resultado en PSI"),
}


def measurement_category(experiment: str, lang: str = "en") -> str:
    cat = MEASUREMENTS.get(str(experiment), {}).get("cat")
    return CATEGORIES[cat][1 if lang == "es" else 0] if cat else ""


# ---------------------------------------------------------------------------
# C3: a material named in the question that has no row in the data
# ---------------------------------------------------------------------------
# word in the question (accents folded) -> (name ES, name EN, tokens searched in the dataset's fuel columns)
_MATERIALS = {
    "litio": ("litio", "lithium", ("lithium",)), "lithium": ("litio", "lithium", ("lithium",)),
    "bateria": ("baterías", "batteries", ("battery", "lithium")), "baterias": ("baterías", "batteries", ("battery", "lithium")),
    "battery": ("baterías", "batteries", ("battery", "lithium")), "batteries": ("baterías", "batteries", ("battery", "lithium")),
    "hidrogeno": ("hidrógeno", "hydrogen", ("hydrogen", "h2")), "hydrogen": ("hidrógeno", "hydrogen", ("hydrogen", "h2")),
    "madera": ("madera", "wood", ("wood",)), "wood": ("madera", "wood", ("wood",)),
    "papel": ("papel", "paper", ("paper", "cellulose")), "paper": ("papel", "paper", ("paper", "cellulose")),
    "gasolina": ("gasolina", "gasoline", ("gasoline",)), "gasoline": ("gasolina", "gasoline", ("gasoline",)),
    "queroseno": ("queroseno", "kerosene", ("kerosene",)), "kerosene": ("queroseno", "kerosene", ("kerosene",)),
    "diesel": ("diésel", "diesel", ("diesel",)),
    "nylon": ("nylon", "nylon", ("nylon",)), "nailon": ("nylon", "nylon", ("nylon",)),
    "polietileno": ("polietileno", "polyethylene", ("polyethylene",)), "polyethylene": ("polietileno", "polyethylene", ("polyethylene",)),
    "aluminio": ("aluminio", "aluminum", ("alumin",)), "aluminum": ("aluminio", "aluminum", ("alumin",)), "aluminium": ("aluminio", "aluminum", ("alumin",)),
    "magnesio": ("magnesio", "magnesium", ("magnesium",)), "magnesium": ("magnesio", "magnesium", ("magnesium",)),
    "titanio": ("titanio", "titanium", ("titanium",)), "titanium": ("titanio", "titanium", ("titanium",)),
    "espuma": ("espuma", "foam", ("foam",)), "foam": ("espuma", "foam", ("foam",)),
    "cable": ("cables", "cables", ("wire", "cable")), "cables": ("cables", "cables", ("wire", "cable")),
    "wire": ("cables", "cables", ("wire", "cable")), "wires": ("cables", "cables", ("wire", "cable")),
    "aceite": ("aceite", "oil", (" oil",)), "oil": ("aceite", "oil", (" oil",)),
}
_PARTIAL_G = re.compile(r"\b(luna|lunar(?:es)?|marte|marcian[oa]s?|moon|mars|martian|gravedad parcial|partial gravity|"
                        r"habitat de superficie|surface habitat)\b")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def missing_material(question: str, df: pd.DataFrame) -> tuple[str, str] | None:
    """(name ES, name EN) of a material the question names and the dataset does not contain, or None."""
    words = set(re.findall(r"[a-z0-9]+", _fold(question)))
    hay = None
    for w in sorted(words & set(_MATERIALS)):
        es, en, tokens = _MATERIALS[w]
        if hay is None:
            cols = [c for c in ("combustible", "tipo_combustible") if c in df.columns]
            hay = " | ".join(" ".join(map(str, df[c].dropna().unique())) for c in cols).lower()
        if not any(tok in hay for tok in tokens):
            return es, en
    return None


_GAS_Q = re.compile(r"\b(gas|gases|co2|co|monoxido|dioxido|olor|olores|oler|huele|smell|smells|odor|odour|sensor|sensores|sensors|"
                    r"combustion lenta|smolder\w*|smoulder\w*)\b")


def asks_about_gases(question: str) -> bool:
    return bool(_GAS_Q.search(_fold(question)))


def gas_change_summary(df: pd.DataFrame, lang: str) -> tuple[str, list[str]]:
    """Median start -> end change of CO2 and CO in the rows that recorded it (today BASS-II), with example rows."""
    parts, ids = [], []
    for col, name in (("co2_delta_ppm", "CO2"), ("co_delta_ppm", "CO")):
        if col not in df.columns:
            continue
        rows = df[pd.to_numeric(df[col], errors="coerce").notna()]
        if rows.empty:
            continue
        exps = ", ".join(dict.fromkeys(rows["experimento"].astype(str)))
        med = float(pd.to_numeric(rows[col]).median())
        parts.append(_t("gas_part", lang, gas=name, med=f"{med:+,.0f}".replace(",", "." if lang == "es" else ","), n=len(rows), exps=exps))
        ids += rows["row_id"].astype(str).head(2).tolist()
    return (_t("gas_other", lang, parts=_t("and", lang).join(parts)) if parts else ""), list(dict.fromkeys(ids))


def mentions_partial_gravity(question: str) -> bool:
    return bool(_PARTIAL_G.search(_fold(question)))


# ---------------------------------------------------------------------------
# The card
# ---------------------------------------------------------------------------
_T = {
    "answer": ("Answer", "Respuesta"),
    "nodata": ("The data are not enough to answer this.", "Los datos no alcanzan para responder esto."),
    "nodata_state": ("no data", "sin datos"),
    "no_material": ("There are no tests with {m} in the PSI data. The closest are {k} tests with other fuels ({exps}), "
                    "which do not answer the question.",
                    "No hay ensayos con {m} en los datos de PSI. Lo más cercano son {k} ensayos con otros combustibles "
                    "({exps}), que no responden la pregunta."),
    "no_rows": ("No row of the dataset matches the conditions of the question.", "Ninguna fila de los datos coincide con las condiciones de la pregunta."),
    "at_o2": ("At {o2} % oxygen, ", "Con {o2} % de oxígeno, "),
    "ext": ("the {fuel}flame went out in {n} of {k} similar tests.", "la llama{fuel} se apagó en {n} de {k} ensayos parecidos."),
    "burn": ("{fuel}burned in {n} of {k} similar tests.", "{fuel}ardió en {n} de {k} ensayos parecidos."),
    "burn_nofuel": ("the sample burned in {n} of {k} similar tests.", "la muestra ardió en {n} de {k} ensayos parecidos."),
    "rows": ("there are {k} similar tests{fuel}", "hay {k} ensayos parecidos{fuel}"),
    "rows_ext": ("; the flame went out in {e} of them.", "; en {e} de ellos la llama se apagó."),
    "gas": ("{n} of {k} similar tests recorded gases at the start and the end.", "{n} de {k} ensayos parecidos registraron gases al inicio y al final."),
    "gas_change": (" Median change in those rows: {parts}.", " Cambio mediano en esas filas: {parts}."),
    "no_gas": ("These experiments did not measure gases; they measured smoke, soot and dust.",
               "Estos experimentos no midieron gases; midieron humo, hollín y polvo."),
    "gas_part": ("{gas} changed by a median of {med} ppm in {n} tests of {exps}", "el {gas} cambió una mediana de {med} ppm en {n} ensayos de {exps}"),
    "gas_other": ("Gas readings exist in other tests: {parts}.", "Sí hay lecturas de gases en otros ensayos: {parts}."),
    "and": (" and ", " y "),
    "rows_cited": ("Example rows: {ids}.", "Filas de ejemplo: {ids}."),
    "unknown": ("the {k} most similar tests{fuel} do not record how the test ended (whether it burned or went out).",
                "los {k} ensayos más parecidos{fuel} no registran cómo terminó el ensayo (si ardió o se apagó)."),
    "flame_out": ("{e} of the {k} most similar tests{fuel} had a flame that went out; the others do not record how they ended.",
                  "en {e} de los {k} ensayos más parecidos{fuel} hubo llama y se apagó; los demás no registran cómo terminaron."),
    "conf": ("{n} of {k} most similar tests", "{n} de {k} ensayos más parecidos"),
    "conf_rows": ("{k} most similar tests", "{k} ensayos más parecidos"),
    "base": ("taken from {x} rows of {y} experiment{s} ({exps})", "tomados de {x} filas de {y} experimento{s} ({exps})"),
    "action": ("Action", "Acción"),
    "no_action": ("The data do not recommend a specific action.", "Los datos no recomiendan una acción concreta."),
    "diluent": ("Tests where the flame went out, by gas added: {parts}.", "Ensayos con la llama apagada según el gas añadido: {parts}."),
    "n2": ("N2 only", "solo N2"),
    "measured": ("What each experiment measured", "Qué midió cada experimento"),
    "moon": ("All PSI tests are in microgravity (ISS and Cygnus). There are no combustion data in partial gravity "
             "(Moon / Mars), as the challenge statement notes; this is an extrapolation.",
             "Todos los ensayos de PSI son en microgravedad (ISS y Cygnus). No hay datos de combustión en gravedad "
             "parcial (Luna/Marte), como señala el enunciado del reto; esto es una extrapolación."),
    "phase": {"prevent": ("Prevent", "Prevenir"), "detect": ("Detect", "Detectar"), "extinguish": ("Extinguish", "Apagar")},
}


def _t(key: str, lang: str, **kw) -> str:
    text = _T[key][1 if lang == "es" else 0]
    return text.format(**kw) if kw else text


def _g(value) -> str:
    return f"{float(value):g}"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def lead_payload(res, view: dict, df: pd.DataFrame) -> dict:
    """The answer-first card for a result. `view` is flame.viz_payload.build_dashboard_view(res, df)."""
    L = "es" if view.get("lang") == "es" else "en"
    v, det, state = view["verdict"], view["detected"], view["state"]
    question = str(view.get("question") or "")
    fuel, o2 = det.get("fuel"), det.get("o2")
    hits = res.retrieval.hits if getattr(res, "retrieval", None) is not None else pd.DataFrame()
    top = hits.head(int(v["k"])) if v["k"] and not hits.empty else hits.iloc[0:0]
    exps = list(dict.fromkeys(top["experimento"].astype(str))) if "experimento" in top.columns else []
    exp_names = ", ".join(exps[:4]) + (f" +{len(exps) - 4}" if len(exps) > 4 else "")
    tied = int(getattr(res.retrieval, "tied", 0) or 0) if getattr(res, "retrieval", None) is not None else 0

    notices = [_t("moon", L)] if mentions_partial_gravity(question) else []
    out: dict = {"state": "ok", "notices": notices, "phase": state if state in config.PHASES else None,
                 "phase_label": _T["phase"][state][1 if L == "es" else 0] if state in config.PHASES else "",
                 "sentence": "", "reason": "", "confidence": "", "action": "", "measurements": [], "hide_count": False}

    lost = missing_material(question, df) if not fuel else None
    if lost or not v["k"] or view.get("insufficient"):
        out["state"] = "nodata"
        out["sentence"] = _t("nodata", L)
        if lost:
            out["reason"] = _t("no_material", L, m=lost[0 if L == "es" else 1], k=v["k"], exps=exp_names or "—")
        elif view.get("missing"):
            out["reason"] = " ".join(view["missing"][:2])
        else:
            out["reason"] = _t("no_rows", L)
        out["action"] = _t("no_action", L)
        return _finish(out, L)

    fuel_txt = term(str(fuel), L) if fuel else ""  # display name: "metanol" in Spanish
    lead_in = _t("at_o2", L, o2=_g(o2)) if o2 is not None else ""
    kind, n, k = v["kind"], v["n"], v["k"]
    no_gas = state == "detect" and not v["counts"].get("reading")
    n_ext, n_burn = int(v["counts"].get("extinguished") or 0), int(v["counts"].get("burned") or 0)
    unknown = (kind == "burned" and not n) or (kind == "extinguished" and not n and not n_burn)
    if unknown:
        # C3: "0 of N" here would only mean the rows do not say how the test ended, not that nothing burned
        out["hide_count"] = True
        f = (f" of {fuel_txt}" if L == "en" else f" de {fuel_txt}") if fuel_txt else ""
        sentence = lead_in + (_t("flame_out", L, e=n_ext, k=k, fuel=f) if n_ext else _t("unknown", L, k=k, fuel=f))
    elif no_gas:
        sentence = _t("no_gas", L)
        if asks_about_gases(question):  # C2: say how much each gas changed where it WAS measured, with rows
            extra, ids = gas_change_summary(df, L)
            if extra:
                out["reason"] = extra + " " + _t("rows_cited", L, ids=", ".join(ids))
    elif kind == "extinguished":
        f = (f"{fuel_txt} " if L == "en" else f" de {fuel_txt}") if fuel_txt else ""
        sentence = lead_in + _t("ext", L, fuel=f, n=n, k=k)
    elif kind == "burned":
        sentence = lead_in + (_t("burn", L, fuel=fuel_txt + " ", n=n, k=k) if fuel_txt else _t("burn_nofuel", L, n=n, k=k))
    elif kind == "reading":
        sentence = _t("gas", L, n=n, k=k)
        parts = []
        for col, name, unit in (("co2_delta_ppm", "CO2", "ppm"), ("co_delta_ppm", "CO", "ppm")):
            vals = pd.to_numeric(top[col], errors="coerce").dropna() if col in top.columns else pd.Series(dtype=float)
            if len(vals):
                parts.append(f"{name} {vals.median():+.4g} {unit} ({len(vals)})")
        if parts:
            sentence += _t("gas_change", L, parts=", ".join(parts))
    else:
        f = (f" of {fuel_txt}" if L == "en" else f" de {fuel_txt}") if fuel_txt else ""
        sentence = lead_in + _t("rows", L, k=k, fuel=f)
        e = int(v["counts"].get("extinguished") or 0)
        sentence += _t("rows_ext", L, e=e) if e else "."
    out["sentence"] = _cap(sentence)

    conf = _t("conf_rows", L, k=k) if (no_gas or unknown or kind == "rows") else _t("conf", L, n=n, k=k)
    bits = [conf]
    if exps:
        bits.append(_t("base", L, x=tied or k, y=len(exps), s="" if len(exps) == 1 else "s", exps=exp_names))
    o2s = pd.to_numeric(top["oxigeno_num"], errors="coerce").dropna() if "oxigeno_num" in top.columns else pd.Series(dtype=float)
    if len(o2s):
        lo, hi = float(o2s.min()), float(o2s.max())
        bits.append(f"O2 {_g(lo)} %" if abs(hi - lo) < 1e-9 else f"O2 {_g(lo)}–{_g(hi)} %")
    out["confidence"] = " · ".join(bits)

    actions = view.get("actions") or []
    bars = [b for b in (view.get("diluent") or []) if b.get("rows", 0) >= config.DILUENT_MIN_ROWS]
    if actions:
        a = actions[0]
        out["action"] = ". ".join(x for x in (str(a.get("title") or "").strip(" ."), str(a.get("body") or "").strip()) if x)[:260]
    elif state == "extinguish" and len(bars) >= 2:
        parts = [f"{_t('n2', L) if b['baseline'] else b['gas']} {b['extinguished']}/{b['rows']}" for b in bars]
        out["action"] = _t("diluent", L, parts=" · ".join(parts))
    else:
        out["action"] = _t("no_action", L)

    if state == "detect":
        out["measurements"] = [{"experiment": e, "text": MEASUREMENTS[e][L]} for e in exps if e in MEASUREMENTS]
    return _finish(out, L)


def _finish(out: dict, L: str) -> dict:
    esc = html.escape
    color = config.PHASE_COLORS.get(out.get("phase") or "", config.TELEMETRY_COLOR)
    nodata = out["state"] == "nodata"
    h = [f'<div class="ff-lead{" ff-lead-nodata" if nodata else ""}" style="--k:{"#8a94a8" if nodata else color}">']
    h.append(f'<span class="ff-tag">{esc(_t("answer", L))}{" · " + esc(_t("nodata_state", L)) if nodata else ""}</span>')
    h.append(f'<p class="ff-lead-s">{esc(out["sentence"])}</p>')
    if out["reason"]:
        h.append(f'<p class="ff-lead-r">{esc(out["reason"])}</p>')
    for n in out["notices"]:
        h.append(f'<div class="ff-banner ff-banner-warn">{esc(n)}</div>')
    if out["confidence"]:
        h.append(f'<p class="ff-lead-c">{esc(out["confidence"])}</p>')
    if out["measurements"]:
        items = "".join(f'<li><b>{esc(m["experiment"])}</b> {esc(m["text"])}</li>' for m in out["measurements"])
        h.append(f'<div class="ff-lead-m"><span class="ff-tag">{esc(_t("measured", L))}</span><ul>{items}</ul></div>')
    label = out["phase_label"].upper()
    h.append(f'<p class="ff-lead-a">{f"<b>{esc(label)}</b> · " if label else ""}{esc(_t("action", L))}: {esc(out["action"])}</p>')
    h.append("</div>")
    out["html"] = "".join(h)
    return out
