"""Stage-2 animations for the Assistant tab.

``build_mission_html(payload)``  the mission-control animation: one self-contained HTML document (inline
    CSS, JavaScript and SVG; no external files, fonts or CDNs) driven by the JSON payload from
    ``flame.viz_payload.build_animation_payload``. See the notes above ``_MISSION_TEMPLATE``.
``build_animation_html(...)``    the earlier CSS-only "question falls into its bin" card. The app falls
    back to it if the payload cannot be built, so the animation never blocks an answer.

Both are meant for ``streamlit.components.v1.html`` / ``st.iframe``.

Legacy card. ``build_animation_html`` returns one self-contained HTML document (CSS keyframes only,
no JavaScript, no external files). Everything that comes from the user or
from the classifier is escaped with ``html.escape``. Timeline (seconds):

    0.0 - 0.6   the question card appears and a light sweeps over it
    0.6 - 1.65  the card falls and shrinks towards its bin
    1.5 - 2.0   the bin lights up in its phase colour (or all bins dim for the other two states)
    1.85        the verdict replaces the "Classifying..." line; confidence and subject fade in

Three end states: a phase (one bin lights up), ``out_of_scope`` (bins dim, grey "out of scope" stamp)
and ``unclear`` (fire-related question without prevent / detect / extinguish wording).
Users who prefer reduced motion get the final state at once.
"""

from __future__ import annotations

import html
import json
import re
from string import Template

from . import config
from .i18n import normalize_lang, phase_name, t

HEIGHT = 420  # iframe height in px (pass the same value to components.html)
PANEL_HEIGHT = HEIGHT - 8
ICONS = {"prevent": "🛡️", "detect": "🔎", "extinguish": "🧯"}
NEUTRAL_COLORS = {"out_of_scope": "#9a9fb2", "unclear": "#aab4d6"}
MAX_QUESTION_CHARS = 140

# Bins sit in a grid with 3 % side margins and a 2 % gap, so their centres (as % of the panel width) are:
_BIN_CENTERS = tuple(round(3 + 94 * (16 + 34 * i) / 100, 2) for i in range(3))  # 18.04, 50.0, 81.96

_LAND_Y_BIN = 222  # px from the top of the panel where the card lands inside a bin
_LAND_Y_FLAT = 104  # px where it stops for the out-of-scope / unclear states (the stamp replaces it)


def hex_to_rgba(color: str, alpha: float) -> str:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def animation_state(phase: str | None) -> str:
    """"prevent" / "detect" / "extinguish" / "out_of_scope" / "unclear"."""
    if phase in config.PHASES:
        return str(phase)
    return "out_of_scope" if phase == "out_of_scope" else "unclear"


def _short(question: str) -> str:
    text = re.sub(r"\s+", " ", str(question)).strip()
    return text if len(text) <= MAX_QUESTION_CHARS else text[: MAX_QUESTION_CHARS - 1].rstrip() + "…"


_CSS = Template("""
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;background:transparent;color:#e6e6e6;overflow:hidden;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
.panel{position:relative;height:${panel_h}px;max-width:760px;margin:4px auto 0 auto;border-radius:24px;
  border:1px solid #2a2f3d;background:linear-gradient(180deg,rgba(28,32,56,.9),rgba(11,13,26,.94));
  overflow:hidden;--c:${c};--c-soft:${c_soft};--c-glow:${c_glow}}
.status,.verdict{position:absolute;top:16px;left:12px;right:12px;text-align:center;font-size:.8rem;
  letter-spacing:.14em;text-transform:uppercase}
.status{color:#9aa3b8;animation:fadeOut .35s ease 1.45s forwards}
.verdict{color:var(--c);font-weight:700;opacity:0;animation:fadeIn .45s ease 1.85s forwards}
.card{position:absolute;top:54px;left:50%;width:min(80%,520px);padding:12px 18px;border-radius:16px;
  background:#2a2c33;border:1px solid #444a5c;font-size:1rem;line-height:1.35;text-align:center;color:#f1f1f1;
  overflow:hidden;z-index:5;transform:translateX(-50%);transform-origin:50% 0;box-shadow:0 8px 24px rgba(0,0,0,.45);
  animation:cardOpacity 1.9s linear both,cardY 1.05s cubic-bezier(.55,0,.85,.4) .6s both,
            cardX 1.05s cubic-bezier(.4,0,.4,1) .6s both,${tilt_anim} both}
.q{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;word-break:break-word}
.card::after{content:"";position:absolute;inset:0;transform:translateX(-120%);
  background:linear-gradient(100deg,transparent 30%,rgba(255,255,255,.2) 50%,transparent 70%);
  animation:sweep .7s ease .3s 1 forwards}
.bins{position:absolute;left:3%;right:3%;bottom:70px;height:118px;display:grid;
  grid-template-columns:repeat(3,1fr);gap:2%}
.bin{position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;
  padding:10px 6px;text-align:center;color:#8d96ad;border:2px solid #343a4d;border-top-width:3px;
  border-radius:6px 6px 22px 22px;background:linear-gradient(180deg,rgba(255,255,255,.02),rgba(255,255,255,.06))}
.ico{font-size:1.8rem;line-height:1;filter:grayscale(.5)}
.lbl{font-weight:700;letter-spacing:.1em;font-size:clamp(.62rem,2.3vw,.9rem)}
.bin.lit{animation:lightUp .55s ease 1.55s forwards}
.bin.lit .ico{animation:unGray .5s ease 1.55s forwards}
.bin.lit .lbl{animation:lblOn .5s ease 1.55s forwards}
.bin.lit::after{content:"";position:absolute;left:50%;top:0;width:70%;aspect-ratio:1/1;border-radius:50%;
  border:2px solid var(--c);opacity:0;transform:translate(-50%,-50%) scale(.2);animation:ripple .75s ease-out 1.5s 1 forwards}
.bin.dim{animation:dim .5s ease 1.55s forwards}
.stamp{position:absolute;left:50%;top:88px;z-index:6;width:max-content;max-width:88%;padding:8px 20px;
  text-align:center;opacity:0;border:3px dashed var(--c);border-radius:12px;color:var(--c);
  background:rgba(10,12,24,.86);font-weight:800;letter-spacing:.12em;font-size:clamp(.95rem,2.8vw,1.3rem);
  transform:translate(-50%,0) rotate(-5deg) scale(1.6);animation:slam .35s cubic-bezier(.2,1.4,.4,1) 1.6s forwards}
.stamp small{display:block;max-width:26em;margin:4px auto 0 auto;font-size:.6em;font-weight:500;letter-spacing:.03em;color:#c3c2b7}
.meta{position:absolute;left:4%;right:4%;bottom:40px;display:flex;justify-content:center;align-items:center;gap:10px;
  min-width:0;font-size:.85rem;color:#c3c2b7;opacity:0;animation:fadeIn .45s ease 2.05s forwards}
.pill{flex:none;padding:2px 11px;border-radius:999px;border:1px solid var(--c);color:var(--c);
  background:var(--c-soft);font-weight:600}
.subject{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hint{position:absolute;left:0;right:0;bottom:13px;text-align:center;font-size:.78rem;color:#7e879c;
  animation:pulse 1.4s ease-in-out infinite}
@keyframes fadeIn{to{opacity:1}}
@keyframes fadeOut{to{opacity:0}}
@keyframes pulse{0%,100%{opacity:.45}50%{opacity:1}}
@keyframes sweep{to{transform:translateX(120%)}}
@keyframes cardOpacity{0%{opacity:0}18%{opacity:1}88%{opacity:1}100%{opacity:0}}
@keyframes cardY{from{top:54px}to{top:${land_y}px}}
@keyframes cardX{from{left:50%}to{left:${tx}}}
@keyframes cardTilt{0%{transform:translateX(-50%) rotate(0) scale(1)}30%{transform:translateX(-50%) rotate(-5deg) scale(.8)}
  60%{transform:translateX(-50%) rotate(4deg) scale(.56)}85%{transform:translateX(-50%) rotate(-2deg) scale(.42)}
  100%{transform:translateX(-50%) rotate(0) scale(.38)}}
@keyframes cardTiltFlat{0%{transform:translateX(-50%) rotate(0) scale(1)}35%{transform:translateX(-50%) rotate(-3deg) scale(.96)}
  55%{transform:translateX(-50%) rotate(3deg) scale(.94)}75%{transform:translateX(-50%) rotate(-2deg) scale(.92)}
  100%{transform:translateX(-50%) rotate(0) scale(.9)}}
@keyframes lightUp{to{border-color:var(--c);background:var(--c-soft);box-shadow:0 0 28px var(--c-glow),inset 0 0 18px var(--c-soft)}}
@keyframes unGray{to{filter:none}}
@keyframes lblOn{to{color:var(--c)}}
@keyframes ripple{0%{opacity:.9;transform:translate(-50%,-50%) scale(.2)}100%{opacity:0;transform:translate(-50%,-50%) scale(1.5)}}
@keyframes dim{to{opacity:.32}}
@keyframes slam{to{opacity:1;transform:translate(-50%,0) rotate(-5deg) scale(1)}}
@media (prefers-reduced-motion:reduce){*{animation-duration:.001s !important;animation-delay:0s !important}}
""")


