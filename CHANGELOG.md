# Changelog

## 1.0.0 — first public release

- **Bring your own file:** Excel or CSV/TSV from any ERP with automatic column mapping
  (SAP, generic and canonical header names), sheet selection and a blank template.
  Only supplier ID and name are required.
- **Explainable duplicate detection:** country-scoped tax ID, registration number and bank
  account matches plus fuzzy name and address similarity, with a transparent rule score.
  Legal forms from 40+ countries are ignored; placeholder identifiers (`N/A`, `0000`, `TBD`)
  and widely shared values never create matches.
- **Duplicate clusters** with a suggested record to keep and one decision per cluster.
- **Data-quality rules,** including IBAN length and mod-97 validation.
- **Review workflow:** prioritized queue, side-by-side comparison (bank accounts masked),
  decisions with reviewer and notes, append-only local history.
- **Action plan:** confirmed duplicates become a keep / block list for the ERP team.
- **Overview dashboard** and a formatted **Excel report**.
- **Settings profiles:** save and load the column mapping and rules as JSON.
- **What's new since last scan:** new and resolved findings, added and removed suppliers and changed
  bank, tax or contact details compared with an earlier file; earlier decisions shown per finding.
- **Check a supplier before creating it** in the app or with `supplier-desk check` (JSON output,
  `--fail-on-match` for scripts).
- **Email and phone** as duplicate evidence (placeholder addresses and numbers ignored).
- **Tax / VAT number checks** for 41 countries, with check digits where the algorithm is public.
- **Database source:** one read-only SQL query against SQLite or any SQLAlchemy database.
- **English and Spanish interface,** following the browser language.
- **Investigation agent (optional):** LangGraph workflow with allow-listed read-only tools,
  LlamaIndex policy retrieval with citations, optional local embeddings and Gemini
  explanations, and a mandatory human checkpoint.
- `supplier-desk` command (`app`, `scan`, `check`, `investigate`, `evaluate`, `sample`, `template`),
  pip packaging, Docker image and compose file, labelled evaluation harness and a
  reproducible sample-data generator.
