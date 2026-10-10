"""What's new, new-supplier check and database input."""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from supplier_agent.changes import change_summary, compare_snapshots, make_snapshot
from supplier_agent.database import describe, read_query, validate_query
from supplier_agent.io import load_supplier_master, validate_supplier_master
from supplier_agent.lookup import find_existing, validate_new_supplier, verdict
from supplier_agent.paths import EXAMPLE_DB, PREVIOUS_SAMPLE, SAMPLE_WORKBOOK
from supplier_agent.review_store import ReviewStore
from supplier_agent.triage import scan_suppliers


def frame(rows):
    base = {"COUNTRY_CODE": "GB", "BANK_COUNTRY": "GB"}
    return validate_supplier_master(pd.DataFrame([base | row for row in rows]))


class ChangeTests(unittest.TestCase):
    def test_new_resolved_added_removed_and_bank_change(self):
        old = frame(
            [
                {"SUPPLIER_ID": "A", "SUPPLIER_NAME": "Acme Ltd", "TAX_ID": "GB123456789", "BANK_ACCOUNT": "GB82WEST12345698765432"},
                {"SUPPLIER_ID": "B", "SUPPLIER_NAME": "Beta Ltd", "TAX_ID": "N/A"},
                {"SUPPLIER_ID": "C", "SUPPLIER_NAME": "Gone Ltd", "TAX_ID": "GB987654321"},
            ]
        )
        new = frame(
            [
                {"SUPPLIER_ID": "A", "SUPPLIER_NAME": "Acme Ltd", "TAX_ID": "GB123456789", "BANK_ACCOUNT": "GB33BUKB20201555555555"},
                {"SUPPLIER_ID": "B", "SUPPLIER_NAME": "Beta Ltd", "TAX_ID": "GB111222333"},
                {"SUPPLIER_ID": "D", "SUPPLIER_NAME": "ACME LIMITED", "TAX_ID": "GB123456789"},
            ]
        )
        changes = compare_snapshots(make_snapshot(scan_suppliers(old), old, salt="s"), make_snapshot(scan_suppliers(new), new, salt="s"))
        summary = change_summary(changes)
        self.assertEqual(summary["new_suppliers"], 1)
        self.assertEqual(summary["removed_suppliers"], 1)
        self.assertGreaterEqual(summary["new_findings"], 1)  # A ~ D duplicate
        self.assertGreaterEqual(summary["resolved_findings"], 1)  # B's placeholder fixed
        bank = changes[changes.SUPPLIER_ID.eq("A") & changes.CHANGE.eq("CHANGED_SUPPLIER")].iloc[0]
        self.assertEqual(bank.PRIORITY, "HIGH")
        self.assertIn("Bank details changed", bank.DETAIL)

    def test_snapshot_keeps_no_raw_identifiers(self):
        data = frame([{"SUPPLIER_ID": "A", "SUPPLIER_NAME": "Acme", "TAX_ID": "GB123456789", "BANK_ACCOUNT": "GB82WEST12345698765432"}])
        text = str(make_snapshot(scan_suppliers(data), data, salt="x"))
        self.assertNotIn("GB82WEST12345698765432", text)
        self.assertNotIn("123456789", text)

    def test_store_saves_and_lists_snapshots(self):
        with TemporaryDirectory() as temp:
            store = ReviewStore(Path(temp) / "r.sqlite3")
            data = load_supplier_master(PREVIOUS_SAMPLE)
            snapshot = make_snapshot(scan_suppliers(data), data, "earlier.xlsx", store.salt())
            first = store.save_snapshot(snapshot)
            self.assertEqual(store.save_snapshot(snapshot), first)  # unchanged scans are not stored twice
            self.assertEqual(store.snapshots()[0]["source_name"], "earlier.xlsx")
            self.assertEqual(store.snapshot(first)["dataset_id"], snapshot["dataset_id"])
            self.assertEqual(store.snapshots(exclude_dataset=snapshot["dataset_id"]), [])

    def test_sample_quarter_comparison(self):
        old, new = load_supplier_master(PREVIOUS_SAMPLE), load_supplier_master(SAMPLE_WORKBOOK)
        summary = change_summary(compare_snapshots(make_snapshot(scan_suppliers(old), old), make_snapshot(scan_suppliers(new), new)))
        self.assertEqual(summary["new_suppliers"], 25)
        self.assertEqual(summary["removed_suppliers"], 5)
        self.assertGreater(summary["sensitive_changes"], 0)


class LookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suppliers = load_supplier_master(SAMPLE_WORKBOOK)

    def test_existing_supplier_is_found_by_name_or_identifier(self):
        by_name = find_existing(self.suppliers, {"SUPPLIER_NAME": "SUMMIT SUPPLY TRADING LIMITED", "COUNTRY_CODE": "GB"})
        self.assertEqual(by_name.iloc[0]["SUPPLIER_ID"], "S100118")
        self.assertEqual(verdict(by_name), "LIKELY_EXISTS")
        tax = self.suppliers.set_index("SUPPLIER_ID").loc["S100118", "TAX_ID"]
        by_tax = find_existing(self.suppliers, {"SUPPLIER_NAME": "Totally Different Name", "COUNTRY_CODE": "GB", "TAX_ID": tax})
        self.assertIn("S100118", set(by_tax["SUPPLIER_ID"]))

    def test_unknown_supplier_and_input_validation(self):
        matches = find_existing(self.suppliers, {"SUPPLIER_NAME": "Zxqv Unheard Of Widgets", "COUNTRY_CODE": "GB"})
        self.assertEqual(verdict(matches), "NO_MATCH")
        problems = validate_new_supplier(
            {
                "SUPPLIER_NAME": "X",
                "COUNTRY_CODE": "DE",
                "TAX_ID": "DE136695977",
                "BANK_ACCOUNT": "GB83WEST12345698765432",
                "BANK_COUNTRY": "GB",
            }
        )
        self.assertEqual(len(problems), 2)


class DatabaseTests(unittest.TestCase):
    def test_query_validation(self):
        self.assertEqual(validate_query("SELECT * FROM vendors;"), "SELECT * FROM vendors")
        for bad in ("DELETE FROM vendors", "SELECT 1; DROP TABLE vendors", "WITH x AS (DELETE FROM v RETURNING *) SELECT * FROM x", ""):
            with self.assertRaises(ValueError):
                validate_query(bad)
        validate_query("SELECT 'drop table' AS note, replace(name, 'a', 'b') FROM vendors -- update later")

    def test_sqlite_file_is_read_only_and_mapped(self):
        raw = read_query(str(EXAMPLE_DB), "SELECT * FROM vendors WHERE country = 'GB'")
        self.assertGreater(len(raw), 10)
        from supplier_agent.columns import apply_mapping, suggest_mapping

        suppliers = validate_supplier_master(apply_mapping(raw, suggest_mapping(raw.columns)))
        self.assertTrue(suppliers["TAX_ID"].ne("").any())
        with TemporaryDirectory() as temp:
            path = Path(temp) / "x.db"
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE t (id TEXT, name TEXT)")
                connection.execute("INSERT INTO t VALUES ('1', 'Acme')")
            connection.close()
            with self.assertRaises(ValueError):
                read_query(str(path), "SELECT * FROM t", max_rows=0)

    def test_sqlalchemy_url_and_credentials_hidden(self):
        try:
            import sqlalchemy  # noqa: F401
        except ImportError:
            self.skipTest("SQLAlchemy not installed")
        raw = read_query(f"sqlite+pysqlite:///{EXAMPLE_DB}", "SELECT vendor_id, vendor_name FROM vendors LIMIT 5")
        self.assertEqual(list(raw.columns), ["vendor_id", "vendor_name"])
        self.assertEqual(describe("postgresql://user:secret@db.example/erp"), "postgresql://***@db.example/erp")


if __name__ == "__main__":
    unittest.main()
