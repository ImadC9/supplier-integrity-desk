"""Generate the fictional sample workbook and the ERP-style example CSV.

    python scripts/generate_sample_data.py

Everything is random but seeded, so the output is reproducible. The workbook
contains a Supplier_Master sheet, a Ground_Truth sheet with the planted issues
(read only by `supplier-desk evaluate`), a field dictionary and a README sheet.

Planted content:
* 30 duplicate clusters (an original plus two re-entered variants), built from
  typical causes: re-keyed in capitals, legal form spelled differently, new bank
  account, tax ID left blank;
* hard negatives that must NOT be merged: sister companies in the same building,
  unrelated companies paid through the same bank account (factoring or payment
  agent), and same-name subsidiaries in other countries;
* data-quality issues: blank or placeholder identifiers, invalid IBANs, malformed
  codes, bank accounts without a bank country, inactive suppliers with recent
  orders, invalid activity values.
"""

from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from supplier_agent.taxid import tax_id_problem  # noqa: E402
from supplier_agent.validators import IBAN_LENGTHS, make_iban  # noqa: E402

SEED = 20261009
TOTAL = 1000
CLUSTERS = 30
TODAY = date(2026, 9, 30)
WORKBOOK = ROOT / "supplier_agent" / "resources" / "sample_suppliers.xlsx"
EXAMPLE_CSV = ROOT / "examples" / "vendors_erp_export.csv"
EXAMPLE_DB = ROOT / "supplier_agent" / "resources" / "sample_suppliers.db"
PREVIOUS_WORKBOOK = ROOT / "supplier_agent" / "resources" / "sample_suppliers_previous.xlsx"

# code, name, currency, region, legal forms, cities, weight
COUNTRIES = [
    ("US", "United States", "USD", "NA", ["Inc", "LLC", "Corp"], ["Chicago", "Houston", "Atlanta", "Denver", "Seattle", "Columbus"], 16),
    ("GB", "United Kingdom", "GBP", "EU", ["Ltd", "Limited", "PLC"], ["London", "Manchester", "Leeds", "Bristol", "Glasgow"], 10),
    ("DE", "Germany", "EUR", "EU", ["GmbH", "AG"], ["Munich", "Hamburg", "Cologne", "Stuttgart", "Leipzig"], 10),
    ("FR", "France", "EUR", "EU", ["SAS", "SARL", "SA"], ["Paris", "Lyon", "Lille", "Nantes", "Toulouse"], 8),
    ("NL", "Netherlands", "EUR", "EU", ["BV", "NV"], ["Utrecht", "Eindhoven", "Amsterdam", "Groningen"], 5),
    ("ES", "Spain", "EUR", "EU", ["SL", "SA"], ["Madrid", "Seville", "Zaragoza", "Bilbao"], 5),
    ("IT", "Italy", "EUR", "EU", ["SRL", "SpA"], ["Milan", "Turin", "Bologna", "Florence"], 5),
    ("PL", "Poland", "PLN", "EU", ["Sp. z o.o.", "SA"], ["Warsaw", "Krakow", "Wroclaw", "Poznan"], 4),
    ("SE", "Sweden", "SEK", "EU", ["AB"], ["Stockholm", "Gothenburg", "Uppsala"], 3),
    ("IE", "Ireland", "EUR", "EU", ["Ltd", "Limited"], ["Dublin", "Cork", "Galway"], 3),
    ("CA", "Canada", "CAD", "NA", ["Inc", "Ltd"], ["Toronto", "Calgary", "Ottawa", "Montreal"], 5),
    ("MX", "Mexico", "MXN", "LA", ["SA de CV"], ["Monterrey", "Guadalajara", "Puebla"], 3),
    ("BR", "Brazil", "BRL", "LA", ["Ltda", "SA"], ["Sao Paulo", "Curitiba", "Campinas"], 4),
    ("IN", "India", "INR", "AP", ["Pvt Ltd", "Limited"], ["Pune", "Bengaluru", "Chennai", "Hyderabad"], 6),
    ("SG", "Singapore", "SGD", "AP", ["Pte Ltd"], ["Singapore"], 3),
    ("AU", "Australia", "AUD", "AP", ["Pty Ltd"], ["Sydney", "Melbourne", "Brisbane", "Perth"], 4),
    ("JP", "Japan", "JPY", "AP", ["KK"], ["Osaka", "Nagoya", "Yokohama"], 2),
    ("ZA", "South Africa", "ZAR", "MEA", ["Pty Ltd"], ["Johannesburg", "Pretoria", "Cape Town"], 2),
    ("AE", "United Arab Emirates", "AED", "MEA", ["LLC", "FZE"], ["Dubai", "Sharjah", "Abu Dhabi"], 2),
]
COUNTRY = {row[0]: row for row in COUNTRIES}

