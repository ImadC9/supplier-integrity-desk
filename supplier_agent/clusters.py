"""Group duplicate pairs into clusters and suggest which record to keep.

Pairs are links; suppliers connected through any chain of links form one
cluster (A~B and B~C put A, B and C together). For each cluster a *survivor*
is suggested from transparent criteria. The suggestion is advisory: merging
records is a business decision made in the ERP, never by this tool.
"""

from __future__ import annotations

import hashlib

import pandas as pd

LIKELIHOOD_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

CLUSTER_COLUMNS = [
    "CLUSTER_ID",
    "SIZE",
    "MAX_SCORE",
    "TOP_LIKELIHOOD",
    "COUNTRY_CODE",
    "SUPPLIER_IDS",
    "NAMES",
    "SURVIVOR_ID",
    "SURVIVOR_NAME",
    "SURVIVOR_REASON",
    "SIGNALS",
]
MEMBER_COLUMNS = [
    "CLUSTER_ID",
    "SUPPLIER_ID",
    "SUPPLIER_NAME",
    "IS_SUGGESTED_SURVIVOR",
    "ACTIVE_STATUS",
    "PO_COUNT_12M",
    "SPEND_12M_USD",
    "COMPLETENESS",
    "CREATED_DATE",
]
COMPLETENESS_FIELDS = (
    "SUPPLIER_NAME",
    "TAX_ID",
    "ASSOCIATION_NO",
    "COUNTRY_CODE",
    "ADDRESS_1",
    "CITY",
    "POSTAL_CODE",
    "BANK_COUNTRY",
    "BANK_ACCOUNT",
    "CURRENCY",
    "EMAIL",
    "PHONE",
)


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: str, right: str) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left != root_right:
            # Deterministic root: the smaller ID.
            low, high = sorted((root_left, root_right))
            self.parent[high] = low


def _number(value: object) -> float:
    number = pd.to_numeric(str(value).replace(",", "") if value is not None else "", errors="coerce")
    return 0.0 if pd.isna(number) else float(number)


def _completeness(row: dict) -> float:
    present = [field for field in COMPLETENESS_FIELDS if field in row]
    if not present:
        return 0.0
    filled = sum(1 for field in present if str(row.get(field, "")).strip())
    return round(100.0 * filled / len(present), 1)


def _distinct_names(rows: list[dict]) -> str:
    """Names in the cluster, ignoring differences in case and spacing."""
    seen: dict[str, str] = {}
    for row in rows:
        name = " ".join(str(row.get("SUPPLIER_NAME", "")).split())
        seen.setdefault(name.casefold(), name)
    return " | ".join(sorted(seen.values(), key=str.casefold))


def survivor_ranking(members: list[dict]) -> list[tuple[dict, str]]:
    """Order members best-first with a short reason for the first one.

    Criteria, in order: active status, purchase orders in 12 months, spend in
    12 months, field completeness, oldest creation date, then supplier ID.
    """

    def key(row: dict):
        active = str(row.get("ACTIVE_STATUS", "")).strip().upper() != "INACTIVE"
        created = pd.to_datetime(row.get("CREATED_DATE") or None, errors="coerce")
        created_rank = created.value if not pd.isna(created) else float("inf")
        return (
            0 if active else 1,
            -_number(row.get("PO_COUNT_12M")),
            -_number(row.get("SPEND_12M_USD")),
            -_completeness(row),
            created_rank,
            str(row["SUPPLIER_ID"]),
        )

    ordered = sorted(members, key=key)
    best = ordered[0]
    reasons = []
    if str(best.get("ACTIVE_STATUS", "")).strip():
        reasons.append(f"status {str(best.get('ACTIVE_STATUS')).strip().upper()}")
    if _number(best.get("PO_COUNT_12M")):
        reasons.append(f"{int(_number(best.get('PO_COUNT_12M'))):,} POs in 12 months")
    if _number(best.get("SPEND_12M_USD")):
        reasons.append(f"{_number(best.get('SPEND_12M_USD')):,.0f} spend in 12 months")
    reasons.append(f"{_completeness(best):.0f}% of key fields filled")
    return [(row, "; ".join(reasons) if index == 0 else "") for index, row in enumerate(ordered)]


