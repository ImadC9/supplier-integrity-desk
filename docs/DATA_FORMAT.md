# Bring your own supplier file

Supplier Integrity Desk reads **Excel** (`.xlsx`, `.xlsm`) and **delimited text**
(`.csv`, `.tsv`, `.txt` — comma, semicolon, tab or pipe; UTF-8 or Windows-1252).
Everything is read as text, so leading zeros in IDs are preserved as long as the
file itself kept them.

## Columns are mapped automatically

You do not need to rename anything. Headers are matched (case, spaces and
punctuation ignored) against common ERP names, and you can correct the mapping in
the sidebar before scanning.

| Field | Required | Used for matching | Recognised headers (examples) |
|---|:-:|:-:|---|
| `SUPPLIER_ID` | ✔ | | Supplier ID, Vendor No, Vendor Code, LIFNR, Creditor |
| `SUPPLIER_NAME` | ✔ | ✔ | Supplier Name, Vendor Name, NAME1, Company Name, Legal Name |
| `TAX_ID` | | ✔ | Tax ID, VAT Number, TIN, EIN, STCD1, NIF |
| `ASSOCIATION_NO` | | ✔ | Registration Number, Company Number, Chamber of Commerce, KvK, SIRET |
| `COUNTRY_CODE` | | ✔ | Country, Country Code, LAND1 |
| `ADDRESS_1` / `ADDRESS_2` | | ✔ | Street, Address, Address Line 1 / 2 |
| `CITY` | | ✔ | City, Town, ORT01 |
| `POSTAL_CODE` | | ✔ | Postal Code, Postcode, ZIP, PSTLZ |
| `BANK_COUNTRY` | | ✔ | Bank Country, BANKS |
| `BANK_ACCOUNT` | | ✔ | IBAN, Bank Account, Account Number, BANKN |
| `ACTIVE_STATUS` | | | Status, Supplier Status (`ACTIVE` / `INACTIVE`) |
| `PO_COUNT_12M`, `SPEND_12M_USD` | | | PO Count, Spend 12M — used for the suggested record to keep |
| `CREATED_DATE`, `LAST_PO_DATE` | | | Created Date, Last PO Date |
| `EMAIL`, `PHONE` | | ✔ | Email, AP Email, Phone, Telephone — an identical address or number adds evidence |
| `COMPANY`, `SITE`, `SUPPLIER_CATEGORY`, `PURCHASE_GROUP`, `CURRENCY` | | | shown for context |

The complete synonym list is in [`supplier_agent/columns.py`](../supplier_agent/columns.py).
`supplier-desk template` writes an empty workbook with every column and a field guide.

## Rules applied while loading

- Supplier IDs are trimmed and upper-cased and must be unique and non-blank.
- Excel files: the sheet named `Supplier_Master` is used when present, otherwise
  the first data sheet; you can choose another sheet in the sidebar. A sheet named
  `Ground_Truth` is never read by the scan or the agent (only by `supplier-desk evaluate`).
- Up to 20,000 suppliers and 25 MB per file.
- A field the file does not provide is not reported row by row. The Overview lists
  it as "not provided".