BRANDS = [
    "Northwind",
    "Bluepeak",
    "Cedarline",
    "Granite",
    "Silverleaf",
    "Brightpath",
    "Ironwood",
    "Redstone",
    "Clearwater",
    "Pinnacle",
    "Evergreen",
    "Keystone",
    "Lakeside",
    "Meridian",
    "Oakridge",
    "Riverbend",
    "Sterling",
    "Quantum",
    "Horizon",
    "Vertex",
    "Aurora",
    "Beacon",
    "Crescent",
    "Falcon",
    "Juniper",
    "Maple",
    "Nimbus",
    "Orchid",
    "Polaris",
    "Sequoia",
    "Tandem",
    "Upland",
    "Willow",
    "Zenith",
    "Atlas",
    "Copperfield",
    "Driftwood",
    "Elmstead",
    "Foxglove",
    "Greystone",
    "Hollis",
    "Ivy",
    "Kingsley",
    "Larkspur",
    "Mosaic",
    "Novella",
    "Pioneer",
    "Rosewood",
    "Solstice",
]
TRADES = [
    ("Office Supplies", "IND"),
    ("Print", "MKT"),
    ("Packaging", "DIR"),
    ("Facility Services", "FAC"),
    ("Cleaning", "FAC"),
    ("Security", "FAC"),
    ("IT Solutions", "IT"),
    ("Software", "IT"),
    ("Data", "IT"),
    ("Consulting", "SVC"),
    ("Staffing", "SVC"),
    ("Engineering", "SVC"),
    ("Electrical", "MRO"),
    ("Tools", "MRO"),
    ("Industrial Supply", "MRO"),
    ("Chemicals", "DIR"),
    ("Plastics", "DIR"),
    ("Metals", "DIR"),
    ("Freight", "LOG"),
    ("Logistics", "LOG"),
    ("Catering", "FAC"),
    ("Furniture", "IND"),
    ("Lab Supplies", "IND"),
    ("Energy", "UTL"),
    ("Media", "MKT"),
    ("Events", "MKT"),
    ("Travel", "IND"),
    ("Medical", "IND"),
]
CATEGORY = {
    "IND": "Indirect Goods",
    "MKT": "Marketing",
    "DIR": "Direct Materials",
    "FAC": "Facilities",
    "IT": "IT & Software",
    "SVC": "Professional Services",
    "MRO": "MRO",
    "LOG": "Logistics",
    "UTL": "Utilities",
}
STREETS = [
    "Main Street",
    "Oak Avenue",
    "Market Street",
    "Station Road",
    "Park Lane",
    "Commerce Drive",
    "Industrial Park",
    "Business Center",
    "River Road",
    "Hill Street",
    "Elm Street",
    "Kingsway",
    "Mill Lane",
    "Innovation Way",
    "Technology Drive",
    "Victoria Road",
    "Church Street",
    "Lakeview Boulevard",
    "Enterprise Avenue",
    "Central Avenue",
]
UNITS = ["Suite 100", "Suite 210", "Unit 4", "Unit 12", "Floor 3", "Building B", "Block C"]
SITES = ["HQ", "DC1", "DC2", "PLT1", "PLT2", "OFF1"]
TERMS = ["NET30", "NET45", "NET60", "NET15", "2/10 NET30"]
ABBREVIATIONS = {"Street": "St", "Avenue": "Ave", "Road": "Rd", "Boulevard": "Blvd", "Suite": "Ste"}
LONG_FORMS = {
    "Ltd": "Limited",
    "Limited": "Ltd",
    "Inc": "Incorporated",
    "Corp": "Corporation",
    "LLC": "L.L.C.",
    "GmbH": "G.m.b.H.",
    "BV": "B.V.",
    "SA": "S.A.",
    "SAS": "S.A.S.",
    "SRL": "S.R.L.",
    "AB": "Aktiebolag",
    "Pty Ltd": "Pty. Limited",
    "Pte Ltd": "Pte. Ltd.",
    "Pvt Ltd": "Private Limited",
    "KK": "K.K.",
}

