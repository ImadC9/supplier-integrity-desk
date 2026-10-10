"""Labelled evaluation kept separate from the production investigation graph."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

import pandas as pd

from .detector import DuplicateDetector
from .exports import csv_text
from .io import load_supplier_master

GROUND_TRUTH_REQUIRED_COLUMNS = {
    "SUPPLIER_ID",
    "DUPLICATE_CLUSTER_ID",
}
PREDICTION_REQUIRED_COLUMNS = {
    "SUPPLIER_ID_A",
    "SUPPLIER_ID_B",
    "DUPLICATE_SCORE",
}
GROUND_TRUTH_SHEET = "Ground_Truth"
GROUND_TRUTH_FILE_COLUMNS = {
    "SUPPLIER_ID",
    "ISSUE_TYPE",
    "DUPLICATE_CLUSTER_ID",
    "EXPECTED_DECISION",
    "NOTES",
}
DEFAULT_EVALUATION_THRESHOLDS = (25.0, 40.0, 50.0, 65.0, 75.0, 85.0, 95.0)


@dataclass(frozen=True)
class EvaluationResult:
    """Pair-level metrics and the observable non-true-negative cases."""

    metrics: dict[str, Any]
    cases: pd.DataFrame
    threshold_analysis: pd.DataFrame = field(default_factory=pd.DataFrame)
    label_profile: pd.DataFrame = field(default_factory=pd.DataFrame)


def _pair(left: Any, right: Any) -> tuple[str, str]:
    values = sorted((str(left).strip().upper(), str(right).strip().upper()))
    if not values[0] or values[0] == values[1]:
        raise ValueError("Evaluation pairs require two different supplier IDs.")
    return values[0], values[1]


def _safe_ratio(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0


def evaluate_duplicate_pairs(
    ground_truth: pd.DataFrame,
    predictions: pd.DataFrame,
    threshold: float = 65.0,
) -> EvaluationResult:
    """Compare scored supplier pairs with labelled duplicate clusters."""
    missing_truth = sorted(GROUND_TRUTH_REQUIRED_COLUMNS - set(ground_truth.columns))
    missing_predictions = sorted(PREDICTION_REQUIRED_COLUMNS - set(predictions.columns))
    if missing_truth:
        raise ValueError(f"Ground_Truth is missing required columns: {missing_truth}")
    if missing_predictions:
        raise ValueError(f"Predictions are missing required columns: {missing_predictions}")
    if not 0.0 <= float(threshold) <= 100.0:
        raise ValueError("threshold must be between 0 and 100.")

    supplier_ids = [str(value).strip().upper() for value in ground_truth["SUPPLIER_ID"]]
    if not supplier_ids or any(not value for value in supplier_ids):
        raise ValueError("Ground_Truth must contain nonblank supplier IDs.")
    supplier_id_set = set(supplier_ids)
    if len(supplier_id_set) != len(supplier_ids):
        raise ValueError("Ground_Truth supplier IDs must be unique.")

    truth_pairs: set[tuple[str, str]] = set()
    pair_clusters: dict[tuple[str, str], str] = {}
    labelled = ground_truth.assign(_SUPPLIER_ID=supplier_ids).dropna(subset=["DUPLICATE_CLUSTER_ID"])
    for cluster_id, cluster in labelled.groupby("DUPLICATE_CLUSTER_ID", sort=True):
        members = sorted(cluster["_SUPPLIER_ID"].tolist())
        for left, right in combinations(members, 2):
            pair = _pair(left, right)
            truth_pairs.add(pair)
            pair_clusters[pair] = str(cluster_id)

    prediction_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in predictions.to_dict("records"):
        pair = _pair(row["SUPPLIER_ID_A"], row["SUPPLIER_ID_B"])
        if pair in prediction_rows:
            raise ValueError(f"Predictions contain duplicate pair: {pair}")
        if pair[0] not in supplier_id_set or pair[1] not in supplier_id_set:
            raise ValueError(f"Prediction references an unknown supplier: {pair}")
        prediction_rows[pair] = row

    predicted_pairs = {pair for pair, row in prediction_rows.items() if float(row["DUPLICATE_SCORE"]) >= float(threshold)}
    true_positives = truth_pairs & predicted_pairs
    false_positives = predicted_pairs - truth_pairs
    false_negatives = truth_pairs - predicted_pairs
    total_pairs = len(supplier_ids) * (len(supplier_ids) - 1) // 2
    true_negatives = total_pairs - len(true_positives) - len(false_positives) - len(false_negatives)

    precision = _safe_ratio(len(true_positives), len(true_positives) + len(false_positives))
    recall = _safe_ratio(len(true_positives), len(true_positives) + len(false_negatives))
    f1_score = _safe_ratio(2 * len(true_positives), 2 * len(true_positives) + len(false_positives) + len(false_negatives))

    metrics = {
        "threshold": float(threshold),
        "supplier_records": len(supplier_ids),
        "total_pairs": total_pairs,
        "ground_truth_positive_pairs": len(truth_pairs),
        "predicted_positive_pairs": len(predicted_pairs),
        "true_positives": len(true_positives),
        "false_positives": len(false_positives),
        "false_negatives": len(false_negatives),
        "true_negatives": true_negatives,
        "precision": precision,
        "recall": recall,
        "f1_score": f1_score,
        "specificity": _safe_ratio(true_negatives, true_negatives + len(false_positives)),
        "accuracy": _safe_ratio(len(true_positives) + true_negatives, total_pairs),
    }

    case_rows = []
    outcomes = (
        ("TRUE_POSITIVE", true_positives),
        ("FALSE_POSITIVE", false_positives),
        ("FALSE_NEGATIVE", false_negatives),
    )
    for outcome, pairs in outcomes:
        for pair in sorted(pairs):
            prediction = prediction_rows.get(pair, {})
            case_rows.append(
                {
                    "SUPPLIER_ID_A": pair[0],
                    "SUPPLIER_ID_B": pair[1],
                    "DUPLICATE_CLUSTER_ID": pair_clusters.get(pair),
                    "DUPLICATE_SCORE": float(prediction.get("DUPLICATE_SCORE", 0.0)),
                    "LIKELIHOOD": prediction.get("LIKELIHOOD"),
                    "EVIDENCE": prediction.get("EVIDENCE"),
                    "OUTCOME": outcome,
                }
            )
    columns = [
        "SUPPLIER_ID_A",
        "SUPPLIER_ID_B",
        "DUPLICATE_CLUSTER_ID",
        "DUPLICATE_SCORE",
        "LIKELIHOOD",
        "EVIDENCE",
        "OUTCOME",
    ]
    return EvaluationResult(metrics=metrics, cases=pd.DataFrame(case_rows, columns=columns))


def load_ground_truth(path: str | Path) -> pd.DataFrame:
    """Load evaluation labels through a boundary unavailable to the agent graph."""
    workbook_path = Path(path)
    if not workbook_path.exists():
        raise FileNotFoundError(f"Supplier workbook not found: {workbook_path}")
    if workbook_path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError("Evaluation input must be an Excel .xlsx or .xlsm workbook.")
    frame = pd.read_excel(
        workbook_path,
        sheet_name=GROUND_TRUTH_SHEET,
        dtype="string",
        keep_default_na=True,
    )
    frame.columns = [str(column).strip().upper() for column in frame.columns]
    missing = sorted(GROUND_TRUTH_FILE_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"Ground_Truth is missing required columns: {missing}")
    if frame.empty:
        raise ValueError("Ground_Truth contains no labelled records.")
    if frame["SUPPLIER_ID"].isna().any():
        raise ValueError("Ground_Truth SUPPLIER_ID contains missing values.")
    if frame["SUPPLIER_ID"].duplicated().any():
        raise ValueError("Ground_Truth SUPPLIER_ID must be unique.")
    cluster_sizes = frame.dropna(subset=["DUPLICATE_CLUSTER_ID"]).groupby("DUPLICATE_CLUSTER_ID").size()
    singleton_clusters = cluster_sizes[cluster_sizes < 2].index.tolist()
    if singleton_clusters:
        raise ValueError(f"Duplicate clusters must contain at least two suppliers: {singleton_clusters[:10]}")
    return frame


def evaluate_workbook(
    path: str | Path,
    threshold: float = 65.0,
    thresholds: tuple[float, ...] = DEFAULT_EVALUATION_THRESHOLDS,
) -> EvaluationResult:
    """Run the current deterministic detector once and score it against labels."""
    suppliers = load_supplier_master(path)
    ground_truth = load_ground_truth(path)
    supplier_ids = set(suppliers["SUPPLIER_ID"].astype(str).str.strip().str.upper())
    truth_ids = set(ground_truth["SUPPLIER_ID"].astype(str).str.strip().str.upper())
    if supplier_ids != truth_ids:
        missing_labels = sorted(supplier_ids - truth_ids)
        unknown_labels = sorted(truth_ids - supplier_ids)
        raise ValueError(
            "Supplier_Master and Ground_Truth supplier IDs do not match. "
            f"Missing labels: {missing_labels[:10]}; unknown labels: {unknown_labels[:10]}"
        )

    predictions = DuplicateDetector().detect(suppliers)
    selected = evaluate_duplicate_pairs(ground_truth, predictions, threshold)
    threshold_rows = []
    for candidate_threshold in sorted(set(float(value) for value in thresholds) | {float(threshold)}):
        result = evaluate_duplicate_pairs(
            ground_truth,
            predictions,
            candidate_threshold,
        )
        threshold_rows.append(
            {
                "threshold": candidate_threshold,
                "predicted_positive_pairs": result.metrics["predicted_positive_pairs"],
                "precision": result.metrics["precision"],
                "recall": result.metrics["recall"],
                "f1_score": result.metrics["f1_score"],
            }
        )

    candidate_result = evaluate_duplicate_pairs(ground_truth, predictions, 0.0)
    metrics = dict(selected.metrics)
    metrics["detector_candidate_pairs"] = len(predictions)
    metrics["candidate_pair_recall"] = candidate_result.metrics["recall"]
    label_profile = (
        ground_truth.groupby(["ISSUE_TYPE", "EXPECTED_DECISION"], dropna=False)
        .size()
        .reset_index(name="RECORD_COUNT")
        .sort_values(["RECORD_COUNT", "ISSUE_TYPE"], ascending=[False, True])
        .reset_index(drop=True)
    )
    return EvaluationResult(
        metrics=metrics,
        cases=selected.cases,
        threshold_analysis=pd.DataFrame(threshold_rows),
        label_profile=label_profile,
    )


def _serializable_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(frame.to_json(orient="records"))


def _rounded_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {key: round(value, 6) if isinstance(value, float) else value for key, value in metrics.items()}


def write_evaluation_outputs(
    result: EvaluationResult,
    output_directory: str | Path,
) -> dict[str, str]:
    """Write the reproducible evaluation metrics and error-analysis artifacts."""
    output_dir = Path(output_directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "evaluation_summary.json"
    cases_path = output_dir / "evaluation_cases.csv"
    thresholds_path = output_dir / "threshold_analysis.csv"
    label_profile_path = output_dir / "label_profile.csv"
    report_path = output_dir / "evaluation_report.md"

    threshold_records = _serializable_records(result.threshold_analysis)
    best_f1 = max((float(row["f1_score"]) for row in threshold_records), default=0.0)
    best_thresholds = [float(row["threshold"]) for row in threshold_records if abs(float(row["f1_score"]) - best_f1) < 1e-12]
    summary = {
        "evaluation_scope": "Deterministic pairwise duplicate detection",
        "metrics": _rounded_metrics(result.metrics),
        "best_observed_f1": round(best_f1, 6),
        "best_observed_thresholds": best_thresholds,
        "threshold_analysis": threshold_records,
        "label_profile": _serializable_records(result.label_profile),
        "methodology": {
            "positive_pair": "Both suppliers share a nonblank duplicate cluster ID.",
            "predicted_positive": "The detector returned the pair with a duplicate score at or above the selected threshold.",
            "unreturned_pair": "Predicted negative.",
            "true_negatives": "Calculated across all unique supplier pairs; not written row by row.",
        },
        "limitations": [
            "The workbook is synthetic and intentionally structured; these metrics do not estimate real-company performance.",
            "Threshold comparisons use the same labels used to report performance and are diagnostic, not an independent validation set.",
            "This evaluation scores duplicate detection. Other data-quality issue labels are profiled but not treated as predicted issue classes.",
        ],
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    for frame, path in (
        (result.cases, cases_path),
        (result.threshold_analysis, thresholds_path),
        (result.label_profile, label_profile_path),
    ):
        Path(path).write_text(csv_text(frame), encoding="utf-8")  # spreadsheet formulas neutralised

    metrics = result.metrics
    threshold_lines = [
        "| Threshold | Predicted positive pairs | Precision | Recall | F1 |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in threshold_records:
        threshold_lines.append(
            f"| {float(row['threshold']):.0f} | {int(row['predicted_positive_pairs'])} | "
            f"{float(row['precision']):.3f} | {float(row['recall']):.3f} | {float(row['f1_score']):.3f} |"
        )
    report = f"""# Duplicate Detection Evaluation

