"""
Text and value normalization utilities.

Kept deliberately simple and deterministic (no ML) so behavior is
predictable and auditable. Anything fuzzier belongs in the matching layer.
"""
import re
import unicodedata
from typing import Optional


_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9а-яё\s]", re.IGNORECASE)

# Common unit / abbreviation normalizations (extend as needed)
_UNIT_REPLACEMENTS = {
    r"\bmm\b": "mm",
    r"\bcm\b": "cm",
    r"\bkg\b": "kg",
    r"\bpcs?\b": "pcs",
    r"\bpc\b": "pcs",
}


def clean_text(value: Optional[str]) -> str:
    """Lowercase, strip accents/punctuation noise, collapse whitespace."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none", "n/a", "-"):
        return ""

    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = _NON_ALNUM_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()

    for pattern, replacement in _UNIT_REPLACEMENTS.items():
        text = re.sub(pattern, replacement, text)

    return text


def clean_code(value: Optional[str]) -> str:
    """Normalize an item/government code: uppercase, strip whitespace."""
    if value is None:
        return ""
    text = str(value).strip().upper()
    if text.lower() in ("nan", "none", ""):
        return ""
    return text


def to_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").replace(" ", ""))
    except (ValueError, TypeError):
        return None


def build_normalized_text(*parts: Optional[str]) -> str:
    """Concatenate several fields into one normalized bag-of-words string."""
    cleaned = [clean_text(p) for p in parts if p]
    return " ".join(c for c in cleaned if c)
