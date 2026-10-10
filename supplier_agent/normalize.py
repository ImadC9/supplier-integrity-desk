"""Pure normalization functions used before supplier comparison."""

import re
import unicodedata

# Legal-form tokens removed from the END of a name before comparison
# ("Acme Trading Ltd" ~ "ACME TRADING LIMITED"). Multi-word forms such as
# "Pty Ltd", "SA de CV" or "Sp. z o.o." are removed token by token.
LEGAL_SUFFIXES = {
    # English-speaking countries
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "limited",
    "ltd",
    "llc",
    "llp",
    "lp",
    "plc",
    "pty",
    "pvt",
    "private",
    "pte",
    "group",
    "holdings",
    # Continental Europe
    "ag",
    "gmbh",
    "kg",
    "ohg",
    "ug",
    "ev",
    "bv",
    "nv",
    "vof",
    "sa",
    "sas",
    "sasu",
    "sarl",
    "eurl",
    "snc",
    "sl",
    "slu",
    "srl",
    "spa",
    "sapa",
    "scs",
    "ab",
    "as",
    "asa",
    "aps",
    "oy",
    "oyj",
    "kft",
    "zrt",
    "doo",
    "ad",
    "sro",
    "spol",
    "sp",
    "z",
    "o",
    "oo",
    "lda",
    "bvba",
    "cv",
    "de",
    # Latin America, Middle East, Africa, Asia
    "ltda",
    "eireli",
    "sab",
    "fze",
    "fzco",
    "fzc",
    "wll",
    "bsc",
    "spc",
    "kk",
    "gk",
    "bhd",
    "sdn",
    "tbk",
    "jsc",
    "pjsc",
    "ojsc",
    "cjsc",
    "au",
}

ADDRESS_REPLACEMENTS = {
    "ave": "avenue",
    "av": "avenue",
    "blvd": "boulevard",
    "ctr": "centre",
    "rd": "road",
    "st": "street",
    "ste": "suite",
}


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "<na>"}:
        return ""
    return text


def normalize_text(value: object) -> str:
    """Lowercase text, remove accents/punctuation, and collapse whitespace."""
    text = unicodedata.normalize("NFKD", _safe_text(value))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"[\W_]+", " ", text.lower(), flags=re.UNICODE)
    return " ".join(text.split())


def normalize_identifier(value: object) -> str:
    """Keep only uppercase letters and digits for governed identifiers."""
    return re.sub(r"[^A-Z0-9]", "", _safe_text(value).upper())


def normalize_company_name(value: object) -> str:
    original = normalize_text(value).split()
    tokens = list(original)
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens or original)  # never reduce a name to nothing


def normalize_address(*values: object) -> str:
    tokens = normalize_text(" ".join(_safe_text(value) for value in values)).split()
    tokens = [ADDRESS_REPLACEMENTS.get(token, token) for token in tokens]
    return " ".join(tokens)


PLACEHOLDER_IDENTIFIERS = {
    "NA",
    "NONE",
    "NULL",
    "NIL",
    "TBD",
    "TBA",
    "UNKNOWN",
    "XXX",
    "XXXX",
    "NOTAPPLICABLE",
    "NOTAVAILABLE",
    "PENDING",
}


def is_placeholder_identifier(value: object) -> bool:
    """True for filler values such as "N/A", "0000" or "TBD"."""
    normalized = normalize_identifier(value)
    return bool(normalized) and (normalized in PLACEHOLDER_IDENTIFIERS or set(normalized) <= {"0", "9", "X"})


def normalize_match_identifier(value: object) -> str:
    """Identifier used for matching; placeholders become blank (never evidence)."""
    return "" if is_placeholder_identifier(value) else normalize_identifier(value)


PLACEHOLDER_EMAIL_USERS = {"noreply", "no-reply", "donotreply", "test", "none", "na", "n/a", "unknown", "dummy"}


def normalize_email(value: object) -> str:
    """Lower-cased e-mail address used for matching; fillers become blank."""
    text = _safe_text(value).lower().replace("mailto:", "").strip()
    if "@" not in text or " " in text:
        return ""
    user, _, domain = text.partition("@")
    if not user or "." not in domain or user in PLACEHOLDER_EMAIL_USERS or domain.endswith(("example.org", "test.com")):
        return ""
    return text


def normalize_phone(value: object) -> str:
    """Last nine digits of a phone number, so +44 20 7946 0000 and 020 7946 0000 match."""
    digits = re.sub(r"\D", "", _safe_text(value))
    if len(digits) < 7 or len(set(digits)) == 1:
        return ""
    return digits[-9:]
