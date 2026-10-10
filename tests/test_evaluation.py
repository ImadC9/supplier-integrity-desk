"""Behavior tests for labelled duplicate evaluation."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from supplier_agent.evaluation import (
    evaluate_duplicate_pairs,
    evaluate_workbook,
    write_evaluation_outputs,
)
from supplier_agent.paths import SAMPLE_WORKBOOK

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKBOOK_PATH = SAMPLE_WORKBOOK


class DuplicateEvaluationTests(unittest.TestCase):
    def test_pair_metrics_follow_a_worked_confusion_matrix(self) -> None:
        ground_truth = pd.DataFrame(
            [
                {"SUPPLIER_ID": "A", "DUPLICATE_CLUSTER_ID": "DUP-1"},
                {"SUPPLIER_ID": "B", "DUPLICATE_CLUSTER_ID": "DUP-1"},
                {"SUPPLIER_ID": "C", "DUPLICATE_CLUSTER_ID": pd.NA},
                {"SUPPLIER_ID": "D", "DUPLICATE_CLUSTER_ID": pd.NA},
            ]
        )
        predictions = pd.DataFrame(
            [
                {
                    "SUPPLIER_ID_A": "A",
                    "SUPPLIER_ID_B": "B",
                    "DUPLICATE_SCORE": 80.0,
                    "LIKELIHOOD": "HIGH",
                    "EVIDENCE": "same Tax ID",
                },
                {
                    "SUPPLIER_ID_A": "A",
                    "SUPPLIER_ID_B": "C",
                    "DUPLICATE_SCORE": 70.0,
                    "LIKELIHOOD": "HIGH",
                    "EVIDENCE": "same bank account",
                },
            ]
        )

        result = evaluate_duplicate_pairs(
            ground_truth,
            predictions,
            threshold=65.0,
        )

        self.assertEqual(result.metrics["true_positives"], 1)
        self.assertEqual(result.metrics["false_positives"], 1)
        self.assertEqual(result.metrics["false_negatives"], 0)
        self.assertEqual(result.metrics["true_negatives"], 4)
        self.assertEqual(result.metrics["precision"], 0.5)
        self.assertEqual(result.metrics["recall"], 1.0)
        self.assertAlmostEqual(result.metrics["f1_score"], 2 / 3, places=4)
        self.assertEqual(
            set(result.cases["OUTCOME"]),
            {"TRUE_POSITIVE", "FALSE_POSITIVE"},
        )

    def test_workbook_evaluation_uses_all_labelled_duplicate_clusters(self) -> None:
        result = evaluate_workbook(WORKBOOK_PATH)

        self.assertEqual(result.metrics["supplier_records"], 1000)
        self.assertEqual(result.metrics["ground_truth_positive_pairs"], 90)
        self.assertGreater(len(result.threshold_analysis), 1)
        self.assertEqual(
            set(result.threshold_analysis.columns),
            {"threshold", "predicted_positive_pairs", "precision", "recall", "f1_score"},
        )
        self.assertTrue(set(result.cases["OUTCOME"]) <= {"TRUE_POSITIVE", "FALSE_POSITIVE", "FALSE_NEGATIVE"})

    def test_evaluation_outputs_are_repeatable_and_auditable(self) -> None:
        result = evaluate_workbook(WORKBOOK_PATH)
        with TemporaryDirectory() as temporary_directory:
            outputs = write_evaluation_outputs(result, temporary_directory)

            self.assertEqual(
                set(outputs),
                {"summary", "cases", "thresholds", "label_profile", "report"},
            )
            summary = json.loads(Path(outputs["summary"]).read_text(encoding="utf-8"))
            self.assertEqual(summary["metrics"]["ground_truth_positive_pairs"], 90)
            self.assertEqual(summary["methodology"]["positive_pair"], "Both suppliers share a nonblank duplicate cluster ID.")
            self.assertIn(
                "Synthetic benchmark limitation",
                Path(outputs["report"]).read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
