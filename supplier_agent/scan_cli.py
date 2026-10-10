"""Backwards-compatible entry point: ``python -m supplier_agent.scan_cli --input FILE``.

Prefer ``supplier-desk scan FILE``.
"""

import argparse

from .cli import main as cli_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan a supplier file for duplicate and quality findings, without AI.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="outputs/review_queue.csv")
    parser.add_argument("--report")
    args = parser.parse_args(argv)
    forwarded = ["scan", args.input, "--output", args.output]
    if args.report:
        forwarded += ["--report", args.report]
    return cli_main(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
