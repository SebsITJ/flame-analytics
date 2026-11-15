"""Mission-control look for the Streamlit page: one CSS string and the small HTML pieces of the page chrome.

No images, fonts or scripts are loaded: the starfield and the HUD grid are CSS gradients, the type is the
system sans and monospace stack. No space-agency logo or insignia is used anywhere; the data source is
credited as text ("Data: NASA PSI").

Classes are prefixed ``ff-``. ``flame.dashboard`` builds the stage-3 markup that uses the ``ff-d-*`` rules.
"""

from __future__ import annotations

import html

from . import config
from .i18n import t

BG = "#04070f"  # deep-space background; also the ring around chart marks
INK = "#e8ecf4"
MUTED = "#8b93a7"
LINE = "rgba(79,209,232,.22)"
MONO = 'ui-monospace,"SF Mono","Cascadia Mono","JetBrains Mono",Menlo,Consolas,"DejaVu Sans Mono",monospace'
SANS = '"Inter","Segoe UI",system-ui,-apple-system,Roboto,"Helvetica Neue",Arial,sans-serif'


def esc(text) -> str:
    """Escape text for HTML that goes through st.markdown / st.html ("$" would start LaTeX in markdown)."""
    return html.escape(str(text), quote=True).replace("$", "&#36;")


def _stars() -> str:
    """Three sparse, differently sized tiles of 1 px stars, so the repeat is not visible."""
    layers = []
    for size, stars in (
        (340, ((30, 40, .85), (190, 120, .6), (260, 300, .7), (110, 250, .45))),
        (470, ((60, 410, .7), (330, 80, .5), (420, 260, .8), (210, 190, .4))),
        (610, ((90, 150, .6), (500, 520, .75), (380, 340, .45), (560, 60, .55))),
    ):
        for x, y, alpha in stars:
            layers.append(
                f"radial-gradient(1.2px 1.2px at {x}px {y}px,rgba(255,255,255,{alpha * 0.7:.2f}) 55%,transparent 60%) 0 0/{size}px {size}px"
            )
    return ",".join(layers)