- `NA` stays a literal value (it is Namibia's country code).

## How matching uses the fields

- **Exact signals** count only inside the same country (tax ID, registration
  number) or bank country (bank account). Placeholder values such as `N/A`,
  `TBD`, `0000` and `9999` are ignored, and a value shared by more than 25
  records is treated as a placeholder.
- **Fuzzy signals** compare normalized names (accents, punctuation and legal
  forms from 40+ countries such as Ltd, GmbH, SAS, Sp. z o.o., Pty Ltd removed) and addresses (St → Street, Rd → Road…).
- Files without a country column can still be scanned: turn on
  *Compare records without a country* (the app does this automatically when no
  country is mapped; on the command line use `--ignore-country`).

## Rule score

| Signal | Points |
|---|---:|
| Same tax ID (same country) | 25 |
| Same registration number (same country) | 20 |
| Same bank account (same bank country) | 20 |
| Same email address | 10 |
| Same phone number (last nine digits, so +44 20… and 020… match) | 10 |
| Name similarity ≥ 70 % | up to 20 |
| Address similarity ≥ 70 % | up to 15 |

Default priorities: **High** ≥ 65, **Medium** ≥ 40, otherwise **Low**. Both are
adjustable. The score orders the review work; it is not a probability and not
proof of legal identity.

## Quality rules

| Code | Meaning | Default priority |
|---|---|---|
| `MISSING_REQUIRED` | A required field is blank (configurable list) | High for name/country, else Medium |
| `MISSING_IDENTIFIER` | Tax ID or registration number blank | Low |
| `PLACEHOLDER_IDENTIFIER` | Identifier holds a filler such as N/A or 0000 | Low |
| `COUNTRY_FORMAT` | Country / bank country is not two letters | Medium |
| `CURRENCY_FORMAT` | Currency is not three letters | Medium |
| `BANK_SCOPE_MISSING` | Bank account without bank country | High |
| `INVALID_IBAN` | IBAN with the wrong length for its country or failing the mod-97 check | High |
| `TAX_ID_FORMAT` | Tax / VAT number does not match its country's format or check digit | Medium |
| `ACTIVITY_VALUE` | PO count / spend is not a valid non-negative number | Medium |
| `INACTIVE_WITH_ACTIVITY` | Inactive supplier with orders in the last 12 months | Low |

Format checks do not verify ISO membership, and a missing identifier is not a
universal compliance failure — record an *accepted exception* where it is legitimate.

## Tax ID checks

`TAX_ID_FORMAT` checks the published format of business tax numbers for 41 countries — all EU VAT
numbers, GB, CH, NO, US (EIN), CA (BN), MX (RFC), BR (CNPJ), AU (ABN), NZ, IN (GSTIN), SG (UEN), JP, ZA
and AE — and the check digit where the algorithm is public (DE, FR, BE, IT, PL, BR, AU). Numbers can be
written with or without the country prefix and with spaces, dots or dashes. A supplier holding another
EU country's VAT number is accepted when that number is valid for its own country. Countries without a
rule are not checked. A passing check means *well-formed*, not *registered*: use VIES, HMRC or the local
registry to confirm registration. Rules live in [`supplier_agent/taxid.py`](../supplier_agent/taxid.py).

## Reading from a database

Choose **Database** in the app (or `--db` / `--query` on the command line). Enter a SQLite file path or a
SQLAlchemy URL and one `SELECT` (or `WITH … SELECT`) that returns one row per supplier; columns are mapped
like a file's. SQLite works out of the box and is opened read-only. Other databases need
`pip install "supplier-integrity-desk[database]"` plus the driver (for example `psycopg2-binary`,
`pyodbc`, `pymysql`, `oracledb`). Statements that write or change the database are rejected, and
credentials are masked in messages. Set `SUPPLIER_DESK_DB_URL` to keep the URL out of the screen and
shell history.

## Comparing with an earlier file

Every scan is remembered as a *snapshot*: finding IDs with a short description, supplier names, and
salted hashes of the key fields (tax ID, registration number, bank account, email, phone, address).
Raw identifiers are never stored. **What's new** compares the current scan with an earlier snapshot or
an uploaded earlier file and lists new and resolved findings, added and removed suppliers, and changed
key fields — bank-account changes are highlighted because they are a common payment-fraud route.

## What leaves your machine

Nothing, by default. If you choose **Gemini** in an investigation, the prompt
contains allow-listed descriptive fields (name, company, site, country, status,
activity), match flags, similarity scores, quality summaries and policy passages.
Raw tax IDs, registration numbers and bank accounts are never included. Names
can still be confidential: use approved data and approved AI accounts.
