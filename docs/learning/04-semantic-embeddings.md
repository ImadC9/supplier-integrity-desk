# Semantic Embeddings and Hybrid Retrieval

## Goal

Improve recall when two supplier records or two policy phrases express a
similar meaning without using the same words.

```text
Exact identifiers + fuzzy text + semantic vectors
                         |
                         v
                explainable candidates
```

Step 6 does not replace the earlier controls. It adds a supporting signal.

## What an embedding is

An embedding converts text into a list of numbers representing its meaning.
Texts with related meanings should point in similar directions in that numeric
space. This project compares directions with cosine similarity and presents the
result as a percentage.

For example, a keyword comparison may miss the relationship between `ocean
cargo services` and `maritime freight solutions` because they share few words.
Embeddings can place them close together because their meanings are related.

## Local model

The project uses FastEmbed 0.8.0 with `BAAI/bge-small-en-v1.5`:

- 384-dimensional vectors;
- CPU inference through ONNX Runtime;
- approximately 67 MB of model files;
- query and passage embedding modes;
- no supplier text sent to an embedding API.

The public model is downloaded once into `.model_cache`. That directory is
excluded from source packages and version control. Later runs reuse it.

## `semantic.py`

`FastEmbedProvider` is the external-model adapter. It exposes two operations:

```python
embed_passages(texts)
embed_query(text)
```

`SemanticSearchIndex` owns normalized vectors and cosine ranking. It can search
using an indexed record ID or arbitrary query text. The embedding provider is
injected, which allows deterministic test vectors without mocking our own
search logic.

## Semantic supplier candidates

Each supplier is represented using approved matching fields:

```text
normalized supplier name
normalized address
supplier category
purchase group
```

The `find_semantic_candidates` controlled tool:

1. receives only a supplier ID and bounded result limit;
2. restricts comparisons to suppliers in the same country;
3. returns safe supplier summary fields;
4. returns `SEMANTIC_SIMILARITY` and `EMBEDDING_MODEL`;
5. writes an audit event like the other data tools.

The graph requests the ten strongest semantic candidates. A record qualifies
as a semantic-only investigation candidate at 85% or higher. That threshold is
a transparent prototype configuration, not an evaluated production threshold.

## Why the deterministic score is unchanged

The existing `DUPLICATE_SCORE` is based on understandable evidence weights for
identifiers, name similarity, and address similarity. Step 8 has not evaluated
an embedding contribution against labelled cases yet.

Therefore Step 6 records semantic similarity separately and uses it for
candidate discovery, but does not add it secretly to `DUPLICATE_SCORE`.
Semantic-only candidates remain `LOW` likelihood until their other evidence is
reviewed. This prevents model similarity from looking like confirmed identity.

## Hybrid policy retrieval

`PolicyRetriever.retrieve()` keeps the Step 5 public contract but now combines:

- LlamaIndex keyword retrieval;
- lexical query overlap;
- FastEmbed semantic-vector similarity.

The prototype hybrid rank is:

```text
40% lexical overlap + 60% semantic similarity
```

Each passage additionally reports:

```text
retrieval_mode = HYBRID_KEYWORD_VECTOR
semantic_similarity
embedding_model
```

This allows a policy question such as `Who can authorize consolidation?` to
retrieve the human Data Steward decision rule even when wording differs.

## Updated workflow

The node order remains unchanged from Step 5:

```text
Get Supplier
    -> Find Candidates
    -> Check Evidence
    -> Retrieve Policy
    -> AI Analysis
    -> Build Recommendation
    -> Human Review
```

What changed inside the nodes:

- `find_candidates` now also calls `find_semantic_candidates`;
- `compare_supplier_pair` adds semantic similarity and model metadata;
- `check_evidence` carries those fields forward;
- `retrieve_policy` performs hybrid retrieval;
- Gemini receives the semantic evidence and cited hybrid results.

LangGraph still controls the order and checkpoints. The LLM still does not
execute the embedding model or calculate the similarity.

## Example result

For `S100118`, the enhanced workflow found:

- two 100% deterministic duplicates with 100% semantic similarity;
- two additional semantic-only candidates above 85%;
- the additional candidates retained a deterministic score of 0 and `LOW`
  likelihood because they lacked exact or strong fuzzy evidence.

This demonstrates higher recall without turning semantic resemblance into an
automatic duplicate decision.

## Safety and governance

- Embeddings run locally.
- Supplier comparisons remain same-country.
- Model name and similarity are visible in evidence.
- Semantic results do not overwrite deterministic scores.
- The model cache is not packaged as source.
- `Ground_Truth` remains untouched until Step 8.
- No merge, delete, or update operation exists.
- Human Data Steward review remains mandatory.

## Replicate the tests

```powershell
python -m unittest discover -s tests -v
```

The first semantic run downloads the public model. Subsequent runs use the
local cache.

Run the complete offline demonstration:

```powershell
supplier-desk investigate `
  --input sample_suppliers.xlsx `
  --supplier-id S100118 `
  --decision NEEDS_INVESTIGATION `
  --output outputs/step6_semantic_investigation.json
```

## Explain it in one minute

> I added local semantic embeddings to improve candidate recall and upgraded
> policy RAG to hybrid keyword/vector retrieval. The embedding model runs with
> ONNX on the local machine, supplier search stays within country boundaries,
> and every result includes similarity and model metadata. I deliberately kept
> semantic similarity separate from the deterministic duplicate score because
> labelled threshold evaluation belongs to the later evaluation step.