rng = random.Random(SEED)


def pick_country() -> tuple:
    return rng.choices(COUNTRIES, weights=[row[-1] for row in COUNTRIES])[0]


def _n(count: int) -> str:
    return "".join(rng.choices("0123456789", k=count))


def _tax_candidate(code: str) -> str:
    letters = "ABCDEFGHJKLMNPRSTUVWXYZ"
    return {
        "US": lambda: f"{rng.randint(10, 99)}-{_n(7)}",
        "GB": lambda: f"GB{_n(9)}",
        "DE": lambda: f"DE{_n(9)}",
        "FR": lambda: f"FR00{_n(9)}",
        "NL": lambda: f"NL{_n(9)}B{rng.randint(1, 99):02d}",
        "ES": lambda: f"ES{rng.choice(letters)}{_n(8)}",
        "IT": lambda: f"IT{_n(11)}",
        "PL": lambda: f"PL{_n(10)}",
        "SE": lambda: f"SE{_n(10)}01",
        "IE": lambda: f"IE{_n(7)}{rng.choice('ABCDEFGHJKLMNPRSTVW')}",
        "CA": lambda: f"{_n(9)}RT0001",
        "MX": lambda: f"{''.join(rng.choices(letters, k=3))}{_n(6)}{rng.choice(letters)}{_n(2)}",
        "BR": lambda: _n(14),
        "IN": lambda: (
            f"{rng.randint(10, 37)}{''.join(rng.choices(letters, k=5))}{_n(4)}{rng.choice(letters)}{rng.randint(1, 9)}Z{rng.choice(letters)}"
        ),
        "SG": lambda: f"{_n(9)}{rng.choice(letters)}",
        "AU": lambda: _n(11),
        "JP": lambda: _n(13),
        "ZA": lambda: f"4{_n(9)}",
        "AE": lambda: f"100{_n(12)}",
    }[code]()


def tax_id(code: str) -> str:
    """A random tax ID that passes the country's format and check-digit rules."""
    while True:
        candidate = _tax_candidate(code)
        if code == "FR":  # compute the French key from the SIREN
            siren = candidate[4:]
            candidate = f"FR{(12 + 3 * (int(siren) % 97)) % 97:02d}{siren}"
        if tax_id_problem(code, candidate) is None:
            return candidate


def registration(code: str) -> str:
    return f"{code}-REG-{rng.randint(10000000, 99999999)}"


def bank_account(code: str) -> str:
    if code in IBAN_LENGTHS:
        body_length = IBAN_LENGTHS[code] - 4
        bban = "SYNB" + "".join(rng.choices("0123456789", k=body_length - 4))
        return make_iban(code, bban)
    return "".join(rng.choices("0123456789", k=rng.choice([10, 11, 12])))


