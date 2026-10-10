"""The serializable case file carried through the LangGraph workflow."""

from typing import Any, TypedDict


class InvestigationState(TypedDict, total=False):
    """State fields are added as nodes complete their responsibilities."""

    supplier_id: str
    requested_candidate_id: str | None
    supplier: dict[str, Any] | None
    supplier_activity: dict[str, Any] | None
    candidates: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    policy_query: str
    policy_context: list[dict[str, Any]]
    policy_citations: list[str]
    ai_analysis: str | None
    analysis_mode: str
    recommendation: str | None
    review_decision: str | None
    status: str
    errors: list[str]
    tool_calls: list[dict[str, Any]]
    quality_findings: list[dict[str, Any]]
    reviewed_candidate_id: str | None
    reviewer: str
    review_notes: str
    reviewed_at: str
    warnings: list[str]