def build_clusters(
    pairs: pd.DataFrame,
    suppliers: pd.DataFrame,
    min_likelihood: str = "MEDIUM",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return ``(clusters, members)`` for pairs at or above ``min_likelihood``."""
    limit = LIKELIHOOD_RANK[min_likelihood]
    if pairs.empty:
        return pd.DataFrame(columns=CLUSTER_COLUMNS), pd.DataFrame(columns=MEMBER_COLUMNS)
    kept = pairs[pairs["LIKELIHOOD"].map(LIKELIHOOD_RANK).le(limit)]
    union = _UnionFind()
    for item in kept.itertuples(index=False):
        union.union(str(item.SUPPLIER_ID_A), str(item.SUPPLIER_ID_B))
    groups: dict[str, list[str]] = {}
    for supplier_id in list(union.parent):
        groups.setdefault(union.find(supplier_id), []).append(supplier_id)

    by_id = suppliers.set_index("SUPPLIER_ID", drop=False).to_dict("index")
    clusters, members = [], []
    for ids in groups.values():
        ids = sorted(ids)
        cluster_id = "CL-" + hashlib.sha256("\0".join(ids).encode()).hexdigest()[:10].upper()
        links = kept[kept["SUPPLIER_ID_A"].isin(ids) & kept["SUPPLIER_ID_B"].isin(ids)]
        signals = []
        for column, label in (
            ("SAME_TAX_ID", "tax ID"),
            ("SAME_ASSOCIATION_NO", "registration no."),
            ("SAME_BANK_ACCOUNT", "bank account"),
            ("SAME_EMAIL", "email"),
            ("SAME_PHONE", "phone"),
        ):
            if column in links and links[column].astype(bool).any():
                signals.append(label)
        if links["NAME_SIMILARITY"].astype(float).ge(70).any():
            signals.append("similar name")
        if links["ADDRESS_SIMILARITY"].astype(float).ge(70).any():
            signals.append("similar address")
        rows = [by_id[supplier_id] for supplier_id in ids if supplier_id in by_id]
        ranking = survivor_ranking(rows)
        survivor, reason = ranking[0]
        countries = sorted({str(row.get("COUNTRY_CODE", "")).strip() for row in rows if str(row.get("COUNTRY_CODE", "")).strip()})
        top = min(links["LIKELIHOOD"], key=lambda value: LIKELIHOOD_RANK[value])
        clusters.append(
            {
                "CLUSTER_ID": cluster_id,
                "SIZE": len(ids),
                "MAX_SCORE": float(links["DUPLICATE_SCORE"].max()),
                "TOP_LIKELIHOOD": top,
                "COUNTRY_CODE": ", ".join(countries),
                "SUPPLIER_IDS": ", ".join(ids),
                "NAMES": _distinct_names(rows),
                "SURVIVOR_ID": survivor["SUPPLIER_ID"],
                "SURVIVOR_NAME": survivor.get("SUPPLIER_NAME", ""),
                "SURVIVOR_REASON": reason,
                "SIGNALS": ", ".join(signals),
            }
        )
        for row, _ in ranking:
            members.append(
                {
                    "CLUSTER_ID": cluster_id,
                    "SUPPLIER_ID": row["SUPPLIER_ID"],
                    "SUPPLIER_NAME": row.get("SUPPLIER_NAME", ""),
                    "IS_SUGGESTED_SURVIVOR": row["SUPPLIER_ID"] == survivor["SUPPLIER_ID"],
                    "ACTIVE_STATUS": row.get("ACTIVE_STATUS", ""),
                    "PO_COUNT_12M": row.get("PO_COUNT_12M", ""),
                    "SPEND_12M_USD": row.get("SPEND_12M_USD", ""),
                    "COMPLETENESS": _completeness(row),
                    "CREATED_DATE": row.get("CREATED_DATE", ""),
                }
            )
    cluster_frame = pd.DataFrame(clusters, columns=CLUSTER_COLUMNS)
    if not cluster_frame.empty:
        cluster_frame["_RANK"] = cluster_frame["TOP_LIKELIHOOD"].map(LIKELIHOOD_RANK)
        cluster_frame = cluster_frame.sort_values(["_RANK", "SIZE", "MAX_SCORE", "CLUSTER_ID"], ascending=[True, False, False, True]).drop(
            columns="_RANK"
        )
    return cluster_frame.reset_index(drop=True), pd.DataFrame(members, columns=MEMBER_COLUMNS)
