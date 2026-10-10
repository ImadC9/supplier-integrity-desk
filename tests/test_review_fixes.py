"""Regression tests for the pre-publication review findings."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from supplier_agent.columns import apply_mapping, suggest_mapping
from supplier_agent.detector import DuplicateDetector
from supplier_agent.io import MAX_SUPPLIERS, validate_supplier_master
from supplier_agent.lookup import find_existing
from supplier_agent.profile import absent_fields
from supplier_agent.triage import scan_suppliers

ROOT = Path(__file__).resolve().parents[1]


class BlankRequiredFieldTests(unittest.TestCase):
    def test_single_supplier_with_blank_name_is_flagged(self):
        frame = pd.DataFrame([{"SUPPLIER_ID": "A", "SUPPLIER_NAME": "", "COUNTRY_CODE": "GB"}])
        findings = scan_suppliers(frame).quality_findings
        self.assertIn(("MISSING_REQUIRED", "SUPPLIER_NAME"), set(zip(findings.RULE_CODE, findings.FIELD, strict=True)))

    def test_mapped_but_entirely_blank_column_is_reported_for_every_row(self):
        raw = pd.DataFrame({"Vendor No": ["1", "2", "3"], "Vendor Name": ["A", "B", "C"], "City": ["", "", ""], "Country": ["GB"] * 3})
        frame = validate_supplier_master(apply_mapping(raw, suggest_mapping(raw.columns)))
        self.assertNotIn("CITY", absent_fields(frame))  # provided, just empty
        findings = scan_suppliers(frame).quality_findings
        self.assertEqual(len(findings[findings.RULE_CODE.eq("MISSING_REQUIRED") & findings.FIELD.eq("CITY")]), 3)

    def test_unmapped_column_is_still_treated_as_not_provided(self):
        raw = pd.DataFrame({"Vendor No": ["1", "2"], "Vendor Name": ["A", "B"], "Country": ["GB", "GB"]})
        frame = validate_supplier_master(apply_mapping(raw, suggest_mapping(raw.columns)))
        self.assertIn("CITY", absent_fields(frame))
        findings = scan_suppliers(frame).quality_findings
        self.assertTrue(findings[findings.FIELD.eq("CITY")].empty)


class LegacyCsvExportTests(unittest.TestCase):
    def test_legacy_entry_point_neutralises_formulas(self):
        with TemporaryDirectory() as temp:
            source, output = Path(temp) / "suppliers.csv", Path(temp) / "pairs.csv"
            pd.DataFrame(
                [
                    {"SUPPLIER_ID": "1", "SUPPLIER_NAME": "=1+1", "COUNTRY_CODE": "GB", "TAX_ID": "T1"},
                    {"SUPPLIER_ID": "2", "SUPPLIER_NAME": "=1+1", "COUNTRY_CODE": "GB", "TAX_ID": "T1"},
                ]
            ).to_csv(source, index=False)
            subprocess.run(
                [sys.executable, "-m", "supplier_agent.cli", "--input", str(source), "--output", str(output)],
                check=True,
                cwd=ROOT,
                capture_output=True,
            )
            exported = pd.read_csv(output, dtype=str, keep_default_na=False)
            self.assertTrue(exported["SUPPLIER_NAME_A"].str.startswith("'=").all())


class SharedIdentifierTests(unittest.TestCase):
    def test_widely_shared_tax_id_adds_no_points_even_when_names_match(self):
        rows = [
            {"SUPPLIER_ID": str(i), "SUPPLIER_NAME": f"Company {i} {i * 7919}", "COUNTRY_CODE": "GB", "TAX_ID": "GB123456789"}
            for i in range(24)
        ]
        rows += [
            {"SUPPLIER_ID": "X1", "SUPPLIER_NAME": "Acme Trading Ltd", "COUNTRY_CODE": "GB", "TAX_ID": "GB123456789"},
            {"SUPPLIER_ID": "X2", "SUPPLIER_NAME": "Acme Trading Ltd", "COUNTRY_CODE": "GB", "TAX_ID": "GB123456789"},
        ]
        frame = validate_supplier_master(pd.DataFrame(rows))
        detector = DuplicateDetector()
        prepared = detector.prepare(frame).set_index("SUPPLIER_ID", drop=False)
        result = detector.score_pair(prepared.loc["X1"], prepared.loc["X2"])
        self.assertFalse(result["SAME_TAX_ID"])
        self.assertLessEqual(result["DUPLICATE_SCORE"], 20.0)  # name only

    def test_identifier_shared_by_a_few_records_still_counts(self):
        rows = [
            {"SUPPLIER_ID": "1", "SUPPLIER_NAME": "Acme Ltd", "COUNTRY_CODE": "GB", "TAX_ID": "GB999"},
            {"SUPPLIER_ID": "2", "SUPPLIER_NAME": "ACME Limited", "COUNTRY_CODE": "GB", "TAX_ID": "GB999"},
        ]
        pairs = DuplicateDetector().detect(validate_supplier_master(pd.DataFrame(rows)))
        self.assertTrue(pairs.iloc[0]["SAME_TAX_ID"])


class LookupLimitTests(unittest.TestCase):
    def test_lookup_works_on_a_master_at_the_size_limit(self):
        count = MAX_SUPPLIERS
        master = pd.DataFrame(
            {"SUPPLIER_ID": [f"V{i}" for i in range(count)], "SUPPLIER_NAME": [f"Firm {i}" for i in range(count)], "COUNTRY_CODE": "GB"}
        )
        matches = find_existing(master, {"SUPPLIER_NAME": "Firm 5", "COUNTRY_CODE": "GB"})
        self.assertIn("V5", set(matches["SUPPLIER_ID"]))


if __name__ == "__main__":
    unittest.main()
