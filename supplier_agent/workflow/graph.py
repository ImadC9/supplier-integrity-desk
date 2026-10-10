"""Construction of the LangGraph supplier investigation workflow."""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from ..data_tools import SupplierDataService
from ..paths import POLICY_DIR
from ..policy_rag import PolicyRetriever
from .analysis import AnalysisProvider, DeterministicAnalysisProvider
from .nodes import make_nodes
from .state import InvestigationState


def _after_get_supplier(state: InvestigationState) -> str:
    return "stop" if state.get("status") == "ERROR" else "continue"


def build_investigation_graph(
    workbook_path: str | None = None,
    analyzer: AnalysisProvider | None = None,
    checkpointer: InMemorySaver | None = None,
    data_service: SupplierDataService | None = None,
    policy_retriever: PolicyRetriever | None = None,
    semantic_enabled: bool = True,
):
    """Compile the graph around the controlled supplier data service."""
    if data_service is None:
        if workbook_path is None:
            raise ValueError("workbook_path or data_service is required.")
        data_service = SupplierDataService(workbook_path, semantic_enabled=semantic_enabled)
    selected_analyzer = analyzer or DeterministicAnalysisProvider()
    selected_policy_retriever = policy_retriever or PolicyRetriever(POLICY_DIR, semantic_enabled=semantic_enabled)
    nodes = make_nodes(
        data_service,
        selected_policy_retriever,
        selected_analyzer,
    )

    builder = StateGraph(InvestigationState)
    for name, node in nodes.items():
        builder.add_node(name, node)

    builder.add_edge(START, "get_supplier")
    builder.add_conditional_edges(
        "get_supplier",
        _after_get_supplier,
        {"continue": "find_candidates", "stop": END},
    )
    builder.add_edge("find_candidates", "check_evidence")
    builder.add_edge("check_evidence", "retrieve_policy")
    builder.add_edge("retrieve_policy", "ai_analysis")
    builder.add_edge("ai_analysis", "build_recommendation")
    builder.add_edge("build_recommendation", "human_review")
    builder.add_edge("human_review", END)

    return builder.compile(checkpointer=checkpointer or InMemorySaver())
