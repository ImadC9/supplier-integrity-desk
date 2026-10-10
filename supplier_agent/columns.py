"""Map arbitrary supplier/vendor exports onto the canonical schema.

ERP exports rarely share column names: SAP calls the vendor number ``LIFNR``,
other systems say ``Vendor No`` or ``Supplier Code``. This module suggests a
mapping from common synonyms and applies a mapping the user has confirmed.
Matching is done on a simplified header key, so ``Vendor-Name`` and
``vendor name`` are treated the same.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    description: str
    synonyms: tuple[str, ...]
    required: bool = False
    used_for_matching: bool = False


FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "SUPPLIER_ID",
        "Supplier ID",
        "Unique key of the supplier record.",
        (
            "supplier id",
            "supplier no",
            "supplier number",
            "supplier code",
            "vendor id",
            "vendor no",
            "vendor number",
            "vendor code",
            "vendor",
            "lifnr",
            "creditor",
            "creditor id",
            "account id",
            "id",
        ),
        required=True,
    ),
    FieldSpec(
        "SUPPLIER_NAME",
        "Supplier name",
        "Legal or display name.",
        ("supplier name", "vendor name", "name", "name1", "company name", "legal name", "supplier", "business name", "creditor name"),
        required=True,
        used_for_matching=True,
    ),
    FieldSpec(
        "TAX_ID",
        "Tax ID / VAT",
        "Tax or VAT registration number.",
        (
            "tax id",
            "tax number",
            "vat",
            "vat id",
            "vat number",
            "vat no",
            "vat registration",
            "tin",
            "ein",
            "stcd1",
            "stceg",
            "fiscal code",
            "nif",
            "tax registration",
        ),
        used_for_matching=True,
    ),
    FieldSpec(
        "ASSOCIATION_NO",
        "Registration number",
        "Company / trade-register number.",
        (
            "association no",
            "association number",
            "registration number",
            "registration no",
            "company registration",
            "company number",
            "reg no",
            "trade register",
            "chamber of commerce",
            "coc number",
            "kvk",
            "siret",
            "siren",
            "crn",
        ),
        used_for_matching=True,
    ),
    FieldSpec(
        "COUNTRY_CODE",
        "Country",
        "Country code (ISO-2 recommended). Matching happens within a country.",
        ("country code", "country", "country iso", "iso country", "land1", "ctry", "nation"),
        used_for_matching=True,
    ),
    FieldSpec(
        "ADDRESS_1",
        "Address line 1",
        "Street and number.",
        ("address 1", "address1", "address line 1", "address", "street", "street address", "stras", "address street"),
        used_for_matching=True,
    ),
    FieldSpec(
        "ADDRESS_2",
        "Address line 2",
        "Building, unit or suite.",
        ("address 2", "address2", "address line 2", "street 2", "street2", "building", "suite"),
        used_for_matching=True,
    ),
    FieldSpec("CITY", "City", "City or town.", ("city", "town", "ort01", "locality", "municipality"), used_for_matching=True),
    FieldSpec(
        "POSTAL_CODE",
        "Postal code",
        "ZIP / postal code.",
        ("postal code", "postcode", "post code", "zip", "zip code", "pstlz"),
        used_for_matching=True,
    ),
    FieldSpec(
        "BANK_COUNTRY",
        "Bank country",
        "Country of the bank account.",
        ("bank country", "bank country code", "banks", "bank ctry"),
        used_for_matching=True,
    ),
    FieldSpec(
        "BANK_ACCOUNT",
        "Bank account / IBAN",
        "Account number or IBAN.",
        ("bank account", "iban", "account number", "bank account number", "bankn", "bank acct"),
        used_for_matching=True,
    ),
    FieldSpec(
        "COMPANY",
        "Company / entity",
        "Buying company or legal entity.",
        ("company", "company code", "bukrs", "entity", "legal entity", "business unit"),
    ),
    FieldSpec("SITE", "Site", "Site, plant or location code.", ("site", "plant", "location", "werks")),
    FieldSpec("ACTIVE_STATUS", "Status", "ACTIVE or INACTIVE.", ("active status", "status", "active", "supplier status", "vendor status")),
    FieldSpec("SUPPLIER_CATEGORY", "Category", "Supplier category.", ("supplier category", "category", "vendor category", "commodity")),
    FieldSpec(
        "PURCHASE_GROUP",
        "Purchase group",
        "Purchasing group / buyer group.",
        ("purchase group", "purchasing group", "ekgrp", "buyer group"),
    ),
    FieldSpec(
        "CREATED_DATE", "Created date", "Date the record was created.", ("created date", "creation date", "created", "created on", "erdat")
    ),
    FieldSpec(
        "LAST_PO_DATE", "Last PO date", "Date of the most recent purchase order.", ("last po date", "last order date", "last purchase date")
    ),
    FieldSpec(
        "PO_COUNT_12M",
        "POs (12 months)",
        "Purchase orders in the last 12 months.",
        ("po count 12m", "po count", "orders 12m", "number of pos", "po count last 12 months"),
    ),
    FieldSpec(
        "SPEND_12M_USD",
        "Spend (12 months)",
        "Spend in the last 12 months.",
        ("spend 12m usd", "spend 12m", "spend", "annual spend", "spend last 12 months"),
    ),
    FieldSpec("CURRENCY", "Currency", "Order currency (ISO-3).", ("currency", "order currency", "waers")),
    FieldSpec(
        "EMAIL",
        "Email",
        "Contact or accounts-payable email.",
        ("email", "e mail", "email address", "ap email", "contact email", "smtp addr"),
        used_for_matching=True,
    ),
    FieldSpec(
        "PHONE",
        "Phone",
        "Phone number.",
        ("phone", "telephone", "phone number", "tel", "telf1", "mobile"),
        used_for_matching=True,
    ),
)

FIELD_BY_NAME = {spec.name: spec for spec in FIELDS}
REQUIRED_FIELDS = tuple(spec.name for spec in FIELDS if spec.required)
MATCHING_FIELDS = tuple(spec.name for spec in FIELDS if spec.used_for_matching)


PROVIDED_FIELDS_ATTR = "provided_fields"


def header_key(value: object) -> str:
    """Simplify a header so spacing, case and punctuation do not matter."""
    return re.sub(r"[^a-z0-9]+", " ", str(value).strip().lower()).strip()


def suggest_mapping(columns: list[str] | pd.Index) -> dict[str, str | None]:
    """Return ``{canonical_field: source_column or None}``.

    Exact canonical names win, then synonyms in priority order. A source column
    is used at most once.
    """
    source = [str(column) for column in columns]
    by_key: dict[str, str] = {}
    for column in source:
        by_key.setdefault(header_key(column), column)
    used: set[str] = set()
    mapping: dict[str, str | None] = {spec.name: None for spec in FIELDS}

    # Pass 1: canonical names (``SUPPLIER_ID``, ``supplier id``...).
    for spec in FIELDS:
        column = by_key.get(header_key(spec.name))
        if column and column not in used:
            mapping[spec.name] = column
            used.add(column)
    # Pass 2: synonyms, in declared priority order.
    for spec in FIELDS:
        if mapping[spec.name]:
            continue
        for synonym in spec.synonyms:
            column = by_key.get(header_key(synonym))
            if column and column not in used:
                mapping[spec.name] = column
                used.add(column)
                break
    return mapping


def missing_required(mapping: dict[str, str | None]) -> list[str]:
    return [name for name in REQUIRED_FIELDS if not mapping.get(name)]


def apply_mapping(frame: pd.DataFrame, mapping: dict[str, str | None]) -> pd.DataFrame:
    """Return a frame with canonical columns; unmapped canonical fields are blank.

    Source columns that are not mapped are kept under their original name when
    they do not collide with a canonical name, so nothing is silently lost.
    """
    missing = missing_required(mapping)
    if missing:
        labels = ", ".join(FIELD_BY_NAME[name].label for name in missing)
        raise ValueError(f"Map the required column(s) before scanning: {labels}.")
    chosen = [column for column in mapping.values() if column]
    if len(chosen) != len(set(chosen)):
        raise ValueError("Each source column can be mapped to only one field.")
    for column in chosen:
        if column not in frame.columns:
            raise ValueError(f"Column not found in the file: {column}")
    result = pd.DataFrame(index=frame.index)
    for spec in FIELDS:
        column = mapping.get(spec.name)
        result[spec.name] = frame[column] if column else ""
    canonical = set(result.columns)
    for column in frame.columns:
        name = str(column).strip()
        if column not in chosen and name.upper() not in canonical:
            result[name] = frame[column]
    # Which canonical fields the source actually provided (a mapped column can still be entirely blank).
    result.attrs[PROVIDED_FIELDS_ATTR] = tuple(sorted(spec.name for spec in FIELDS if mapping.get(spec.name)))
    return result


def mapped_fields(mapping: dict[str, str | None]) -> set[str]:
    return {name for name, column in mapping.items() if column}
