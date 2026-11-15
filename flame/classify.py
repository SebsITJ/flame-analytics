"""Classify a question: phase, subject and whether it is in scope.

Deterministic only (keywords and regular expressions). Spanish and English.
Nothing in this module calls an LLM.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

from .i18n import phase_name, t, term, terms

# ---------------------------------------------------------------------------
# Fuel / material synonyms (canonical label -> phrases that refer to it)
# ---------------------------------------------------------------------------

FUEL_SYNONYMS: dict[str, list[str]] = {
    "PMMA": ["pmma", "plexiglass", "plexiglas", "acrylic", "polymethyl methacrylate"],
    "Cotton-Fiberglass (SIBAL)": [
        "cotton-fiberglass", "cotton fiberglass", "cotton/fiberglass", "sibal",
        "cotton-fibreglass", "cotton fibreglass",
    ],
    "n-heptane": ["n-heptane", "n heptane", "heptane", "n-heptano", "heptano"],
    "ethanol": ["ethanol", "ethyl alcohol", "etanol"],
    "methanol": ["methanol", "methyl alcohol", "metanol"],
    "Nomex": ["nomex"],
    "silicone": ["silicone rubber", "silicone", "silicona"],
    "candle": ["japan wax", "paraffin wax", "parrafin wax", "candle", "vela", "parafina"],
    "Teflon": ["teflon", "ptfe"],
    "Kapton": ["kapton"],
    "Pyrell": ["pyrell"],
    "Lampwick": ["lampwick", "lamp wick"],
    "ethylene": ["ethylene", "etileno", "c2h4"],
    "propane": ["propane", "propano", "c3h8"],
    "propylene": ["propylene", "propileno"],
    "methane": ["methane", "metano", "ch4"],
    "butane": ["butane", "butano"],
    "ethane": ["ethane", "etano"],
    "decane": ["n-decane", "decane", "decano"],
    "octane": ["n-octane", "isooctane", "iso-octane", "iso octane", "octane", "octano"],
    "hydrogen": ["hydrogen", "hidrogeno", "hidrógeno", "h2"],
    "Ultem": ["ultem"],
    "Dibutyl Phthalate": ["dibutyl phthalate", "dbp"],
    "C12H26": ["c12h26", "iso-dodecane", "isododecane", "dodecane"],
}

# Extra ES/EN aliases merged into the table above. A family with no rows in the CSV is harmless:
# it only fills Subject.material, and retrieval then reports the gap.
_EXTRA_ALIASES: dict[str, list[str]] = {
    "PMMA": ["acrilico", "metacrilato", "polimetilmetacrilato", "poly methyl methacrylate", "perspex"],
    "Cotton-Fiberglass (SIBAL)": ["cotton", "algodon", "fiberglass", "fibra de vidrio"],
    "candle": ["wax", "cera"],
    "Lampwick": ["wick", "mecha"],
    "Teflon": ["politetrafluoroetileno", "fep"],
    "Pyrell": ["polyurethane", "poliuretano"],
    "ethanol": ["alcohol etilico"],
    "methanol": ["alcohol metilico"],
    "polyethylene": ["polyethylene", "polietileno", "ldpe", "hdpe"],
    "nylon": ["nylon", "nailon"],
    # "paper"/"papel" removed (review, minor): the CSV has no paper rows, and "¿Qué papel juega…?"
    # was read as the material paper.
    "cellulose": ["cellulose", "celulosa"],
    "wire insulation": ["wire insulation", "cable insulation", "aislamiento de cable", "aislante"],
}
for _canonical, _aliases in _EXTRA_ALIASES.items():
    _known = FUEL_SYNONYMS.setdefault(_canonical, [])
    _known.extend(a for a in _aliases if a not in _known)

# All patterns below run on normalize_text(question): lowercase, no accents, subscripts folded
# (CO₂ -> co2). So they are written without accents.
_CO2 = r"\b(?:co2|carbon dioxide|dioxido de carbono|anhidrido carbonico)\b"
_N2 = r"\b(?:n2|nitrogen|nitrogeno)\b"

# Diluent / ambient gases named in the question.
GAS_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("CO2", re.compile(_CO2)),
    ("N2", re.compile(_N2)),
    ("He", re.compile(r"\b(?:helium|helio)\b")),
    ("Ar", re.compile(r"\bargon\b")),
    ("O2", re.compile(r"\b(?:o2|oxygen|oxigeno)\b")),
]
# The symbol "He" is read on the raw question, case-sensitive and never at the start of a
# sentence, so the English pronoun and the Spanish verb ("He visto humo") are not helium.
_HE_SYMBOL = re.compile(r"(?<=[a-z0-9,%] )He\b|(?<=[/(+])He\b")

# Suppression agents and actions.
INHIBITOR_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("CO2", re.compile(_CO2)),
    ("water mist", re.compile(
        r"\b(?:(?:fine\s+)?water\s*(?:mist|spray|fog)|agua\s+nebulizada"
        r"|(?:niebla|neblina|rocio|aspersion)(?:\s+de\s+agua)?)\b")),
    ("N2", re.compile(_N2)),
    ("He", re.compile(r"\b(?:helium|helio)\b")),
    ("Ar", re.compile(r"\bargon\b")),
    ("Halon", re.compile(r"\bhalon(?:es)?(?:\s*1301)?\b")),
    ("foam", re.compile(r"\b(?:foam|espuma)\b")),
    ("portable extinguisher", re.compile(r"\b(?:extinguishers?|extintor(?:es)?|extinguidor(?:es)?|pfe)\b")),
    ("ventilation shutdown", re.compile(
        r"\b(?:stop|shut|cut|turn|switch)\w*\s+(?:\w+\s+){0,3}?(?:ventilat\w*|fans?|airflow|air\s+flow)\b"
        r"|\bventilation\s+(?:shut\s*down|shutoff|off)\b"
        r"|\b(?:cortar|corta|parar|detener|cerrar|apagar)\s+(?:\w+\s+){0,3}?(?:ventilac\w*|ventilador\w*|flujo)\b")),
    ("O2 cutoff", re.compile(
        r"\b(?:cut|shut|stop|remov|reduc|lower)\w*\s+(?:\w+\s+){0,3}?(?:oxygen|o2)\b"
        r"|\b(?:cortar|quitar|reducir|bajar|disminuir)\s+(?:\w+\s+){0,3}?(?:oxigeno|o2)\b")),
    ("depressurization", re.compile(r"\b(?:depressuri\w*|despresuri\w*|vent(?:ing)?\s+to\s+(?:vacuum|space))\b")),
    ("diluent (unspecified)", re.compile(r"\b(?:dilu\w*|inert\w*|purg\w*|inhibi\w*)\b")),
]

# Variables that can reveal a fire. A unit such as "ppm" is not a variable, so it is not listed.
DETECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("smoke", re.compile(r"\b(?:smoke|humo|soot|hollin)\b")),
    ("particles", re.compile(r"\b(?:particles?|particulates?|particulas?|aerosol(?:es|s)?|obscur\w*|oscurec\w*)\b")),
    ("CO", re.compile(r"\b(?:co|carbon monoxide|monoxido de carbono)\b")),
    ("CO2", re.compile(_CO2)),
    ("O2 depletion", re.compile(
        r"\b(?:o2|oxygen|oxigeno)\b.{0,25}\b(?:deplet\w*|consum\w*|drop\w*|agota\w*|caida|disminu\w*)")),
    ("HCN", re.compile(r"\b(?:hcn|hydrogen cyanide|cianuro de hidrogeno|acido cianhidrico)\b")),
    ("HCl", re.compile(r"\b(?:hcl|hydrogen chloride|cloruro de hidrogeno|acido clorhidrico)\b")),
    ("HF", re.compile(r"\b(?:hf|hydrogen fluoride|fluoruro de hidrogeno|acido fluorhidrico)\b")),
    ("acid gases", re.compile(r"\b(?:acid gas(?:es)?|gases? acidos?)\b")),
    ("temperature", re.compile(r"\b(?:temperatur\w*|thermal|termic\w*|heat|calor|overheat\w*|sobrecalent\w*)\b")),
    ("mass loss rate", re.compile(
        r"\b(?:(?:mass|weight)\s+loss|burning\s+rate|perdida\s+de\s+(?:masa|peso)|tasa\s+de\s+quemado|(?:tasa|velocidad)\s+de\s+combustion)\b")),
    ("flame radiation", re.compile(r"\b(?:radiat\w*|radiaci\w*|radiometer|infrared|infrarroj\w*|ultraviolet\w*)\b")),
]

_PRODUCT = r"(?:co2?|carbon\s+(?:di|mon)oxide|(?:di|mon)oxido\s+de\s+carbono|gas(?:es)?|smoke|humo|soot|hollin)"
_EMIT = r"(?:generat|produc|releas|emit|genera|libera|emite|forma)\w*"

# Phrase lists used to score the phase. Stems (\w*) cover conjugations in both languages:
# extinguishes / extingue / extintor, apaga / apagar, detects / detecta, diluents / dilucion.
# Each pattern is counted once, so no word is scored twice.
PHASE_PHRASES: dict[str, list[tuple[int, str]]] = {
    "extinguish": [
        (3, r"\bput(?:s|ting)?\s+(?:\w+\s+){0,3}?out\b"),
        (3, r"\bextin\w*"),
        (3, r"\bapag\w*"),
        (3, r"\bsuppress\w*|\bsupres\w*|\bsuprim\w*"),
        (3, r"\bsofoc\w*|\bsmother\w*|\bquench\w*"),
        (3, r"\b(?:stop|fight|kill|control|contain)\w*\s+(?:\w+\s+){0,3}?(?:fire|flame|blaze)s?\b"
            r"|\b(?:detener|combatir|controlar|parar|contener)\s+(?:\w+\s+){0,3}?(?:fuego|incendio|llama)s?\b"),
        (2, r"\b(?:water|agua)\s*(?:mist|spray|fog|nebulizada)\b|\b(?:niebla|neblina|rocio|aspersion)\s+de\s+agua\b"),
        (2, r"\bdilu\w*"),
        (2, r"\binhibi\w*|\binert\w*|\bpurg\w*"),
        (2, r"\bdepressuri\w*|\bdespresuri\w*"),
        (2, r"\b(?:stop|shut|cut|turn|switch)\w*\s+(?:\w+\s+){0,3}?(?:ventilat\w*|fans?|airflow|air\s+flow|oxygen|o2)\b"
            r"|\b(?:cortar|corta|parar|detener|cerrar)\s+(?:\w+\s+){0,3}?(?:ventilac\w*|ventilador\w*|flujo|oxigeno|o2)\b"),
        (1, r"\bhalon\w*|\bfoam\b|\bespuma\b|\bhelium\b|\bhelio\b|\bargon\b|\bmist\b|\bniebla\b|\bblow\s*-?\s*(?:off|out)\b"),
    ],
    "detect": [
        (3, r"\bdetec\w*"),
        (3, rf"\b{_PRODUCT}\b.{{0,40}}?\b{_EMIT}|\b{_EMIT}\b.{{0,40}}?\b{_PRODUCT}\b"),
        (2, r"\bsensor\w*|\balarm\w*|\bmonitor\w*"),
        (2, r"\bsmoke\b|\bhumo\b|\bsoot\b|\bhollin\b|\baerosol\w*|\bparticle\w*|\bparticula\w*|\bobscur\w*"),
        (2, r"\bsmou?lder\w*|\boverheat\w*|\bsobrecalent\w*|\bpyrolys\w*|\bpirolisis\b"),
        (2, r"\bindica\w*|\bsignature\w*|\bprecursor\w*|\bearly\s+warning\b|\balerta\s+temprana\b"),
        (1, r"\bppm\b|\bco\b|\bcarbon monoxide\b|\bmonoxido de carbono\b|\bhcn\b|\bhcl\b|\bacid gas\w*|\bgases? acidos?\b"),
        (1, r"\bmeasur\w*|\bmedi(?:r|cion\w*|do|da)\b|\bmide\w*"),
    ],
    "prevent": [
        (3, r"\bpreven\w*|\bprevien\w*|\bevit\w*|\bavoid\w*"),
        (2, r"\bignit\w*|\bignic\w*|\bencend\w*|\binflam\w*|\bflammab\w*"),
        (2, r"\bflame\s+spread\w*|\bspread\s+rate\b|\bpropaga\w*"),
        (2, r"\boxygen\s+index\b|\bloi\b|\bmoc\b|\bindice\s+de\s+oxigeno\b"
            r"|\b(?:flammability|oxygen)\s+limit\w*|\blimite\s+de\s+(?:inflamabilidad|oxigeno)\b"),
        (1, r"\brisk\w*|\briesgo\w*|\bsafe\w*|\bsegur\w*|\bhazard\w*|\bpeligr\w*"),
        (1, r"\bmaterial\w*|\bfabric\w*|\btela\w*|\binsulation\b|\baislamiento\b|\baislante\w*"),
        (1, r"\bburn\w*|\bquema\w*|\barde\w*|\bcombusti\w*"),
        (1, r"\bhabitab\w*|\batmos[fp]\w*"),
    ],
}

# Stems carry \w* so that "ignition", "flammability", "extinguisher" or "atmosfera" count.
FIRE_TERMS = re.compile(
    r"\b(?:fire\w*|flame\w*|burn\w*|combusti\w*|ignit\w*|ignic\w*|flammab\w*|inflam\w*"
    r"|smoke|humo|soot|hollin|spacecraft|spaceship|habitat\w*|microgravi\w*|iss|nasa"
    r"|oxygen|oxigeno|fuel\w*|extin\w*|apag\w*|detec\w*|sensor\w*|alarm\w*"
    r"|fuego|llama\w*|incendi\w*|quema\w*|arde\w*|espacial\w*|nave|cabin\w*|atmos[fp]\w*"
    r"|dilu\w*|ventila\w*|purg\w*|depressuri\w*|despresuri\w*|crew|tripulaci\w*"
    r"|heptan\w*|pmma|methanol|metanol|cotton|sibal)\b",
    re.I,
)

OUT_OF_SCOPE_HINTS = re.compile(
    r"\b(?:recipe|weather|clima|futbol|fútbol|world\s+cup|mundial|bitcoin|movie|pel[ií]cula"
    r"|programming|javascript|python tutorial|homework about history)\b",
    re.I,
)


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize_text(text: str) -> str:
    """Lowercase, strip accents, keep letters/digits so fuels like n-heptane stay intact."""
    text = _strip_accents(str(text)).lower()
    text = text.replace("¿", " ").replace("?", " ").replace("¡", " ").replace("!", " ")
    return text


def normalize_fuel(name: str) -> str:
    text = _strip_accents(str(name)).lower()
    text = re.sub(r"\b[nN]-", "", text)  # n-heptane -> heptane
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


@lru_cache(maxsize=4096)
def fuel_families(name: str) -> frozenset[str]:
    """Canonical families named in a fuel string (a dataset row or a question)."""
    text = " " + normalize_fuel(name) + " "
    return frozenset(
        canonical
        for canonical, aliases in FUEL_SYNONYMS.items()
        if any(f" {normalize_fuel(alias)} " in text for alias in (canonical, *aliases))
    )


def fuel_matches(row_fuel: str, wanted: str) -> bool:
    a, b = set(normalize_fuel(row_fuel).split()), set(normalize_fuel(wanted).split())
    if not a or not b:
        return False
    # Whole-word match only: "heptane" matches "n-heptane/iso-octane", "ethanol" never matches "methanol".
    if a <= b or b <= a:
        return True
    # Same family through the synonym table: "SIBAL Fabric" is "Cotton-Fiberglass (SIBAL)",
    # "Japan wax" is "candle", "lamp wick" is "Lampwick".
    return bool(fuel_families(str(row_fuel)) & fuel_families(str(wanted)))


@dataclass
class Subject:
    """What the question is about, when it names a thing."""

    material: str | None = None  # fuel or material as named / canonical
    fuel: str | None = None  # only set when it matches a dataset fuel
    gases: list[str] = field(default_factory=list)
    inhibitors: list[str] = field(default_factory=list)
    detection_vars: list[str] = field(default_factory=list)
    also_named: list[str] = field(default_factory=list)  # other fuels in the question (only `fuel` is used)

    def is_empty(self) -> bool:
        return not any([self.material, self.fuel, self.gases, self.inhibitors, self.detection_vars])

    def summary(self, lang: str = "en") -> str:
        """One-line description of the subject. Labels are translated; fuel names stay as written."""
        parts: list[str] = []
        if self.material:
            parts.append(t("subj.material", lang, value=term(self.material, lang)))
        if self.gases:
            parts.append(t("subj.gases", lang, value=", ".join(terms(self.gases, lang))))
        if self.inhibitors:
            parts.append(t("subj.inhibitors", lang, value=", ".join(terms(self.inhibitors, lang))))
        if self.detection_vars:
            parts.append(t("subj.detection", lang, value=", ".join(terms(self.detection_vars, lang))))
        return " · ".join(parts) if parts else t("none_m", lang)


@dataclass
class Classification:
    phase: str | None  # prevent / detect / extinguish / out_of_scope / None
    confidence: float
    matched_keywords: list[str] = field(default_factory=list)
    subject: Subject = field(default_factory=Subject)
    reason: str = ""
    phase_scores: dict[str, int] = field(default_factory=dict)

    @property
    def out_of_scope(self) -> bool:
        return self.phase == "out_of_scope"


def _find_phrases(question: str) -> tuple[dict[str, int], list[str], dict[str, int]]:
    scores = {p: 0 for p in PHASE_PHRASES}
    first = {p: len(question) + 1 for p in PHASE_PHRASES}  # where each phase is first named
    matched: list[str] = []
    for phase, phrases in PHASE_PHRASES.items():
        for weight, pattern in phrases:
            m = re.search(pattern, question, flags=re.IGNORECASE)
            if not m:
                continue
            token = re.sub(r"\s+", " ", m.group(0).strip().lower())
            if token and token not in matched:
                matched.append(token)
            scores[phase] += weight  # each pattern counted once
            first[phase] = min(first[phase], m.start())
    return scores, matched, first


_GAS_AGENTS = {"CO2", "N2", "He", "Ar"}


def resolve_roles(subject: "Subject", phase: str | None) -> "Subject":
    """A gas named in a detection question is a measured product, not a suppressant, and vice versa."""
    if phase == "detect":
        subject.inhibitors = [i for i in subject.inhibitors if i not in _GAS_AGENTS]
    elif phase == "extinguish":
        subject.detection_vars = [d for d in subject.detection_vars if d not in subject.inhibitors]
    return subject


def extract_subject(question: str, known_fuels: list[str]) -> Subject:
    subject = Subject()
    q_norm = " " + normalize_fuel(question) + " "

    # When several fuels are named, the one named FIRST is used, in EN and ES alike (it used to be the longest
    # table name in English and the first synonym-table entry in Spanish).
    def _pos(name: str) -> int:
        n = normalize_fuel(name)
        i = q_norm.find(f" {n} ") if n else -1
        return i if i >= 0 else 10**9

    # 1. Dataset fuel names in the question: earliest first, then longest.
    table = [f for f in {f for f in known_fuels if str(f).strip()} if _pos(f) < 10**9]
    table.sort(key=lambda f: (_pos(f), -len(normalize_fuel(f))))

    # 2. Synonyms / family names: earliest alias position.
    syn = []
    for canonical, aliases in FUEL_SYNONYMS.items():
        best = min((_pos(a) for a in (*aliases, canonical)), default=10**9)
        if best < 10**9:
            syn.append((best, canonical))
    syn.sort(key=lambda x: x[0])
    mentioned_canonical: str | None = syn[0][1] if syn else None

    if table and (not syn or _pos(table[0]) <= syn[0][0]):
        subject.fuel = subject.material = table[0]
    elif mentioned_canonical is not None:
        subject.material = mentioned_canonical

    # Other fuels named in the same question: only one is used, so the pipeline warns (review, minor).
    families_used = fuel_families(str(subject.fuel or subject.material or ""))
    for canonical, aliases in FUEL_SYNONYMS.items():
        if canonical in families_used:
            continue
        if any(normalize_fuel(a) and f" {normalize_fuel(a)} " in q_norm for a in (canonical, *aliases)):
            if canonical not in subject.also_named:
                subject.also_named.append(canonical)

    if subject.fuel is None and mentioned_canonical is not None:
        for fuel in known_fuels:
            if fuel_matches(str(fuel), mentioned_canonical):
                subject.fuel = mentioned_canonical
                break
        # If the material is named but not in this dataset, keep it on material only
        # so "ethanol" never becomes a match for "methanol".

    q_plain = normalize_text(question)
    for label, pattern in GAS_PATTERNS:
        if pattern.search(q_plain) and label not in subject.gases:
            subject.gases.append(label)
    if _HE_SYMBOL.search(str(question)) and "He" not in subject.gases:
        subject.gases.append("He")

    for label, pattern in INHIBITOR_PATTERNS:
        if pattern.search(q_plain) and label not in subject.inhibitors:
            subject.inhibitors.append(label)
    # A named agent makes the generic "diluent" label redundant.
    if len(subject.inhibitors) > 1 and "diluent (unspecified)" in subject.inhibitors:
        subject.inhibitors.remove("diluent (unspecified)")

    for label, pattern in DETECTION_PATTERNS:
        if pattern.search(q_plain) and label not in subject.detection_vars:
            subject.detection_vars.append(label)

    return subject


def classify_question(question: str, known_fuels: list[str] | None = None, lang: str = "en") -> Classification:
    """Return phase, confidence, matched keywords and the subject of the question.

    ``lang`` only changes the language of the human-readable ``reason``; the decision never depends on it.
    """
    known = [str(f) for f in (known_fuels or []) if str(f).strip()]
    q = str(question)
    q_plain = normalize_text(q)
    scores, matched, first = _find_phrases(q_plain)
    subject = extract_subject(q, known)

    best = max(scores.values()) if scores else 0
    winners = [p for p, n in scores.items() if n == best]
    fire_related = bool(FIRE_TERMS.search(q_plain) or not subject.is_empty())
    off_topic = bool(OUT_OF_SCOPE_HINTS.search(q_plain))

    if off_topic and not fire_related:
        return Classification(
            phase="out_of_scope",
            confidence=0.9,
            matched_keywords=matched,
            subject=subject,
            reason=t("clf.oos_offtopic", lang),
            phase_scores=scores,
        )

    if best == 0:
        if fire_related:
            return Classification(
                phase=None,
                confidence=0.0,
                matched_keywords=matched,
                subject=subject,
                reason=t("clf.no_phase", lang),
                phase_scores=scores,
            )
        return Classification(
            phase="out_of_scope",
            confidence=0.85,
            matched_keywords=matched,
            subject=subject,
            reason=t("clf.oos_nofire", lang),
            phase_scores=scores,
        )

    if len(winners) > 1:
        # Tie: use the phase the question names first, and say so.
        phase = min(winners, key=lambda p: first[p])
        return Classification(
            phase=phase,
            confidence=0.5,
            matched_keywords=matched,
            subject=resolve_roles(subject, phase),
            reason=t("clf.tie", lang, phases=f" {t('word.and', lang)} ".join(phase_name(w, lang) for w in winners)),
            phase_scores=scores,
        )

    phase = winners[0]
    second = sorted(scores.values(), reverse=True)[1]
    confidence = round(min(1.0, best / (best + second + 1.0)), 3)
    # A single clear phrase should still look confident.
    if second == 0 and best >= 2:
        confidence = max(confidence, 0.8)
    return Classification(
        phase=phase,
        confidence=confidence,
        matched_keywords=matched,
        subject=resolve_roles(subject, phase),
        reason=t("clf.matched", lang, phase=phase_name(phase, lang)),
        phase_scores=scores,
    )


# English wording (kept for code that imports it); the Spanish text lives in flame/i18n.py.
OUT_OF_SCOPE_MESSAGE = t("out_of_scope.message", "en")