THEME_CSS = f"""
<style>
:root{{--ff-cy:{config.TELEMETRY_COLOR};--ff-ac:{config.ACCENT_COLOR};--ff-gold:{config.QUESTION_COLOR};--ff-ink:{INK};--ff-mut:{MUTED};
  --ff-line:{LINE};--ff-mono:{MONO};--ff-sans:{SANS};--ff-glass:rgba(10,16,32,.72)}}
[data-testid="stAppViewContainer"]{{
  background:{_stars()},
    linear-gradient(rgba(79,209,232,.03) 1px,transparent 1px) 0 0/100% 64px,
    linear-gradient(90deg,rgba(79,209,232,.03) 1px,transparent 1px) 0 0/64px 100%,
    radial-gradient(ellipse 90% 55% at 50% 112%,rgba(27,52,120,.55),transparent 70%),
    radial-gradient(ellipse 45% 35% at 88% -8%,rgba(217,89,38,.12),transparent 70%),
    {BG};
  background-attachment:fixed}}
[data-testid="stHeader"]{{background:transparent}}
[data-testid="stMainBlockContainer"],.block-container{{padding-top:1.5rem;padding-bottom:1.6rem;max-width:1480px}}
[data-testid="stSidebar"]{{background:rgba(5,8,18,.94);border-right:1px solid var(--ff-line)}}
[data-testid="stSidebar"] h2{{font-family:var(--ff-mono);font-size:.74rem;letter-spacing:.16em;text-transform:uppercase;color:var(--ff-cy);font-weight:600}}
html,body,[data-testid="stAppViewContainer"]{{font-family:var(--ff-sans)}}

/* tabs, buttons, expanders, form */
[data-baseweb="tab-list"],[role="tablist"]{{gap:1.1rem}}
button[data-baseweb="tab"] p,[data-testid="stTab"] p,[role="tab"] p{{font-family:var(--ff-mono);font-size:.74rem;letter-spacing:.16em;text-transform:uppercase}}
[data-testid="stButton"] button,[data-testid="stDownloadButton"] button{{border-radius:6px;border:1px solid var(--ff-line);
  background:rgba(79,209,232,.05);transition:border-color .2s,box-shadow .2s,background .2s}}
[data-testid="stButton"] button:hover,[data-testid="stDownloadButton"] button:hover{{border-color:var(--ff-cy);color:var(--ff-ink);
  box-shadow:0 0 14px rgba(79,209,232,.25)}}
[data-testid="stButton"] button[kind="primary"],[data-testid="stFormSubmitButton"] button{{background:var(--ff-ac);border:1px solid #f08a5d;
  color:#fff;box-shadow:0 0 18px rgba(217,89,38,.4);border-radius:6px}}
[data-testid="stButton"] button[kind="primary"]:hover,[data-testid="stFormSubmitButton"] button:hover{{background:#ea6a36;border-color:#ffb08a;
  color:#fff;box-shadow:0 0 22px rgba(217,89,38,.6)}}
[data-testid="stButton"] button:focus-visible,[data-testid="stFormSubmitButton"] button:focus-visible{{outline:2px solid var(--ff-cy);outline-offset:2px}}
[data-testid="stExpander"] details{{border:1px solid var(--ff-line);border-radius:8px;background:var(--ff-glass)}}
[data-testid="stExpander"] summary p{{font-family:var(--ff-mono);font-size:.7rem;letter-spacing:.08em;text-transform:uppercase}}
.st-key-new_question button{{white-space:nowrap}} .st-key-new_question button p{{white-space:nowrap}}
div[data-testid="stForm"]{{position:relative;border:1px solid var(--ff-line) !important;border-radius:10px !important;
  background:var(--ff-glass) !important;-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);
  padding:.7rem 1rem .5rem 1rem !important;max-width:820px;margin:0 auto;box-shadow:0 0 44px rgba(79,209,232,.08)}}
div[data-testid="stForm"]::before,div[data-testid="stForm"]::after{{content:"";position:absolute;width:16px;height:16px;border:2px solid var(--ff-cy);pointer-events:none}}
div[data-testid="stForm"]::before{{top:-1px;left:-1px;border-right:0;border-bottom:0;border-radius:10px 0 0 0}}
div[data-testid="stForm"]::after{{bottom:-1px;right:-1px;border-left:0;border-top:0;border-radius:0 0 10px 0}}
div[data-testid="stForm"] textarea{{background:transparent !important;border:none !important;font-size:1.08rem;box-shadow:none !important}}
div[data-testid="stForm"] [data-baseweb="textarea"],div[data-testid="stForm"] [data-baseweb="base-input"]{{background:transparent !important;border:none !important}}
div[data-testid="stForm"] [class*="st-key-FormSubmitter"],div[data-testid="stForm"] [data-testid="stElementContainer"]:has([data-testid="stFormSubmitButton"]){{align-self:flex-end;margin-left:auto}}
[class*="st-key-chip_"] button{{border-radius:999px;font-size:.86rem}}
.st-key-see_results button{{font-family:var(--ff-mono);letter-spacing:.1em;text-transform:uppercase;font-size:.78rem}}

/* page chrome */
.ff-mono{{font-family:var(--ff-mono);font-size:.7rem;letter-spacing:.15em;text-transform:uppercase;color:var(--ff-mut)}}
.ff-brand{{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem .9rem;padding:.1rem 0 .55rem 0;margin-bottom:.35rem;border-bottom:1px solid var(--ff-line)}}
.ff-brand svg{{width:22px;height:22px;flex:none}}
.ff-brand b{{font-family:var(--ff-mono);font-size:.86rem;letter-spacing:.2em;color:var(--ff-ink);font-weight:700}}
.ff-brand .ff-grow{{flex:1}}
.ff-tele{{display:inline-flex;align-items:center;gap:.45rem}}
.ff-tele i{{width:7px;height:7px;border-radius:50%;background:var(--ff-cy);box-shadow:0 0 8px var(--ff-cy)}}
.ff-hero{{text-align:center;margin:7vh 0 1.1rem 0}}
.ff-hero h1{{font-size:clamp(1.9rem,3.6vw,2.9rem);font-weight:300;letter-spacing:-.01em;margin:.5rem 0 0 0;padding:0;color:var(--ff-ink);
  text-shadow:0 0 28px rgba(79,209,232,.25)}}
.ff-hero p{{color:#aab2c5;margin:.7rem auto 0 auto;font-size:1.04rem;max-width:44rem;line-height:1.5}}
.ff-lang-note{{text-align:center;color:var(--ff-mut);font-size:.8rem;margin:-.3rem 0 1rem 0}}
.ff-ai-badge{{display:inline-block;margin:.1rem 0 .5rem;padding:.25rem .7rem;border-radius:999px;border:1px solid rgba(79,209,232,.55);background:rgba(79,209,232,.10);color:#bdf3fb;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.78rem}}
.ff-ai-engine{{border-color:rgba(217,89,38,.6);background:rgba(217,89,38,.12);color:#ffd2bf}}
.ff-ai-footer{{margin-top:.3rem;border-top:none;padding-top:0}}
.ff-footer{{margin-top:1.4rem;padding-top:.6rem;border-top:1px solid var(--ff-line);color:var(--ff-mut);font-size:.78rem;text-align:center}}
.ff-loader{{height:120px;display:flex;align-items:center;justify-content:center;gap:.8rem;border:1px solid var(--ff-line);border-radius:10px;background:var(--ff-glass)}}
.ff-loader i{{width:9px;height:9px;border-radius:50%;background:var(--ff-cy);animation:ff-blink 1s ease-in-out infinite}}
@keyframes ff-blink{{0%,100%{{opacity:.25}}50%{{opacity:1}}}}

/* stage 3: dashboard */
.ff-d{{display:flex;flex-direction:column;gap:.8rem;margin-bottom:.8rem;font-size:.92rem;line-height:1.45;color:#c9cfdc}}
.ff-d-strip{{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem .6rem;min-height:2.4rem}}
.ff-d-q{{color:#aab2c5;flex:1 1 20rem;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.ff-pill{{display:inline-flex;align-items:center;gap:.35rem;padding:.16rem .6rem;border-radius:999px;border:1px solid var(--ff-line);
  background:rgba(79,209,232,.06);color:var(--ff-ink) !important;font-family:var(--ff-mono);font-size:.7rem;letter-spacing:.04em;
  text-decoration:none !important;white-space:nowrap}}
a.ff-pill:hover{{border-color:var(--ff-cy);box-shadow:0 0 10px rgba(79,209,232,.3)}}
.ff-pill.ff-phase{{border-color:var(--ff-k);background:var(--ff-k-soft);letter-spacing:.12em;text-transform:uppercase;font-weight:700}}
.ff-card{{position:relative;border:1px solid var(--ff-line);border-radius:10px;background:var(--ff-glass);padding:.75rem 1rem;min-width:0;
  -webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px)}}
.ff-card h4{{font-family:var(--ff-mono);font-size:.7rem;letter-spacing:.15em;text-transform:uppercase;color:var(--ff-mut);font-weight:600;
  margin:0 0 .5rem 0;padding:0}}
.ff-d-row{{display:grid;gap:.8rem;grid-template-columns:minmax(0,2.3fr) minmax(190px,.9fr) minmax(0,1.7fr)}}
.ff-d-row.ff-two{{grid-template-columns:minmax(0,2.3fr) minmax(190px,.9fr)}}
.ff-d-row.ff-one{{grid-template-columns:minmax(0,1fr)}}
.ff-verdict{{border-color:var(--ff-k);background:linear-gradient(135deg,var(--ff-k-soft),rgba(10,16,32,.72) 60%)}}
.ff-verdict::before{{content:"";position:absolute;top:-1px;left:-1px;width:16px;height:16px;border:2px solid var(--ff-k);border-right:0;border-bottom:0;border-radius:10px 0 0 0}}
.ff-big{{display:flex;align-items:baseline;flex-wrap:wrap;gap:.2rem .8rem;margin:.1rem 0 .35rem 0}}
.ff-big b{{font-size:3.6rem;line-height:.9;font-weight:300;color:var(--ff-ink);font-variant-numeric:tabular-nums;letter-spacing:-.02em}}
.ff-sample{{font-size:.78rem;color:var(--ff-mut);margin:-.2rem 0 .35rem 0;letter-spacing:.02em}}
.ff-big b small{{font-size:1.5rem;color:var(--ff-mut);font-weight:400;letter-spacing:0}}
.ff-big span{{font-size:1.12rem;color:var(--ff-ink);font-weight:600}}
.ff-clamp{{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}}
.ff-warnline{{margin-top:.45rem;padding:.35rem .6rem;border-left:3px solid var(--ff-gold);background:rgba(255,210,122,.07);color:var(--ff-ink)}}
.ff-list{{margin:.4rem 0 0 1.1rem;padding:0}}
.ff-ring{{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.45rem}}
.ff-ring svg{{width:128px;height:128px}}
.ff-ring text{{fill:var(--ff-ink);font-family:var(--ff-sans)}}
.ff-key{{display:flex;flex-direction:column;gap:.15rem;font-size:.84rem}}
.ff-key span{{display:flex;align-items:center;gap:.45rem}}
.ff-sw{{width:10px;height:10px;border-radius:50%;flex:none}}
.ff-bar{{margin:.42rem 0}}
.ff-bar-h{{display:flex;justify-content:space-between;align-items:baseline;gap:.6rem;margin-bottom:.18rem}}
.ff-bar b{{color:var(--ff-ink);font-weight:600}}
.ff-track{{height:10px;border-radius:4px;background:rgba(255,255,255,.07);overflow:hidden}}
.ff-fill{{height:100%;border-radius:0 4px 4px 0;background:var(--ff-cy)}}
.ff-fill.ff-base{{background:#7f8aa6}}
.ff-val{{font-family:var(--ff-mono);font-size:.74rem;color:var(--ff-ink);white-space:nowrap}}
.ff-sub{{color:var(--ff-mut);font-size:.84rem}}
.ff-o2{{position:relative;margin:1.8rem .4rem 3rem .4rem;height:22px}}
.ff-o2-track{{position:absolute;inset:0;border-radius:5px;background:rgba(255,255,255,.06);overflow:hidden}}
.ff-zone{{position:absolute;top:0;bottom:0;display:flex;align-items:center;justify-content:center;font-size:.74rem;color:var(--ff-ink);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:0 .4rem}}
.ff-zone.ff-flame{{background:rgba(217,89,38,.5);border-left:2px solid var(--ff-ac)}}
.ff-zone.ff-noflame{{background:rgba(25,158,112,.42);border-right:2px solid #199e70}}
.ff-zone.ff-untested{{background:repeating-linear-gradient(135deg,rgba(255,255,255,.07) 0 6px,transparent 6px 12px);color:#aab2c5}}
.ff-asked{{position:absolute;top:-1.55rem;bottom:-6px;width:0;border-left:2px solid var(--ff-gold);filter:drop-shadow(0 0 5px var(--ff-gold))}}
.ff-asked span{{position:absolute;top:-.15rem;left:.4rem;white-space:nowrap;color:var(--ff-gold);font-weight:600;font-size:.82rem}}
.ff-asked.ff-left span{{left:auto;right:.4rem}}
.ff-tick{{position:absolute;top:100%;transform:translateX(-50%);padding-top:.25rem;font-family:var(--ff-mono);font-size:.68rem;color:var(--ff-mut)}}
.ff-tick::before{{content:"";position:absolute;left:50%;top:0;height:.22rem;border-left:1px solid rgba(255,255,255,.3)}}
.ff-ref{{position:absolute;top:calc(100% + 1.25rem);transform:translateX(-50%);white-space:nowrap;font-size:.76rem;color:#aab2c5;
  padding:.05rem .45rem;border:1px dashed rgba(255,255,255,.25);border-radius:4px}}
.ff-ref::before{{content:"";position:absolute;left:50%;bottom:100%;height:1.25rem;border-left:1px dashed rgba(255,255,255,.3)}}
.ff-ref.ff-off{{transform:none;right:0;left:auto !important}} .ff-ref.ff-off::before{{display:none}}
.ff-actions{{display:grid;gap:.8rem;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}}
.ff-act-h{{display:flex;flex-wrap:wrap;align-items:center;gap:.35rem .5rem;margin-bottom:.3rem}}
.ff-act-h b{{color:var(--ff-ink);font-size:.98rem;font-weight:600}}
.ff-act-body{{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}}
@media (max-width:900px){{.ff-d-row,.ff-d-row.ff-two{{grid-template-columns:minmax(0,1fr)}}}}
@media (prefers-reduced-motion:reduce){{.ff-loader i{{animation:none}}}}
</style>
"""

