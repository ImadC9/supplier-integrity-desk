"""Turn confirmed duplicate decisions into an action list for the ERP team.

The tool never changes supplier data. This list tells the people who do which
record to keep and which to block, so it can be loaded into a mass-change or
ticketing process.
"""

from __future__ import annotations

import pandas as pd

from .clusters import _UnionFind, survivor_ranking

ACTION_COLUMNS = [
    "GROUP_ID",
    "KEEP_ID",
    "KEEP_NAME",
    "RETIRE_ID",
    "RETIRE_NAME",
    "ACTION",
    "DECIDED_BY",
    "DECIDED_AT",
    "NOTES",
]
ACTION_TEXT = (
    "Block RETIRE_ID for purchasing and payment; move open orders, contracts and catalogue items to KEEP_ID; "
    "check open invoices and payments before blocking."
)


def action_plan(queue: pd.DataFrame, latest: dict[str, dict], suppliers: pd.DataFrame) -> pd.DataFrame:
    """Build keep/retire rows from the latest CONFIRM_DUPLICATE decisions.

    ``queue`` maps finding IDs to supplier pairs, ``latest`` is
    ``ReviewStore.latest(dataset_id)``. A later decision on the same pair
    (for example NOT_DUPLICATE) replaces an earlier confirmation.
    """
    pairs = queue[queue["TYPE"].eq("DUPLICATE")].set_index("FINDING_ID")
    union = _UnionFind()
    decisions: dict[str, list[dict]] = {}
    for finding, review in latest.items():
        if review.get("decision") != "CONFIRM_DUPLICATE" or finding not in pairs.index:
            continue
        pair = pairs.loc[finding]
        left, right = str(pair["SUPPLIER_ID"]), str(pair["CANDIDATE_ID"])
        union.union(left, right)
        decisions.setdefault(left, []).append(review)
        decisions.setdefault(right, []).append(review)
    if not union.parent:
        return pd.DataFrame(columns=ACTION_COLUMNS)

    by_id = suppliers.set_index("SUPPLIER_ID", drop=False).to_dict("index")
    groups: dict[str, list[str]] = {}
    for supplier_id in list(union.parent):
        groups.setdefault(union.find(supplier_id), []).append(supplier_id)
    rows = []
    for number, members in enumerate(sorted(groups.values(), key=lambda ids: sorted(ids)[0]), start=1):
        records = [by_id[supplier_id] for supplier_id in sorted(members) if supplier_id in by_id]
        keep = survivor_ranking(records)[0][0]
        for record in records:
            if record["SUPPLIER_ID"] == keep["SUPPLIER_ID"]:
                continue
            reviews = sorted(decisions.get(record["SUPPLIER_ID"], []), key=lambda item: item.get("reviewed_at", ""))
            last = reviews[-1] if reviews else {}
            rows.append(
                {
                    "GROUP_ID": f"MERGE-{number:03d}",
                    "KEEP_ID": keep["SUPPLIER_ID"],
                    "KEEP_NAME": keep.get("SUPPLIER_NAME", ""),
                    "RETIRE_ID": record["SUPPLIER_ID"],
                    "RETIRE_NAME": record.get("SUPPLIER_NAME", ""),
                    "ACTION": ACTION_TEXT,
                    "DECIDED_BY": last.get("reviewer", ""),
                    "DECIDED_AT": last.get("reviewed_at", ""),
                    "NOTES": last.get("notes", ""),
                }
            )
    return pd.DataFrame(rows, columns=ACTION_COLUMNS)
