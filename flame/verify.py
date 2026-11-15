"""Check Gemini's text against the evidence it was given."""

from __future__ import annotations

import re
from collections.abc import Iterable

# A number not glued to a letter, so "O2", "CO2", "R3" or "FLEX2" are not read as numbers.
_NUM = re.compile(r"(?<![A-Za-z0-9_.])\d+(?:\.\d+)?")


def numbers_in(text: str) -> list[str]:
    return _NUM.findall(str(text))


def unsupported_numbers(answer_parts: Iterable[str], allowed_texts: Iterable[str]) -> list[str]:
    """Numbers in the answer that appear nowhere in the question, rows or computed facts.

    A value with decimals passes if it is a rounding of an allowed value
    (0.69 for 0.694). An integer must match exactly, so "1 atm" never passes for 0.7.
    """
    allowed = {float(n) for t in allowed_texts for n in numbers_in(t)}
    bad: list[str] = []
    for part in answer_parts:
        for n in numbers_in(part):
            value = float(n)
            decimals = len(n.split(".")[1]) if "." in n else 0
            ok = any(
                abs(value - a) < 1e-9 or (decimals > 0 and round(a, decimals) == value)
                for a in allowed
            )
            if not ok and n not in bad:
                bad.append(n)
    return bad


def unknown_row_ids(cited: Iterable[str], valid: Iterable[str]) -> list[str]:
    valid_set = {v.upper() for v in valid}
    return [c for c in cited if str(c).strip().upper() not in valid_set]


def row_ids_in(text: str) -> list[str]:
    return re.findall(r"\bR\d+\b", str(text))


# ---------------------------------------------------------------------------
# v7: checks on the AI interpretation (flame/agent.py) against the tool ledger (flame/tools.py)
# ---------------------------------------------------------------------------

# Numbers as people write them: 0.52, 0,52 (Spanish decimal comma), 1,982 / 1.982 (thousands), 91 %.
_NUM_LOOSE = re.compile(r"(?<![A-Za-z0-9_.,])\d+(?:[.,]\d+)*(?![A-Za-z0-9_])|(?<![A-Za-z0-9_.,])\d+(?:[.,]\d+)*(?=[%°])")
_ID = re.compile(r"\b([RE])(\d+)\b")


def _candidates(token: str) -> list[tuple[float, int]]:
    """(value, decimals) readings of a written number: as is, comma as decimal point, separators removed."""
    out: list[tuple[float, int]] = []
    plain = token.replace(",", "")
    for text in {token.replace(",", "."), plain, token.replace(".", "").replace(",", ".")}:
        try:
            value = float(text)
        except ValueError:
            continue
        decimals = len(text.split(".")[1]) if "." in text else 0
        out.append((value, decimals))
    return out


def _allowed_numbers(texts: Iterable[str]) -> set[float]:
    found: set[float] = set()
    for t in texts:
        for n in _NUM.findall(str(t)):
            found.add(float(n))
    return found


def _number_ok(token: str, allowed: set[float]) -> bool:
    for value, decimals in _candidates(token):
        for a in allowed:
            if abs(value - a) < 1e-9:
                return True
            if decimals > 0 and round(a, decimals) == value:
                return True
            # Whole-number rounding only for values >= 10 (91 for 91.3 %); "1 atm" never passes for 0.7.
            if decimals == 0 and abs(a) >= 10 and round(a) == value:
                return True
    return False


def ledger_texts(ledger, question: str = "") -> list[str]:
    import json

    texts = [question]
    texts += [json.dumps(r, ensure_ascii=False, default=str) for r in ledger.rows.values()]
    for fact in ledger.facts.values():
        texts.append(json.dumps(fact.get("values", {}), ensure_ascii=False, default=str))
        texts.append(json.dumps(fact.get("args", {}), ensure_ascii=False, default=str))
    # Counts the reader can see in the pack: rows returned, facts, experiments.
    texts.append(" ".join(str(n) for n in (len(ledger.rows), len(ledger.facts))))
    return texts


