"""Stage-3 dashboard markup: the dict from ``flame.viz_payload.build_dashboard_view`` -> one HTML string.

Pure string building (no Streamlit), so it can be tested. Every value is escaped with ``theme.esc``; links
are only written for http(s) URLs. The CSS lives in ``flame.theme.THEME_CSS`` (``ff-d-*`` and friends).

Layout, top to bottom (one screen at 1440 x 900):
    strip     phase + confidence, source pills (DOI), the question
    row       verdict card  |  ring of the top rows by outcome  |  diluent bars vs N2 only
    line      oxygen line 0-40 % with the asked level, the recorded flame bound and reference atmospheres
    actions   one card per recommended action, with the sources of the rows it cites
The app adds native expanders (calculations, evidence, ranked rows) and the "New question" button.
"""

from __future__ import annotations

import math

from . import config
from .animation import hex_to_rgba
from .i18n import t, term
from .theme import esc
from .viz_payload import STATUS_COLORS

_KIND_COLORS = {
    "extinguished": STATUS_COLORS["extinguished"],
    "burned": STATUS_COLORS["burned"],
    "reading": STATUS_COLORS["reading"],
    "rows": config.TELEMETRY_COLOR,
}
_NEUTRAL = "#9aa3b8"
_WARN = config.QUESTION_COLOR


def _g(value) -> str:
    return f"{float(value):g}"


def pill(label: str, url: str = "", title: str = "") -> str:
    """A small rounded tag; a link when ``url`` is http(s)."""
    if str(url).startswith(("http://", "https://")):
        return (f'<a class="ff-pill" href="{esc(url)}" target="_blank" rel="noopener noreferrer"'
                f' title="{esc(title)}">{esc(label)}</a>')
    return f'<span class="ff-pill">{esc(label)}</span>'


def kind_color(view: dict) -> str:
    if view["state"] == "out_of_scope":
        return _NEUTRAL
    if not view["verdict"]["k"]:
        return _WARN
    return _KIND_COLORS.get(view["verdict"]["kind"], config.TELEMETRY_COLOR)


def strip_html(view: dict) -> str:
    lang, det = view["lang"], view["detected"]
    if det["confidence"] and view["state"] in config.PHASES:
        phase = t("dash.phase_pill", lang, phase=det["phase_label"], value=f"{det['confidence']:.2f}")
    else:
        phase = det["phase_label"]
    parts = [f'<span class="ff-pill ff-phase">{esc(phase)}</span>']
    parts += [pill(s["label"], s["url"], t("dash.open_source", lang)) for s in view["sources"]]
    parts.append(f'<span class="ff-d-q" title="{esc(view["question"])}">{esc(t("results.your_question", lang))}: '
                 f'{esc(view["question"])}</span>')
    color = kind_color(view)
    style = f"--ff-k:{color};--ff-k-soft:{hex_to_rgba(color, 0.16)}"
    return f'<div class="ff-d-strip" style="{style}">{"".join(parts)}</div>'


def verdict_html(view: dict) -> str:
    lang, v = view["lang"], view["verdict"]
    if view["state"] == "out_of_scope":
        return (f'<div class="ff-card ff-verdict"><h4>{esc(t("dash.out_of_scope_title", lang))}</h4>'
                f'<div>{esc(v["answer"])}</div></div>')
    if view.get("nodata"):  # C3: say it first, never a big 0/N or an N/8 of other fuels
        return (f'<div class="ff-card ff-verdict ff-nodata"><h4>{esc(t("dash.insufficient_title", lang))}</h4>'
                f'<div>{esc(view["nodata"])}</div></div>')
    missing = "".join(f"<li>{esc(m)}</li>" for m in view["missing"][:3])
    missing = f'<ul class="ff-list">{missing}</ul>' if missing else ""
    if not v["k"]:
        return (f'<div class="ff-card ff-verdict"><h4>{esc(t("dash.insufficient_title", lang))}</h4>'
                f'<div>{esc(t("insufficient", lang))}</div>{missing}</div>')
    headline = " · ".join([v["headline"]] + list(v["context"]))
    warn = ""
    if view["insufficient"]:
        warn = f'<div class="ff-warnline">{esc(t("insufficient", lang))} {esc(t("res.closest", lang))}{missing}</div>'
    return (
        f'<div class="ff-card ff-verdict"><h4>{esc(t("dash.verdict_title", lang))}</h4>'
        f'<div class="ff-big"><b>{v["n"]}<small>/{v["k"]}</small></b><span>{esc(headline)}</span></div>'
        + (f'<div class="ff-sample">{esc(v["sample"])}</div>' if v.get("sample") else "")
        + f'<div class="ff-clamp">{esc(v["answer"])}</div>{warn}</div>'
    )