_MARK = (
    '<svg viewBox="0 0 32 32" fill="none" aria-hidden="true">'
    '<circle cx="16" cy="16" r="12.2" stroke="#5cc8ff" stroke-width="1.5" opacity=".85"/>'
    '<path d="M16 5.5c1.2 4.1 6.2 6.2 6.2 11.1a6.2 6.2 0 1 1-12.4 0c0-2.8 1.7-5.2 3.2-7.2.5 2.1 1.5 2.5 3 2.2.8-1.8.8-3.8 0-6.1Z" fill="#55cfff"/>'
    '<circle cx="16" cy="17" r="2.6" fill="#d9f8ff"/>'
    '</svg>'
)


def brand_html(lang: str, rows: int, experiments: int, gemini: bool) -> str:
    """Top bar: project name, team and two telemetry read-outs. Text only, no agency insignia."""
    engine = t("hud.engine_ai", lang) if gemini else t("hud.engine_rules", lang)
    return (
        f'<div class="ff-brand">{_MARK}<b>FLAME ANALYTICS</b><span class="ff-brand-sub">MICROGRAVITY RESEARCH</span>'
        f'<span class="ff-mono">{esc(t("hud.console", lang))}</span><span class="ff-grow"></span>'
        f'<span class="ff-mono ff-tele"><i></i>{esc(t("hud.loaded", lang, rows=rows, experiments=experiments))}</span>'
        f'<span class="ff-mono">{esc(engine)}</span></div>'
    )


def hero_html(lang: str) -> str:
    """Branded hero shell; the original localized scientific prompt remains intact below the title."""
    return (
        f'<div class="ff-hero"><div class="ff-mono ff-hero-kicker">{esc(t("hud.team", lang))}</div>'
        '<h1>Beyond <span>the flame.</span></h1>'
        f'<p>{esc(t("hero.subtitle", lang))}</p></div>'
    )


def loader_html(lang: str) -> str:
    return f'<div class="ff-loader"><i></i><span class="ff-mono">{esc(t("spinner.searching", lang))}</span></div>'


def footer_html(lang: str) -> str:
    return f'<div class="ff-footer">{esc(t("hud.footer", lang))}</div>'
