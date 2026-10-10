# Controlled Data Tools

## Goal

Move data access out of LangGraph nodes and behind an approved, read-only
interface.

```text
LangGraph workflow
        |
        v
Controlled supplier tools
        |
        v
SupplierDataService
        |
        v
Supplier_Master worksheet
```

The graph is allowed to ask specific business questions. It is not allowed to
submit arbitrary SQL, choose columns dynamically, open another file, or update
supplier data.

## Why this matters

Giving an LLM unrestricted database access creates unnecessary security and
reliability risks. A narrow function such as `find_by_tax_id(supplier_id)`
defines exactly:

- what input is allowed;
- what lookup is performed;
- what fields are returned;
- how many results may be returned;
- what gets written to the audit trail.

## The service layer

`supplier_agent/data_tools.py` contains `SupplierDataService`. It loads the
approved workbook once and owns every permitted data operation.

The service currently uses Excel. In a future internal version, its
implementation can call SQL or the Power BI API. The LangGraph nodes continue
calling the same business operations, so the workflow does not need to know
where the data lives.

## Approved operations

### `get_supplier(supplier_id)`

Retrieves one exact supplier. The model-facing wrapper returns only approved
non-sensitive fields.

### `find_by_tax_id(supplier_id)`

Looks up the selected supplier's Tax ID internally, applies the country scope,
and returns matching suppliers. The caller never supplies arbitrary Tax IDs.

### `find_by_association_no(supplier_id)`

Performs the equivalent country-scoped Association Number lookup.

### `find_by_bank_account(supplier_id)`

Looks up the bank account internally and scopes it by bank country. Raw bank
values are not returned to the model.

### `find_similar_names(supplier_id, limit)`

Uses the Step 2 normalization and RapidFuzz logic. Results are limited to the
same country and the requested limit is capped at 25.

### `find_similar_addresses(supplier_id, limit)`

Uses normalized address similarity with the same country boundary and
result-limit protection.

### `get_supplier_activity(supplier_id)`

Returns activity fields such as active status, last PO date, 12-month PO count,
spend, and currency.

### `compare_supplier_pair(supplier_id, candidate_supplier_id)`

Runs the deterministic Step 2 evidence calculation for one explicit pair.

## LangChain tool wrappers

`create_langchain_supplier_tools()` converts the allow-listed functions into
typed tools. Their type hints produce schemas that a model can understand.
Descriptions tell the model when each tool should be used.

The current LangGraph workflow chooses the tool sequence deterministically for
reliability. The same registered wrappers are ready for a later conversational
agent layer in which the model selects among approved tools.

## Current workflow behavior

The `get_supplier` node now calls:

```text
get_supplier
get_supplier_activity
```

The `find_candidates` node calls:

```text
find_by_tax_id
find_by_association_no
find_by_bank_account
find_similar_names
find_similar_addresses
compare_supplier_pair
```

The old direct workbook access has been removed from the nodes.

## Candidate qualification

Search tools may retrieve weak candidates so they can be examined. A pair
enters the final candidate list only when:

- it has at least one exact Tax ID, Association Number, or bank-account signal;
  or
- its fuzzy duplicate score reaches the existing Step 2 minimum.

This keeps the Step 4 refactor from silently changing Step 2 detection behavior.

## Audit trail

Every service call records:

```text
tool name
supplier ID
result count
UTC timestamp
```

The audit data is stored in LangGraph state as `tool_calls`. It helps answer
which data operations ran during an investigation.

## Safety properties

- Read-only operations only
- No access to `Ground_Truth`
- No arbitrary SQL or DAX
- No dynamic workbook path exposed to the model
- No raw Tax ID, Association Number, or bank account in model-facing results
- Same-country boundaries for exact and fuzzy matching
- Bounded fuzzy-search results
- Human review remains mandatory

## Replicate the tests

```powershell
python -m unittest discover -s tests -v
```

The Step 4 tests check:

- the exact tool allow list;
- matching candidates for known data;
- removal of sensitive fields from the model-facing supplier view;
- absence of arbitrary query and file-path arguments;
- audited tool use inside the LangGraph workflow;
- preservation of the original candidate threshold.

## Explain it in one minute

> I separated orchestration from data access. LangGraph nodes call a controlled
> supplier service instead of reading the workbook directly. The service exposes
> only approved, typed, read-only operations and records an audit trail.
> LangChain-compatible tool schemas make those operations model-callable without
> exposing arbitrary SQL or the underlying data source. We can later replace
> Excel with SQL or Power BI while keeping the workflow contract stable.
