"""Public UI journey tests for the Data Steward application."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "streamlit_app.py"


def _app(timeout: int = 90) -> AppTest:
    return AppTest.from_file(str(APP_PATH), default_timeout=timeout).run()


class StreamlitAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.environment = patch.dict(os.environ, {"SUPPLIER_REVIEW_DB": str(Path(self.temp.name) / "reviews.sqlite3")})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_app_loads_scans_and_every_page_renders(self) -> None:
        app = _app()
        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value, "Supplier Integrity Desk")
        self.assertIn("scan_result", app.session_state)
        self.assertGreater(len(app.session_state["scan_result"].clusters), 0)
        for page in ["Review queue", "Clusters", "What's new", "Check a supplier", "Investigation", "Review history", "Guide", "Overview"]:
            app.radio(key="page").set_value(page).run()
            self.assertFalse(app.exception, page)
            self.assertFalse(app.error, page)
        app.radio(key="page").set_value("Investigation").run()
        pick = "supplier_pick_" + app.session_state["dataset_id"][:12]
        self.assertEqual(app.selectbox(key=pick).value, "S100118")

    def test_steward_can_review_and_complete_a_case(self) -> None:
        app = _app()
        app.radio(key="page").set_value("Investigation").run()
        app.button(key="start_investigation").click().run(timeout=90)
        self.assertFalse(app.exception)
        self.assertTrue(any("awaiting human review" in item.value.lower() for item in app.warning))
        self.assertEqual(set(app.radio(key="review_decision").options), {"Confirm Duplicate", "Not Duplicate", "Needs Investigation"})
        app.radio(key="review_decision").set_value("NEEDS_INVESTIGATION")
        app.text_input(key="reviewer").set_value("Test Steward")
        app.button(key="submit_decision").click().run(timeout=60)
        self.assertFalse(app.exception)
        self.assertTrue(any("human review complete" in item.value.lower() for item in app.success))
        exported = json.loads(app.session_state["investigation_session"].export_json())
        self.assertFalse(exported["paused_for_review"])
        self.assertEqual(exported["final_state"]["reviewer"], "Test Steward")
        self.assertIsNotNone(exported["final_state"]["reviewed_candidate_id"])
        app.radio(key="page").set_value("Review history").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe[0].value), 1)

    def test_queue_opens_a_pair_and_quality_review_survives_a_new_session(self) -> None:
        app = _app()
        app.radio(key="page").set_value("Review queue").run()
        app.selectbox(key="queue_type").set_value("DUPLICATE").run()
        self.assertFalse(app.exception)
        selected = app.selectbox(key="queue_finding").value
        scan = app.session_state["scan_result"]
        expected_candidate = scan.queue[scan.queue.FINDING_ID.eq(selected)].iloc[0].CANDIDATE_ID
        self.assertTrue(any("Match" in item.value for item in app.markdown))  # side-by-side comparison rendered
        app.button(key="open_finding").click().run()
        self.assertEqual(app.radio(key="page").value, "Investigation")
        app.button(key="start_investigation").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox(key="review_candidate_id").value, expected_candidate)
        app.button(key="new_case").click().run()
        app.radio(key="page").set_value("Review queue").run()
        app.selectbox(key="queue_type").set_value("DATA_QUALITY").run()
        app.text_input(key="dq_reviewer").set_value("Quality Steward")
        app.button(key="FormSubmitter:quality_review-Save quality review").click().run()
        self.assertFalse(app.exception)
        fresh = _app()
        fresh.radio(key="page").set_value("Review history").run()
        self.assertFalse(fresh.exception)
        self.assertEqual(fresh.dataframe[0].value.iloc[0]["reviewer"], "Quality Steward")

    def test_queue_options_identify_each_duplicate_pair(self) -> None:
        app = _app()
        app.radio(key="page").set_value("Review queue").run()
        app.selectbox(key="queue_type").set_value("DUPLICATE").run()
        options = app.selectbox(key="queue_finding").options
        self.assertEqual(len(options), len(set(options)))
        pairs = {frozenset(label.split(" · ")[0].split(" → ")) for label in options}
        self.assertIn(frozenset({"S200019", "S100790"}), pairs)
        self.assertIn(frozenset({"S200019", "S200020"}), pairs)

    def test_cluster_decision_records_every_pair(self) -> None:
        app = _app()
        app.radio(key="page").set_value("Clusters").run()
        self.assertFalse(app.exception)
        cluster_id = app.selectbox(key="cluster_pick").value
        app.radio(key="cluster_decision").set_value("CONFIRM_DUPLICATE")
        app.text_input(key="cluster_reviewer").set_value("Cluster Steward")
        app.button(key="FormSubmitter:cluster_review-Save cluster decision").click().run()
        self.assertFalse(app.exception)
        scan = app.session_state["scan_result"]
        pairs = scan.queue[scan.queue.CLUSTER_ID.eq(cluster_id)]
        app.radio(key="page").set_value("Review history").run()
        history = app.dataframe[0].value
        self.assertEqual(len(history), len(pairs))
        self.assertEqual(set(history["decision"]), {"CONFIRM_DUPLICATE"})
        plan = app.dataframe[1].value  # the action plan for the ERP team
        self.assertEqual(len(plan), 2)  # a cluster of three: keep one, block two
        self.assertEqual(plan["KEEP_ID"].nunique(), 1)

    def test_whats_new_compares_with_previous_quarter(self) -> None:
        app = _app()
        app.radio(key="page").set_value("What's new").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox(key="baseline_choice").value, "sample")
        self.assertTrue(any("bank details" in item.value.lower() for item in app.warning))
        self.assertGreater(len(app.dataframe[0].value), 10)

    def test_check_a_new_supplier(self) -> None:
        app = _app()
        app.radio(key="page").set_value("Check a supplier").run()
        app.text_input(key="chk_name").set_value("Summit Supply Trading Limited")
        app.text_input(key="chk_country").set_value("GB")
        app.button(key="FormSubmitter:new_supplier_check-Check").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("S100118" in item.value for item in app.error))

    def test_database_source(self) -> None:
        app = _app()
        app.radio(key="source").set_value("Database").run()
        self.assertFalse(app.exception)
        app.button(key="FormSubmitter:database_source-Load from database").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["scan_result"].supplier_count, 1000)

    def test_settings_profile_restores_rules(self) -> None:
        app = _app()
        app.session_state["pending_profile"] = {
            "app": "supplier-integrity-desk",
            "mapping": {},
            "settings": {"cfg_high": 80, "cfg_ibans": False},
        }
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.slider(key="cfg_high").value, 80)
        self.assertNotIn("INVALID_IBAN", set(app.session_state["scan_result"].quality_findings.RULE_CODE))

    def test_settings_change_rescans(self) -> None:
        app = _app()
        before = len(app.session_state["scan_result"].duplicate_pairs)
        app.slider(key="cfg_name").set_value(95).run()
        app.slider(key="cfg_address").set_value(95).run()
        self.assertFalse(app.exception)
        self.assertLessEqual(len(app.session_state["scan_result"].duplicate_pairs), before)
        app.checkbox(key="cfg_missing_ids").uncheck().run()
        self.assertNotIn("MISSING_IDENTIFIER", set(app.session_state["scan_result"].quality_findings.RULE_CODE))


if __name__ == "__main__":
    unittest.main()
