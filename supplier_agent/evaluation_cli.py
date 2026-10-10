"""Command-line entry point for labelled evaluation."""

from __future__ import annotations

import argparse
import json

from .evaluation import evaluate_workbook, write_evaluation_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate deterministic duplicate pairs against Ground_Truth labels.")
    parser.add_argument("--input", required=True, help="Supplier Excel workbook.")
    parser.add_argument(
        "--threshold",
        type=float,
        default=65.0,
        help="Duplicate-score threshold used for the headline metrics.",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/evaluation",
        help="Directory for the JSON, CSV, and Markdown evaluation outputs.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    result = evaluate_workbook(args.input, threshold=args.threshold)
    outputs = write_evaluation_outputs(result, args.output_dir)
    print(
        json.dumps(
            {
                "metrics": result.metrics,
                "outputs": outputs,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
