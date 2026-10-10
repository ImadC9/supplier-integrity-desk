"""Useful queue outcomes tested through its public interface."""

import unittest
from io import BytesIO

import pandas as pd

from supplier_agent.io import load_supplier_master, validate_supplier_master
from supplier_agent.normalize import normalize_company_name
from supplier_agent.quality import QualityConfig, check_quality
from supplier_agent.triage import dataset_fingerprint, scan_suppliers
from tests.test_detector import supplier_frame


class TriageTests(unittest.TestCase):
    def test_queue_combines_pair_and_quality_evidence_without_raw_identifiers(self):
        frame = supplier_frame()
        frame.loc[2, "SUPPLIER_NAME"] = ""
        result = scan_suppliers(frame)
        self.assertEqual(result.supplier_count, 3)
        self.assertEqual(set(result.queue.TYPE), {"DUPLICATE", "DATA_QUALITY"})
        self.assertTrue(result.queue.FINDING_ID.is_unique)
        self.assertEqual(result.queue.iloc[0].PRIORITY, "HIGH")
        self.assertNotIn("GB01 TEST 123", result.queue.to_json())
        self.assertNotIn("GB 999 111", result.queue.to_json())
        self.assertEqual(set(result.queue.FINDING_ID), set(scan_suppliers(frame.iloc[::-1]).queue.FINDING_ID))
        self.assertEqual(result.dataset_id, dataset_fingerprint(frame.iloc[::-1]))

    def test_missing_scope_never_creates_a_duplicate(self):
        frame = supplier_frame().iloc[:2].copy()
        frame["COUNTRY_CODE"] = ""
        frame["BANK_COUNTRY"] = ""
        result = scan_suppliers(frame)
        self.assertTrue(result.duplicate_pairs.empty)
        self.assertIn("BANK_SCOPE_MISSING", set(result.quality_findings.RULE_CODE))

    def test_quality_rules_are_configurable_and_do_not_assume_tax_id_is_mandatory(self):
        frame = supplier_frame().iloc[2:].copy()
        frame["ACTIVE_STATUS"] = "INACTIVE"
        frame["PO_COUNT_12M"] = "1.5"
        frame["SPEND_12M_USD"] = "12"
        findings = check_quality(frame, QualityConfig(required_fields=("TAX_ID",)))
        self.assertIn("TAX_ID", set(findings.FIELD))
        self.assertIn("ACTIVITY_VALUE", set(findings.RULE_CODE))
        self.assertIn("INACTIVE_WITH_ACTIVITY", set(findings.RULE_CODE))
        default = check_quality(frame)
        self.assertEqual(default[default.FIELD.eq("TAX_ID")].iloc[0].RULE_CODE, "MISSING_IDENTIFIER")

    def test_blank_and_case_colliding_ids_are_rejected(self):
        frame = supplier_frame()
        frame.loc[0, "SUPPLIER_ID"] = "  "
        with self.assertRaisesRegex(ValueError, "blank"):
            validate_supplier_master(frame)
        frame.loc[0, "SUPPLIER_ID"] = " s2 "
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_supplier_master(frame)

    def test_upload_only_reads_supplier_master_and_preserves_na_country(self):
        frame = supplier_frame()
        frame.loc[0, "COUNTRY_CODE"] = "NA"
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            frame.to_excel(writer, sheet_name="Supplier_Master", index=False)
            pd.DataFrame({"SECRET_LABEL": ["never-read-this"]}).to_excel(writer, sheet_name="Ground_Truth", index=False)
        loaded = load_supplier_master(buffer.getvalue())
        self.assertEqual(loaded.iloc[0].COUNTRY_CODE, "NA")
        self.assertNotIn("SECRET_LABEL", loaded.columns)
        self.assertNotIn("never-read-this", scan_suppliers(loaded).queue.to_json())

    def test_international_names_are_not_erased(self):
        self.assertEqual(normalize_company_name("شركة النور"), "شركة النور")

    def test_clean_unrelated_records_return_an_empty_queue(self):
        frame = supplier_frame().iloc[2:].copy()
        frame["TAX_ID"] = "GB123456789"
        frame["ASSOCIATION_NO"] = "DISTINCT-REG"
        frame["BANK_ACCOUNT"] = "12345678"  # a domestic account number, not an IBAN
        self.assertTrue(scan_suppliers(frame).queue.empty)
