# Running and deploying

## On your computer

```bash
pip install "supplier-integrity-desk[all] @ git+https://github.com/ImadC9/supplier-integrity-desk"
supplier-desk app
```

or from a clone: `pip install -e ".[all]"` then `supplier-desk app`
(`streamlit run streamlit_app.py` also works). Decisions are stored in
`./outputs/reviews.sqlite3` relative to where you start the app; set
`SUPPLIER_REVIEW_DB` to keep them elsewhere. All settings are listed in
[`.env.example`](../.env.example).

## Language

The interface follows the browser language (English or Spanish). Force it with `?lang=es` in the URL
or `SUPPLIER_DESK_LANG=es`.

## Docker

```bash
docker compose up --build          # http://localhost:8501
```

or without compose:

```bash
docker build -t supplier-integrity-desk .
docker run --rm -p 8501:8501 -v desk-data:/data supplier-integrity-desk
```

The image runs as a non-root user, stores review history in the `/data` volume
and has a health check. Pass `GEMINI_API_KEY` at runtime (`-e` or your
orchestrator's secrets) — never bake it into the image.

## Streamlit Community Cloud (public demo)

1. Fork the repository.
2. Create an app pointing at `streamlit_app.py` on the `main` branch.
   `requirements.txt` installs the pinned dependencies and the package itself.
3. Optional: add `GEMINI_API_KEY` under *App settings → Secrets*; the app copies
   it into the environment.

Hosted SQLite storage is temporary on most free hosts, and the app has **no
authentication** — use the sample data only for public demos.

## Inside a company

The tool is designed to run locally or on an internal host. Before using real
supplier data, check with your data-protection and IT teams: put the app behind
your single sign-on (for example a reverse proxy), keep the review database on
managed storage, replace the example policies through `SUPPLIER_DESK_POLICY_DIR`,
and use only an AI provider your organisation has approved (or none — every
feature works offline).
