import unittest

from supplier_agent.workflow.analysis import GeminiAnalysisProvider


class _FakeInteraction:
    output_text = "The review is required. A Data Steward makes the final decision."


class _FakeInteractions:
    def __init__(self) -> None:
        self.arguments = None

    def create(self, **kwargs):
        self.arguments = kwargs
        return _FakeInteraction()


class _FakeGeminiClient:
    def __init__(self) -> None:
        self.interactions = _FakeInteractions()


class GeminiAnalysisProviderTests(unittest.TestCase):
    def test_prompt_excludes_raw_tax_and_bank_values(self) -> None:
        client = _FakeGeminiClient()
        provider = GeminiAnalysisProvider(client=client)
        supplier = {
            "SUPPLIER_ID": "S1",
            "SUPPLIER_NAME": "Example Supplier",
            "COUNTRY_CODE": "GB",
            "TAX_ID": "SECRET-TAX-VALUE",
            "BANK_ACCOUNT": "SECRET-BANK-VALUE",
        }
        candidates = [
            {
                "SUPPLIER_ID_B": "S2",
                "SUPPLIER_NAME_B": "Example Supplier Ltd",
                "SAME_TAX_ID": True,
                "SAME_ASSOCIATION_NO": False,
                "SAME_BANK_ACCOUNT": True,
                "NAME_SIMILARITY": 95.0,
                "ADDRESS_SIMILARITY": 80.0,
                "DUPLICATE_SCORE": 72.0,
                "LIKELIHOOD": "HIGH",
                "EVIDENCE": "same Tax ID; same bank account",
            }
        ]

        policy_context = [
            {
                "document": "Synthetic Duplicate Supplier Review Policy",
                "section": "3. Strong duplicate indicators",
                "text": "A Data Steward must approve the final decision.",
                "citation": ("Synthetic Duplicate Supplier Review Policy § 3. Strong duplicate indicators"),
            }
        ]

        result = provider.analyze(supplier, candidates, policy_context)
        prompt = client.interactions.arguments["input"]

        self.assertIn("Data Steward", result)
        self.assertNotIn("SECRET-TAX-VALUE", prompt)
        self.assertNotIn("SECRET-BANK-VALUE", prompt)
        self.assertIn('"SAME_TAX_ID": true', prompt)
        self.assertIn("Policy context JSON", prompt)
        self.assertIn("Synthetic Duplicate Supplier Review Policy", prompt)
        self.assertIn("Cite only the supplied policy passages", prompt)


if __name__ == "__main__":
    unittest.main()
