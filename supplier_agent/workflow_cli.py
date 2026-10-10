"""Run and observe the checkpointed supplier investigation workflow."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from langgraph.types import Command

from .workflow import build_investigation_graph
from .workflow.analysis import (
    DeterministicAnalysisProvider,
    GeminiAnalysisProvider,
)
from .workflow.nodes import ALLOWED_REVIEW_DECISIONS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a checkpointed supplier duplicate investigation.")
    parser.add_argument("--input", required=True, help="Supplier file (.xlsx, .xlsm, .csv).")
    parser.add_argument("--supplier-id", required=True, help="Supplier to investigate.")
    parser.add_argument("--candidate-id", help="Candidate this human decision applies to.")
    parser.add_argument("--semantic", action="store_true", help="Enable optional local embeddings (first run downloads a model).")
    parser.add_argument(
        "--decision",
        choices=sorted(ALLOWED_REVIEW_DECISIONS),
        help="Optional human decision used to resume the paused workflow.",
    )
    parser.add_argument(
        "--analysis-provider",
        choices=["deterministic", "gemini"],
        default="deterministic",
        help="Use deterministic output for offline tests or Gemini for AI analysis.",
    )
    parser.add_argument(
        "--gemini-model",
        default=os.environ.get("GEMINI_MODEL", "gemini-3.6-flash"),
        help="Gemini model used when --analysis-provider gemini is selected.",
    )
    parser.add_argument(
        "--output",
        help="Optional JSON path. Defaults to outputs/investigation_<supplier>.json.",
    )
    return parser


def _interrupt_payload(result: dict) -> dict | None:
    interrupts = result.get("__interrupt__", ())
    return interrupts[0].value if interrupts else None


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    analyzer = GeminiAnalysisProvider(model=args.gemini_model) if args.analysis_provider == "gemini" else DeterministicAnalysisProvider()
    graph = build_investigation_graph(args.input, analyzer=analyzer, semantic_enabled=args.semantic)
    thread_id = f"{args.supplier_id}-{uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}

    result = graph.invoke({"supplier_id": args.supplier_id}, config=config)
    payload = _interrupt_payload(result)

    if payload is not None and args.decision:
        result = graph.invoke(
            Command(resume={"decision": args.decision, "candidate_supplier_id": args.candidate_id}),
            config=config,
        )
        output = {
            "thread_id": thread_id,
            "paused_for_review": False,
            "review_request": payload,
            "final_state": result,
        }
    elif payload is not None:
        output = {
            "thread_id": thread_id,
            "paused_for_review": True,
            "review_request": payload,
            "note": ("The in-memory checkpoint exists only in this running process. Pass --decision to demonstrate resume in one command."),
        }
    else:
        output = {
            "thread_id": thread_id,
            "paused_for_review": False,
            "final_state": result,
        }

    output_path = Path(args.output or f"outputs/investigation_{args.supplier_id}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(output, indent=2, default=str))
    print(f"\nSaved: {output_path.resolve()}")


if __name__ == "__main__":
    main()