def base_record(supplier_id: str, code: str | None = None, brand: str | None = None, trade: tuple | None = None) -> dict:
    country = COUNTRY[code] if code else pick_country()
    code, country_name, currency, region, forms, cities, _ = country
    brand = brand or rng.choice(BRANDS)
    trade_name, group = trade or rng.choice(TRADES)
    form = rng.choice(forms)
    name = f"{brand} {trade_name} {form}"
    created = TODAY - timedelta(days=rng.randint(200, 3600))
    active = rng.random() < 0.86
    po_count = max(0, int(rng.gauss(45, 35))) if active else 0
    spend = round(po_count * rng.uniform(400, 9000), 2) if po_count else 0.0
    last_po = TODAY - timedelta(days=rng.randint(3, 330)) if po_count else created + timedelta(days=rng.randint(10, 150))
    slug = f"{brand}{trade_name.split()[0]}".lower()
    return {
        "SUPPLIER_ID": supplier_id,
        "SUPPLIER_NAME": name,
        "ASSOCIATION_NO": registration(code),
        "TAX_ID": tax_id(code),
        "COMPANY": f"{region}{rng.randint(1, 3):02d}",
        "SITE": rng.choice(SITES),
        "COUNTRY_CODE": code,
        "COUNTRY": country_name,
        "ADDRESS_1": f"{rng.randint(1, 980)} {rng.choice(STREETS)}",
        "ADDRESS_2": rng.choice(UNITS) if rng.random() < 0.35 else "",
        "CITY": rng.choice(cities),
        "POSTAL_CODE": f"{rng.randint(10000, 99999)}",
        "PHONE": f"+{rng.randint(1, 99)}-{rng.randint(100, 999)}-{rng.randint(1000000, 9999999)}",
        "EMAIL": f"ap@{slug}-{code.lower()}.example",
        "CURRENCY": currency,
        "PAYMENT_TERMS": rng.choice(TERMS),
        "SUPPLIER_CATEGORY": CATEGORY[group],
        "PURCHASE_GROUP": group,
        "DEFAULT_BUYER": f"B{rng.randint(1, 12):02d}",
        "ACTIVE_STATUS": "ACTIVE" if active else "INACTIVE",
        "CREATED_DATE": created.isoformat(),
        "LAST_MODIFIED_DATE": (created + timedelta(days=rng.randint(0, 400))).isoformat(),
        "LAST_PO_DATE": last_po.isoformat(),
        "PO_COUNT_12M": po_count,
        "SPEND_12M_USD": spend,
        "BANK_COUNTRY": code,
        "BANK_ACCOUNT": bank_account(code),
        "DATA_SOURCE": "SYNTHETIC_SAMPLE",
    }


def legal_form(name: str, code: str) -> str:
    for form in sorted(COUNTRY[code][4], key=len, reverse=True):
        if name.endswith(" " + form):
            return form
    return ""


def variant(original: dict, supplier_id: str, kind: str) -> dict:
    """A re-entered copy of ``original`` with typical data-entry differences."""
    row = dict(original)
    row["SUPPLIER_ID"] = supplier_id
    created = date.fromisoformat(original["CREATED_DATE"]) + timedelta(days=rng.randint(30, 700))
    row["CREATED_DATE"] = min(created, TODAY - timedelta(days=5)).isoformat()
    row["LAST_MODIFIED_DATE"] = row["CREATED_DATE"]
    row["PO_COUNT_12M"] = rng.randint(0, 12)
    row["SPEND_12M_USD"] = round(row["PO_COUNT_12M"] * rng.uniform(200, 3000), 2)
    if kind == "rekeyed":  # typed again in capitals with abbreviations and formatted identifiers
        row["SUPPLIER_NAME"] = "  ".join(original["SUPPLIER_NAME"].upper().split(" ", 1))
        address = original["ADDRESS_1"]
        for long, short in ABBREVIATIONS.items():
            address = address.replace(long, short)
        row["ADDRESS_1"] = address
        row["TAX_ID"] = original["TAX_ID"][:2] + " " + original["TAX_ID"][2:]
        row["ASSOCIATION_NO"] = original["ASSOCIATION_NO"].replace("-", "")
    elif kind == "legal_form":  # legal form written differently, created by another entity
        form = legal_form(original["SUPPLIER_NAME"], original["COUNTRY_CODE"])
        if form:
            row["SUPPLIER_NAME"] = original["SUPPLIER_NAME"][: -len(form)] + LONG_FORMS.get(form, form)
        row["COMPANY"] = original["COMPANY"][:-2] + f"{(int(original['COMPANY'][-2:]) % 3) + 1:02d}"
        row["SITE"] = rng.choice([site for site in SITES if site != original["SITE"]])
    elif kind == "new_bank":  # supplier changed bank; someone created a new record
        row["BANK_ACCOUNT"] = bank_account(original["COUNTRY_CODE"])
        row["ADDRESS_2"] = original["ADDRESS_2"] or rng.choice(UNITS)
    elif kind == "no_tax_id":  # created in a hurry without the tax ID
        row["TAX_ID"] = ""
    return row


# Variant pairs chosen so every pair inside a cluster shares at least two identifiers.
VARIANT_PAIRS = [
    ("rekeyed", "legal_form"),
    ("rekeyed", "new_bank"),
    ("legal_form", "new_bank"),
    ("rekeyed", "no_tax_id"),
    ("legal_form", "no_tax_id"),
]


