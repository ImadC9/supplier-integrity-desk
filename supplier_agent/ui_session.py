"""Session boundary between Streamlit and the checkpointed LangGraph workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
from langgraph.types import Command

from .data_tools import AGENT_SAFE_SUPPLIER_FIELDS, SupplierDataService
from .detector import DetectionConfig
from .workflow import build_investigation_graph
from .workflow.analysis import DeterministicAnalysisProvider, GeminiAnalysisProvider
from .workflow.nodes import ALLOWED_REVIEW_DECISIONS


class InvestigationSession:
    """Own one graph, checkpoint thread, and review lifecycle."""

    def __init__(
        self,
        workbook_path: str | Path | pd.DataFrame,
        analysis_provider: str = "deterministic",
        semantic_enabled: bool = False,
        detection_config: DetectionConfig | None = None,
    ) -> None:
        if analysis_provider not in {"gemini", "deterministic"}:
            raise ValueError("Choose gemini or deterministic analysis.")
        analyzer = GeminiAnalysisProvider() if analysis_provider == "gemini" else DeterministicAnalysisProvider()
        service = SupplierDataService(workbook_path, semantic_enabled=semantic_enabled, detection_config=detection_config)
        self.graph = build_investigation_graph(data_service=service, analyzer=analyzer, semantic_enabled=semantic_enabled)
        self.thread_id = str(uuid4())
        self.config = {"configurable": {"thread_id": self.thread_id}}
        self.review_request: dict[str, Any] | None = None
        self.current_state: dict[str, Any] | None = None
        self.final_state: dict[str, Any] | None = None

    @staticmethod
    def _interrupt_payload(result: dict[str, Any]) -> dict[str, Any] | None:
        interrupts = result.get("__interrupt__", ())
        return interrupts[0].value if interrupts else None

    @property
    def paused_for_review(self) -> bool:
        return self.review_request is not None and self.final_state is None

    def start(self, supplier_id: str, candidate_supplier_id: str | None = None) -> dict[str, Any]:
        """Run through the automated stages and stop at human review."""
        result = self.graph.invoke(
            {"supplier_id": supplier_id.strip().upper(), "requested_candidate_id": candidate_supplier_id}, config=self.config
        )
        self.current_state = result
        self.review_request = self._interrupt_payload(result)
        if self.review_request is None:
            self.final_state = result
        return result

    def submit_decision(
        self, decision: str, candidate_supplier_id: str | None = None, reviewer: str = "", notes: str = ""
    ) -> dict[str, Any]:
        """Resume the same checkpoint with a steward's controlled decision."""
        if not self.paused_for_review:
            raise RuntimeError("This investigation is not awaiting human review.")
        if decision not in ALLOWED_REVIEW_DECISIONS:
            raise ValueError("Choose a permitted review decision.")
        candidates = (self.current_state or {}).get("candidates", [])
        candidate_ids = {str(item["SUPPLIER_ID_B"]) for item in candidates}
        if candidate_supplier_id is None and len(candidates) == 1:
            candidate_supplier_id = next(iter(candidate_ids))
        if candidate_supplier_id is not None and candidate_supplier_id not in candidate_ids:
            raise ValueError("Select a candidate from this investigation.")
        if decision == "CONFIRM_DUPLICATE" and candidate_supplier_id is None:
            raise ValueError("A confirmed duplicate must identify a candidate.")
        if candidates and decision == "NOT_DUPLICATE" and candidate_supplier_id is None:
            raise ValueError("Select the candidate this decision applies to.")
        result = self.graph.invoke(
            Command(
                resume={
                    "decision": decision,
                    "candidate_supplier_id": candidate_supplier_id,
                    "reviewer": reviewer.strip(),
                    "notes": notes.strip(),
                }
            ),
            config=self.config,
        )
        self.current_state = result
        self.final_state = result
        return result

    def export_json(self) -> str:
        """Return the complete case record for local download."""
        state = dict(self.final_state or self.current_state or {})
        state.pop("__interrupt__", None)
        supplier = state.get("supplier")
        if supplier:
            state["supplier"] = {field: supplier.get(field) for field in AGENT_SAFE_SUPPLIER_FIELDS}
        payload = {
            "schema_version": 1,
            "thread_id": self.thread_id,
            "paused_for_review": self.paused_for_review,
            "review_request": self.review_request,
            "final_state": state,
        }
        return json.dumps(payload, indent=2, default=str)
