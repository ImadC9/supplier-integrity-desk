"""Node functions for the supplier investigation graph."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from langgraph.types import interrupt

from ..data_tools import SupplierDataService
from ..policy_rag import PolicyRetriever
from .analysis import AnalysisProvider, DeterministicAnalysisProvider
from .state import InvestigationState

ALLOWED_REVIEW_DECISIONS = {
    "CONFIRM_DUPLICATE",
    "NOT_DUPLICATE",
    "NEEDS_INVESTIGATION",
}


def make_nodes(
    data_service: SupplierDataService,
    policy_retriever: PolicyRetriever,
    analyzer: AnalysisProvider,
) -> dict[str, Any]:
    """Create nodes with access only to the approved data service."""

    def get_supplier(state: InvestigationState) -> dict[str, Any]:
        supplier_id = str(state.get("supplier_id", "")).strip().upper()
        supplier = data_service.get_supplier(supplier_id)
        if supplier is None:
            return {
                "supplier_id": supplier_id,
                "supplier": None,
                "status": "ERROR",
                "errors": [f"Unknown supplier ID: {supplier_id}"],
                "tool_calls": data_service.audit_snapshot(),
            }
        activity = data_service.get_supplier_activity(supplier_id)
        quality = data_service.quality_findings
        findings = quality[quality["SUPPLIER_ID"].eq(supplier_id)].to_dict("records")
        return {
            "supplier_id": supplier_id,
            "supplier": supplier,
            "supplier_activity": activity,
            "quality_findings": findings,
            "status": "SUPPLIER_LOADED",
            "errors": [],
            "tool_calls": data_service.audit_snapshot(),
        }

    def find_candidates(state: InvestigationState) -> dict[str, Any]:
        supplier_id = state["supplier_id"]
        candidate_ids: set[str] = set()
        if state.get("requested_candidate_id"):
            candidate_ids.add(str(state["requested_candidate_id"]).strip().upper())
        searches = [
            data_service.find_by_tax_id(supplier_id),
            data_service.find_by_association_no(supplier_id),
            data_service.find_by_bank_account(supplier_id),
            data_service.find_by_email(supplier_id),
            data_service.find_by_phone(supplier_id),
            data_service.find_similar_names(supplier_id, limit=25),
            data_service.find_similar_addresses(supplier_id, limit=25),
            data_service.find_semantic_candidates(supplier_id, limit=10),
        ]
        for results in searches:
            candidate_ids.update(str(result["SUPPLIER_ID"]) for result in results)

        candidates = []
        for candidate_id in sorted(candidate_ids):
            evidence = data_service.compare_supplier_pair(
                supplier_id,
                candidate_id,
            )
            if data_service.qualifies_as_candidate(evidence):
                candidates.append(evidence)
        candidates.sort(
            key=lambda candidate: (
                -float(candidate["DUPLICATE_SCORE"]),
                str(candidate["SUPPLIER_ID_B"]),
            )
        )
        return {
            "candidates": candidates,
            "status": "CANDIDATES_FOUND" if candidates else "NO_CANDIDATES",
            "tool_calls": data_service.audit_snapshot(),
        }

    def check_evidence(state: InvestigationState) -> dict[str, Any]:
        evidence_fields = [
            "SUPPLIER_ID_B",
            "SAME_TAX_ID",
            "SAME_ASSOCIATION_NO",
            "SAME_BANK_ACCOUNT",
            "SAME_EMAIL",
            "SAME_PHONE",
            "NAME_SIMILARITY",
            "ADDRESS_SIMILARITY",
            "SEMANTIC_SIMILARITY",
            "EMBEDDING_MODEL",
            "DUPLICATE_SCORE",
            "LIKELIHOOD",
            "EVIDENCE",
        ]
        evidence = [{field: candidate.get(field) for field in evidence_fields} for candidate in state.get("candidates", [])]
        return {"evidence": evidence, "status": "EVIDENCE_CHECKED"}

    def retrieve_policy(state: InvestigationState) -> dict[str, Any]:
        evidence = state.get("evidence", [])
        query_terms = ["duplicate supplier review", "Data Steward"]
        if any(item.get("SAME_TAX_ID") for item in evidence):
            query_terms.append("same tax identifier")
        if any(item.get("SAME_ASSOCIATION_NO") for item in evidence):
            query_terms.append("same association number")
        if any(item.get("SAME_BANK_ACCOUNT") for item in evidence):
            query_terms.append("same bank account")
        if any(float(item.get("NAME_SIMILARITY") or 0) > 0 for item in evidence):
            query_terms.append("name similarity")
        if any(float(item.get("ADDRESS_SIMILARITY") or 0) > 0 for item in evidence):
            query_terms.append("address similarity")
        if any(float(item.get("SEMANTIC_SIMILARITY") or 0) > 0 for item in evidence):
            query_terms.append("semantic embedding similarity")
        if not evidence:
            query_terms.append("no candidate threshold")
        if state.get("quality_findings"):
            query_terms.append("required fields completeness country data quality activity lifecycle")

        query = " ".join(query_terms)
        passages = policy_retriever.retrieve(query, limit=3)
        return {
            "policy_query": query,
            "policy_context": passages,
            "policy_citations": [item["citation"] for item in passages],
            "status": "POLICY_RETRIEVED",
        }

    def ai_analysis(state: InvestigationState) -> dict[str, Any]:
        supplier = dict(state["supplier"])
        supplier["DATA_QUALITY_FINDINGS"] = state.get("quality_findings", [])
        warnings = []
        mode = analyzer.mode
        try:
            explanation = analyzer.analyze(supplier, state.get("candidates", []), state.get("policy_context", []))
        except Exception:
            if not mode.startswith("GEMINI:"):
                raise
            explanation = DeterministicAnalysisProvider().analyze(supplier, state.get("candidates", []), state.get("policy_context", []))
            mode = "DETERMINISTIC_FALLBACK"
            warnings.append(
                "Gemini could not provide an explanation. Evidence is still available; this case uses a rule-based explanation. Check credentials, model, quota and network before retrying."
            )
        return {
            "ai_analysis": explanation,
            "analysis_mode": mode,
            "warnings": warnings,
            "status": "ANALYSIS_COMPLETE",
        }

    def build_recommendation(state: InvestigationState) -> dict[str, Any]:
        candidates = state.get("candidates", [])
        if not candidates:
            recommendation = "No likely duplicate was found by the current deterministic checks."
        else:
            top = candidates[0]
            recommendation = str(top["RECOMMENDATION"])
        return {
            "recommendation": recommendation,
            "status": "AWAITING_HUMAN_REVIEW",
        }

    def human_review(state: InvestigationState) -> dict[str, Any]:
        review_request = {
            "supplier_id": state["supplier_id"],
            "supplier_name": state["supplier"]["SUPPLIER_NAME"],
            "recommendation": state["recommendation"],
            "ai_analysis": state["ai_analysis"],
            "evidence": state.get("evidence", []),
            "policy_citations": state.get("policy_citations", []),
            "quality_findings": state.get("quality_findings", []),
            "allowed_decisions": sorted(ALLOWED_REVIEW_DECISIONS),
        }
        response = interrupt(review_request)
        decision = response.get("decision") if isinstance(response, dict) else str(response)
        decision = str(decision).strip().upper()
        if decision not in ALLOWED_REVIEW_DECISIONS:
            return {
                "review_decision": None,
                "status": "ERROR",
                "errors": [f"Invalid review decision: {decision}. Allowed values: {sorted(ALLOWED_REVIEW_DECISIONS)}"],
            }
        candidate_id = response.get("candidate_supplier_id") if isinstance(response, dict) else None
        candidates = state.get("candidates", [])
        if candidate_id is None and len(candidates) == 1:
            candidate_id = str(candidates[0]["SUPPLIER_ID_B"])
        valid_ids = {str(item["SUPPLIER_ID_B"]) for item in candidates}
        if (
            (candidate_id is not None and candidate_id not in valid_ids)
            or (candidates and decision != "NEEDS_INVESTIGATION" and candidate_id not in valid_ids)
            or (decision == "CONFIRM_DUPLICATE" and not candidate_id)
        ):
            raise ValueError("Select the candidate this decision applies to; a duplicate requires a candidate.")
        return {
            "review_decision": decision,
            "reviewed_candidate_id": candidate_id,
            "reviewer": str(response.get("reviewer", "") if isinstance(response, dict) else ""),
            "review_notes": str(response.get("notes", "") if isinstance(response, dict) else ""),
            "reviewed_at": datetime.now(UTC).isoformat(),
            "status": "HUMAN_REVIEW_COMPLETE",
        }

    return {
        "get_supplier": get_supplier,
        "find_candidates": find_candidates,
        "check_evidence": check_evidence,
        "retrieve_policy": retrieve_policy,
        "ai_analysis": ai_analysis,
        "build_recommendation": build_recommendation,
        "human_review": human_review,
    }
