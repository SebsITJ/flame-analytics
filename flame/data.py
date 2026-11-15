"""Load the experiments CSV, whatever encoding or separator it comes in.

The original text values are kept untouched. Numeric versions of the oxygen and
pressure columns are added next to them (``oxigeno_num``, ``presion_num``).
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import config
from .enrich import enrich_frame

ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")  # latin-1 never fails, so it goes last
DELIMITERS = (",", ";", "\t", "|")

# English or alternative headers mapped to the official Spanish names.
COLUMN_ALIASES = {
    "experiment": "experimento",
    "fuel": "combustible",
    "oxygen": "oxigeno",
    "o2": "oxigeno",
    "pressure": "presion",
    "result": "resultado",
    "phase": "fase",
    "source": "fuente",
}

PHASE_ALIASES = {
    "prevent": "prevent",
    "prevention": "prevent",
    "prevencion": "prevent",
    "detect": "detect",
    "detection": "detect",
    "deteccion": "detect",
    "extinguish": "extinguish",
    "extinction": "extinguish",
    "suppression": "extinguish",
    "suppress": "extinguish",
    "extincion": "extinguish",
    "supresion": "extinguish",
}

_NUMBER = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?)\s*(%|atm)?\s*$", re.IGNORECASE)


class DataError(ValueError):
    """The file cannot be used as the experiments table."""


@dataclass
class Dataset:
    df: pd.DataFrame
    encoding: str
    delimiter: str
    issues: list[str] = field(default_factory=list)

    @property
    def has_simulated(self) -> bool:
        return bool(self.df["simulated"].any())


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _normalize_header(name: str) -> str:
    key = _strip_accents(str(name)).strip().lower().replace(" ", "_")
    return COLUMN_ALIASES.get(key, key)


def _decode(raw: bytes) -> tuple[str, str]:
    for enc in ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise DataError("Could not decode the file.")  # unreachable with latin-1, kept for safety


def _guess_delimiter(text: str) -> str:
    header = text.splitlines()[0] if text.strip() else ""
    counts = {d: header.count(d) for d in DELIMITERS}
    best = max(counts, key=counts.get)
    if counts[best] == 0:
        raise DataError("The first line has no separator (comma, semicolon, tab or |).")
    return best


def to_number(value: str) -> float | None:
    """'21', '21 %', '0,7', '0.7 atm' -> float. Anything else -> None."""
    text = str(value).strip()
    if not text:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")  # decimal comma (common in cp1252 / Spanish Excel files)
    match = _NUMBER.match(text)
    return float(match.group(1)) if match else None


def load_dataset(source: str | Path | bytes) -> Dataset:
    raw = source if isinstance(source, bytes) else Path(source).read_bytes()
    text, encoding = _decode(raw)
    if not text.strip():
        raise DataError("The file is empty.")
    delimiter = _guess_delimiter(text)

    df = pd.read_csv(
        io.StringIO(text),
        sep=delimiter,
        dtype=str,
        keep_default_na=False,
        skipinitialspace=True,
    )
    df.columns = [_normalize_header(c) for c in df.columns]

    missing = [c for c in config.REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise DataError(
            "Missing columns: " + ", ".join(missing)
            + ". Expected: " + " | ".join(config.REQUIRED_COLUMNS)
        )

    df = df.apply(lambda col: col.astype(str).str.strip())
    df = df[~(df[config.REQUIRED_COLUMNS] == "").all(axis=1)].reset_index(drop=True)
    if df.empty:
        raise DataError("The file has headers but no rows.")

    issues: list[str] = []
    df["row_id"] = [f"R{i + 1}" for i in range(len(df))]

    df["oxigeno_num"] = df["oxigeno"].map(to_number).astype(float)
    df["presion_num"] = df["presion"].map(to_number).astype(float)
    for col, num_col, label in (("oxigeno", "oxigeno_num", "oxygen"), ("presion", "presion_num", "pressure")):
        bad = df[(df[col] != "") & df[num_col].isna()]
        for _, row in bad.iterrows():
            issues.append(f"{row.row_id}: {label} value '{row[col]}' is not a plain number; ignored in filters.")

    out_of_range = df[(df["oxigeno_num"] < 0) | (df["oxigeno_num"] > 100)]
    for _, row in out_of_range.iterrows():
        issues.append(f"{row.row_id}: oxygen {row.oxigeno} is outside 0–100 %.")

    phase_key = df["fase"].map(lambda v: _strip_accents(v).lower().strip())
    df["fase"] = phase_key.map(lambda v: PHASE_ALIASES.get(v, v))
    for _, row in df[~df["fase"].isin(config.PHASES)].iterrows():
        issues.append(f"{row.row_id}: phase '{row.fase}' is not prevent / detect / extinguish.")

    for _, row in df[df["fuente"] == ""].iterrows():
        issues.append(f"{row.row_id}: no source (DOI or link).")

    tag = config.SIMULATED_TAG.lower()
    df["simulated"] = df[config.REQUIRED_COLUMNS].apply(
        lambda r: any(tag in str(v).lower() for v in r), axis=1
    )

    df = enrich_frame(df)

    return Dataset(df=df, encoding=encoding, delimiter=delimiter, issues=issues)


def source_url(source: str) -> str | None:
    """Turn a DOI or link into a clickable URL. Returns None when it is neither."""
    text = str(source).strip()
    if text.lower().startswith(("http://", "https://")):
        return text
    doi = re.sub(r"^(doi:\s*|https?://(dx\.)?doi\.org/)", "", text, flags=re.IGNORECASE)
    if re.match(r"^10\.\d{4,9}/\S+$", doi):
        return f"https://doi.org/{doi}"
    return None
