"""``supplier-desk`` command-line interface.

supplier-desk app                         open the web interface
supplier-desk scan FILE [--report r.xlsx] scan a file and write the review queue
supplier-desk scan FILE --compare OLD      also list what changed since an earlier file
supplier-desk scan --db URL --query SQL    scan a table read from a database
supplier-desk check FILE --name ... --tax-id ...   does this supplier already exist?
supplier-desk investigate --input FILE --supplier-id ID
supplier-desk evaluate --input FILE       benchmark against Ground_Truth labels
supplier-desk sample [PATH]               copy the fictional sample workbook
supplier-desk template [PATH]             write a blank input template
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__


def _load(args: argparse.Namespace, path: str | None = None):
    """Load suppliers from ``path``/``args.input`` or from ``--db``/``--query``; print errors."""
    from .columns import apply_mapping, suggest_mapping
    from .database import read_query
    from .io import load_supplier_master, validate_supplier_master

    try:
        if path is None and getattr(args, "db", None):
            raw = read_query(args.db, args.query or "")
            return validate_supplier_master(apply_mapping(raw, suggest_mapping(raw.columns)))
        source = path or args.input
        if not source:
            raise ValueError("Give a supplier file, or --db and --query.")
        return load_supplier_master(source, sheet=getattr(args, "sheet", None) if path is None else None)
    except (ValueError, FileNotFoundError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return None


def _scan(args: argparse.Namespace) -> int:
    from .changes import change_summary, compare_snapshots, make_snapshot
    from .detector import DetectionConfig
    from .exports import csv_text
    from .quality import QualityConfig
    from .reports import build_excel_report
    from .triage import scan_suppliers

    suppliers = _load(args)
    if suppliers is None:
        return 2
    detection = DetectionConfig(
        high_threshold=args.high, medium_threshold=min(args.medium, args.high), require_country=not args.ignore_country
    )
    result = scan_suppliers(suppliers, QualityConfig(), detection, args.cluster_level)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(csv_text(result.queue), encoding="utf-8")
    written = [str(output)]
    if args.clusters:
        Path(args.clusters).parent.mkdir(parents=True, exist_ok=True)
        Path(args.clusters).write_text(csv_text(result.cluster_members), encoding="utf-8")
        written.append(args.clusters)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_bytes(build_excel_report(result, source_name=Path(args.input).name if args.input else "database"))
        written.append(args.report)
    changes_summary = None
    if args.compare:
        previous = _load(args, args.compare)
        if previous is None:
            return 2
        earlier = scan_suppliers(previous, QualityConfig(), detection, args.cluster_level)
        changes = compare_snapshots(make_snapshot(earlier, previous), make_snapshot(result, suppliers))
        target = Path(args.changes)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(csv_text(changes), encoding="utf-8")
        written.append(str(target))
        changes_summary = change_summary(changes)
    pairs = result.duplicate_pairs
    summary = {
        "suppliers": result.supplier_count,
        "duplicate_pairs": {
            level: int(pairs["LIKELIHOOD"].eq(level).sum()) if not pairs.empty else 0 for level in ("HIGH", "MEDIUM", "LOW")
        },
        "clusters": len(result.clusters),
        "quality_findings": len(result.quality_findings),
        "written": written,
    }
    if changes_summary is not None:
        summary["changes_since_earlier_file"] = changes_summary
    print(json.dumps(summary, indent=2))
    return 0


def _check(args: argparse.Namespace) -> int:
    from .detector import DetectionConfig
    from .lookup import find_existing, validate_new_supplier, verdict

    suppliers = _load(args)
    if suppliers is None:
        return 2
    record = {
        "SUPPLIER_NAME": args.name or "",
        "COUNTRY_CODE": (args.country or "").upper(),
        "TAX_ID": args.tax_id or "",
        "ASSOCIATION_NO": args.registration or "",
        "ADDRESS_1": args.address or "",
        "CITY": args.city or "",
        "POSTAL_CODE": args.postal_code or "",
        "BANK_ACCOUNT": args.bank_account or "",
        "BANK_COUNTRY": (args.bank_country or args.country or "").upper() if args.bank_account else "",
        "EMAIL": args.email or "",
        "PHONE": args.phone or "",
    }
    matches = find_existing(suppliers, record, DetectionConfig())
    outcome = verdict(matches)
    print(
        json.dumps(
            {"verdict": outcome, "problems": validate_new_supplier(record), "matches": matches.to_dict("records")}, indent=2, default=str
        )
    )
    return 3 if outcome == "LIKELY_EXISTS" and args.fail_on_match else 0


def _pairs(args: argparse.Namespace) -> int:
    """Legacy: pairwise duplicate candidates only (``python -m supplier_agent.cli --input``)."""
    from .detector import DuplicateDetector
    from .exports import csv_text
    from .io import load_supplier_master

    suppliers = load_supplier_master(args.input)
    results = DuplicateDetector().detect(suppliers, supplier_id=args.supplier_id)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(csv_text(results), encoding="utf-8")  # spreadsheet formulas neutralised
    print(
        json.dumps(
            {
                "supplier_records_loaded": len(suppliers),
                "candidate_pairs_returned": len(results),
                "high_likelihood": int((results["LIKELIHOOD"] == "HIGH").sum()),
                "medium_likelihood": int((results["LIKELIHOOD"] == "MEDIUM").sum()),
                "low_likelihood": int((results["LIKELIHOOD"] == "LOW").sum()),
                "supplier_filter": args.supplier_id,
                "output": str(output.resolve()),
            },
            indent=2,
        )
    )
    return 0


# Same settings as .streamlit/config.toml, so `supplier-desk app` looks right from any folder.
_APP_OPTIONS = [
    "--theme.base=light",
    "--theme.primaryColor=#0b3558",
    "--theme.backgroundColor=#f5f8f4",
    "--theme.secondaryBackgroundColor=#e8efed",
    "--theme.textColor=#102a43",
    "--server.maxUploadSize=25",
    "--client.toolbarMode=viewer",
    "--browser.gatherUsageStats=false",
]


def _app(args: argparse.Namespace) -> int:
    from streamlit.web import cli as streamlit_cli

    app = Path(__file__).resolve().parent / "app.py"
    sys.argv = ["streamlit", "run", str(app), "--server.port", str(args.port), *_APP_OPTIONS]
    if args.headless:
        sys.argv += ["--server.headless", "true"]
    return streamlit_cli.main()


def _copy_sample(args: argparse.Namespace) -> int:
    from .paths import SAMPLE_WORKBOOK

    target = Path(args.path)
    shutil.copyfile(SAMPLE_WORKBOOK, target)
    print(f"Wrote {target} (1,000 fictional suppliers; the Ground_Truth sheet is for `supplier-desk evaluate`).")
    return 0


def _template(args: argparse.Namespace) -> int:
    from .io import template_workbook

    Path(args.path).write_bytes(template_workbook())
    print(f"Wrote {args.path}")
    return 0


def _add_db_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", help="SQLite file or SQLAlchemy URL (or set SUPPLIER_DESK_DB_URL).", default=None)
    parser.add_argument("--query", help="One read-only SELECT returning the supplier table.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="supplier-desk", description="Explainable supplier duplicate and data-quality review.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    app = commands.add_parser("app", help="Open the web interface.")
    app.add_argument("--port", type=int, default=8501)
    app.add_argument("--headless", action="store_true", help="Do not open a browser window.")
    app.set_defaults(func=_app)

    scan = commands.add_parser("scan", help="Scan a supplier file and write the review queue.")
    scan.add_argument("input", nargs="?", help="Supplier file (.xlsx, .xlsm, .csv, .tsv). Omit when using --db.")
    _add_db_arguments(scan)
    scan.add_argument("--compare", metavar="EARLIER_FILE", help="List what changed since this earlier version of the file.")
    scan.add_argument("--changes", default="outputs/changes.csv", help="Where to write the changes (with --compare).")
    scan.add_argument("--sheet", help="Excel sheet (default: Supplier_Master or the first data sheet).")
    scan.add_argument("--output", default="outputs/review_queue.csv", help="Review queue CSV.")
    scan.add_argument("--report", help="Also write a formatted Excel report to this path.")
    scan.add_argument("--clusters", help="Also write duplicate cluster members to this CSV.")
    scan.add_argument("--high", type=float, default=65.0, help="Rule score for HIGH priority (default 65).")
    scan.add_argument("--medium", type=float, default=40.0, help="Rule score for MEDIUM priority (default 40).")
    scan.add_argument("--cluster-level", choices=["HIGH", "MEDIUM"], default="HIGH")
    scan.add_argument("--ignore-country", action="store_true", help="Compare records even when country is blank.")
    scan.set_defaults(func=_scan)

    check = commands.add_parser("check", help="Check whether a new supplier already exists in a file or database.")
    check.add_argument("input", nargs="?", help="Supplier file. Omit when using --db.")
    _add_db_arguments(check)
    check.add_argument("--name")
    check.add_argument("--country", help="Two-letter country code.")
    check.add_argument("--tax-id")
    check.add_argument("--registration")
    check.add_argument("--address")
    check.add_argument("--city")
    check.add_argument("--postal-code")
    check.add_argument("--bank-account", help="IBAN or account number.")
    check.add_argument("--bank-country")
    check.add_argument("--email")
    check.add_argument("--phone")
    check.add_argument("--fail-on-match", action="store_true", help="Exit with code 3 when the supplier likely exists.")
    check.set_defaults(func=_check, sheet=None)

    investigate = commands.add_parser("investigate", help="Run the LangGraph investigation for one supplier.", add_help=False)
    investigate.set_defaults(func=None, delegate="investigate")
    evaluate = commands.add_parser("evaluate", help="Benchmark duplicate detection against Ground_Truth labels.", add_help=False)
    evaluate.set_defaults(func=None, delegate="evaluate")

    sample = commands.add_parser("sample", help="Copy the fictional sample workbook.")
    sample.add_argument("path", nargs="?", default="sample_suppliers.xlsx")
    sample.set_defaults(func=_copy_sample)

    template = commands.add_parser("template", help="Write a blank input template.")
    template.add_argument("path", nargs="?", default="supplier_template.xlsx")
    template.set_defaults(func=_template)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0].startswith("--") and argv[0] not in {"--help", "-h", "--version"}:
        legacy = argparse.ArgumentParser(prog="supplier_agent.cli")
        legacy.add_argument("--input", required=True)
        legacy.add_argument("--supplier-id")
        legacy.add_argument("--output", default="outputs/duplicate_candidates.csv")
        return _pairs(legacy.parse_args(argv))
    if argv and argv[0] == "investigate":
        from .workflow_cli import main as investigate_main

        investigate_main(argv[1:])
        return 0
    if argv and argv[0] == "evaluate":
        from .evaluation_cli import main as evaluate_main

        evaluate_main(argv[1:])
        return 0
    args = build_parser().parse_args(argv)
    if getattr(args, "query", None) and not args.db:
        import os

        args.db = os.environ.get("SUPPLIER_DESK_DB_URL")
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
