"""One workbook scan behind a small interface shared by the UI and CLI."""

import hashlib
from dataclasses import dataclass, field, replace

import pandas as pd

from .clusters import build_clusters
from .detector import DetectionConfig, DuplicateDetector
from .io import validate_supplier_master
from .profile import absent_fields as find_absent_fields
from .profile import field_completeness
from .quality import QualityConfig, check_quality

QUEUE_COLUMNS = [
    "FINDING_ID",
    "TYPE",
    "PRIORITY",
    "SUPPLIER_ID",
    "SUPPLIER_NAME",
    "CANDIDATE_ID",
    "CANDIDATE_NAME",
    "RULE_CODE",
    "FIELD",
    "SCORE",
    "SUMMARY",
    "ACTION",
    "CLUSTER_ID",
]


def finding_id(kind: str, *parts: str) -> str:
    return kind + "-" + hashlib.sha256("\0".join(parts).encode()).hexdigest()[:20]


def dataset_fingerprint(suppliers: pd.DataFrame) -> str:
    """Only supplier content participates; label sheets never do."""
    frame = validate_supplier_master(suppliers)
    frame = frame.sort_values("SUPPLIER_ID").reindex(sorted(frame.columns), axis=1)
    return hashlib.sha256(frame.to_json(orient="split", index=False).encode()).hexdigest()


@dataclass
class ScanResult:
    dataset_id: str
    supplier_count: int
    queue: pd.DataFrame
    duplicate_pairs: pd.DataFrame
    quality_findings: pd.DataFrame
    clusters: pd.DataFrame = field(default_factory=pd.DataFrame)
    cluster_members: pd.DataFrame = field(default_factory=pd.DataFrame)
    completeness: pd.DataFrame = field(default_factory=pd.DataFrame)
    absent_fields: frozenset = frozenset()


def scan_suppliers(
    suppliers: pd.DataFrame,
    quality_config: QualityConfig | None = None,
    detection_config: DetectionConfig | None = None,
    cluster_min_likelihood: str = "HIGH",
) -> ScanResult:
    frame = validate_supplier_master(suppliers)
    absent = find_absent_fields(frame)
    quality_config = quality_config or QualityConfig()
    if not quality_config.absent_fields:
        quality_config = replace(quality_config, absent_fields=absent)
    pairs = DuplicateDetector(detection_config).detect(frame)
    quality = check_quality(frame, quality_config)
    clusters, members = build_clusters(pairs, frame, cluster_min_likelihood)
    cluster_of = dict(zip(members["SUPPLIER_ID"], members["CLUSTER_ID"]))
    rows = []
    for item in pairs.to_dict("records"):
        a, b = str(item["SUPPLIER_ID_A"]), str(item["SUPPLIER_ID_B"])
        rows.append(
            {
                "FINDING_ID": finding_id("DUP", *sorted((a, b))),
                "TYPE": "DUPLICATE",
                "PRIORITY": item["LIKELIHOOD"],
                "SUPPLIER_ID": a,
                "SUPPLIER_NAME": item["SUPPLIER_NAME_A"],
                "CANDIDATE_ID": b,
                "CANDIDATE_NAME": item["SUPPLIER_NAME_B"],
                "RULE_CODE": "DUPLICATE_EVIDENCE",
                "FIELD": "",
                "SCORE": item["DUPLICATE_SCORE"],
                "SUMMARY": item["EVIDENCE"],
                "ACTION": item["RECOMMENDATION"],
                "CLUSTER_ID": cluster_of.get(a, "") if cluster_of.get(a) == cluster_of.get(b) else "",
            }
        )
    for item in quality.to_dict("records"):
        rows.append(
            {
                "FINDING_ID": finding_id("DQ", item["SUPPLIER_ID"], item["RULE_CODE"], item["FIELD"]),
                "TYPE": "DATA_QUALITY",
                "PRIORITY": item["PRIORITY"],
                "SUPPLIER_ID": item["SUPPLIER_ID"],
                "SUPPLIER_NAME": item["SUPPLIER_NAME"],
                "CANDIDATE_ID": "",
                "CANDIDATE_NAME": "",
                "RULE_CODE": item["RULE_CODE"],
                "FIELD": item["FIELD"],
                "SCORE": None,
                "SUMMARY": item["SUMMARY"],
                "ACTION": item["ACTION"],
                "CLUSTER_ID": "",
            }
        )
    queue = pd.DataFrame(rows, columns=QUEUE_COLUMNS)
    if not queue.empty:
        queue["_RANK"] = queue["PRIORITY"].map({"HIGH": 0, "MEDIUM": 1, "LOW": 2})
        queue = (
            queue.sort_values(["_RANK", "SCORE", "FINDING_ID"], ascending=[True, False, True], na_position="last")
            .drop(columns="_RANK")
            .reset_index(drop=True)
        )
    return ScanResult(
        dataset_fingerprint(frame), len(frame), queue, pairs, quality, clusters, members, field_completeness(frame, absent), absent
    )