def ring_html(view: dict) -> str:
    """Donut of the top rows by outcome. Segments are separated by a small gap; the key repeats the counts."""
    lang, v, ring = view["lang"], view["verdict"], view["ring"]
    if not v["k"] or not ring or view.get("nodata"):
        return ""
    radius, width = 46.0, 12.0
    circ = 2 * math.pi * radius
    total = sum(seg["n"] for seg in ring) or 1
    gap = 3.0 if len(ring) > 1 else 0.0
    arcs, start = [], 0.0
    for seg in ring:
        length = seg["n"] / total * circ
        arcs.append(
            f'<circle cx="60" cy="60" r="{radius:g}" fill="none" stroke="{esc(seg["color"])}" stroke-width="{width:g}"'
            f' stroke-dasharray="{max(length - gap, 0.5):.2f} {circ - max(length - gap, 0.5):.2f}"'
            f' stroke-dashoffset="{-start:.2f}" transform="rotate(-90 60 60)"/>'
        )
        start += length
    key = "".join(
        f'<span><i class="ff-sw" style="background:{esc(seg["color"])}"></i>{seg["n"]} · {esc(seg["label"])}</span>'
        for seg in ring
    )
    label = f'{v["n"]}/{v["k"]} {t("viz.verdict_" + v["kind"], lang)}'
    return (
        f'<div class="ff-card ff-ring"><svg viewBox="0 0 120 120" role="img" aria-label="{esc(label)}">'
        f'<circle cx="60" cy="60" r="{radius:g}" fill="none" stroke="rgba(255,255,255,.07)" stroke-width="{width:g}"/>'
        f'{"".join(arcs)}<text x="60" y="64" text-anchor="middle" font-size="24" font-weight="300">{v["n"]} / {v["k"]}</text>'
        f'<text x="60" y="80" text-anchor="middle" font-size="7.5" opacity=".7">{esc(t("dash.ring_center", lang))}</text></svg>'
        f'<div class="ff-key">{key}</div></div>'
    )


def diluent_html(view: dict) -> str:
    lang, bars = view["lang"], view["diluent"]
    if not bars:
        return ""
    rows = []
    for b in bars:
        if b["baseline"]:
            name = t("dash.diluent_vs", lang, gas=b["versus"]) if b["versus"] else t("dash.diluent_n2", lang)
        else:
            name = b["gas"]
        med = _g(b["o2_median"]) if b["o2_median"] is not None else "?"
        value = t("dash.diluent_value", lang, ext=b["extinguished"], rows=b["rows"], med=med)
        rows.append(
            f'<div class="ff-bar"><div class="ff-bar-h"><b>{esc(name)}</b><span class="ff-val">{esc(value)}</span></div>'
            f'<div class="ff-track"><div class="ff-fill{" ff-base" if b["baseline"] else ""}"'
            f' style="width:{b["fraction"] * 100:.1f}%"></div></div></div>'
        )
    note = t("dash.diluent_sub", lang)
    if any(not b["comparable"] for b in bars if not b["baseline"]):
        note += " " + t("dash.diluent_differs", lang) + "."
    return (f'<div class="ff-card"><h4>{esc(t("dash.diluent_title", lang))}</h4>{"".join(rows)}'
            f'<div class="ff-sub">{esc(note)}</div></div>')


