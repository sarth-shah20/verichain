# Pipeline 2 — Content Extraction & Verification

The right-hand branch of the document-fraud detection architecture. Given a
customer-submitted document (image or PDF), it reads the content, normalizes it,
checks it against the bank's database-of-record, and emits a verification
report. Separate utilities then cross-check multiple documents and fuse this
pipeline's output with Pipeline 1 (forensics) into a single risk score.

## Flow

```
Input doc ─▶ extract (VLM/OCR + normalize) ─▶ DB fetch ─▶ verify (separate session) ─▶ verification report
                                                                                              │
                          multiple verification reports ─▶ cross-document discrepancy report  │
                                                                                              ▼
                       verification report + forensics report (+ cross-doc + flag history) ─▶ fusion ─▶ holistic risk score
```

## Files

| File | Role |
|------|------|
| `config.py` | Model id (from env), Vertex routing, mock toggle. **Model name is never hard-coded.** |
| `llm_client.py` | litellm wrapper (text + vision), JSON parsing, deterministic mock backend. |
| `schemas.py` | Per-document-type extraction + validation schemas. Add a doc type here only. |
| `db.py` | **Integration point for the DB teammate.** Pipeline only calls `fetch_record(...)`. |
| `extract.py` | Step 1 — OCR + normalization in one LLM session → structured fields. |
| `verify.py` | Step 2 — fresh LLM session comparing extracted fields vs DB record. |
| `pipeline.py` | Orchestrates extract → DB → verify → verification report. |
| `discrepancy.py` | Cross-checks several documents from one applicant. |
| `fusion.py` | Merges verification + forensics (+ cross-doc + flag history) → risk score. |
| `demo.py` | Full offline run with the mock LLM. |

## Setup

```bash
pip install -r requirements.txt
```

Environment (Vertex AI):

```bash
export LLM_MODEL="vertex_ai/<model-id>"     # kept out of source
export VERTEXAI_PROJECT="your-gcp-project"
export VERTEXAI_LOCATION="us-central1"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
```

## Run

Offline demo (no credentials needed):

```bash
LLM_MOCK=1 python demo.py
```

Verify one document:

```bash
python pipeline.py path/to/itr.pdf salaried_itr reports
# omit the doc_type to let the model auto-classify:
python pipeline.py path/to/document.png
```

Cross-document check:

```bash
python discrepancy.py reports/itr.verification.json reports/payslip.verification.json
```

Fuse with the forensics report:

```bash
python fusion.py reports/itr.verification.json forensics.json
```

## DB integration contract (for the DB teammate)

Implement `_backend_fetch(collection, key, values)` in `db.py` (or replace
`SAMPLE_DB`). It must return the authoritative record dict, or `None`.
`fetch_record` wraps it into:

```json
{ "found": true, "source": "itr", "record": { ... }, "as_of": "2026-06-01" }
```

Keep `record` keys aligned with the field names in `schemas.py` so verification
compares like-for-like. The composite lookup key is the schema's `key_fields`
joined by `|`.

## Supported document types

ITR, Form 16, payslip, NRI salary certificate, CA/net-worth certificate, bank
statement, cheque, demand draft, plan approval, occupancy certificate, sale
agreement, title chain, property tax/khata, vehicle RC, generic/rent/lease
agreement, address proof, PoA, AOD, death/legal-heir certificate, compliance
(freeze) letter, GST return, Udyam/MSME, DSC e-stamp, employer ID, PAN, Aadhaar.
Unknown types fall back to a generic schema. Add new types in `schemas.py`.

## Notes

- Extraction and verification run as **separate LLM sessions** by design — the
  verifier judges the A-vs-B comparison on data alone, with no extraction context.
- `LLM_MOCK=1` returns canned, schema-shaped JSON so the full flow is testable
  offline / in CI without Vertex.
- Aadhaar handling stores only the last 4 digits.
```
