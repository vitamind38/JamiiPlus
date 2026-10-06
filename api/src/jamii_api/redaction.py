"""Rule-based masking of names and numbers, applied before any report text is stored.

This is the always-on first pass. In assisted mode the workers add a second pass with a
named-entity model; if that fails the report is held for manual redaction.
"""

import re
from dataclasses import dataclass

NAME = "[NAME]"
NUMBER = "[NUMBER]"
EMAIL = "[EMAIL]"

# Words that introduce a person in Swahili, Sheng and English. Case-insensitive.
_HONORIFICS = (
    r"mama|baba|bw\.?|bwana|bi\.?|bibi|mzee|mze|dada|kaka|mwalimu|nyanya|shosho|cucu|daktari|dkt\.?|"
    r"mr\.?|mrs\.?|ms\.?|miss|dr\.?|mtoto\s+wa|mke\s+wa|mume\s+wa"
)
# Phrases after which the next one or two words are a name, whatever their case.
_NAME_CUES = (
    r"jina\s+lake\s+ni|jina\s+lake|anaitwa|aitwaye|wanaitwa|kwa\s+jina|majina\s+yao\s+ni|"
    r"his\s+name\s+is|her\s+name\s+is|their\s+names\s+are|named|called|by\s+the\s+name"
)
_WORD = r"[A-Za-z][A-Za-z'\-]+"
_CAP_WORD = r"[A-Z][A-Za-z'\-]+"

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_CUE_RE = re.compile(rf"(?i:\b(?:{_NAME_CUES})\b)\s+({_WORD})(\s+{_CAP_WORD})?")
_HONORIFIC_RE = re.compile(rf"(?i:\b(?:{_HONORIFICS}))\s+({_CAP_WORD})(\s+{_CAP_WORD})?")
# A run of digits, allowing the spaces, dots and dashes people put inside phone numbers.
_DIGITS_RE = re.compile(r"\+?\d[\d\s.\-]{3,}\d")
_CURRENCY_BEFORE = re.compile(r"(?i)(ksh|kes|sh|shs|shilingi|bob)\.?\s*$")
_CURRENCY_AFTER = re.compile(r"(?i)^\s*(/=|/-|shillings|shilingi|bob|ksh|kes)")


@dataclass(frozen=True)
class Redacted:
    text: str
    masked: int


def _mask_digits(text: str) -> tuple[str, int]:
    out: list[str] = []
    last = 0
    count = 0
    for m in _DIGITS_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        is_money = _CURRENCY_BEFORE.search(text[: m.start()]) or _CURRENCY_AFTER.search(text[m.end() :])
        # Phones (9+ digits) and ID numbers (7-8) always go. Five or six digits go unless
        # they are an amount of money, which is evidence of a cost barrier.
        if len(digits) >= 7 or (len(digits) >= 5 and not is_money):
            out.append(text[last : m.start()])
            out.append(NUMBER)
            last = m.end()
            count += 1
    out.append(text[last:])
    return "".join(out), count


def redact(text: str | None) -> Redacted:
    if not text:
        return Redacted(text or "", 0)
    total = 0

    text, n = _EMAIL_RE.subn(EMAIL, text)
    total += n

    def _cue(m: re.Match[str]) -> str:
        nonlocal total
        total += 1
        return m.group(0)[: m.start(1) - m.start(0)] + NAME

    def _honorific(m: re.Match[str]) -> str:
        nonlocal total
        total += 1
        return m.group(0)[: m.start(1) - m.start(0)] + NAME

    text = _CUE_RE.sub(_cue, text)
    text = _HONORIFIC_RE.sub(_honorific, text)
    text, n = _mask_digits(text)
    total += n
    return Redacted(text, total)