def build() -> tuple[pd.DataFrame, pd.DataFrame]:
    originals_needed = TOTAL - 2 * CLUSTERS
    original_ids = [f"S1{number:05d}" for number in range(1, originals_needed + 1)]
    names_seen: set[tuple[str, str]] = set()
    rows: dict[str, dict] = {}
    labels: dict[str, dict] = {}

    def label(supplier_id: str, issue: str, decision: str, cluster: str = "", note: str = "") -> None:
        labels[supplier_id] = {
            "SUPPLIER_ID": supplier_id,
            "ISSUE_TYPE": issue,
            "DUPLICATE_CLUSTER_ID": cluster,
            "EXPECTED_DECISION": decision,
            "NOTES": note,
        }

    for supplier_id in original_ids:
        while True:
            record = base_record(supplier_id)
            key = (record["COUNTRY_CODE"], " ".join(record["SUPPLIER_NAME"].split()[:2]))
            if key not in names_seen:
                names_seen.add(key)
                break
        rows[supplier_id] = record
        label(supplier_id, "CLEAN", "NO_ISSUE", note="Clean fictional supplier")

    # Demo cases referenced in the README and tests.
    rows["S100118"] = base_record("S100118", "GB", "Summit", ("Supply Trading", "IND"))
    rows["S100118"]["SUPPLIER_NAME"] = "Summit Supply Trading Ltd"
    rows["S100118"]["ACTIVE_STATUS"], rows["S100118"]["PO_COUNT_12M"] = "ACTIVE", 128
    rows["S100118"]["SPEND_12M_USD"] = 612450.0

    pool = [supplier_id for supplier_id in original_ids if supplier_id not in {"S100118", "S100790"}]
    rng.shuffle(pool)
    cluster_originals = pool[: CLUSTERS - 2]
    cluster_originals.insert(9, "S100790")
    cluster_originals.insert(19, "S100118")
    for index, original_id in enumerate(cluster_originals, start=1):
        cluster = f"DUP-{index:03d}"
        original = rows[original_id]
        if original["ACTIVE_STATUS"] == "INACTIVE":  # the record people kept using
            original["ACTIVE_STATUS"], original["PO_COUNT_12M"] = "ACTIVE", rng.randint(20, 160)
            original["SPEND_12M_USD"] = round(original["PO_COUNT_12M"] * rng.uniform(800, 6000), 2)
        first, second = VARIANT_PAIRS[index % len(VARIANT_PAIRS)]
        label(original_id, "DUPLICATE_ORIGINAL", "KEEP_CANONICAL", cluster, "Original record of a planted duplicate cluster")
        for offset, kind in ((1, first), (2, second)):
            variant_id = f"S2{2 * index - 2 + offset:05d}"
            rows[variant_id] = variant(original, variant_id, kind)
            label(variant_id, "INTENTIONAL_DUPLICATE", "MERGE_OR_BLOCK", cluster, f"Duplicate variant: {kind.replace('_', ' ')}")

    clean = [supplier_id for supplier_id in pool[CLUSTERS:] if labels[supplier_id]["ISSUE_TYPE"] == "CLEAN"]
    rng.shuffle(clean)
    take = iter(clean)

    def issue(count: int, issue_type: str, decision: str, note: str, change) -> None:
        for _ in range(count):
            supplier_id = next(take)
            change(rows[supplier_id])
            label(supplier_id, issue_type, decision, note=note)

    # Hard negatives: sister companies at the same address (different identifiers).
    for _ in range(8):
        left_id, right_id = next(take), next(take)
        left, right = rows[left_id], rows[right_id]
        right.update(
            {
                key: left[key]
                for key in ("COUNTRY_CODE", "COUNTRY", "ADDRESS_1", "ADDRESS_2", "CITY", "POSTAL_CODE", "BANK_COUNTRY", "CURRENCY")
            }
        )
        right["SUPPLIER_NAME"] = (
            f"{left['SUPPLIER_NAME'].split()[0]} {rng.choice(['Holdings', 'Services', 'International', 'Solutions'])} {legal_form(left['SUPPLIER_NAME'], left['COUNTRY_CODE']) or 'Ltd'}"
        )
        right["BANK_ACCOUNT"] = bank_account(left["COUNTRY_CODE"])
        right["TAX_ID"], right["ASSOCIATION_NO"] = tax_id(left["COUNTRY_CODE"]), registration(left["COUNTRY_CODE"])
        if rng.random() < 0.5:  # shared reception phone in the same building
            right["PHONE"] = left["PHONE"]
        for supplier_id in (left_id, right_id):
            label(
                supplier_id,
                "SISTER_COMPANY",
                "NO_ISSUE",
                note=f"Different legal entity at the same address as {right_id if supplier_id == left_id else left_id}",
            )
    # Hard negatives: unrelated suppliers paid through the same factoring / payment-agent account.
    for _ in range(6):
        left_id, right_id = next(take), next(take)
        left, right = rows[left_id], rows[right_id]
        for key in ("COUNTRY_CODE", "COUNTRY", "CURRENCY", "BANK_COUNTRY"):
            right[key] = left[key]
        right["TAX_ID"], right["ASSOCIATION_NO"] = tax_id(left["COUNTRY_CODE"]), registration(left["COUNTRY_CODE"])
        right["BANK_ACCOUNT"] = left["BANK_ACCOUNT"]
        for supplier_id in (left_id, right_id):
            label(
                supplier_id,
                "SHARED_BANK_ACCOUNT",
                "INVESTIGATE",
                note="Unrelated suppliers sharing a bank account (factoring or payment agent)",
            )
    # Same brand in another country: a subsidiary, never a duplicate across borders.
    for _ in range(5):
        left_id, right_id = next(take), next(take)
        left, right = rows[left_id], rows[right_id]
        if right["COUNTRY_CODE"] == left["COUNTRY_CODE"]:
            right.update(base_record(right_id, "DE" if left["COUNTRY_CODE"] != "DE" else "FR"))
        stem = " ".join(left["SUPPLIER_NAME"].split()[:-1])
        right["SUPPLIER_NAME"] = f"{stem} {rng.choice(COUNTRY[right['COUNTRY_CODE']][4])}"
        for supplier_id in (left_id, right_id):
            label(supplier_id, "FOREIGN_SUBSIDIARY", "NO_ISSUE", note="Same brand registered in another country")

    issue(45, "MISSING_TAX_ID", "REVIEW_DATA_QUALITY", "Tax ID left blank", lambda r: r.update(TAX_ID=""))

    def mistype_tax_id(record: dict) -> None:
        value = record["TAX_ID"]
        record["TAX_ID"] = value[:-2] if len(value) > 6 else value + "9"  # two digits lost while typing

    issue(8, "TAX_ID_FORMAT", "REVIEW_DATA_QUALITY", "Tax ID with missing digits", mistype_tax_id)
    issue(30, "MISSING_REGISTRATION_NO", "REVIEW_DATA_QUALITY", "Registration number left blank", lambda r: r.update(ASSOCIATION_NO=""))
    placeholders = iter(["N/A", "0000", "TBD", "000000000", "NA", "N/A", "9999", "UNKNOWN", "n/a", "00000"])
    issue(
        10,
        "PLACEHOLDER_IDENTIFIER",
        "REVIEW_DATA_QUALITY",
        "Filler value instead of a tax ID",
        lambda r: r.update(TAX_ID=next(placeholders)),
    )

    def break_iban(record: dict) -> None:
        account = record["BANK_ACCOUNT"]
        if not account[:2].isalpha():  # move the supplier to an IBAN country first
            record.update(
                COUNTRY_CODE="NL",
                COUNTRY="Netherlands",
                BANK_COUNTRY="NL",
                CURRENCY="EUR",
                TAX_ID=tax_id("NL"),
                ASSOCIATION_NO=registration("NL"),
            )
            account = bank_account("NL")
        # Changing one digit always breaks the mod-97 check.
        record["BANK_ACCOUNT"] = account[:-1] + str((int(account[-1]) + 3) % 10)

    issue(8, "INVALID_IBAN", "REVIEW_DATA_QUALITY", "IBAN check digits do not match (typo)", break_iban)
    currencies = iter(["EURO", "US$", "EU", "POUND", "$", "Dollar"])
    issue(6, "CURRENCY_ANOMALY", "REVIEW_DATA_QUALITY", "Currency is not an ISO code", lambda r: r.update(CURRENCY=next(currencies)))
    long_names = {"US": "USA", "GB": "U.K.", "DE": "Deutschland", "FR": "FRA"}
    for wanted in long_names:  # written-out country names instead of ISO codes
        supplier_id = next(sid for sid in take if rows[sid]["COUNTRY_CODE"] == wanted)
        rows[supplier_id]["COUNTRY_CODE"] = long_names[wanted]
        label(supplier_id, "COUNTRY_FORMAT", "REVIEW_DATA_QUALITY", note="Country is not a two-letter code")
    issue(5, "BANK_SCOPE_MISSING", "REVIEW_DATA_QUALITY", "Bank account without a bank country", lambda r: r.update(BANK_COUNTRY=""))
    issue(6, "MISSING_CITY", "REVIEW_DATA_QUALITY", "City left blank", lambda r: r.update(CITY=""))
    issue(3, "ACTIVITY_VALUE", "REVIEW_DATA_QUALITY", "Negative spend", lambda r: r.update(SPEND_12M_USD=-round(rng.uniform(50, 900), 2)))

    def inactive_with_activity(record: dict) -> None:
        record["ACTIVE_STATUS"] = "INACTIVE"
        record["PO_COUNT_12M"] = record["PO_COUNT_12M"] or rng.randint(1, 15)
        record["SPEND_12M_USD"] = record["SPEND_12M_USD"] or round(rng.uniform(500, 40000), 2)

    issue(50, "INACTIVE_WITH_RECENT_ACTIVITY", "REVIEW_STATUS", "Inactive status but orders in the last 12 months", inactive_with_activity)

    # A few remaining inactive records legitimately have no activity.
    order = list(rows)
    rng.shuffle(order)
    master = pd.DataFrame([rows[supplier_id] for supplier_id in order])
    truth = pd.DataFrame([labels[supplier_id] for supplier_id in order])
    return master, truth


