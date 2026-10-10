"""Human authority, durable history, and offline behavior checks."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from supplier_agent.data_tools import SupplierDataService
from supplier_agent.paths import POLICY_DIR
from supplier_agent.policy_rag import PolicyRetriever
from supplier_agent.review_store import ReviewStore
from supplier_agent.ui_session import InvestigationSession
from supplier_agent.workflow.graph import build_investigation_graph
from tests.test_detector import supplier_frame

POLICIES = POLICY_DIR


class ReviewTests(unittest.TestCase):
    def test_multiple_candidates_require_an_explicit_pair_and_other_pairs_stay_unreviewed(self):
        frame = supplier_frame()
        other = frame.iloc[[1]].copy()
        other["SUPPLIER_ID"] = "S4"
        session = InvestigationSession(pd.concat([frame, other], ignore_index=True))
        session.start("S1", "S4")
        with self.assertRaisesRegex(ValueError, "candidate"):
            session.submit_decision("NOT_DUPLICATE")
        result = session.submit_decision("NOT_DUPLICATE", "S4", "Steward")
        self.assertEqual(result["reviewed_candidate_id"], "S4")
        self.assertEqual({item["SUPPLIER_ID_B"] for item in result["candidates"]}, {"S2", "S4"})

    def test_history_is_append_only_persistent_and_dataset_scoped(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "reviews.sqlite3"
            store = ReviewStore(path)
            store.record("one", "pair", "DUPLICATE", "NEEDS_INVESTIGATION", "Reviewer", "first")
            store.record("one", "pair", "DUPLICATE", "NOT_DUPLICATE", "Reviewer", "second")
            fresh = ReviewStore(path)
            self.assertEqual(len(fresh.history("one")), 2)
            self.assertEqual(fresh.latest("one")["pair"]["notes"], "second")
            self.assertEqual(fresh.history("two"), [])
            with self.assertRaises(ValueError):
                store.record("one", "dq", "DATA_QUALITY", "CONFIRM_DUPLICATE", "Reviewer")
            with self.assertRaises(ValueError):
                store.record("one", "dq", "DATA_QUALITY", "FIX_REQUIRED", " ")

    def test_offline_case_never_loads_embeddings_and_redacts_export(self):
        with (
            patch("supplier_agent.data_tools.get_default_embedding_provider", side_effect=AssertionError("download")),
            patch("supplier_agent.policy_rag.get_default_embedding_provider", side_effect=AssertionError("download")),
        ):
            session = InvestigationSession(supplier_frame(), semantic_enabled=False)
            session.start("S1")
            self.assertTrue(session.paused_for_review)
            with self.assertRaises(ValueError):
                session.submit_decision("CONFIRM_DUPLICATE", "NOT-IN-CASE")
            self.assertTrue(session.paused_for_review)
            session.submit_decision("CONFIRM_DUPLICATE", "S2", "Steward", "Verified pair")
            payload = json.loads(session.export_json())
            self.assertEqual(payload["final_state"]["reviewed_candidate_id"], "S2")
            self.assertNotIn("BANK_ACCOUNT", payload["final_state"]["supplier"])
            self.assertNotIn("GB01 TEST 123", session.export_json())

    def test_cannot_confirm_duplicate_without_a_candidate(self):
        session = InvestigationSession(supplier_frame().iloc[2:].copy())
        session.start("S3")
        with self.assertRaises(ValueError):
            session.submit_decision("CONFIRM_DUPLICATE")
        self.assertTrue(session.paused_for_review)
        session.submit_decision("NOT_DUPLICATE", reviewer="Steward")

    def test_gemini_failure_keeps_evidence_and_labels_fallback(self):
        class UnavailableGemini:
            mode = "GEMINI:test"

            def analyze(self, *args):
                raise ConnectionError("private-provider-details")

        service = SupplierDataService(supplier_frame(), semantic_enabled=False)
        graph = build_investigation_graph(
            data_service=service, analyzer=UnavailableGemini(), policy_retriever=PolicyRetriever(POLICIES, semantic_enabled=False)
        )
        result = graph.invoke({"supplier_id": "S1"}, config={"configurable": {"thread_id": "fallback"}})
        self.assertIn("__interrupt__", result)
        self.assertEqual(result["analysis_mode"], "DETERMINISTIC_FALLBACK")
        self.assertGreater(len(result["evidence"]), 0)
        self.assertNotIn("private-provider-details", str(result["warnings"]))