def build_animation_html(
    question: str,
    phase: str | None,
    confidence: float | None,
    subject: str,
    lang: str = "en",
    colors: dict[str, str] | None = None,
) -> str:
    """HTML document for the falling-question animation.

    ``phase``      classifier phase: prevent / detect / extinguish / out_of_scope / None
    ``confidence`` classifier confidence (0-1) or None
    ``subject``    one-line subject text, already in ``lang`` (``Subject.summary(lang)``)
    """
    lang = normalize_lang(lang)
    colors = colors or config.PHASE_COLORS
    state = animation_state(phase)
    is_bin = state in config.PHASES
    color = colors[state] if is_bin else NEUTRAL_COLORS[state]

    if is_bin:
        target = config.PHASES.index(state)
        tx, land_y = f"{_BIN_CENTERS[target]}%", _LAND_Y_BIN
        tilt_anim = "cardTilt 1.05s ease-in-out .6s"
    else:
        tx, land_y = "50%", _LAND_Y_FLAT
        tilt_anim = "cardTiltFlat 1.05s ease-in-out .6s"

    css = _CSS.substitute(
        panel_h=PANEL_HEIGHT, c=color, c_soft=hex_to_rgba(color, 0.16), c_glow=hex_to_rgba(color, 0.5),
        tx=tx, land_y=land_y, tilt_anim=tilt_anim,
    )

    esc = html.escape
    bins = []
    for i, p in enumerate(config.PHASES):
        cls = "bin" + (" lit" if is_bin and p == state else " dim" if not is_bin else "")
        bins.append(
            f'<div class="{cls}"><div class="ico">{ICONS[p]}</div>'
            f'<div class="lbl">{esc(phase_name(p, lang).upper())}</div></div>'
        )

    if is_bin:
        verdict = t("anim.verdict", lang, phase=phase_name(state, lang).upper())
        stamp = ""
    elif state == "out_of_scope":
        verdict = t("anim.out_of_scope", lang)
        stamp = f'<div class="stamp">✕ {esc(verdict)}<small>{esc(t("anim.out_of_scope_hint", lang))}</small></div>'
    else:
        verdict = t("anim.unclear", lang)
        stamp = f'<div class="stamp">? {esc(verdict)}<small>{esc(t("anim.unclear_hint", lang))}</small></div>'

    meta = []
    # ``confidence`` is accepted for compatibility but never shown (the classifier's certainty is internal)
    subject_text = t("anim.subject", lang, subject=subject)
    meta.append(f'<span class="subject" title="{esc(subject_text, quote=True)}">{esc(subject_text)}</span>')

    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="color-scheme" content="dark">'
        f"<style>{css}</style></head><body>"
        f'<div class="panel state-{state}" role="img" aria-label="{esc(verdict, quote=True)}">'
        f'<div class="status">{esc(t("anim.classifying", lang))}</div>'
        f'<div class="verdict">{esc(verdict)}</div>'
        f'<div class="card"><div class="q">{esc(_short(question))}</div></div>'
        f'<div class="bins">{"".join(bins)}</div>'
        f"{stamp}"
        f'<div class="meta">{"".join(meta)}</div>'
        f'<div class="hint">{esc(t("spinner.searching", lang))}</div>'
        "</div></body></html>"
    )


# ---------------------------------------------------------------------------
# Mission-control animation (stage 2)
# ---------------------------------------------------------------------------
# One HTML document, no external resources. The payload is embedded as JSON in a <script type=
# "application/json"> block and every piece of text reaches the page through textContent, so nothing typed
# by the user is ever parsed as markup.
#
# Timeline (seconds; "scatter" mode):
#   0.0  the question appears; the words the engine read light up with their label (phase, fuel, O2, agent)
#   1.5  those words drop into the PREVENT / DETECT / EXTINGUISH bin; 2.35 the bin lights, confidence shows
#   3.3  the table appears as a cloud (x = O2 %, y = pressure atm, colour = phase) and the counter shows all rows
#   4.5  the cloud narrows to the rows that share fuel / experiment with the question
#   5.5  it narrows again to the top-k rows the engine retrieved (rings)
#   6.2  the question lands as a glowing point at its O2 (on the "no pressure" strip if none was stated)
#   7.0  the rings take the colour of their outcome and the counter runs up to N / K
#   8.0  "View results" appears. Python moves on by itself after config.ANIMATION_SECONDS.
# Other modes: "bars" (top rows without numeric O2, typical for detect) replaces the cloud with the table
# split by phase and bars of what matched; "empty" shows the cloud and that no row qualified; "scope"
# (out of scope) stops after the bins with a stamp.
# "View results" clicks the Streamlit button with key ``button_key`` in the parent page; when the page
# cannot be reached the control turns into a pointer to that button, which sits right below the animation.
# Reduced motion: the final state is shown at once.

MISSION_HEIGHT = 660  # iframe height in px

