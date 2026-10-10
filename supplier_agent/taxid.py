"""Country-specific tax / VAT identifier checks.

Each rule checks the published *format* of a country's business tax number and,
where the algorithm is public and stable, its check digit. A passing check
means the number is well-formed — not that it is registered or belongs to this
supplier (use VIES, HMRC or the local registry for that).

Values may be written with or without the country prefix and with spaces,
dots, dashes or slashes (``DE 123.456.789``, ``12-3456789``).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass


def _digits(text: str) -> list[int]:
    return [int(char) for char in text]


def _de(number: str) -> bool:  # ISO 7064 MOD 11,10
    product = 10
    for digit in _digits(number[:8]):
        total = (digit + product) % 10 or 10
        product = (2 * total) % 11
    return (11 - product) % 10 == int(number[8])


def _fr(number: str) -> bool:  # key = (12 + 3 * (SIREN mod 97)) mod 97
    key, siren = number[:2], number[2:]
    return not key.isdigit() or int(key) == (12 + 3 * (int(siren) % 97)) % 97


def _be(number: str) -> bool:
    return 97 - int(number[:8]) % 97 == int(number[8:])


def _it(number: str) -> bool:  # Luhn on the 11-digit partita IVA
    total = 0
    for index, digit in enumerate(_digits(number[:10])):
        if index % 2:
            digit *= 2
            digit -= 9 if digit > 9 else 0
        total += digit
    return (10 - total % 10) % 10 == int(number[10])


def _pl(number: str) -> bool:
    weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    check = sum(w * d for w, d in zip(weights, _digits(number[:9]), strict=True)) % 11
    return check != 10 and check == int(number[9])


def _au(number: str) -> bool:  # ABN: subtract 1 from the first digit, weighted sum divisible by 89
    weights = (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19)
    digits = _digits(number)
    digits[0] -= 1
    return sum(w * d for w, d in zip(weights, digits, strict=True)) % 89 == 0


def _br(number: str) -> bool:  # CNPJ two mod-11 check digits
    digits = _digits(number)
    for size in (12, 13):
        weights = list(range(size - 7, 1, -1)) + list(range(9, 1, -1))
        remainder = sum(w * d for w, d in zip(weights, digits[:size], strict=True)) % 11
        if digits[size] != (0 if remainder < 2 else 11 - remainder):
            return False
    return True


@dataclass(frozen=True)
class TaxIdRule:
    pattern: str
    example: str
    checksum: Callable[[str], bool] | None = None
    prefixes: tuple[str, ...] = ()

    def matches(self, body: str) -> bool:
        return re.fullmatch(self.pattern, body) is not None


RULES: dict[str, TaxIdRule] = {
    # European Union VAT numbers (VIES formats)
    "AT": TaxIdRule(r"U\d{8}", "ATU12345678"),
    "BE": TaxIdRule(r"[01]\d{9}", "BE0123456749", _be),
    "BG": TaxIdRule(r"\d{9,10}", "BG123456789"),
    "CY": TaxIdRule(r"\d{8}[A-Z]", "CY12345678X"),
    "CZ": TaxIdRule(r"\d{8,10}", "CZ12345678"),
    "DE": TaxIdRule(r"\d{9}", "DE136695976", _de),
    "DK": TaxIdRule(r"\d{8}", "DK12345678"),
    "EE": TaxIdRule(r"\d{9}", "EE123456789"),
    "ES": TaxIdRule(r"[A-Z0-9]\d{7}[A-Z0-9]", "ESB12345678"),
    "FI": TaxIdRule(r"\d{8}", "FI12345678"),
    "FR": TaxIdRule(r"[A-HJ-NP-Z0-9]{2}\d{9}", "FR40303265045", _fr),
    "GR": TaxIdRule(r"\d{9}", "EL123456789", prefixes=("EL", "GR")),
    "HR": TaxIdRule(r"\d{11}", "HR12345678901"),
    "HU": TaxIdRule(r"\d{8}", "HU12345678"),
    "IE": TaxIdRule(r"\d{7}[A-W][A-IW]?|\d[A-Z+*]\d{5}[A-W]", "IE1234567T"),
    "IT": TaxIdRule(r"\d{11}", "IT00743110157", _it),
    "LT": TaxIdRule(r"\d{9}|\d{12}", "LT123456789"),
    "LU": TaxIdRule(r"\d{8}", "LU12345678"),
    "LV": TaxIdRule(r"\d{11}", "LV12345678901"),
    "MT": TaxIdRule(r"\d{8}", "MT12345678"),
    "NL": TaxIdRule(r"\d{9}B\d{2}", "NL123456789B01"),
    "PL": TaxIdRule(r"\d{10}", "PL5260250995", _pl),
    "PT": TaxIdRule(r"\d{9}", "PT123456789"),
    "RO": TaxIdRule(r"\d{2,10}", "RO1234567"),
    "SE": TaxIdRule(r"\d{10}01", "SE123456789701"),
    "SI": TaxIdRule(r"\d{8}", "SI12345678"),
    "SK": TaxIdRule(r"\d{10}", "SK1234567890"),
    # Other countries
    "GB": TaxIdRule(r"\d{9}|\d{12}|GD\d{3}|HA\d{3}", "GB123456789", prefixes=("GB", "XI")),
    "CH": TaxIdRule(r"\d{9}(MWST|TVA|IVA)?", "CHE-123.456.789 MWST", prefixes=("CHE",)),
    "NO": TaxIdRule(r"\d{9}(MVA)?", "NO123456789MVA"),
    "US": TaxIdRule(r"\d{9}", "12-3456789 (EIN)"),
    "CA": TaxIdRule(r"\d{9}([A-Z]{2}\d{4})?", "123456789RT0001 (BN)"),
    "MX": TaxIdRule(r"[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3}", "ABC010203AB1 (RFC)"),
    "BR": TaxIdRule(r"\d{14}", "11.222.333/0001-81 (CNPJ)", _br),
    "AU": TaxIdRule(r"\d{11}", "51 824 753 556 (ABN)", _au),
    "NZ": TaxIdRule(r"\d{8,9}", "123-456-789 (GST)"),
    "IN": TaxIdRule(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]", "27AAPFU0939F1ZV (GSTIN)"),
    "SG": TaxIdRule(r"\d{8}[A-Z]|\d{9}[A-Z]|[TSR]\d{2}[A-Z]{2}\d{4}[A-Z]", "201912345K (UEN)"),
    "JP": TaxIdRule(r"\d{13}", "T1234567890123 (corporate number)", prefixes=("T",)),
    "ZA": TaxIdRule(r"4\d{9}", "4123456789 (VAT)"),
    "AE": TaxIdRule(r"\d{15}", "100123456700003 (TRN)"),
}
# Alternative country codes people use for the same rule.
RULES["EL"] = RULES["GR"]
RULES["UK"] = RULES["GB"]
EU_PREFIXES = {
    code for code in RULES if code not in {"GB", "UK", "CH", "NO", "US", "CA", "MX", "BR", "AU", "NZ", "IN", "SG", "JP", "ZA", "AE"}
}


def compact(value: object) -> str:
    return re.sub(r"[\s.\-/,]", "", str(value or "")).upper()


def _strip_prefix(text: str, country: str, rule: TaxIdRule) -> str:
    for prefix in rule.prefixes or (country,):
        if text.startswith(prefix) and not rule.matches(text):
            return text[len(prefix) :]
    return text


def tax_id_problem(country: object, value: object) -> str | None:
    """Return why ``value`` is not a well-formed tax ID for ``country``, or None.

    Countries without a rule are not checked. A VAT number with another EU
    country's prefix is accepted when it is valid for that country (suppliers
    can hold foreign VAT registrations).
    """
    code = compact(country)[:3]
    rule = RULES.get(code) or RULES.get(code[:2])
    text = compact(value)
    if not rule or not text:
        return None
    foreign = text[:2]
    if foreign != code and foreign in EU_PREFIXES and foreign in RULES and code in EU_PREFIXES | {"GB", "UK"}:
        other = RULES[foreign]
        body = text[2:]
        if other.matches(body):
            return None if other.checksum is None or other.checksum(body) else f"check digit does not match ({foreign} VAT)"
    body = _strip_prefix(text, code, rule)
    if not rule.matches(body):
        return f"does not match the {code} format, e.g. {rule.example}"
    if rule.checksum is not None and not rule.checksum(body):
        return "check digit does not match"
    return None


def supported_countries() -> list[str]:
    return sorted(code for code in RULES if code not in {"EL", "UK"})
