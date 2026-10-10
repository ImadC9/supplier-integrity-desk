import unittest

from supplier_agent.semantic import SemanticSearchIndex


class _FixedEmbeddingProvider:
    model_name = "fixed-test-vectors"

    def __init__(self) -> None:
        self.vectors = {
            "office cleaning services": [1.0, 0.0],
            "janitorial facility care": [0.9, 0.1],
            "steel tubing": [0.0, 1.0],
        }

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors[text] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.vectors[text]


class SemanticSearchIndexTests(unittest.TestCase):
    def test_search_finds_conceptually_similar_text_without_shared_words(self) -> None:
        index = SemanticSearchIndex(
            {
                "S1": "office cleaning services",
                "S2": "janitorial facility care",
                "S3": "steel tubing",
            },
            embedding_provider=_FixedEmbeddingProvider(),
        )

        results = index.search("S1", candidate_ids={"S2", "S3"}, limit=2)

        self.assertEqual(results[0]["id"], "S2")
        self.assertEqual(results[0]["similarity"], 99.4)
        self.assertEqual(results[1]["id"], "S3")
        self.assertEqual(results[1]["similarity"], 0.0)


if __name__ == "__main__":
    unittest.main()
