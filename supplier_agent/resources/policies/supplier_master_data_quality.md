# Example Supplier Master Data Quality Standard

> Example standard bundled with Supplier Integrity Desk. It is fictional — replace it with your organisation's own standard (see `SUPPLIER_DESK_POLICY_DIR`).

## 1. Required identity data

A supplier record should contain a legal name, country, address, applicable registration or tax identifier, ownership company, site, and active status. Missing fields are data-quality issues but do not alone prove duplication.

## 2. Normalization

Comparison may normalize casing, whitespace, punctuation, and common legal suffixes. Normalized values are used for matching only and must not overwrite source values.

## 3. Country and company scope

Identifiers must be interpreted in the correct country and legal-company scope. Similar values across unrelated jurisdictions require cautious review rather than an automatic duplicate conclusion.

## 4. Activity and lifecycle context

Inactive supplier status, recent purchase orders, and recent spend provide lifecycle context for review. Activity can affect remediation priority, but an inactive supplier or zero spend is not proof that a record may be deleted.
