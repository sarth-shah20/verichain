"""
Initialize verichain.db — the single authoritative store for VeriChain.

Replaces both seed.py (fake fixture data) and load_authoritative.py (land only).
Run once from the project root:
    python init_db.py

Tables created:
    land_records   — authoritative parcel data  (from extracted/*.json, doc_type=land_record)
    itr_records    — authoritative ITR data      (from extracted/*.json, doc_type=itr, genuine only)
    blockchain_log — verdict audit trail          (appended by the backend at verify-time)
"""

import glob
import json
import os
import sqlite3

DB_PATH = os.environ.get("VERICHAIN_DB", "verichain.db")
EXTRACT_DIR = "extracted"


def setup(cur: sqlite3.Cursor) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS land_records (
            record_key          TEXT PRIMARY KEY,
            state_form          TEXT,
            parcel_id           TEXT,
            state               TEXT,
            district            TEXT,
            taluka              TEXT,
            village             TEXT,
            survey_number       TEXT,
            owner_name          TEXT,
            area_hectare        REAL,
            encumbrance         TEXT,
            encumbrance_present INTEGER,
            digitally_signed    INTEGER,
            source_file         TEXT
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_land_locality ON land_records
        (state, district, taluka, village, survey_number)
    """)

    # Column names match pipeline2/schemas.py salaried_itr field definitions exactly
    # so pipeline2/verify.py compares extracted vs DB values like-for-like.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS itr_records (
            record_key             TEXT PRIMARY KEY,
            pan                    TEXT,
            name                   TEXT,
            assessment_year        TEXT,
            gross_total_income     INTEGER,
            total_tax_paid         INTEGER,
            employer_name          TEXT,
            acknowledgement_number TEXT
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_itr_pan ON itr_records (pan, assessment_year)
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS blockchain_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            applicant_id TEXT,
            doc_hash     TEXT,
            risk_score   INTEGER,
            decision     TEXT,
            timestamp    TEXT,
            tx_hash      TEXT,
            event_type   TEXT DEFAULT 'system_verdict'
        )
    """)

    # Persistent history of completed verifications (survives restart). The full
    # report lives in result_json so a report can be reopened by job_id; delete
    # is soft (deleted=1) so the append-only audit log above is never rewritten.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS verifications (
            job_id               TEXT PRIMARY KEY,
            applicant_id         TEXT,
            submitted_at         TEXT,
            doc_names            TEXT,
            document_count       INTEGER,
            decision             TEXT,
            risk_score           INTEGER,
            underwriter_decision TEXT,
            result_json          TEXT,
            deleted              INTEGER DEFAULT 0
        )
    """)


def _land_key(d: dict) -> str:
    if d.get("parcel_id"):
        return d["parcel_id"]
    return "|".join(
        str(d.get(k, ""))
        for k in ("state", "district", "taluka", "village", "survey_number")
    )


def _load_land(cur: sqlite3.Cursor, d: dict) -> str:
    h = d.get("applicant_holding", {})
    cur.execute(
        "INSERT OR REPLACE INTO land_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            _land_key(d), d.get("state_form"), d.get("parcel_id"),
            d.get("state"), d.get("district"), d.get("taluka"), d.get("village"),
            d.get("survey_number"), h.get("owner_name"),
            h.get("area_hectare"), d.get("encumbrance"),
            1 if d.get("encumbrance_present") else 0,
            1 if d.get("digitally_signed") else 0,
            d.get("source_file"),
        ),
    )
    return f"land : {h.get('owner_name')} / survey {d.get('survey_number')} ({d.get('state')})"


def _load_itr(cur: sqlite3.Cursor, d: dict) -> str | None:
    if d.get("_load_as_authoritative") is False:
        return None
    key = f"{d.get('pan', '')}|{d.get('assessment_year', '')}"
    cur.execute(
        "INSERT OR REPLACE INTO itr_records VALUES (?,?,?,?,?,?,?,?)",
        (
            key,
            d.get("pan"),
            d.get("name"),
            d.get("assessment_year"),
            d.get("gross_income"),        # our JSON field → gross_total_income column
            d.get("tax_paid_total"),      # our JSON field → total_tax_paid column
            None,                          # employer_name not in our ITR JSONs
            d.get("acknowledgement_number"),
        ),
    )
    return f"itr  : {d.get('pan')} / AY {d.get('assessment_year')}"


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    setup(cur)

    files = sorted(glob.glob(os.path.join(EXTRACT_DIR, "*.json")))
    if not files:
        print(f"No JSONs found in ./{EXTRACT_DIR}/  — run extraction first.")
        conn.close()
        return

    loaded = skipped = 0
    for f in files:
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        dt = d.get("doc_type")
        fname = os.path.basename(f)

        if dt == "land_record":
            print(f"  + {_load_land(cur, d)}")
            loaded += 1
        elif dt == "itr":
            msg = _load_itr(cur, d)
            if msg:
                print(f"  + {msg}")
                loaded += 1
            else:
                print(f"  - skip  {fname}  (_load_as_authoritative=false — fraud test doc)")
                skipped += 1
        elif dt in ("salary_slip", "sale_deed"):
            print(f"  - skip  {fname}  ({dt} → cross-validation, not DB lookup)")
            skipped += 1
        else:
            print(f"  ? skip  {fname}  (unknown doc_type '{dt}')")
            skipped += 1

    conn.commit()
    conn.close()
    print(f"\nDone — {loaded} records loaded into {DB_PATH}, {skipped} skipped.")
    print(f"Next: cd backend && uvicorn main:app --reload")


if __name__ == "__main__":
    main()
