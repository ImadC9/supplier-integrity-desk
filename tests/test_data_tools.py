import unittest

from supplier_agent.data_tools import (
    SupplierDataService,
    create_langchain_supplier_tools,
)
from supplier_agent.paths import SAMPLE_WORKBOOK

WORKBOOK = SAMPLE_WORKBOOK


class _SupplierEmbeddingProvider:
    model_name = "supplier-test-vectors"

    @staticmethod
    def _vector(text: str) -> list[float]:
        return [1.0, 0.0] if "summit supply trading" in text.casefold() else [0.0, 1.0]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class SupplierDataToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = SupplierDataService(str(WORKBOOK))
        cls.tools = {item.name: item for item in create_langchain_supplier_tools(cls.service)}

    def test_registry_contains_only_allow_listed_tools(self) -> None:
        self.assertEqual(
            set(self.tools),
            {
                "get_supplier",
                "find_by_tax_id",
                "find_by_association_no",
                "find_by_bank_account",
                "find_by_email",
                "find_by_phone",
                "find_similar_names",
                "find_similar_addresses",
                "find_semantic_candidates",
                "get_supplier_activity",
                "compare_supplier_pair",
            },
        )

    def test_get_supplier_tool_excludes_raw_sensitive_identifiers(self) -> None:
        result = self.tools["get_supplier"].invoke({"supplier_id": "S100118"})
        self.assertEqual(result["SUPPLIER_ID"], "S100118")
        self.assertNotIn("TAX_ID", result)
        self.assertNotIn("ASSOCIATION_NO", result)
        self.assertNotIn("BANK_ACCOUNT", result)

    def test_exact_match_tools_find_known_candidates(self) -> None:
        for tool_name in (
            "find_by_tax_id",
            "find_by_association_no",
            "find_by_bank_account",
        ):
            results = self.tools[tool_name].invoke({"supplier_id": "S100118"})
            result_ids = {item["SUPPLIER_ID"] for item in results}
            self.assertEqual(result_ids, {"S200039", "S200040"})

    def test_tool_schemas_do_not_allow_query_or_file_path(self) -> None:
        for tool_name, controlled_tool in self.tools.items():
            properties = set(controlled_tool.args_schema.model_json_schema().get("properties", {}))
            self.assertNotIn("query", properties, tool_name)
            self.assertNotIn("sql", properties, tool_name)
            self.assertNotIn("workbook_path", properties, tool_name)

    def test_semantic_tool_finds_same_concept_with_model_metadata(self) -> None:
        service = SupplierDataService(
            str(WORKBOOK),
            embedding_provider=_SupplierEmbeddingProvider(),
        )
        tools = {item.name: item for item in create_langchain_supplier_tools(service)}

        results = tools["find_semantic_candidates"].invoke({"supplier_id": "S100118", "limit": 5})

        result_ids = {item["SUPPLIER_ID"] for item in results}
        self.assertTrue({"S200039", "S200040"}.issubset(result_ids))
        self.assertEqual(results[0]["EMBEDDING_MODEL"], "supplier-test-vectors")
        self.assertEqual(results[0]["SEMANTIC_SIMILARITY"], 100.0)


if __name__ == "__main__":
    unittest.main()
