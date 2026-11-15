"""Presentation helpers for the AI panel (v7): safe citation links and the chart drawn from the ledger.

Gemini's text is untrusted: brackets, HTML and LaTeX markers are neutralised before our own links are added,
so the model cannot inject links. Charts use only rows the engine returned (ledger tables), never values
written by the model.
"""

from __future__ import annotations

import re

import altair as alt
import pandas as pd

from . import config
from .viz_payload import first_url

_ID = re.compile(r"\b([RE])(\d+)\b")
NUMERIC = {"oxigeno", "presion", "metric_value"}
BOOLEAN = {"extinguished", "flame_recorded", "did_not_ignite"}


def row_urls(df: pd.DataFrame, ids) -> dict[str, str]:
    """R# -> first source link of that row (DOI or PSI page)."""
    wanted = {str(i).upper() for i in ids}
    sub = df[df["row_id"].str.upper().isin(wanted)]
    return {str(r.row_id).upper(): first_url(str(r.fuente)) for r in sub.itertuples()}


def cited_ids(answer) -> list[str]:
    ids: list[str] = []
    texts = [answer.summary, getattr(answer, "conclusion", ""), getattr(answer, "recommendation", ""),
             answer.limitations, answer.missing] + [c.text for c in answer.claims]
    texts += [f.finding for f in getattr(answer, "agents", [])]
    for c in answer.claims:
        ids += [str(r).strip().upper() for r in c.row_ids]
    for t in texts:
        ids += [f"R{n}" for k, n in _ID.findall(str(t)) if k == "R"]
    return list(dict.fromkeys(ids))


def safe_text(text: str) -> str:
    """Model text -> markdown that cannot carry links, HTML or LaTeX."""
    text = str(text)
    text = re.sub(r"[\[\]]", "", text)  # no markdown links from the model
    text = text.replace("<", "‹").replace(">", "›").replace("$", "\\$")
    text = re.sub(r"([*_`#|~])", r"\\\1", text)
    return text


def linkify(text: str, urls: dict[str, str]) -> str:
    """Safe text with every R# turned into a link to its source and every E# in bold."""
    text = safe_text(text)

    def repl(m: re.Match) -> str:
        rid = f"{m.group(1)}{m.group(2)}"
        if m.group(1) == "R":
            url = urls.get(rid.upper())
            return f"[{rid}]({url})" if url else f"**{rid}**"
        return f"**{rid}**"

    return _ID.sub(repl, text)


def chart_frame(spec, ledger) -> pd.DataFrame:
    fact = ledger.facts.get(spec.evidence_id) or {}
    return pd.DataFrame(fact.get("table") or [])


def _enc_type(field: str) -> str:
    return "quantitative" if field in NUMERIC else "nominal"


def build_chart(spec, ledger, titles: dict[str, str] | None = None) -> alt.Chart | None:
    """Altair chart for a verified ChartSpec, from the engine rows of its E# table. None if it cannot be drawn."""
    data = chart_frame(spec, ledger)
    fields = [f for f in (spec.x, spec.y, spec.color) if f]
    if data.empty or any(f not in data.columns for f in fields):
        return None
    titles = titles or {}
    for b in BOOLEAN & set(data.columns):
        data[b] = data[b].astype(int)
    tooltip = [c for c in ("row_id", "experimento", "combustible", "oxigeno", "presion", "metric_value") if c in data.columns]
    color = alt.value(config.TELEMETRY_COLOR)
    if spec.color:
        if spec.color in BOOLEAN:  # readable legend for flags instead of 0 / 1
            data["_color"] = data[spec.color].map({1: "\u2713", 0: "\u2717"})
            color = alt.Color("_color:N", title=titles.get(spec.color, spec.color),
                              scale=alt.Scale(domain=["\u2713", "\u2717"], range=[config.TELEMETRY_COLOR, "#e8693a"]))
        else:
            color = alt.Color(f"{spec.color}:N", title=titles.get(spec.color, spec.color))
    x, y = spec.x, spec.y
    if spec.type == "bar":
        # One bar per category; booleans are counted (rows with flag = 1), numbers averaged.
        if x in NUMERIC and y not in NUMERIC and y not in BOOLEAN:
            x, y = y, x
        if y in BOOLEAN:  # share of the category's rows with the flag, as the engine reports it (e.g. 79.2 %)
            y_enc = alt.Y(f"mean({y}):Q", title="% " + titles.get(y, y), axis=alt.Axis(format="%"),
                          scale=alt.Scale(domain=[0, 1]))
        elif y in NUMERIC:
            y_enc = alt.Y(f"mean({y}):Q", title=titles.get(y, y))
        else:
            y_enc = alt.Y("count():Q", title="n")
        chart = alt.Chart(data).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X(f"{x}:N", title=titles.get(x, x), sort="-y"), y=y_enc, color=color,
            tooltip=[alt.Tooltip(f"{x}:N"), alt.Tooltip("count():Q", title="n")])
    elif spec.type == "strip":
        q, n = (x, y) if x in NUMERIC else (y, x)
        chart = alt.Chart(data).mark_tick(thickness=2, size=18).encode(
            x=alt.X(f"{q}:Q", title=titles.get(q, q), scale=alt.Scale(zero=False, padding=12)), y=alt.Y(f"{n}:N", title=titles.get(n, n)),
            color=color, tooltip=tooltip)
    else:  # scatter
        chart = alt.Chart(data).mark_circle(size=70, opacity=0.8).encode(
            x=alt.X(f"{x}:{_enc_type(x)[0].upper()}", title=titles.get(x, x)),
            y=alt.Y(f"{y}:{_enc_type(y)[0].upper()}", title=titles.get(y, y)),
            color=color, tooltip=tooltip)
    return chart.properties(height=300, title=str(spec.title)[:90])
