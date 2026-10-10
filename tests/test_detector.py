import unittest

import pandas as pd

from supplier_agent.detector import DuplicateDetector


def supplier_frame() -> pd.DataFrame:
    base = {
        "ASSOCIATION_NO": "",
        "TAX_ID": "",
        "COUNTRY_CODE": "GB",
        "ADDRESS_1": "",
        "ADDRESS_2": "",
        "CITY": "London",
        "POSTAL_CODE": "E1 1AA",
        "BANK_COUNTRY": "GB",
        "BANK_ACCOUNT": "",
    }
    rows = [
        {
            **base,
            "SUPPLIER_ID": "S1",
            "SUPPLIER_NAME": "ABC Industrial Ltd",
            "ASSOCIATION_NO": "GB-REG-123",
            "TAX_ID": "GB 999 111",
            "ADDRESS_1": "10 Station Road",
            "BANK_ACCOUNT": "GB01 TEST 123",
        },
        {
            **base,
            "SUPPLIER_ID": "S2",
            "SUPPLIER_NAME": "A.B.C. Industrial Limited",
            "ASSOCIATION_NO": "GBREG123",
            "TAX_ID": "GB999111",
            "ADDRESS_1": "10 Station Rd.",
            "BANK_ACCOUNT": "GB01TEST123",
        },
        {
            **base,
            "SUPPLIER_ID": "S3",
            "SUPPLIER_NAME": "North Star Catering PLC",
            "ADDRESS_1": "88 Market Street",
            "BANK_ACCOUNT": "GB99 OTHER 555",
        },
    ]
    return pd.DataFrame(rows)


class DuplicateDetectorTests(unittest.TestCase):
    def test_exact_and_fuzzy_evidence_produces_high_likelihood(self) -> None:
        result = DuplicateDetector().detect(supplier_frame())
        pair = result[(result["SUPPLIER_ID_A"] == "S1") & (result["SUPPLIER_ID_B"] == "S2")].iloc[0]
        self.assertTrue(pair["SAME_TAX_ID"])
        self.assertTrue(pair["SAME_ASSOCIATION_NO"])
        self.assertTrue(pair["SAME_BANK_ACCOUNT"])
        self.assertEqual(pair["LIKELIHOOD"], "HIGH")

    def test_blank_identifiers_are_not_treated_as_matches(self) -> None:
        result = DuplicateDetector().detect(supplier_frame())
        unrelated = result[(result["SUPPLIER_ID_A"] == "S1") & (result["SUPPLIER_ID_B"] == "S3")]
        self.assertTrue(unrelated.empty)

    def test_supplier_filter_limits_results(self) -> None:
        result = DuplicateDetector().detect(supplier_frame(), supplier_id="S1")
        self.assertEqual(set(result["SUPPLIER_ID_A"]), {"S1"})
        self.assertNotIn("S1", set(result["SUPPLIER_ID_B"]))


if __name__ == "__main__":
    unittest.main()