def oxygen_html(view: dict) -> str:
    lang, s = view["lang"], view["o2_scale"]
    if not s:
        return ""
    top = float(s["max"])

    def pct(value: float) -> float:
        return max(0.0, min(100.0, float(value) / top * 100))

    def zone(cls: str, lo: float, hi: float, text: str) -> str:
        if hi - lo <= 0:
            return ""
        return (f'<div class="ff-zone {cls}" style="left:{pct(lo):.2f}%;width:{pct(hi) - pct(lo):.2f}%" title="{esc(text)}">'
                f"{esc(text)}</div>")

    zones, notes = [], []
    flame, under = s["flame_from"], s["no_flame_at"]
    if flame:
        f_o2 = min(float(flame["o2"]), top)
        flame_text = t("dash.o2_flame_zone", lang, o2=_g(flame["o2"]), row=flame["row_id"])
        if under:
            u_o2 = min(float(under["o2"]), f_o2)
            zones.append(zone("ff-noflame", 0, u_o2, t("dash.o2_noflame", lang, o2=_g(under["o2"]), kind=under["kind"], row=under["row_id"])))
            zones.append(zone("ff-untested", u_o2, f_o2, t("dash.o2_gap", lang)))
        else:
            zones.append(zone("ff-untested", 0, f_o2, t("dash.o2_untested", lang, o2=_g(flame["o2"]))))
        zones.append(zone("ff-flame", f_o2, top, flame_text))
        notes.append(t("dash.o2_note", lang))
    else:
        notes.append(t("dash.o2_no_bound", lang))

    asked = ""
    if s["asked"] is not None:
        left = pct(s["asked"])
        asked = (f'<div class="ff-asked{" ff-left" if left > 72 else ""}" style="left:{left:.2f}%">'
                 f'<span>{esc(t("dash.o2_asked", lang, o2=_g(s["asked"])))}</span></div>')

    step = 10 if top <= 50 else 20
    ticks = "".join(f'<span class="ff-tick" style="left:{pct(v):.2f}%">{v}</span>' for v in range(0, int(top) + 1, step))
    refs = []
    for ref in s["refs"]:
        if ref["off_scale"]:
            notes.append(t("dash.o2_off", lang, label=ref["label"], o2=_g(ref["o2"])) + ".")
        else:
            refs.append(f'<span class="ff-ref" style="left:{pct(ref["o2"]):.2f}%">{esc(ref["label"])} {_g(ref["o2"])} %</span>')

    title = t("dash.o2_title", lang, max=_g(top)) + (f' · {term(s["fuel"], lang)}' if s["fuel"] else "")
    return (
        f'<div class="ff-card"><h4>{esc(title)}</h4><div class="ff-o2"><div class="ff-o2-track">{"".join(zones)}</div>'
        f'{asked}{ticks}{"".join(refs)}</div><div class="ff-sub">{esc(" ".join(notes))}</div></div>'
    )


def actions_html(view: dict) -> str:
    lang = view["lang"]
    if view["state"] == "out_of_scope" or not view["verdict"]["k"]:
        return ""
    if view.get("nodata") and not view["actions"]:
        return ""
    if not view["actions"]:
        return (f'<div class="ff-card"><h4>{esc(t("res.actions", lang))}</h4>'
                f'<div class="ff-sub">{esc(t("res.no_actions", lang))}</div></div>')
    cards = []
    for a in view["actions"]:
        pills = "".join(pill(p["label"], p["url"], t("dash.open_source", lang)) for p in a["pills"])
        cards.append(f'<div class="ff-card"><div class="ff-act-h"><b>{esc(a["title"])}</b>{pills}</div>'
                     f'<div class="ff-act-body" title="{esc(a["body"])}">{esc(a["body"])}</div></div>')
    return f'<div class="ff-actions">{"".join(cards)}</div>'


def dashboard_html(view: dict, include_strip: bool = True) -> str:
    """The whole stage-3 dashboard as one HTML string (single line, safe for st.markdown / st.html).

    ``include_strip=False`` leaves the top strip out, for when the app draws it next to "New question".
    """
    color = kind_color(view)
    cells = [c for c in (verdict_html(view), ring_html(view), diluent_html(view)) if c]
    row_class = {1: " ff-one", 2: " ff-two"}.get(len(cells), "")
    if len(cells) == 2 and "ff-ring" not in cells[1]:  # verdict + diluent, no ring
        row_class = " ff-two"
    body = [
        strip_html(view) if include_strip else "",
        f'<div class="ff-d-row{row_class}">{"".join(cells)}</div>',
        oxygen_html(view),
        actions_html(view),
    ]
    style = f"--ff-k:{color};--ff-k-soft:{hex_to_rgba(color, 0.16)}"
    return f'<div class="ff-d" style="{style}">{"".join(b for b in body if b)}</div>'
