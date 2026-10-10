# Streamlit Data Steward Interface

## Goal

Give a Data Steward a usable way to run the investigation built in Steps 1–6
without changing its rules or authority model.

```text
Supplier ID
    |
    v
Streamlit -> InvestigationSession -> LangGraph -> human interrupt
    ^                                      |
    |                                      v
    +---------- decision + checkpoint resume
```

Streamlit is the presentation layer. It does not perform duplicate detection,
policy retrieval, or AI reasoning itself.

## Why `ui_session.py` exists

Streamlit reruns the Python page after every interaction. LangGraph, however,
must resume the exact investigation thread that paused for review.

`InvestigationSession` keeps these objects together:

- the compiled graph;
- the unique LangGraph `thread_id`;
- the checkpoint configuration;
- the original human-review request;
- the latest and final case state.

When the steward clicks **Start investigation**, `start()` invokes the graph.
The graph runs every automated node and pauses at `human_review`.

When the steward clicks **Submit steward decision**, `submit_decision()` sends
a LangGraph `Command(resume=...)` into the same thread. It does not start a
second investigation.

## What the screen shows

The route at the top mirrors the workflow:

1. Load record.
2. Find candidates.
3. Check evidence.
4. Retrieve policy.
5. Human review.

The case area then separates three kinds of information:

- **deterministic evidence:** exact identifiers, fuzzy similarities, and the
  original rule score;
- **semantic evidence:** the embedding similarity used for candidate discovery;
- **policy and explanation:** retrieved citations plus the selected analysis
  provider's narrative.

This separation is intentional. A 90% semantic similarity is not displayed as
a 90% duplicate score.

## Human control

The interface exposes only the three decisions already allowed by the graph:

- `CONFIRM_DUPLICATE`
- `NOT_DUPLICATE`
- `NEEDS_INVESTIGATION`

The agent cannot merge, delete, or edit supplier records. After the decision,
the steward can download the complete local case record as JSON.

## Deterministic and Gemini modes

The offline deterministic provider is always available. The Gemini option is
shown only when `GEMINI_API_KEY` or `GOOGLE_API_KEY` exists in the environment.
Both providers receive evidence already calculated by the controlled workflow.
Neither provider can change a score or submit a decision.

## How to run it

From the project directory:

```powershell
supplier-desk app
```

Use `S100118` for the richest learning example: it produces exact-identifier
matches and semantic-only candidates, making the distinction visible.

## How it is tested

Streamlit's public `AppTest` interface runs the page like a user:

1. confirm the page and synthetic warning load;
2. click **Start investigation**;
3. verify the graph pauses for human review;
4. choose `NEEDS_INVESTIGATION`;
5. submit and verify the completed state and download action.

The older detector, tool, retrieval, embedding, prompt-safety, and workflow
tests remain unchanged. Step 7 adds an interface; it does not replace them.
