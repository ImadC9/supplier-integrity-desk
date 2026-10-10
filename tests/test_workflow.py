import unittest

from langgraph.types import Command

from supplier_agent.paths import SAMPLE_WORKBOOK
from supplier_agent.workflow import build_investigation_graph

WORKBOOK = SAMPLE_WORKBOOK


class InvestigationWorkflowTests(unittest.TestCase):
    def test_known_supplier_pauses_and_resumes_for_human_review(self) -> None:
        graph = build_investigation_graph(str(WORKBOOK), semantic_enabled=False)
        config = {"configurable": {"thread_id": "workflow-test-known"}}

        paused = graph.invoke({"supplier_id": "S100118"}, config=config)

        self.assertIn("__interrupt__", paused)
        request = paused["__interrupt__"][0].value
        self.assertEqual(request["supplier_id"], "S100118")
        self.assertGreaterEqual(len(paused["policy_context"]), 1)
        self.assertEqual(
            paused["policy_context"][0]["document"],
            "Example Duplicate Supplier Review Policy",
        )
        self.assertEqual(
            request["policy_citations"],
            [item["citation"] for item in paused["policy_context"]],
        )
        self.assertIn("Policy basis:", paused["ai_analysis"])
        self.assertEqual(
            request["allowed_decisions"],
            ["CONFIRM_DUPLICATE", "NEEDS_INVESTIGATION", "NOT_DUPLICATE"],
        )

        completed = graph.invoke(
            Command(resume={"decision": "NEEDS_INVESTIGATION"}),
            config=config,
        )
        self.assertEqual(completed["status"], "HUMAN_REVIEW_COMPLETE")
        self.assertEqual(completed["review_decision"], "NEEDS_INVESTIGATION")
        candidate_ids = {item["SUPPLIER_ID_B"] for item in completed["candidates"]}
        self.assertTrue({"S200039", "S200040"}.issubset(candidate_ids))
        self.assertTrue(all("SEMANTIC_SIMILARITY" in item for item in completed["candidates"]))
        tool_names = {event["tool"] for event in completed["tool_calls"]}
        self.assertTrue(
            {
                "get_supplier",
                "find_by_tax_id",
                "find_by_association_no",
                "find_by_bank_account",
                "find_similar_names",
                "find_similar_addresses",
                "find_semantic_candidates",
                "get_supplier_activity",
                "compare_supplier_pair",
            }.issubset(tool_names)
        )

    def test_unknown_supplier_stops_before_review(self) -> None:
        graph = build_investigation_graph(str(WORKBOOK), semantic_enabled=False)
        config = {"configurable": {"thread_id": "workflow-test-unknown"}}

        result = graph.invoke({"supplier_id": "NOT-A-SUPPLIER"}, config=config)

        self.assertEqual(result["status"], "ERROR")
        self.assertNotIn("__interrupt__", result)
        self.assertIn("Unknown supplier ID", result["errors"][0])


if __name__ == "__main__":
    unittest.main()
