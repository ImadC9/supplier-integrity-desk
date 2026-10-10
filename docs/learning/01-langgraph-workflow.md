# LangGraph

## Goal

Wrap the existing Python duplicate detector in a stateful investigation workflow:

```text
START
  -> get_supplier
  -> find_candidates
  -> check_evidence
  -> ai_analysis
  -> build_recommendation
  -> human_review
  -> END
```

LangGraph does not replace the matching algorithm. It coordinates when each part runs, carries the case state, saves checkpoints, and pauses for human input.

## Vocabulary

- **State:** the investigation case file passed between steps.
- **Node:** one Python function that reads state and returns state updates.
- **Edge:** the route from one node to the next.
- **Conditional edge:** chooses a route after inspecting state.
- **Checkpointer:** saves the state after graph steps.
- **Thread ID:** identifies one saved investigation.
- **Interrupt:** pauses execution and returns a review request.
- **Command(resume=...):** supplies the human response and continues the same thread.

## File-by-file explanation

### `workflow/state.py`

`InvestigationState` defines the fields that nodes may exchange. It uses a `TypedDict` so editors and type checkers can detect misspelled fields while LangGraph can still pass an ordinary dictionary at runtime.

The graph stores dictionaries and lists instead of a complete Pandas DataFrame. Small serializable state is easier to inspect and persist.

### `workflow/nodes.py`

`make_nodes()` creates six node functions:

1. `get_supplier` reads the approved worksheet and returns one supplier.
2. `find_candidates` calls the Step 2 detector for that supplier.
3. `check_evidence` creates a compact evidence view.
4. `ai_analysis` asks the configured analysis provider to explain the facts.
5. `build_recommendation` selects the deterministic recommendation.
6. `human_review` pauses with `interrupt()` and validates the resumed decision.

The human-review node has no merge, update or delete operation.

### `workflow/analysis.py`

`AnalysisProvider` is a contract. Any provider must accept the supplier and candidate evidence and return an explanation.

The `DeterministicAnalysisProvider` lets us test the graph without credentials,
network calls or model variability. Its output is explicitly labelled
`DETERMINISTIC_PLACEHOLDER`.

`GeminiAnalysisProvider` uses Google's official `google-genai` SDK and
`gemini-3.6-flash`. It reads the credential from `GEMINI_API_KEY`. The key is
never accepted as a command-line argument because command history and process
inspection could expose it.

The Gemini prompt contains only selected supplier context and derived evidence.
Raw Tax IDs, Association Numbers and bank-account values are excluded.

The LLM will explain existing evidence. It will not change similarity values, duplicate scores or supplier data.

### `workflow/graph.py`

`StateGraph(InvestigationState)` creates the graph builder. Nodes are registered by name, then edges define their execution order.

After `get_supplier`, a conditional edge checks the status:

```text
ERROR    -> END
success  -> find_candidates
```

The compiled graph uses `InMemorySaver`. This is suitable for learning and the local prototype. It does not survive a process restart.

### `workflow_cli.py`

The CLI creates a unique thread ID, starts the graph, displays the interrupt payload and optionally resumes it with a human decision.

## Replicate the demonstration

Activate the environment:

```powershell
.venv\Scripts\Activate.ps1  # macOS/Linux: source .venv/bin/activate
```

Run the tests:

```powershell
python -m unittest discover -s tests -v
```

Run a complete pause/resume demonstration:

```powershell
supplier-desk investigate --input sample_suppliers.xlsx --supplier-id S100118 --decision NEEDS_INVESTIGATION
```

Look for these state transitions:

```text
SUPPLIER_LOADED
CANDIDATES_FOUND
EVIDENCE_CHECKED
ANALYSIS_COMPLETE
AWAITING_HUMAN_REVIEW
HUMAN_REVIEW_COMPLETE
```

Test the error route:

```powershell
supplier-desk investigate --input sample_suppliers.xlsx --supplier-id NOT-A-SUPPLIER
```

That run should stop after `get_supplier` and should never reach human review.

## Why the program reloads the workbook

At this stage, nodes call the existing data-loading and detector functions directly. This keeps Step 3 focused on LangGraph.

In Step 4, we will introduce controlled tools such as `get_supplier()` and `find_by_tax_id()`. Those tools will own data access and remove this temporary coupling between graph nodes and the workbook.

## Current limitations

- Gemini 3.6 has been verified in a live synthetic-data investigation.
- Checkpoints live only in process memory.
- Nodes access the workbook directly until Step 4.
- The CLI demonstrates human review; Streamlit remains Step 7.
- The graph recommends and records a decision but never modifies supplier data.

## Explain it in one minute

> The deterministic Python layer creates the factual duplicate evidence. LangGraph carries the investigation state through small nodes, uses conditional routing for controlled outcomes, checkpoints the case, and pauses at an interrupt for Data Steward review. The analysis provider can explain evidence but cannot change scores or supplier records.

## Exercises

1. Run the graph for a supplier with multiple candidates.
2. Run an unknown supplier and identify which conditional edge ends the graph.
3. Change the review decision and compare the final state.
4. Add a harmless field such as `investigation_started_at` to the state and one node update.
5. Explain why storing the complete DataFrame in checkpoint state would be undesirable.
