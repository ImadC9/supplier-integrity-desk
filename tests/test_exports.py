import unittest

import pandas as pd

from supplier_agent.exports import csv_text


class ExportTests(unittest.TestCase):
    def test_free_text_formulas_are_escaped_but_numbers_stay_numeric(self):
        output = csv_text(pd.DataFrame({"name": ["=1+1", " @SUM(1)", "Normal Supplier"], "score": [65, -1, 0]}))
        self.assertIn("'=1+1", output)
        self.assertIn("' @SUM(1)", output)
        self.assertIn("Normal Supplier,0", output)
        self.assertIn(",-1", output)
