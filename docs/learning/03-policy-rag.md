# LlamaIndex Policy RAG

## Goal

Give the investigation access to relevant Supplier Master and data-governance
rules without placing every rule inside the model prompt permanently.

```text
Deterministic evidence
        |
        v
Controlled policy query
        |
        v
LlamaIndex keyword index
        |
        v
Cited policy passages
        |
        v
Gemini analysis and human review
```

This is Retrieval-Augmented Generation (RAG): retrieve the relevant knowledge
first, then give that knowledge to the LLM together with the case evidence.

## What was added

### Fictional policy corpus

The `supplier_agent/resources/policies` directory contains three synthetic training documents:

- Synthetic Duplicate Supplier Review Policy
- Synthetic Data Steward Decision Workflow
- Synthetic Supplier Master Data Quality Standard

They are not any real company's policies. Each
file says explicitly that it is fictional. Approved internal documents can
replace these files later without changing the graph contract.

### `PolicyRetriever`

`supplier_agent/policy_rag.py` parses each Markdown `##` section into a
LlamaIndex `Document`. Metadata is attached before indexing:

```text
document title
section heading
source filename
stable node ID
```

At Step 5, the module built a `SimpleKeywordTableIndex`. It extracted keywords
locally with regular expressions, so retrieval did not call an external model.
Step 6 now combines this keyword index with local semantic embeddings while
preserving the same `retrieve()` interface and citations.

The public method is:

```python
PolicyRetriever.retrieve(query, limit=3)
```

The limit is capped at 10. A result contains `document`, `section`, `text`,
`citation`, and `source_file`.

## Why keyword retrieval now

The fixed plan puts improved similarity and embeddings in Step 6. Adding vector
embeddings in Step 5 would silently combine two roadmap steps. Keyword retrieval
lets us learn and verify the complete RAG architecture now:

1. ingest documents;
2. split them into retrievable units;
3. attach metadata;
4. build an index;
5. retrieve relevant context;
6. cite the source;
7. augment the LLM prompt.

Step 6 can replace or complement the keyword retriever with semantic vector
retrieval while preserving the `retrieve()` result contract.

## The new LangGraph node

The workflow order is now:

```text
Get Supplier
    -> Find Candidates
    -> Check Evidence
    -> Retrieve Policy
    -> AI Analysis
    -> Build Recommendation
    -> Human Review
```

`retrieve_policy` reads the evidence already in LangGraph state. It constructs
a query from known signal categories such as:

- same tax identifier;
- same association number;
- same bank account;
- name similarity;
- address similarity;
- no qualifying candidate.

The query contains no raw identifier values. Retrieved passages are saved as
`policy_context`; their citation strings are also saved as
`policy_citations`. Because this is a normal graph node, the checkpointer records
its completed state just like the other workflow stages.

## What the LLM now receives

The Gemini analysis node receives two bounded JSON blocks:

```text
Evidence JSON
Policy context JSON
```

Its instruction says to preserve deterministic scores, cite only supplied
policy passages, invent no policy, and leave the final decision to a human Data
Steward.

The deterministic offline provider also prints the retrieved policy citations,
so the complete RAG flow can be tested without Gemini or an API key.

## Responsibility split

```text
Python detector  -> calculates duplicate evidence
Data tools       -> retrieve supplier facts
LlamaIndex       -> retrieves applicable policy passages
LangGraph        -> controls order and checkpoints state
Gemini           -> explains evidence using retrieved context
Data Steward     -> makes the final decision
```

LlamaIndex does not calculate the duplicate score. Gemini does not search the
workbook. LangGraph does not decide whether two suppliers are duplicates.

## Safety properties

- Only local Markdown files in the configured policy directory are indexed.
- Every bundled policy is clearly marked as fictional.
- `Ground_Truth` is not loaded or indexed.
- Retrieval sends no data to an external model.
- Raw tax, association, and bank values are absent from the policy query.
- Retrieved passages carry citations.
- Gemini cannot alter deterministic scores or approve a duplicate.
- Human review remains mandatory.

## Replicate the tests

From the project directory:

```powershell
python -m unittest discover -s tests -v
```

The Step 5 tests verify that:

- duplicate evidence retrieves the strong-indicator rule and citation;
- governance questions retrieve the human-decision rule;
- lifecycle questions retrieve the activity-context rule;
- Gemini receives policy context without receiving raw identifiers;
- a complete LangGraph investigation carries citations into human review.

Run the offline demonstration:

```powershell
supplier-desk investigate `
  --input sample_suppliers.xlsx `
  --supplier-id S100118 `
  --decision NEEDS_INVESTIGATION `
  --output outputs/step5_rag_investigation.json
```

## Explain it in one minute

> I added a RAG stage between deterministic evidence collection and LLM
> analysis. LlamaIndex ingests synthetic governance documents as section-level
> nodes with citation metadata and retrieves the most relevant passages using
> local keyword matching. LangGraph checkpoints that context and supplies it to
> Gemini, which explains but cannot alter the score or make the final decision.
> I intentionally deferred semantic embeddings to the next roadmap step.