_MISSION_CSS = r"""
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;background:transparent;overflow:hidden;color:#e8ecf4;-webkit-font-smoothing:antialiased;
  font-family:"Inter","Segoe UI",system-ui,-apple-system,Roboto,"Helvetica Neue",Arial,sans-serif}
:root{--cy:#4fd1e8;--ac:#d95926;--gold:#ffd27a;--ink:#e8ecf4;--mut:#8b93a7;--line:rgba(79,209,232,.24);
  --ph:#4fd1e8;--ph-soft:rgba(79,209,232,.14);--ph-glow:rgba(79,209,232,.45);
  --mono:ui-monospace,"SF Mono","Cascadia Mono","JetBrains Mono",Menlo,Consolas,"DejaVu Sans Mono",monospace}
.console{position:relative;height:calc(100% - 6px);margin:3px;border:1px solid var(--line);border-radius:10px;
  background:linear-gradient(180deg,rgba(10,16,32,.88),rgba(5,8,18,.94));overflow:hidden;display:flex;flex-direction:column}
.console::before{content:"";position:absolute;inset:0;pointer-events:none;opacity:.55;
  background-image:linear-gradient(rgba(79,209,232,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(79,209,232,.05) 1px,transparent 1px);
  background-size:36px 36px}
.corner{position:absolute;width:16px;height:16px;border:2px solid var(--cy);pointer-events:none;z-index:3}
.corner.tl{top:-1px;left:-1px;border-right:0;border-bottom:0;border-radius:10px 0 0 0}
.corner.tr{top:-1px;right:-1px;border-left:0;border-bottom:0;border-radius:0 10px 0 0}
.corner.bl{bottom:-1px;left:-1px;border-right:0;border-top:0;border-radius:0 0 0 10px}
.corner.br{bottom:-1px;right:-1px;border-left:0;border-top:0;border-radius:0 0 10px 0}
.mono{font-family:var(--mono);font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--mut)}
.hud{position:relative;flex:none;height:40px;display:flex;align-items:center;gap:18px;padding:0 18px;border-bottom:1px solid var(--line)}
.steps{display:flex;gap:6px;list-style:none;flex:1;justify-content:center;min-width:0}
.steps li{display:flex;align-items:center;gap:6px;white-space:nowrap;transition:color .3s}
.steps li + li::before{content:"";width:22px;height:1px;background:rgba(255,255,255,.18);margin-right:6px}
.steps li.cur{color:var(--cy)} .steps li.done{color:var(--ink)}
.steps b{font-weight:600}
.clock{color:var(--cy);min-width:74px;text-align:right;font-variant-numeric:tabular-nums}
.ctl{font:inherit;font-family:var(--mono);font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--mut);
  background:transparent;border:1px solid rgba(255,255,255,.16);border-radius:4px;padding:4px 9px;cursor:pointer}
.ctl:hover{color:var(--ink);border-color:var(--cy)} .ctl:focus-visible,.cta:focus-visible{outline:2px solid var(--cy);outline-offset:2px}
.stage{position:relative;flex:1;min-height:0}
.scene{position:absolute;inset:0;opacity:0;pointer-events:none;transition:opacity .5s ease}
.scene.on{opacity:1;pointer-events:auto}
/* scene A: classify */
.A{display:flex;flex-direction:column;align-items:center;padding:18px 24px 14px}
.status{margin-bottom:8px;transition:color .3s} .status.done{color:var(--ph);font-weight:700}
.qwrap{flex:1;min-height:0;display:flex;align-items:center;justify-content:center;width:100%;padding-bottom:18px}
.qbig{max-width:1080px;text-align:center;font-size:clamp(18px,2.35vw,28px);line-height:2.25;max-height:100%;overflow:hidden}
.seg.k{position:relative;display:inline-block;line-height:1.35;padding:1px 10px;margin:0 1px;border:1px solid transparent;border-radius:7px;
  transition:border-color .35s,background .35s,box-shadow .35s,color .35s}
.seg.k::before{content:attr(data-label);position:absolute;left:50%;top:-16px;transform:translateX(-50%);white-space:nowrap;
  font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--cy);opacity:0;transition:opacity .35s}
.seg.k.lit{border-color:var(--cy);background:rgba(79,209,232,.1);box-shadow:0 0 16px rgba(79,209,232,.22);color:#fff}
.seg.k.lit::before{opacity:1}
.seg.k-phase.lit{border-color:var(--ph);background:var(--ph-soft);box-shadow:0 0 16px var(--ph-glow)}
.seg.k-phase::before{color:var(--ph)}
.console .ghost{position:absolute;margin:0;z-index:5;pointer-events:none;font-size:clamp(18px,2.35vw,28px);text-align:center}
.bins{flex:none;display:grid;grid-template-columns:repeat(3,1fr);gap:16px;width:min(96%,1020px)}
.bin{position:relative;height:124px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;
  border:1px solid rgba(255,255,255,.13);border-top:2px solid rgba(255,255,255,.22);border-radius:4px 4px 12px 12px;
  background:rgba(255,255,255,.025);color:#6f7890;transition:border-color .45s,box-shadow .45s,background .45s,color .45s,opacity .45s}
.bin svg{width:40px;height:40px;stroke:currentColor;fill:none;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
.bin span{font-family:var(--mono);font-size:13px;font-weight:700;letter-spacing:.2em}
.bin.lit{color:var(--ph);border-color:var(--ph);background:var(--ph-soft);box-shadow:0 0 34px var(--ph-glow),inset 0 0 22px var(--ph-soft)}
.bin.lit::after{content:"";position:absolute;left:50%;top:0;width:60%;aspect-ratio:1/1;border-radius:50%;border:2px solid var(--ph);
  opacity:0;transform:translate(-50%,-50%) scale(.2);animation:ripple .8s ease-out 1 forwards}
.bin.dim{opacity:.3}
.conf{flex:none;height:26px;margin-top:10px;font-size:15px;color:var(--mut);opacity:0;transition:opacity .4s}
.conf.on{opacity:1} .conf b{color:var(--ink)} .conf::first-letter{text-transform:uppercase}
.stamp{position:absolute;left:50%;bottom:92px;z-index:6;max-width:88%;padding:10px 24px;text-align:center;opacity:0;
  border:2px dashed var(--ph);border-radius:8px;color:var(--ph);background:rgba(6,9,20,.92);font-family:var(--mono);font-weight:700;
  letter-spacing:.16em;font-size:clamp(15px,2vw,22px);transform:translate(-50%,0) rotate(-4deg) scale(1.5)}
.stamp.on{opacity:1;transform:translate(-50%,0) rotate(-4deg) scale(1);transition:opacity .25s,transform .35s cubic-bezier(.2,1.4,.4,1)}
.stamp small{display:block;margin-top:6px;font-family:inherit;font-weight:400;letter-spacing:.02em;font-size:13px;color:#c3c8d6;
  font-family:"Inter","Segoe UI",system-ui,sans-serif;text-transform:none}
/* scene B: locate, narrow, count */
.B{display:flex;flex-direction:column;padding:10px 16px 6px}
.readouts{flex:none;display:flex;flex-wrap:wrap;gap:6px;min-height:26px}
.ro{display:flex;align-items:baseline;gap:7px;padding:3px 9px;border:1px solid var(--line);border-radius:4px;background:rgba(79,209,232,.05)}
.ro b{font-family:"Inter","Segoe UI",system-ui,sans-serif;font-size:13px;font-weight:600;letter-spacing:0;text-transform:none;color:var(--ink)}
.ro.k-phase{border-color:var(--ph);background:var(--ph-soft)}
.funnel{flex:none;display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:9px 0 8px;min-height:36px}
.fp{opacity:0;transform:translateY(5px);transition:opacity .35s,transform .35s,border-color .35s,color .35s,box-shadow .35s;
  border:1px solid rgba(255,255,255,.16);border-radius:999px;padding:6px 15px;font-size:15px;color:var(--mut);white-space:nowrap}
.fp.on{opacity:1;transform:none}
.fp.cur{border-color:var(--ac);color:var(--ink);box-shadow:0 0 16px rgba(217,89,38,.35)}
.fp .n{font-family:var(--mono);font-weight:700;font-variant-numeric:tabular-nums;color:var(--ink)}
.arrow{color:var(--mut);opacity:0;transition:opacity .35s} .arrow.on{opacity:1}
.rel{margin-left:4px;opacity:0;transition:opacity .35s} .rel.on{opacity:1}
.main{flex:1;min-height:0;display:flex;gap:16px}
.chart{position:relative;flex:1;min-width:0;border:1px solid rgba(255,255,255,.09);border-radius:8px;background:rgba(3,6,14,.6);overflow:hidden}
.chart svg{display:block;width:100%;height:100%}
.chart text{font-family:"Inter","Segoe UI",system-ui,sans-serif;fill:var(--mut);font-size:12px}
.chart .cloud g{transition:opacity .6s ease}
.ring{fill:rgba(79,209,232,.08);stroke:var(--cy);stroke-width:2;opacity:0;transform-box:fill-box;transform-origin:center;transform:scale(.2);
  transition:opacity .3s,transform .35s cubic-bezier(.2,1.5,.4,1),fill .3s,stroke .3s;cursor:default}
.ring.on{opacity:1;transform:scale(1)} .ring.flip{animation:pop .4s ease 1}
.halo{fill:none;stroke:#04070f;stroke-width:5;opacity:0;transition:opacity .3s} .halo.on{opacity:1}
.qline{stroke:var(--gold);stroke-width:1.5;stroke-dasharray:5 4;opacity:.75}
.qdot{fill:var(--gold);stroke:#04070f;stroke-width:2;filter:drop-shadow(0 0 7px var(--gold))}
.qdot.est{fill:none;stroke:var(--gold);stroke-width:2;stroke-dasharray:3 2.5;filter:drop-shadow(0 0 5px var(--gold))}
.qpulse.est{stroke-dasharray:3 3}
.qlabel.est{font-style:italic}
.sw.qest{background:transparent!important;border:2px dashed var(--gold)}
.qpulse{fill:none;stroke:var(--gold);stroke-width:1.5;transform-box:fill-box;transform-origin:center;animation:pulse 1.8s ease-out infinite}
.chart text.qlabel{fill:var(--gold);font-weight:600;font-size:13px;paint-order:stroke;stroke:#04070f;stroke-width:4px;stroke-linejoin:round}
.chart text.striplab{font-size:11px;paint-order:stroke;stroke:#04070f;stroke-width:4px;stroke-linejoin:round}
.scan{stroke:var(--cy);stroke-width:1.5;filter:drop-shadow(0 0 6px var(--cy))}
.side{flex:none;width:256px;display:flex;flex-direction:column;justify-content:center;gap:12px;opacity:0;transition:opacity .45s}
.side.on{opacity:1}
.count{font-size:88px;line-height:.9;font-weight:300;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.count small{font-size:36px;color:var(--mut);font-weight:400;letter-spacing:0}
.vtext{font-size:16px;line-height:1.35}
.dots{display:flex;flex-wrap:wrap;gap:7px}
.dots i{width:16px;height:16px;border-radius:50%;border:2px solid var(--cy);background:transparent;transition:background .3s,border-color .3s}
.klist{display:flex;flex-direction:column;gap:5px;font-size:13.5px;color:#c3c8d6;opacity:0;transition:opacity .45s}
.klist.on{opacity:1}
.klist div{display:flex;align-items:center;gap:8px}
.sw{flex:none;width:10px;height:10px;border-radius:50%}
.legend{flex:none;display:flex;flex-wrap:wrap;gap:4px 18px;align-items:center;min-height:22px;margin-top:6px;font-size:12.5px;color:var(--mut);
  opacity:0;transition:opacity .45s}
.legend.on{opacity:1} .legend span{display:flex;align-items:center;gap:6px}
.sw.ringsw{background:transparent;border:2px solid var(--cy)}
.note{font-size:13px;line-height:1.4;color:var(--mut)}
.msg{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);max-width:70%;text-align:center;font-size:17px;line-height:1.4;
  padding:14px 20px;border:1px solid var(--line);border-radius:8px;background:rgba(6,9,20,.92);opacity:0;transition:opacity .4s}
.msg.on{opacity:1}
/* bars mode */
.bars{flex:1;min-width:0;display:flex;flex-direction:column;justify-content:center;gap:13px;padding:14px 22px;border:1px solid rgba(255,255,255,.09);border-radius:8px;
  background:rgba(3,6,14,.6);overflow:hidden}
.bt{margin-top:10px}
.pstrip{display:flex;gap:2px;height:26px}
.pseg{min-width:3px;border-radius:3px;opacity:.85;transition:opacity .5s,box-shadow .5s}
.pstrip.narrow .pseg{opacity:.2} .pstrip.narrow .pseg.sel{opacity:1;box-shadow:0 0 14px var(--ph-glow)}
.plab{display:flex;flex-wrap:wrap;gap:4px 18px;font-size:13px;color:#c3c8d6}
.plab span{display:flex;align-items:center;gap:6px} .plab b{font-family:var(--mono);font-weight:600;color:var(--ink)}
.brow{display:grid;grid-template-columns:minmax(120px,250px) 1fr 62px;gap:14px;align-items:center;font-size:15px}
.track{height:16px;border-radius:4px;background:rgba(255,255,255,.07);overflow:hidden}
.fill{height:100%;width:0;border-radius:0 4px 4px 0;background:var(--cy);transition:width .7s cubic-bezier(.2,.8,.2,1)}
.bval{font-family:var(--mono);font-size:13px;color:var(--ink);text-align:right;font-variant-numeric:tabular-nums}
/* footer */
.foot{position:relative;flex:none;height:54px;display:flex;align-items:center;gap:16px;padding:0 18px;border-top:1px solid var(--line)}
.grow{flex:1}
.auto{opacity:0;transition:opacity .4s;text-transform:none;letter-spacing:.04em} .auto.on{opacity:1}
.cta{font:600 15px "Inter","Segoe UI",system-ui,sans-serif;color:#fff;background:var(--ac);border:1px solid #f08a5d;border-radius:6px;
  padding:9px 20px;cursor:pointer;opacity:0;pointer-events:none;transform:translateY(4px);transition:opacity .4s,transform .4s,background .2s;
  box-shadow:0 0 20px rgba(217,89,38,.5)}
.cta.on{opacity:1;pointer-events:auto;transform:none} .cta:hover{background:#ea6a36}
.cta.hint{background:transparent;border-color:var(--line);color:var(--ink);box-shadow:none;cursor:default}
.autobar{position:absolute;left:0;top:-1px;height:2px;width:0;background:var(--ac);box-shadow:0 0 8px var(--ac)}
.tip{position:absolute;z-index:8;pointer-events:none;display:none;max-width:260px;padding:8px 11px;border:1px solid var(--line);border-radius:6px;
  background:rgba(6,9,20,.96);font-size:12.5px;line-height:1.45;color:#c3c8d6;box-shadow:0 6px 20px rgba(0,0,0,.5)}
.tip b{display:block;color:var(--ink)}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@keyframes ripple{0%{opacity:.9;transform:translate(-50%,-50%) scale(.2)}100%{opacity:0;transform:translate(-50%,-50%) scale(1.5)}}
@keyframes pop{0%{transform:scale(1)}45%{transform:scale(1.45)}100%{transform:scale(1)}}
@keyframes pulse{0%{transform:scale(1);opacity:.9}100%{transform:scale(3.2);opacity:0}}
.no-anim *,.no-anim *::before,.no-anim *::after{transition:none !important;animation:none !important}
@media (max-width:820px){.side{width:190px}.count{font-size:64px}.steps li + li::before{width:8px}.hud .hide-s{display:none}}
@media (max-width:520px){.steps li:not(.cur){display:none}.steps li + li::before{display:none}.clock{min-width:0;font-size:11px}}
@media (max-width:620px){.main{flex-direction:column}.side{width:auto;flex-direction:row;flex-wrap:wrap;align-items:center}.count{font-size:44px}.klist{display:none}}
"""

