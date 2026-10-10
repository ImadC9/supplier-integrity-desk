"""Explainable data-quality rules; defaults are demo rules, not legal standards."""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field

import pandas as pd

from .normalize import is_placeholder_identifier
from .taxid import tax_id_problem
from .validators import iban_problem


@dataclass(frozen=True)
class QualityConfig:
    required_fields: tuple[str, ...] = ("SUPPLIER_NAME", "COUNTRY_CODE", "ADDRESS_1", "CITY")
    review_missing_identifiers: bool = True
    check_code_formats: bool = True
    check_placeholders: bool = True
    check_ibans: bool = True
    check_tax_ids: bool = True
    # Columns the source file did not provide at all; they are not reported
    # row by row (that would flood the queue with one finding per supplier).
    absent_fields: frozenset[str] = dataclass_field(default_factory=frozenset)


RULE_DESCRIPTIONS = {
    "MISSING_REQUIRED": "A required field is blank.",
    "MISSING_IDENTIFIER": "Tax ID or registration number is blank, so exact matching cannot use it.",
    "PLACEHOLDER_IDENTIFIER": "An identifier holds a filler value such as N/A or 0000.",
    "COUNTRY_FORMAT": "Country code is not two letters.",
    "CURRENCY_FORMAT": "Currency is not a three-letter code.",
    "BANK_SCOPE_MISSING": "A bank account has no bank country.",
    "TAX_ID_FORMAT": "A tax / VAT number does not match its country's format or check digit.",
    "INVALID_IBAN": "An IBAN fails its length or mod-97 check-digit test (usually a typo).",
    "ACTIVITY_VALUE": "PO count or spend is not a valid non-negative number.",
    "INACTIVE_WITH_ACTIVITY": "Inactive supplier with purchasing activity in the last 12 months.",
}


QUALITY_COLUMNS = ["SUPPLIER_ID", "SUPPLIER_NAME", "RULE_CODE", "FIELD", "PRIORITY", "SUMMARY", "ACTION"]


def check_quality(suppliers: pd.DataFrame, config: QualityConfig | None = None) -> pd.DataFrame:
    config = config or QualityConfig()
    findings = []
    for row in suppliers.fillna("").to_dict("records"):

        def add(code: str, field: str, priority: str, summary: str, action: str) -> None:
            findings.append(
                {
                    "SUPPLIER_ID": row["SUPPLIER_ID"],
                    "SUPPLIER_NAME": row.get("SUPPLIER_NAME", ""),
                    "RULE_CODE": code,
                    "FIELD": field,
                    "PRIORITY": priority,
                    "SUMMARY": summary,
                    "ACTION": action,
                }
            )

        for field in config.required_fields:
            if field in config.absent_fields:
                continue
            if not str(row.get(field, "")).strip():
                add(
                    "MISSING_REQUIRED",
                    field,
                    "HIGH" if field in {"SUPPLIER_NAME", "COUNTRY_CODE"} else "MEDIUM",
                    f"{field} is missing.",
                    "Ask the data owner to complete this field.",
                )
        if config.review_missing_identifiers:
            for field in ("TAX_ID", "ASSOCIATION_NO"):
                if field in config.absent_fields:
                    continue
                if not str(row.get(field, "")).strip() and field not in config.required_fields:
                    add(
                        "MISSING_IDENTIFIER",
                        field,
                        "LOW",
                        f"{field} is missing; exact-match coverage is reduced.",
                        "Check whether this identifier applies to this supplier. It is not universally mandatory.",
                    )
        if config.check_placeholders:
            for field in ("TAX_ID", "ASSOCIATION_NO", "BANK_ACCOUNT"):
                if is_placeholder_identifier(row.get(field, "")):
                    add(
                        "PLACEHOLDER_IDENTIFIER",
                        field,
                        "LOW",
                        f"{field} holds a placeholder value.",
                        "Replace the filler with the real identifier or leave it blank; placeholders are ignored for matching.",
                    )
        for field in ("COUNTRY_CODE", "BANK_COUNTRY") if config.check_code_formats else ():
            value = str(row.get(field, "")).strip()
            if value and not re.fullmatch(r"[A-Za-z]{2}", value):
                add(
                    "COUNTRY_FORMAT",
                    field,
                    "MEDIUM",
                    f"{field} is not a two-letter code.",
                    "Verify the country code against your approved country list.",
                )
        currency = str(row.get("CURRENCY", "")).strip()
        if config.check_code_formats and currency and not re.fullmatch(r"[A-Za-z]{3}", currency):
            add(
                "CURRENCY_FORMAT",
                "CURRENCY",
                "MEDIUM",
                "CURRENCY is not a three-letter code.",
                "Verify the currency against your approved list; foreign currencies can be legitimate.",
            )
        if config.check_tax_ids and not is_placeholder_identifier(row.get("TAX_ID", "")):
            problem = tax_id_problem(row.get("COUNTRY_CODE", ""), row.get("TAX_ID", ""))
            if problem:
                add(
                    "TAX_ID_FORMAT",
                    "TAX_ID",
                    "MEDIUM",
                    f"TAX_ID {problem}.",
                    "Check the number against the supplier's invoice or the official registry (for EU VAT: VIES).",
                )
        if config.check_ibans:
            problem = iban_problem(row.get("BANK_ACCOUNT", ""))
            if problem:
                add(
                    "INVALID_IBAN",
                    "BANK_ACCOUNT",
                    "HIGH",
                    f"BANK_ACCOUNT is not a valid IBAN ({problem}).",
                    "Confirm the bank details with the supplier through a verified channel before the next payment.",
                )
        if str(row.get("BANK_ACCOUNT", "")).strip() and not str(row.get("BANK_COUNTRY", "")).strip():
            add(
                "BANK_SCOPE_MISSING",
                "BANK_COUNTRY",
                "HIGH",
                "A bank account has no bank country.",
                "Verify the bank country before comparing bank accounts.",
            )
        for field in ("PO_COUNT_12M", "SPEND_12M_USD"):
            value = str(row.get(field, "")).strip()
            if value:
                try:
                    number = float(value)
                    valid = number >= 0 and number != float("inf") and (field != "PO_COUNT_12M" or number.is_integer())
                except ValueError:
                    valid = False
                if not valid:
                    add(
                        "ACTIVITY_VALUE",
                        field,
                        "MEDIUM",
                        f"{field} is not a valid nonnegative value.",
                        "Verify the activity value and its source.",
                    )
        status = str(row.get("ACTIVE_STATUS", "")).strip().upper()
        if status == "INACTIVE":
            orders = pd.to_numeric(row.get("PO_COUNT_12M", ""), errors="coerce")
            spend = pd.to_numeric(row.get("SPEND_12M_USD", ""), errors="coerce")
            if orders > 0 or spend > 0:
                add(
                    "INACTIVE_WITH_ACTIVITY",
                    "ACTIVE_STATUS",
                    "LOW",
                    "Inactive supplier has activity in the last 12 months.",
                    "Check timing and lifecycle status; historic activity can be legitimate.",
                )
    return pd.DataFrame(findings, columns=QUALITY_COLUMNS)