def previous_version(master: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """The same supplier master three months earlier, for the "What's new" comparison.

    Since then: 10 duplicate variants and 15 suppliers were added, 4 suppliers
    changed bank details or e-mail, and 6 placeholder tax IDs were fixed... in
    the earlier file they still held fillers, so the current scan shows them as
    resolved.
    """
    local = random.Random(SEED + 1)
    earlier = master.copy()
    variants = truth[truth["ISSUE_TYPE"].eq("INTENTIONAL_DUPLICATE")]["SUPPLIER_ID"].tolist()
    clean = truth[truth["ISSUE_TYPE"].eq("CLEAN")]["SUPPLIER_ID"].tolist()
    added = set(local.sample(variants, 10)) | set(local.sample(clean, 15))
    earlier = earlier[~earlier["SUPPLIER_ID"].isin(added)].copy()
    remaining = [sid for sid in clean if sid not in added]
    for supplier_id in local.sample(remaining, 4):  # bank or e-mail changed since then
        index = earlier.index[earlier["SUPPLIER_ID"].eq(supplier_id)][0]
        code = earlier.at[index, "BANK_COUNTRY"] or earlier.at[index, "COUNTRY_CODE"]
        earlier.at[index, "BANK_ACCOUNT"] = bank_account(code) if code in COUNTRY else earlier.at[index, "BANK_ACCOUNT"]
    for supplier_id in local.sample(remaining, 6):  # fillers that have been corrected since
        index = earlier.index[earlier["SUPPLIER_ID"].eq(supplier_id)][0]
        earlier.at[index, "TAX_ID"] = "N/A"
    gone = pd.DataFrame([base_record(f"S19{number:04d}") for number in range(1, 6)])  # suppliers deleted since
    return pd.concat([earlier, gone], ignore_index=True)


def readme() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("Purpose", "Fictional supplier master for trying Supplier Integrity Desk."),
            ("Important", "100% synthetic. Names, identifiers, addresses and bank accounts are invented."),
            ("Records", TOTAL),
            ("Main sheet", "Supplier_Master"),
            ("Labels", "Ground_Truth — planted issues; read only by `supplier-desk evaluate`."),
            ("Duplicate clusters", f"{CLUSTERS} (an original plus two variants each)"),
            ("Hard negatives", "Sister companies at one address, shared factoring accounts, foreign subsidiaries"),
            ("Regenerate", "python scripts/generate_sample_data.py"),
        ],
        columns=["Item", "Value"],
    )