_MISSION_JS = r"""
(function(){
'use strict';
var P = JSON.parse(document.getElementById('payload').textContent);
var L = P.labels, C = P.colors, root = document.getElementById('console');
var NS = 'http://www.w3.org/2000/svg';
var reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
var PHASE_KEYS = P.phases.map(function(p){ return p.key; });
var pageT0 = Date.now(), instant = false, timers = [], rafs = [], R = {}, clockTimer = null, playT0 = 0, finished = false;

function el(tag, cls, text){ var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
function sv(tag, attrs){ var e = document.createElementNS(NS, tag); for (var k in attrs) e.setAttribute(k, attrs[k]); return e; }
function fmt(n){ try { return Math.round(n).toLocaleString(P.lang); } catch (e) { return String(Math.round(n)); } }
function num(v){ return (Math.round(v * 1000) / 1000).toString(); }
function later(ms, fn){ timers.push(setTimeout(fn, ms)); }
function ease(k){ return 1 - Math.pow(1 - k, 3); }
function tween(ms, fn, done){
  if (instant || ms <= 0){ fn(1); if (done) done(); return; }
  var t0 = performance.now();
  function frame(now){ var k = Math.max(0, Math.min(1, (now - t0) / ms)); fn(ease(k)); if (k < 1) rafs.push(requestAnimationFrame(frame)); else if (done) done(); }
  rafs.push(requestAnimationFrame(frame));
}
function clearAll(){ timers.forEach(clearTimeout); rafs.forEach(cancelAnimationFrame); timers = []; rafs = []; if (clockTimer){ clearInterval(clockTimer); clockTimer = null; } }
function stagger(n, gap, fn){ for (var i = 0; i < n; i++){ (function(i){ if (instant) fn(i); else later(i * gap, function(){ fn(i); }); })(i); } }
function kindLabel(k){ return k === 'phase' ? L['viz.kind_phase'] : k === 'o2' ? 'O2' : (L['viz.kind_' + k] || k); }
function statusColor(s){ return C.status[s] || C.muted; }
function icon(kind){
  var s = sv('svg', {viewBox: '0 0 24 24', 'aria-hidden': 'true'});
  if (kind === 'prevent'){ s.appendChild(sv('path', {d: 'M12 2.5l8 3v5.6c0 5-3.4 8.7-8 10.4-4.6-1.7-8-5.4-8-10.4V5.500z'})); s.appendChild(sv('path', {d: 'M8.500 12l2.500 2.500 4.500-5'})); }
  else if (kind === 'detect'){ s.appendChild(sv('circle', {cx: 12, cy: 12, r: 9})); s.appendChild(sv('circle', {cx: 12, cy: 12, r: 4.500})); s.appendChild(sv('path', {d: 'M12 12l6.400-6.400'})); s.appendChild(sv('circle', {cx: 16.500, cy: 14.500, r: .8})); }
  else { s.appendChild(sv('path', {d: 'M12 2.500c.6 3.300 4.800 5.200 4.800 10a4.800 4.800 0 0 1-9.600 0c0-2.300 1.400-3.600 2.200-5.800.9 1.400 2 .2 2.600-4.200z'})); s.appendChild(sv('path', {d: 'M4.500 19.500l15-15'})); }
  return s;
}

/* ---------- build the (hidden) scenes ---------- */
function build(){
  clearAll(); finished = false;
  while (root.firstChild) root.removeChild(root.firstChild);
  R = {chips: [], bins: [], pills: [], arrows: [], rings: [], halos: [], dots: [], fills: []};
  ['tl', 'tr', 'bl', 'br'].forEach(function(c){ root.appendChild(el('i', 'corner ' + c)); });

  var hud = el('header', 'hud mono');
  hud.appendChild(el('span', 'hide-s', 'Flame in Freefall'));
  R.steps = el('ol', 'steps');
  ['viz.step_classify', 'viz.step_locate', 'viz.step_narrow', 'viz.step_verdict'].forEach(function(key, i){
    var li = el('li'); li.appendChild(el('b', null, String(i + 1))); li.appendChild(document.createTextNode(L[key])); R.steps.appendChild(li);
  });
  hud.appendChild(R.steps);
  var replay = el('button', 'ctl', L['viz.replay']); replay.type = 'button'; replay.addEventListener('click', function(){ build(); play(); });
  var skip = el('button', 'ctl', L['viz.skip']); skip.type = 'button'; skip.addEventListener('click', finish);
  hud.appendChild(replay); hud.appendChild(skip);
  root.appendChild(hud);

  var stage = el('div', 'stage'); root.appendChild(stage);
  buildA(stage);
  if (P.mode !== 'scope') buildB(stage);

  var foot = el('footer', 'foot');
  R.autobar = el('i', 'autobar'); foot.appendChild(R.autobar);
  foot.appendChild(el('span', 'mono', L['viz.credit']));
  foot.appendChild(el('span', 'grow'));
  R.auto = el('span', 'mono auto'); foot.appendChild(R.auto);
  R.cta = el('button', 'cta', L['viz.cta'] + ' ▸'); R.cta.type = 'button'; R.cta.addEventListener('click', advance);
  foot.appendChild(R.cta);
  root.appendChild(foot);
  R.tip = el('div', 'tip'); root.appendChild(R.tip);
  root.appendChild(el('p', 'sr', document.body.getAttribute('data-summary') || ''));
  if (R.chart) drawChart();  /* after the footer exists, so the chart box has its final size */
}

function buildA(stage){
  var a = el('section', 'scene A on'); R.A = a;
  R.status = el('div', 'mono status', L['anim.classifying']); a.appendChild(R.status);
  var qwrap = el('div', 'qwrap'); R.q = el('p', 'qbig');
  P.question.segments.forEach(function(s){
    var sp = el('span', s.k ? 'seg k k-' + s.k : 'seg', s.t);
    if (s.k){ sp.setAttribute('data-label', kindLabel(s.k)); R.chips.push(sp); }
    R.q.appendChild(sp);
  });
  qwrap.appendChild(R.q); a.appendChild(qwrap);
  var bins = el('div', 'bins');
  P.phases.forEach(function(p){ var b = el('div', 'bin'); b.appendChild(icon(p.key)); b.appendChild(el('span', null, p.label)); bins.appendChild(b); R.bins.push(b); });
  a.appendChild(bins);
  R.conf = el('div', 'conf'); a.appendChild(R.conf);  /* spacer: the classifier's certainty is never shown */
  if (P.state === 'out_of_scope' || P.state === 'unclear'){
    R.stamp = el('div', 'stamp', P.state === 'out_of_scope' ? L['anim.out_of_scope'] : L['anim.unclear']);
    R.stamp.appendChild(el('small', null, P.state === 'out_of_scope' ? L['anim.out_of_scope_hint'] : L['anim.unclear_hint']));
    a.appendChild(R.stamp);
  }
  stage.appendChild(a);
}

function buildB(stage){
  var b = el('section', 'scene B'); R.B = b;
  var ro = el('div', 'readouts');
  P.detected.readouts.forEach(function(r){ var d = el('span', 'ro mono k-' + r.k, r.label); d.appendChild(el('b', null, r.value)); ro.appendChild(d); });
  b.appendChild(ro);

  var fun = el('div', 'funnel');
  P.funnel.forEach(function(f, i){
    if (i){ var ar = el('span', 'arrow', '→'); fun.appendChild(ar); R.arrows.push(ar); }
    var pill = el('span', 'fp'), parts = f.label.split('{n}');
    pill.appendChild(document.createTextNode(parts[0]));
    var n = el('span', 'n', fmt(f.n)); pill.appendChild(n); pill._n = n;
    pill.appendChild(document.createTextNode(parts.length > 1 ? parts.slice(1).join('') : ''));
    fun.appendChild(pill); R.pills.push(pill);
  });
  R.rel = el('span', 'mono rel', L['viz.relevance']); fun.appendChild(R.rel);
  b.appendChild(fun);

  var main = el('div', 'main'); b.appendChild(main);
  if (P.mode === 'bars') buildBars(main); else { R.chart = el('div', 'chart'); main.appendChild(R.chart); }

  var side = el('aside', 'side'); R.side = side;
  var V = P.verdict;
  if (P.mode !== 'empty'){
    R.count = el('div', 'count', '0'); R.countN = document.createTextNode('0'); R.count.textContent = '';
    R.count.appendChild(R.countN); R.count.appendChild(el('small', null, '/' + V.k));
    side.appendChild(R.count);
    side.appendChild(el('div', 'vtext', L['viz.verdict_' + V.kind]));
    var dots = el('div', 'dots'); P.topk.forEach(function(){ var d = el('i'); dots.appendChild(d); R.dots.push(d); }); side.appendChild(dots);
    R.klist = el('div', 'klist');
    ['extinguished', 'burned', 'other', 'reading', 'none'].forEach(function(s){
      if (!V.counts[s] || V.kind === 'rows') return;
      var row = el('div'); var sw = el('i', 'sw'); sw.style.background = statusColor(s); row.appendChild(sw);
      row.appendChild(document.createTextNode(V.counts[s] + ' · ' + L['viz.status_' + s])); R.klist.appendChild(row);
    });
    side.appendChild(R.klist);
  } else {
    side.appendChild(el('div', 'note', L['viz.empty']));
  }
  main.appendChild(side);

  R.legend = el('div', 'legend');
  if (P.mode !== 'bars'){
    P.phases.forEach(function(p){ var s = el('span'); var sw = el('i', 'sw'); sw.style.background = p.color; s.appendChild(sw); s.appendChild(document.createTextNode(p.label.charAt(0) + p.label.slice(1).toLowerCase())); R.legend.appendChild(s); });
    if (P.topk.length){ var s2 = el('span'); s2.appendChild(el('i', 'sw ringsw')); s2.appendChild(document.createTextNode(L['viz.legend_top'])); R.legend.appendChild(s2); }
    if (P.qpoint){ var est = !!P.qpoint.estimated; var s3 = el('span'); var q = el('i', est ? 'sw qest' : 'sw'); if (!est) q.style.background = C.question; s3.appendChild(q); s3.appendChild(document.createTextNode(est ? L['viz.your_question_est'] : L['viz.your_question'])); R.legend.appendChild(s3); }
    R.legend.appendChild(el('span', null, L['viz.cloud_note'] + (P.cloud.sampled ? ' ' + L['viz.sampled'] : '')));
  }
  b.appendChild(R.legend);
  stage.appendChild(b);
}

function buildBars(main){
  var w = el('div', 'bars'); R.bars = w;
  w.appendChild(el('div', 'mono bt', L['viz.phase_strip']));
  R.pstrip = el('div', 'pstrip'); var lab = el('div', 'plab');
  P.phases.forEach(function(p){
    var s = el('i', 'pseg' + (p.key === P.state ? ' sel' : '')); s.style.background = p.color; s.style.flex = Math.max(p.n, 1) + ' 1 0'; R.pstrip.appendChild(s);
    var l = el('span'); var sw = el('i', 'sw'); sw.style.background = p.color; l.appendChild(sw);
    l.appendChild(document.createTextNode(p.label.charAt(0) + p.label.slice(1).toLowerCase() + ' ')); l.appendChild(el('b', null, fmt(p.n))); lab.appendChild(l);
  });
  w.appendChild(R.pstrip); w.appendChild(lab);
  ['match', 'readings'].forEach(function(group){
    var rows = P.bars.filter(function(x){ return x.group === group; });
    if (!rows.length) return;
    w.appendChild(el('div', 'mono bt', L['viz.bars_' + group]));
    rows.forEach(function(x){
      var row = el('div', 'brow'); row.appendChild(el('span', null, x.label.charAt(0).toUpperCase() + x.label.slice(1)));
      var tr = el('div', 'track'), f = el('div', 'fill'); f._w = Math.max(0, Math.min(1, x.max ? x.value / x.max : 0)); f._g = group;
      tr.appendChild(f); row.appendChild(tr); row.appendChild(el('span', 'bval', x.text)); w.appendChild(row); R.fills.push(f);
    });
  });
  main.appendChild(w);
}

/* ---------- the cloud (SVG) ---------- */
function drawChart(){
  var box = R.chart, W = Math.max(320, box.clientWidth), H = Math.max(220, box.clientHeight);
  var cl = P.cloud, xd = cl.x_domain, yd = cl.y_domain, q = P.qpoint;
  var strip = cl.n_no_pressure > 0 || (q && q.p == null) || P.topk.some(function(r){ return r.o2 != null && r.p == null; });
  var m = {l: 56, r: 16, t: 18, b: 42}, stripH = strip ? 36 : 0, gap = strip ? 8 : 0;
  var plotH = H - m.t - m.b - stripH - gap, plotW = W - m.l - m.r, stripTop = m.t + plotH + gap;
  function X(v){ return m.l + (v - xd[0]) / (xd[1] - xd[0]) * plotW; }
  function Y(p){ return m.t + plotH - (p - yd[0]) / (yd[1] - yd[0]) * plotH; }
  function YS(i){ var h = ((Math.imul(i + 1, 2654435761) >>> 0) % 1000) / 1000; return stripTop + 7 + h * (stripH - 14); }
  var svg = sv('svg', {viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': L['viz.cloud_title']});
  var defs = sv('defs', {}), clip = sv('clipPath', {id: 'reveal'});
  R.clipRect = sv('rect', {x: 0, y: 0, width: 0, height: H}); clip.appendChild(R.clipRect); defs.appendChild(clip); svg.appendChild(defs);

  var grid = sv('g', {});
  var yStep = yd[1] > 8 ? Math.ceil(yd[1] / 5) : 1, xStep = (xd[1] - xd[0]) > 50 ? 10 : 5, v, t;
  for (v = yd[0]; v <= yd[1] + 1e-9; v += yStep){
    grid.appendChild(sv('line', {x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), stroke: 'rgba(255,255,255,.08)'}));
    t = sv('text', {x: m.l - 10, y: Y(v) + 4, 'text-anchor': 'end'}); t.textContent = num(v); grid.appendChild(t);
  }
  for (v = xd[0]; v <= xd[1] + 1e-9; v += xStep){
    grid.appendChild(sv('line', {x1: X(v), x2: X(v), y1: m.t, y2: stripTop + stripH, stroke: 'rgba(255,255,255,.05)', 'stroke-dasharray': '2 4'}));
    t = sv('text', {x: X(v), y: H - m.b + 18, 'text-anchor': 'middle'}); t.textContent = num(v); grid.appendChild(t);
  }
  t = sv('text', {x: m.l + plotW / 2, y: H - 8, 'text-anchor': 'middle'}); t.textContent = L['viz.axis_o2']; grid.appendChild(t);
  t = sv('text', {x: 16, y: m.t + plotH / 2, 'text-anchor': 'middle', transform: 'rotate(-90 16 ' + (m.t + plotH / 2) + ')'}); t.textContent = L['viz.axis_pressure']; grid.appendChild(t);
  if (strip){
    grid.appendChild(sv('rect', {x: m.l, y: stripTop, width: plotW, height: stripH, fill: 'rgba(255,255,255,.04)', rx: 3}));
    t = sv('text', {'class': 'striplab', x: W - m.r - 8, y: stripTop + 14, 'text-anchor': 'end'}); t.textContent = L['viz.strip']; grid.appendChild(t);
  }
  svg.appendChild(grid);

  var cloud = sv('g', {'class': 'cloud', 'clip-path': 'url(#reveal)'});
  R.gOther = sv('g', {}); R.gSub = sv('g', {}); cloud.appendChild(R.gOther); cloud.appendChild(R.gSub);
  var r = W > 900 ? 2.700 : 2.200, pts = cl.points, i, p, c;
  for (i = 0; i < pts.length; i++){
    p = pts[i];
    c = sv('circle', {cx: X(p[0]).toFixed(1), cy: (p[1] == null ? YS(i) : Y(p[1])).toFixed(1), r: r, fill: p[2] >= 0 ? C.phases[p[2]] : C.muted, 'fill-opacity': .72});
    (p[3] ? R.gSub : R.gOther).appendChild(c);
  }
  svg.appendChild(cloud);
  R.scan = sv('line', {'class': 'scan', x1: 0, x2: 0, y1: m.t, y2: stripTop + stripH, opacity: 0}); svg.appendChild(R.scan);
  R.W = W;

  R.gQ = sv('g', {opacity: 0}); svg.appendChild(R.gQ);
  var gTop = sv('g', {}); svg.appendChild(gTop);
  P.topk.forEach(function(row, k){
    if (row.o2 == null){ R.rings.push(null); R.halos.push(null); return; }
    var cx = X(row.o2), cy = row.p == null ? stripTop + stripH / 2 : Y(row.p);
    var halo = sv('circle', {'class': 'halo', cx: cx, cy: cy, r: 9}); gTop.appendChild(halo); R.halos.push(halo);
    var ring = sv('circle', {'class': 'ring', cx: cx, cy: cy, r: 9}); var title = sv('title', {});
    title.textContent = row.id + ' · ' + row.experiment + ' · ' + row.fuel; ring.appendChild(title);
    ring.addEventListener('mouseenter', function(){ tip(row, cx, cy); }); ring.addEventListener('mouseleave', function(){ R.tip.style.display = 'none'; });
    gTop.appendChild(ring); R.rings.push(ring);
  });
  if (q){
    svg.appendChild(R.gQ);  /* above the top-k rings, so a point that sits on them (estimated) stays visible */
    var qx = X(q.o2), qy = q.p == null ? stripTop + stripH / 2 : Y(q.p);
    R.gQ.appendChild(sv('line', {'class': 'qline', x1: qx, x2: qx, y1: m.t - 6, y2: stripTop + stripH}));
    var est = !!q.estimated, xc = est ? ' est' : '';
    R.qpulse = sv('circle', {'class': 'qpulse' + xc, cx: qx, cy: qy, r: est ? 13 : 6}); R.gQ.appendChild(R.qpulse);
    R.qdot = sv('circle', {'class': 'qdot' + xc, cx: qx, cy: qy, r: est ? 13 : 6.500}); R.gQ.appendChild(R.qdot); R.qy = qy; R.qTop = m.t - 6;
    var right = qx < W * 0.62;
    t = sv('text', {'class': 'qlabel' + xc, x: qx + (right ? 14 : -14), y: Math.max(m.t + 12, qy - 14), 'text-anchor': right ? 'start' : 'end'});
    t.textContent = est
      ? L['viz.your_question_est'] + ': ≈' + num(q.o2) + ' % O2' + (q.p == null ? '' : ', ≈' + num(q.p) + ' atm')
      : L['viz.your_question'] + ': ' + num(q.o2) + ' % O2' + (q.p == null ? ', ' + L['viz.no_pressure_stated'] : ', ' + num(q.p) + ' atm');
    R.gQ.appendChild(t);
  } else if (P.mode === 'scatter'){
    R.noq = sv('text', {x: m.l + 10, y: m.t + 14, opacity: 0}); R.noq.textContent = L['viz.no_o2_stated']; svg.appendChild(R.noq);
  }
  box.appendChild(svg);
  if (P.mode === 'empty'){ R.msg = el('div', 'msg', L['viz.empty']); box.appendChild(R.msg); }
}
function tip(row, cx, cy){
  var tp = R.tip; while (tp.firstChild) tp.removeChild(tp.firstChild);
  tp.appendChild(el('b', null, row.id + ' · ' + row.experiment));
  tp.appendChild(el('div', null, row.fuel));
  tp.appendChild(el('div', null, (row.o2 != null ? num(row.o2) + ' % O2' : '') + (row.p != null ? ' · ' + num(row.p) + ' atm' : '')));
  if (L['viz.status_' + row.status]) tp.appendChild(el('div', null, L['viz.status_' + row.status]));
  var cr = root.getBoundingClientRect(), br = R.chart.getBoundingClientRect(), sc = br.width / R.W;
  tp.style.display = 'block';
  tp.style.left = Math.min(cr.width - 270, br.left - cr.left + cx * sc + 16) + 'px';
  tp.style.top = Math.max(8, br.top - cr.top + cy * sc - 20) + 'px';
}

/* ---------- steps ---------- */
function setStep(i){ var li = R.steps.children; for (var k = 0; k < li.length; k++){ li[k].className = k < i ? 'done' : k === i ? 'cur' : ''; } }
function lightTokens(){ stagger(R.chips.length, 170, function(i){ R.chips[i].classList.add('lit'); }); }
function drop(){
  var target = R.bins[PHASE_KEYS.indexOf(P.state)]; if (!target || instant) return;
  var cr = root.getBoundingClientRect(), tr = target.getBoundingClientRect(), srcs = R.chips.length ? R.chips : [R.q];
  srcs.forEach(function(src, i){
    var r = src.getBoundingClientRect(), g = src.cloneNode(true);
    g.classList.add('ghost'); g.style.left = (r.left - cr.left) + 'px'; g.style.top = (r.top - cr.top) + 'px'; g.style.width = r.width + 'px';
    if (!g.animate) return;
    root.appendChild(g);
    var dx = (tr.left + tr.width / 2) - (r.left + r.width / 2), dy = (tr.top + tr.height * .42) - (r.top + r.height / 2);
    var an = g.animate([
      {transform: 'translate(0,0) scale(1)', opacity: 1},
      {transform: 'translate(' + dx * .55 + 'px,' + dy * .3 + 'px) scale(.92)', opacity: 1, offset: .45},
      {transform: 'translate(' + dx + 'px,' + dy + 'px) scale(.4)', opacity: 0}
    ], {duration: 820, delay: i * 70, easing: 'cubic-bezier(.5,0,.8,.45)', fill: 'forwards'});
    an.onfinish = function(){ if (g.parentNode) g.parentNode.removeChild(g); };
  });
}
function binLit(){
  var idx = PHASE_KEYS.indexOf(P.state);
  R.bins.forEach(function(b, i){ b.classList.add(i === idx ? 'lit' : 'dim'); });
  if (idx >= 0){
    R.status.textContent = L['anim.verdict']; R.status.classList.add('done');
    var d = P.detected;
    R.conf.classList.add('on');
  } else if (R.stamp){ R.status.textContent = ''; R.stamp.classList.add('on'); }
}
function pill(i, from){
  var p = R.pills[i]; if (!p) return;
  R.pills.forEach(function(x){ x.classList.remove('cur'); });
  p.classList.add('on'); p.classList.add('cur'); if (i && R.arrows[i - 1]) R.arrows[i - 1].classList.add('on');
  var to = P.funnel[i].n; tween(650, function(k){ p._n.textContent = fmt(from + (to - from) * k); });
}
function toB(){
  R.A.classList.remove('on'); R.B.classList.add('on'); setStep(1); pill(0, 0);
  if (R.clipRect){
    var W = R.W; R.scan.setAttribute('opacity', instant ? 0 : 1);
    tween(950, function(k){ R.clipRect.setAttribute('width', W * k); R.scan.setAttribute('x1', W * k); R.scan.setAttribute('x2', W * k); }, function(){ R.scan.setAttribute('opacity', 0); });
  }
  if (R.pstrip) R.legend.classList.add('on');
}
function narrowSubset(){
  setStep(2); pill(1, P.funnel[0].n);
  if (R.gOther){ R.gOther.style.opacity = .22; }
  if (R.pstrip) R.pstrip.classList.add('narrow');
}
function narrowTop(){
  setStep(2); var last = P.funnel.length - 1; pill(last, P.funnel[last - 1].n);
  if (R.gOther){ R.gOther.style.opacity = .2; R.gSub.style.opacity = P.funnel.length > 2 ? .75 : .32; }
  stagger(R.rings.length, 70, function(i){ if (R.rings[i]){ R.rings[i].classList.add('on'); R.halos[i].classList.add('on'); } });
  if (L['viz.relevance']) R.rel.classList.add('on');
  R.fills.forEach(function(f){ if (f._g === 'match') f.style.width = (f._w * 100) + '%'; });
  if (R.msg) R.msg.classList.add('on');
}
function landQuestion(){
  if (R.noq){ R.noq.setAttribute('opacity', 1); }
  R.fills.forEach(function(f){ if (f._g === 'readings') f.style.width = (f._w * 100) + '%'; });
  if (!R.qdot) return;
  R.gQ.setAttribute('opacity', 1);
  tween(620, function(k){ var y = R.qTop + (R.qy - R.qTop) * k; R.qdot.setAttribute('cy', y); R.qpulse.setAttribute('cy', y); });
}
function verdict(){
  setStep(3); if (R.side) R.side.classList.add('on');
  var V = P.verdict, seen = 0;
  if (!R.countN) return;
  stagger(P.topk.length, 120, function(i){
    var row = P.topk[i], col = V.kind === 'rows' ? C.telemetry : statusColor(row.status);
    if (R.rings[i]){ R.rings[i].style.fill = col; R.rings[i].style.stroke = col; if (!instant) R.rings[i].classList.add('flip'); }
    if (R.dots[i]){ R.dots[i].style.background = col; R.dots[i].style.borderColor = col; }
    var hit = V.kind === 'rows' || row.status === V.kind; if (hit) seen++;
    R.countN.nodeValue = String(instant ? V.n : seen);
  });
  if (instant || !P.topk.length) R.countN.nodeValue = String(V.n);
}
function end(){
  finished = true; setStep(4);
  if (R.klist) R.klist.classList.add('on');
  if (R.legend) R.legend.classList.add('on');
  if (R.side) R.side.classList.add('on');
  R.cta.classList.add('on'); R.auto.classList.add('on');
  if (clockTimer){ clearInterval(clockTimer); clockTimer = null; }
}
function steps(){
  var s = [[0, function(){ setStep(0); }], [300, lightTokens]];
  if (P.mode === 'scope'){ s.push([1300, binLit], [2600, end]); return s; }
  if (P.state === 'unclear') s.push([1500, binLit]); else s.push([1500, drop], [2350, binLit]);
  s.push([3300, toB]);
  var t = 4500;
  if (P.funnel.length > 2){ s.push([t, narrowSubset]); t += 1000; }
  s.push([t, narrowTop], [t + 700, landQuestion]);
  if (P.mode === 'empty'){ s.push([t + 1500, end]); return s; }
  s.push([t + 1500, verdict], [t + 2500, end]);
  return s;
}
function play(){
  root.classList.remove('no-anim'); instant = false; playT0 = performance.now();
  steps().forEach(function(st){ later(st[0], st[1]); });
}
function finish(){
  build(); root.classList.add('no-anim'); instant = true;
  steps().forEach(function(st){ st[1](); });
  instant = false;
}

/* ---------- hand over to Streamlit ---------- */
function parentButton(){
  try {
    var d = window.parent && window.parent.document; if (!d || d === document) return null;
    var b = d.querySelector('.st-key-' + P.cta_key + ' button'); if (b) return b;
    var all = d.querySelectorAll('button'), want = (L['btn.see_results'] || '').trim();
    for (var i = 0; i < all.length; i++){ if ((all[i].innerText || '').trim() === want) return all[i]; }
  } catch (e) {}
  return null;
}
function advance(){
  var b = parentButton();
  if (b){ R.cta.disabled = true; b.click(); return; }
  R.cta.textContent = L['viz.cta_below'] + ' ↓'; R.cta.classList.add('hint');
}
function autoTick(){
  var total = P.auto_seconds || 0; if (total <= 0 || !R.auto) return;
  var left = total - (Date.now() - pageT0) / 1000;
  R.autobar.style.width = Math.max(0, Math.min(100, (1 - left / total) * 100)) + '%';
  R.auto.textContent = left > 0.5 ? L['viz.auto'].replace('{n}', String(Math.ceil(left))) : '';
}

var resizeT = null;
window.addEventListener('resize', function(){ clearTimeout(resizeT); resizeT = setTimeout(function(){ if (finished) finish(); else { build(); play(); } }, 180); });
document.addEventListener('keydown', function(e){ if (e.key === 'Enter' && finished && document.activeElement === document.body) advance(); });
/* One "View results" control: when this page can press the Streamlit button, hide that button (and its row) so
   only the in-console control shows. If the parent page cannot be reached, the Streamlit button stays visible. */
function hideParentButton(){
  var b = parentButton(); if (!b) return false;
  try {
    var row = b.closest('[data-testid="stHorizontalBlock"]');
    var box = (row && row.querySelectorAll('button').length === 1) ? row : (b.closest('[class*="st-key-"]') || b);
    box.style.display = 'none'; box.setAttribute('data-ff-hidden', '1');
  } catch (e) { return false; }
  return true;
}
build();
if (!hideParentButton()){ setTimeout(hideParentButton, 400); }
if (reduce) finish(); else play();
setInterval(autoTick, 200); autoTick();
})();
"""

