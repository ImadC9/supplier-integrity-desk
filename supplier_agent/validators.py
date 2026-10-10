"""Format checks for identifiers that have a public, deterministic structure."""

from __future__ import annotations

import re

# ISO 13616 IBAN lengths per country (registry release; countries not listed are not checked).
IBAN_LENGTHS = {
    "AD": 24,
    "AE": 23,
    "AL": 28,
    "AT": 20,
    "AZ": 28,
    "BA": 20,
    "BE": 16,
    "BG": 22,
    "BH": 22,
    "BR": 29,
    "BY": 28,
    "CH": 21,
    "CR": 22,
    "CY": 28,
    "CZ": 24,
    "DE": 22,
    "DK": 18,
    "DO": 28,
    "EE": 20,
    "EG": 29,
    "ES": 24,
    "FI": 18,
    "FO": 18,
    "FR": 27,
    "GB": 22,
    "GE": 22,
    "GI": 23,
    "GL": 18,
    "GR": 27,
    "GT": 28,
    "HR": 21,
    "HU": 28,
    "IE": 22,
    "IL": 23,
    "IQ": 23,
    "IS": 26,
    "IT": 27,
    "JO": 30,
    "KW": 30,
    "KZ": 20,
    "LB": 28,
    "LC": 32,
    "LI": 21,
    "LT": 20,
    "LU": 20,
    "LV": 21,
    "MC": 27,
    "MD": 24,
    "ME": 22,
    "MK": 19,
    "MR": 27,
    "MT": 31,
    "MU": 30,
    "NL": 18,
    "NO": 15,
    "PK": 24,
    "PL": 28,
    "PS": 29,
    "PT": 25,
    "QA": 29,
    "RO": 24,
    "RS": 22,
    "SA": 24,
    "SC": 31,
    "SE": 24,
    "SI": 19,
    "SK": 24,
    "SM": 27,
    "ST": 25,
    "SV": 28,
    "TL": 23,
    "TN": 24,
    "TR": 26,
    "UA": 29,
    "VA": 22,
    "VG": 24,
    "XK": 20,
}

_IBAN_SHAPE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]+$")


def compact(value: object) -> str:
    return re.sub(r"[\s\-.]", "", str(value or "")).upper()


def looks_like_iban(value: object) -> bool:
    """True when the value has an IBAN shape for a country that uses IBANs."""
    text = compact(value)
    return bool(_IBAN_SHAPE.match(text)) and text[:2] in IBAN_LENGTHS


def _mod97(text: str) -> int:
    rearranged = text[4:] + text[:4]
    digits = "".join(str(int(char, 36)) for char in rearranged)
    remainder = 0
    for start in range(0, len(digits), 9):
        remainder = int(str(remainder) + digits[start : start + 9]) % 97
    return remainder


def iban_problem(value: object) -> str | None:
    """Return a short reason when an IBAN-shaped value is invalid, else None."""
    text = compact(value)
    if not looks_like_iban(text):
        return None
    expected = IBAN_LENGTHS[text[:2]]
    if len(text) != expected:
        return f"length {len(text)} instead of {expected} for {text[:2]}"
    if _mod97(text) != 1:
        return "check digits do not match"
    return None


def make_iban(country: str, bban: str) -> str:
    """Build a valid IBAN from a country code and a basic bank account number."""
    country, bban = country.upper(), compact(bban)
    check = 98 - _mod97(f"{country}00{bban}")
    return f"{country}{check:02d}{bban}"