def dictionary() -> pd.DataFrame:
    from supplier_agent.columns import FIELD_BY_NAME

    extra = {
        "COUNTRY": "Country name",
        "PAYMENT_TERMS": "Payment terms",
        "DEFAULT_BUYER": "Buyer code",
        "LAST_MODIFIED_DATE": "Last change to the record",
        "DATA_SOURCE": "Marks synthetic records",
    }
    rows = []
    for column in base_record("S000000").keys():
        spec = FIELD_BY_NAME.get(column)
        rows.append(
            {
                "FIELD": column,
                "DESCRIPTION": spec.description if spec else extra[column],
                "USED_FOR_MATCHING": "yes" if spec and spec.used_for_matching else "",
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    master, truth = build()
    WORKBOOK.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(WORKBOOK, engine="openpyxl") as writer:
        readme().to_excel(writer, sheet_name="README", index=False)
        master.to_excel(writer, sheet_name="Supplier_Master", index=False)
        truth.to_excel(writer, sheet_name="Ground_Truth", index=False)
        dictionary().to_excel(writer, sheet_name="Data_Dictionary", index=False)
        for sheet in writer.sheets.values():
            for column in sheet.columns:
                sheet.column_dimensions[column[0].column_letter].width = min(max(len(str(c.value or "")) for c in column) + 2, 48)

    with pd.ExcelWriter(PREVIOUS_WORKBOOK, engine="openpyxl") as writer:
        previous_version(master, truth).to_excel(writer, sheet_name="Supplier_Master", index=False)

    # ERP-style export: a subset with different headers and a semicolon delimiter.
    subset = master[master["COUNTRY_CODE"].isin(["GB", "DE", "FR", "US"])].rename(
        columns={
            "SUPPLIER_ID": "Vendor No",
            "SUPPLIER_NAME": "Vendor Name",
            "TAX_ID": "VAT Number",
            "ASSOCIATION_NO": "Company Registration",
            "ADDRESS_1": "Street",
            "ADDRESS_2": "Address Line 2",
            "CITY": "City",
            "POSTAL_CODE": "Zip",
            "COUNTRY_CODE": "Country",
            "BANK_ACCOUNT": "IBAN",
            "BANK_COUNTRY": "Bank Country",
            "EMAIL": "Email",
            "CURRENCY": "Currency",
            "ACTIVE_STATUS": "Status",
            "PO_COUNT_12M": "PO Count 12M",
            "SPEND_12M_USD": "Spend 12M",
        }
    )
    columns = [
        "Vendor No",
        "Vendor Name",
        "VAT Number",
        "Company Registration",
        "Street",
        "Address Line 2",
        "City",
        "Zip",
        "Country",
        "IBAN",
        "Bank Country",
        "Email",
        "Currency",
        "Status",
        "PO Count 12M",
        "Spend 12M",
    ]
    EXAMPLE_CSV.parent.mkdir(parents=True, exist_ok=True)
    subset[columns].to_csv(EXAMPLE_CSV, index=False, sep=";")
    # SQLite database with snake_case vendor columns, for the database input.
    import sqlite3

    EXAMPLE_DB.unlink(missing_ok=True)
    database = master.rename(
        columns={
            "SUPPLIER_ID": "vendor_id",
            "SUPPLIER_NAME": "vendor_name",
            "TAX_ID": "vat_number",
            "ASSOCIATION_NO": "registration_number",
            "COUNTRY_CODE": "country",
            "ADDRESS_1": "street",
            "ADDRESS_2": "address_line_2",
            "CITY": "city",
            "POSTAL_CODE": "zip",
            "BANK_COUNTRY": "bank_country",
            "BANK_ACCOUNT": "iban",
            "EMAIL": "email",
            "PHONE": "phone",
            "ACTIVE_STATUS": "status",
            "CURRENCY": "currency",
            "PO_COUNT_12M": "po_count_12m",
            "SPEND_12M_USD": "spend_12m",
            "CREATED_DATE": "created_date",
        }
    )
    with sqlite3.connect(EXAMPLE_DB) as connection:
        database[[column for column in database.columns if column.islower()]].to_sql("vendors", connection, index=False)
    connection.close()
    print(f"Wrote {WORKBOOK.relative_to(ROOT)} ({len(master)} suppliers) and {EXAMPLE_CSV.relative_to(ROOT)} ({len(subset)} rows)")
    print(truth["ISSUE_TYPE"].value_counts().to_string())


if __name__ == "__main__":
    main()