def unsupported_numbers_loose(parts: Iterable[str], allowed_texts: Iterable[str]) -> list[str]:
    allowed = _allowed_numbers(allowed_texts)
    bad: list[str] = []
    for part in parts:
        clean = _ID.sub(" ", str(part))  # R12 / E3 are ids, not numbers
        clean = re.sub(r"[A-Za-z]+[-_]?\d+(?:\.\d+)?", " ", clean)  # O2, CO2, FLEX2, PSI-69 are names
        for token in _NUM_LOOSE.findall(clean):
            if not _number_ok(token, allowed) and token not in bad:
                bad.append(token)
    return bad


def verify_interpretation(answer, ledger, question: str, lang: str | None = None,
                          max_claims: int = 8) -> list[str]:
    """Problems found in an InterpretedAnswer. An empty list means it can be shown; anything else -> fallback."""
    problems: list[str] = []
    if not str(answer.summary).strip():
        problems.append("empty summary")
    if not ledger.facts:
        problems.append("no tool was called: nothing to interpret")
    if len(answer.claims) > max_claims:
        problems.append(f"too many claims ({len(answer.claims)} > {max_claims})")

    texts = [answer.summary, getattr(answer, "conclusion", ""), getattr(answer, "recommendation", ""),
             answer.limitations, answer.missing] + [c.text for c in answer.claims]
    texts += [f.finding for f in getattr(answer, "agents", [])]
    if answer.chart:
        texts.append(answer.chart.title)
    bad = unsupported_numbers_loose(texts, ledger_texts(ledger, question))
    if bad:
        problems.append("numbers not in the tool outputs: " + ", ".join(bad[:8]))

    rows = {k.upper() for k in ledger.rows}
    facts = {k.upper() for k in ledger.facts}
    cited_r, cited_e = [], []
    for c in answer.claims:
        cited_r += [str(r).strip().upper() for r in c.row_ids]
        cited_e += [str(e).strip().upper() for e in c.evidence_ids]
    for t in texts:
        for kind, n in _ID.findall(str(t)):
            (cited_r if kind == "R" else cited_e).append(f"{kind}{n}")
    unknown = sorted({i for i in cited_r if i not in rows} | {i for i in cited_e if i not in facts})
    if unknown:
        problems.append("ids not in the evidence pack: " + ", ".join(unknown[:8]))

    for c in answer.claims:
        own = [str(r).strip().upper() for r in c.row_ids] + [str(e).strip().upper() for e in c.evidence_ids]
        own += [f"{k}{n}" for k, n in _ID.findall(c.text)]
        if not [i for i in own if i in rows or i in facts]:
            problems.append(f"claim without a valid citation: {c.text[:60]}")
    active = list(getattr(ledger, "agents", []) or [])
    for f in getattr(answer, "agents", []):
        if active and f.agent not in active:
            problems.append(f"finding from an agent that was not active: {f.agent}")
    if answer.enough_evidence and not answer.claims:
        problems.append("enough_evidence=true but no claims")

    if answer.chart is not None:
        from .ai_schema import CHART_FIELDS, CHART_TYPES

        ch = answer.chart
        fact = ledger.facts.get(str(ch.evidence_id).strip().upper()) or ledger.facts.get(ch.evidence_id)
        table = (fact or {}).get("table") or []
        cols = set(table[0]) if table else set()
        if ch.type not in CHART_TYPES:
            problems.append(f"chart type not allowed: {ch.type}")
        if not table:
            problems.append(f"chart evidence {ch.evidence_id} has no table")
        for f in (ch.x, ch.y, ch.color):
            if f is None:
                continue
            if f not in CHART_FIELDS:
                problems.append(f"chart field not allowed: {f}")
            elif table and f not in cols:
                problems.append(f"chart field not in {ch.evidence_id}: {f}")
        if ch.x == ch.y:
            problems.append("chart x and y are the same field")

    if lang:
        from .i18n import detect_language

        said = detect_language(answer.summary, default=lang)
        if said != lang:
            problems.append(f"answer language {said} != question language {lang}")
    return problems