## Selected threshold: {float(metrics["threshold"]):.0f}

| Metric | Result |
|---|---:|
| Labelled supplier records | {int(metrics["supplier_records"]):,} |
| Ground-truth duplicate pairs | {int(metrics["ground_truth_positive_pairs"]):,} |
| Detector candidate pairs | {int(metrics["detector_candidate_pairs"]):,} |
| Predicted duplicate pairs | {int(metrics["predicted_positive_pairs"]):,} |
| True positives | {int(metrics["true_positives"]):,} |
| False positives | {int(metrics["false_positives"]):,} |
| False negatives | {int(metrics["false_negatives"]):,} |
| Precision | {float(metrics["precision"]):.3f} |
| Recall | {float(metrics["recall"]):.3f} |
| F1 score | {float(metrics["f1_score"]):.3f} |
| Candidate-pair recall | {float(metrics["candidate_pair_recall"]):.3f} |

## Threshold comparison

{chr(10).join(threshold_lines)}

## Interpretation

The selected threshold is evaluated at the pair level. Two suppliers are a
ground-truth duplicate pair when they share the same nonblank cluster ID. The
case CSV contains true positives, false positives, and false negatives so each
meaningful result can be inspected. True negatives are counted in the summary
but omitted from the case file because there are many of them.

## Synthetic benchmark limitation

The source labels are synthetic and the intentional duplicates are unusually
clean. Perfect results here prove that the implementation can recover the
designed cases; they do not prove that it will perform perfectly on real
supplier data. Threshold selection must be repeated on an approved real-data
pilot with approved data.

Other labelled data-quality issues are included in `label_profile.csv`, but the
current detector does not predict those issue classes. This evaluation does not pretend
that duplicate metrics measure missing identifiers, lifecycle anomalies, or
currency anomalies.
"""
    report_path.write_text(report, encoding="utf-8")
    return {
        "summary": str(summary_path.resolve()),
        "cases": str(cases_path.resolve()),
        "thresholds": str(thresholds_path.resolve()),
        "label_profile": str(label_profile_path.resolve()),
        "report": str(report_path.resolve()),
    }
