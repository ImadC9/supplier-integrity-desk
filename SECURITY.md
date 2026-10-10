# Security and data protection

## Reporting a vulnerability

Please report security issues privately through GitHub's
**Security → Report a vulnerability** on this repository rather than in a
public issue. You can expect an acknowledgement within a week.

## How the tool treats data

- Source files are only read; nothing is written back, merged or deleted.
- Uploaded files stay in the app's memory; completed decisions go to a local
  SQLite file (`SUPPLIER_REVIEW_DB`).
- The default mode makes **no network calls**. Gemini is used only if you set an
  API key and select it, and its prompt never contains tax IDs, registration
  numbers or bank accounts.
- CSV and Excel exports neutralise spreadsheet formulas.
- Database sources accept one read-only `SELECT`; SQLite files are opened read-only and passwords in
  connection URLs are masked in messages. Use a read-only database account.
- Scan snapshots for *What's new* store salted hashes of identifiers, never the identifiers themselves.

## Limits

There is no authentication, user management or tamper-proof audit trail, and
reviewer names are self-reported. Do not expose the app to the internet with real
data; put it behind your organisation's access control. Free-text notes are stored
as typed — do not enter credentials or identifiers in them.
