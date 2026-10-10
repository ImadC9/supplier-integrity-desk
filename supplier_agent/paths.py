"""Locations of files that ship inside the package."""

import os
from pathlib import Path

RESOURCES = Path(__file__).resolve().parent / "resources"
SAMPLE_WORKBOOK = RESOURCES / "sample_suppliers.xlsx"
EXAMPLE_DB = RESOURCES / "sample_suppliers.db"  # the sample as a SQLite database (table: vendors)
PREVIOUS_SAMPLE = RESOURCES / "sample_suppliers_previous.xlsx"  # the same sample, one quarter earlier
# Point SUPPLIER_DESK_POLICY_DIR at a folder of Markdown policies to replace the
# bundled fictional ones (one "# Title" and several "## Section" headings per file).
POLICY_DIR = Path(os.environ.get("SUPPLIER_DESK_POLICY_DIR") or RESOURCES / "policies")
