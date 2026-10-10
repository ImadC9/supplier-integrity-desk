"""Read the supplier table straight from a database with one read-only query.

* SQLite files work out of the box (opened in read-only mode).
* Other databases (PostgreSQL, SQL Server, MySQL, Oracle, Snowflake…) use a
  SQLAlchemy URL and need the optional extra plus the database driver::

      pip install "supplier-integrity-desk[database]" psycopg2-binary

Only a single SELECT (or WITH … SELECT) statement is accepted, and the tool
never writes to the database. Use a read-only database account anyway.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd

from .io import MAX_SUPPLIERS

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|upsert|drop|alter|create|truncate|grant|revoke|exec|execute|call|attach|detach|pragma|vacuum|copy)\b",
    re.IGNORECASE,
)
SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


def _without_literals(sql: str) -> str:
    return re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", "''", sql)


def validate_query(sql: str) -> str:
    """Return the cleaned query or raise ValueError when it is not a single read-only SELECT."""
    query = (sql or "").strip().rstrip(";").strip()
    if not query:
        raise ValueError("Enter a SELECT query.")
    bare = _without_literals(query)
    bare = re.sub(r"--[^\n]*|/\*.*?\*/", " ", bare, flags=re.DOTALL)
    if ";" in bare:
        raise ValueError("Only one statement is allowed.")
    if not re.match(r"^\s*(select|with)\b", bare, re.IGNORECASE):
        raise ValueError("The query must start with SELECT or WITH.")
    found = _FORBIDDEN.search(bare)
    if found:
        raise ValueError(f"Only read-only queries are allowed (found '{found.group(0)}').")
    return query


def _sqlite_path(connection: str) -> Path | None:
    if connection.startswith("sqlite:///"):
        return Path(connection[len("sqlite:///") :])
    if "://" in connection:
        return None  # any other URL goes through SQLAlchemy
    path = Path(connection)
    return path if path.suffix.lower() in SQLITE_SUFFIXES else None


def read_query(connection: str, sql: str, max_rows: int = MAX_SUPPLIERS) -> pd.DataFrame:
    """Run ``sql`` against ``connection`` (SQLite path or SQLAlchemy URL) and return text columns.

    Database errors are re-raised as ``RuntimeError`` with a short message and
    any credentials in the URL masked.
    """
    try:
        return _read_query(connection, sql, max_rows)
    except (ValueError, FileNotFoundError, RuntimeError):
        raise
    except Exception as error:  # noqa: BLE001 - driver errors have many types
        first_line = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
        raise RuntimeError(f"The database query failed: {re.sub(r'//[^@/]*@', '//***@', first_line)}") from error


def _read_query(connection: str, sql: str, max_rows: int) -> pd.DataFrame:
    query = validate_query(sql)
    connection = (connection or "").strip()
    if not connection:
        raise ValueError("Enter a database connection (a SQLite file path or a SQLAlchemy URL).")
    sqlite_path = _sqlite_path(connection)
    if sqlite_path is not None:
        if not sqlite_path.exists():
            raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")
        db = sqlite3.connect(f"{sqlite_path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            cursor = db.execute(query)
            columns = [item[0] for item in cursor.description or []]
            rows = cursor.fetchmany(max_rows + 1)
        finally:
            db.close()
    else:
        try:
            from sqlalchemy import create_engine, text
        except ImportError as error:
            raise RuntimeError(
                'Databases other than SQLite need the optional extra: pip install "supplier-integrity-desk[database]" '
                "plus the driver for your database."
            ) from error
        engine = create_engine(connection, pool_pre_ping=True)
        try:
            with engine.connect() as db:
                result = db.execution_options(stream_results=True).execute(text(query))
                columns = list(result.keys())
                rows = result.fetchmany(max_rows + 1)
                db.rollback()  # nothing to commit; make that explicit
        finally:
            engine.dispose()
    if len(rows) > max_rows:
        raise ValueError(f"The query returned more than {max_rows:,} rows; filter it (for example by country or company).")
    frame = pd.DataFrame.from_records(rows, columns=columns)
    return frame.astype("string").fillna("")


def describe(connection: str) -> str:
    """A display label without credentials."""
    sqlite_path = _sqlite_path(connection or "")
    if sqlite_path is not None:
        return sqlite_path.name
    return re.sub(r"//[^@/]*@", "//***@", connection or "")
