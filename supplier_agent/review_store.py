"""Append-only local decision history and scan snapshots."""

import json
import secrets
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

DUPLICATE_DECISIONS = {"CONFIRM_DUPLICATE", "NOT_DUPLICATE", "NEEDS_INVESTIGATION"}
QUALITY_DECISIONS = {"FIX_REQUIRED", "ACCEPTED_EXCEPTION", "NEEDS_INVESTIGATION"}


class ReviewStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY, dataset_id TEXT NOT NULL, finding_id TEXT NOT NULL,
                finding_type TEXT NOT NULL, decision TEXT NOT NULL, reviewer TEXT NOT NULL,
                notes TEXT NOT NULL, reviewed_at TEXT NOT NULL, case_json TEXT NOT NULL)""")
            connection.execute("""CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY, dataset_id TEXT NOT NULL, source_name TEXT NOT NULL, created_at TEXT NOT NULL,
                supplier_count INTEGER NOT NULL, finding_count INTEGER NOT NULL, payload TEXT NOT NULL)""")
            connection.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('salt', ?)", (secrets.token_hex(16),))

    @contextmanager
    def _connection(self):
        # sqlite's transaction context commits but does not close the connection.
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                yield connection

    def record(
        self, dataset_id: str, finding_id: str, finding_type: str, decision: str, reviewer: str, notes: str = "", case_json: str = ""
    ) -> None:
        allowed = DUPLICATE_DECISIONS if finding_type == "DUPLICATE" else QUALITY_DECISIONS if finding_type == "DATA_QUALITY" else set()
        if decision not in allowed:
            raise ValueError("The decision is not valid for this finding type.")
        if not reviewer.strip():
            raise ValueError("Enter a reviewer name or initials.")
        if not dataset_id or not finding_id:
            raise ValueError("Dataset and finding IDs are required.")
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO reviews (dataset_id,finding_id,finding_type,decision,reviewer,notes,reviewed_at,case_json) VALUES (?,?,?,?,?,?,?,?)",
                (dataset_id, finding_id, finding_type, decision, reviewer.strip(), notes.strip(), datetime.now(UTC).isoformat(), case_json),
            )

    def history(self, dataset_id: str) -> list[dict]:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute("SELECT * FROM reviews WHERE dataset_id=? ORDER BY id DESC", (dataset_id,))]

    def latest(self, dataset_id: str) -> dict[str, dict]:
        result = {}
        for row in self.history(dataset_id):
            result.setdefault(row["finding_id"], row)
        return result

    def latest_elsewhere(self, dataset_id: str) -> dict[str, dict]:
        """Latest decision per finding recorded on *other* datasets (earlier versions of the file)."""
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT * FROM reviews WHERE dataset_id<>? ORDER BY id DESC", (dataset_id,))
            result: dict[str, dict] = {}
            for row in rows:
                result.setdefault(row["finding_id"], dict(row))
            return result

    # ------------------------------------------------------------ snapshots
    def salt(self) -> str:
        with self._connection() as connection:
            return connection.execute("SELECT value FROM meta WHERE key='salt'").fetchone()[0]

    def save_snapshot(self, snapshot: dict) -> int:
        """Store a scan snapshot unless the latest one for this dataset has the same findings."""
        with self._connection() as connection:
            last = connection.execute(
                "SELECT id, payload FROM snapshots WHERE dataset_id=? ORDER BY id DESC LIMIT 1", (snapshot["dataset_id"],)
            ).fetchone()
            if last and set(json.loads(last[1])["findings"]) == set(snapshot["findings"]):
                return int(last[0])
            cursor = connection.execute(
                "INSERT INTO snapshots (dataset_id, source_name, created_at, supplier_count, finding_count, payload) VALUES (?,?,?,?,?,?)",
                (
                    snapshot["dataset_id"],
                    snapshot.get("source", ""),
                    snapshot["created_at"],
                    snapshot["supplier_count"],
                    len(snapshot["findings"]),
                    json.dumps(snapshot),
                ),
            )
            return int(cursor.lastrowid)

    def snapshots(self, exclude_dataset: str | None = None) -> list[dict]:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT id, dataset_id, source_name, created_at, supplier_count, finding_count FROM snapshots ORDER BY id DESC"
            )
            return [dict(row) for row in rows if row["dataset_id"] != exclude_dataset]

    def snapshot(self, snapshot_id: int) -> dict:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
            if row is None:
                raise KeyError(snapshot_id)
            return json.loads(row[0])