_MISSION_NEUTRAL = {"out_of_scope": "#9a9fb2", "unclear": "#aab4d6"}


def json_for_script(payload) -> str:
    """JSON that is safe inside a <script> element: no "<", ">" or "&" can end the block or start markup."""
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    for raw, escaped in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"), (" ", "\\u2028"), (" ", "\\u2029")):
        text = text.replace(raw, escaped)
    return text


def mission_summary(payload: dict) -> str:
    """One plain sentence with what the animation shows (screen readers, <noscript>)."""
    labels = payload.get("labels", {})
    state = payload.get("state")
    if state == "out_of_scope":
        return f'{labels.get("anim.out_of_scope", "")}. {labels.get("anim.out_of_scope_hint", "")}'.strip()
    parts = [labels.get("anim.verdict", "")]
    parts += [f["label"].replace("{n}", str(f["n"])) for f in payload.get("funnel", [])]
    verdict = payload.get("verdict") or {}
    if verdict.get("k"):
        parts.append(f'{verdict["n"]}/{verdict["k"]} {labels.get("viz.verdict_" + str(verdict.get("kind")), "")}')
    elif payload.get("mode") == "empty":
        parts.append(labels.get("viz.empty", ""))
    return ". ".join(p.strip() for p in parts if p and p.strip()) + "."


