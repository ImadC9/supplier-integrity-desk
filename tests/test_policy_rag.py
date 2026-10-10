import unittest

from supplier_agent.paths import POLICY_DIR
from supplier_agent.policy_rag import PolicyRetriever

POLICIES = POLICY_DIR


class _PolicyEmbeddingProvider:
    model_name = "policy-test-vectors"

    @staticmethod
    def _vector(text: str) -> list[float]:
        if "authorize consolidation" in text.casefold():
            return [1.0, 0.0]
        if "only a human data steward" in text.casefold():
            return [1.0, 0.0]
        return [0.0, 1.0]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class PolicyRetrieverTests(unittest.TestCase):
    def test_duplicate_evidence_retrieves_review_rule_with_citation(self) -> None:
        retriever = PolicyRetriever(POLICIES, semantic_enabled=False)

        results = retriever.retrieve(
            "same tax identifier and same bank account duplicate review",
            limit=3,
        )

        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(
            results[0]["document"],
            "Example Duplicate Supplier Review Policy",
        )
        self.assertEqual(results[0]["section"], "3. Strong duplicate indicators")
        self.assertIn("Data Steward", results[0]["text"])
        self.assertEqual(
            results[0]["citation"],
            "Example Duplicate Supplier Review Policy § 3. Strong duplicate indicators",
        )

    def test_human_decision_query_retrieves_governance_passage(self) -> None:
        retriever = PolicyRetriever(POLICIES, semantic_enabled=False)

        results = retriever.retrieve(
            "human approval merge delete audit decision record",
            limit=2,
        )

        self.assertEqual(
            results[0]["document"],
            "Example Data Steward Decision Workflow",
        )
        self.assertEqual(results[0]["section"], "3. Decision and audit record")
        self.assertIn("human Data Steward", results[0]["text"])

    def test_inactive_supplier_query_retrieves_lifecycle_rule(self) -> None:
        retriever = PolicyRetriever(POLICIES, semantic_enabled=False)

        results = retriever.retrieve(
            "inactive supplier purchase orders spend lifecycle review",
            limit=2,
        )

        self.assertEqual(
            results[0]["document"],
            "Example Supplier Master Data Quality Standard",
        )
        self.assertEqual(results[0]["section"], "4. Activity and lifecycle context")

    def test_vector_retrieval_finds_policy_when_query_uses_different_words(self) -> None:
        retriever = PolicyRetriever(
            POLICIES,
            embedding_provider=_PolicyEmbeddingProvider(),
        )

        results = retriever.retrieve("Who can authorize consolidation?", limit=2)

        self.assertEqual(
            results[0]["citation"],
            "Example Data Steward Decision Workflow § 3. Decision and audit record",
        )
        self.assertEqual(results[0]["retrieval_mode"], "HYBRID_KEYWORD_VECTOR")
        self.assertEqual(results[0]["embedding_model"], "policy-test-vectors")


if __name__ == "__main__":
    unittest.main()