def build_mission_html(payload: dict, button_key: str = "see_results") -> str:
    """The stage-2 animation as one self-contained HTML document.

    ``payload``     dict from ``flame.viz_payload.build_animation_payload``
    ``button_key``  key of the Streamlit button that "View results" presses in the parent page
    """
    data = dict(payload)
    # the page never shows the classifier's certainty or matched keywords: they are not sent to the browser
    if isinstance(data.get("detected"), dict):
        data["detected"] = {k: v for k, v in data["detected"].items() if k not in ("confidence", "keywords")}
        data["detected"]["readouts"] = [r for r in data["detected"].get("readouts", []) if r.get("k") != "confidence"]
    if isinstance(data.get("labels"), dict):
        data["labels"] = {k: v for k, v in data["labels"].items() if k not in ("word.confidence", "word.keywords")}
    data["cta_key"] = re.sub(r"[^A-Za-z0-9_-]", "", str(button_key))
    lang = normalize_lang(data.get("lang"))
    state = animation_state(data.get("state")) if data.get("state") != "unclear" else "unclear"
    phase_colors = dict(zip(config.PHASES, (data.get("colors") or {}).get("phases") or []))
    color = phase_colors.get(state) or config.PHASE_COLORS.get(state) or _MISSION_NEUTRAL.get(state, "#aab4d6")
    summary = mission_summary(data)
    style = f":root{{--ph:{color};--ph-soft:{hex_to_rgba(color, 0.15)};--ph-glow:{hex_to_rgba(color, 0.5)}}}"
    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="color-scheme" content="dark"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<style>{_MISSION_CSS}{style}</style></head>"
        f'<body data-summary="{html.escape(summary, quote=True)}">'
        f'<div id="console" class="console state-{state} mode-{html.escape(str(data.get("mode", "")), quote=True)}"></div>'
        f"<noscript><p style=\"padding:24px;font:16px sans-serif;color:#e8ecf4\">{html.escape(summary)}</p></noscript>"
        f'<script id="payload" type="application/json">{json_for_script(data)}</script>'
        f"<script>{_MISSION_JS}</script></body></html>"
    )
