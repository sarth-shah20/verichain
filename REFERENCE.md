# VeriChain — Technical Reference

A complete, factual picture of the system. Everything here reflects the actual code.

---

## 1. What it is

Document fraud/tampering detection for bank loan underwriting. Submit an applicant's
documents (ITR, salary slip, land record); get a **trust score (0–100)**, a **decision**
(`auto_approve` / `human_review` / `auto_reject`), and **evidence** for each. Decision
*support* — a human makes the final call.

Core design: **two independent pipelines answer two different questions, then a fusion
step combines them.**
- Pipeline 1 (`ai/`): *is the file tampered/forged?*
- Pipeline 2 (`pipeline2/`): *does the data match reality?*

Scope built: Maharashtra 7/12 land records + Indian ITR/salary slip, running live on
**Google Gemini 3.1 Pro (Vertex AI)**. No offline/mock mode — a real LLM is required.

---

## 2. Request flow

```
Frontend                     Backend (FastAPI)
POST /verify/batch  ───►  create in-memory job (jobs.py) → {job_id}, process in bg thread:
                            per doc (concurrent): process_document()
                              1. Pipeline 1 forensics
                              2. Pipeline 2: extract → DB fetch → verify
                              3. fusion.fuse_reports() → per-doc verdict
                              4. log to blockchain_log
                            if ≥2 docs verified → cross-document check
                            _overall_from_documents() → application verdict
poll GET /verify/batch/{id} ◄─ {status, progress, overall, documents[], cross_document[]}
adapter maps response → UI
```

Async job model + polling because each real LLM call is ~30–60s/doc. Per-document
pipelines run concurrently. Cross-document runs only with 2+ verified docs.

---

## 3. Pipeline 1 — Forensics (`ai/pipeline1/`)

Classifies the file (`signed_pdf` / `born_digital_pdf` / `scanned_image`), then runs:
- **Tier 0 – Provenance** (`provenance/tier0.py`): digital-signature check, QR payloads.
- **Tier 1 – Structure** (`structure/tier1.py`): PDF metadata (Producer, Create vs Mod
  date, incremental-update flags), font-family/style mismatches, and — for scans —
  typography-outlier / baseline-misalignment checks. Includes **revision recovery**.
- **Tier 2 – Pixel forensics** (`pixel_forensics/tier2.py`, scans only): copy-move, DCT,
  ELA, noise → localizes edited regions.

**Revision recovery (`structure/revision_recovery.py`)** — the standout check. An edited
PDF saved as an incremental update keeps the original bytes; we reconstruct the prior
revision (slice at the earlier `%%EOF`), diff it, and recover the original value of the
edited field ("Gross Earnings: 80,000 → 2,00,000"). Field-weighted; a benign re-save
scores nothing.

The backend calls `classify`, `run_tier0`, `run_tier1`, and `run_tier2` (tier 2 only for
scanned images).

---

## 4. Pipeline 2 — Content & Verification (`pipeline2/`)

`pipeline.py` orchestrates: extract → DB fetch → verify.

- **Extract (`extract.py`)** — two passes: (1) Gemini OCRs the whole document (regional
  scripts translated) into `full_text` + doc type; (2) a text call derives the schema's
  fields from that text. Full text preserves context (co-owners, whole tables) so
  verification isn't fooled by benign variance.
- **DB fetch (`db.py`)** — looks up the authoritative record by the schema's `key_fields`
  (land: `state|district|taluka|village|survey_number`; ITR: `pan|assessment_year`).
- **Verify (`verify.py`)** — a separate LLM session compares extracted fields vs the DB
  record → `match_status` (match / partial_match / mismatch / unverified) + per-field
  results + discrepancies. Semantic (handles transliteration, name order, ₹ formats,
  co-owners). Also folds in deterministic validators (§5). No DB record (e.g. payslip) →
  "unverified" (not fraud), but validators still run.

---

## 5. Deterministic validators (`pipeline2/validators.py`)

Pure Python, no LLM, unit-tested. Certain and cheap; run on every doc, even with no DB
record. A failed *definitive* check forces `match_status = mismatch`.

| Check | Validates |
|---|---|
| PAN | format + holder-type char + 5th char = surname initial (vs extracted name) |
| Aadhaar | Verhoeff checksum over 12 digits |
| GSTIN | structure + state code + mod-36 checksum + embedded PAN |
| Payslip arithmetic | gross − deductions must equal net pay |

**Cross-document (`discrepancy.py`)** adds, over 2+ docs: PAN must match across documents;
a GSTIN's embedded PAN must equal the applicant's PAN. Plus an LLM consistency pass
(name / income / employer across docs) — this is what catches income understatement
(salary slip vs ITR).

---

## 6. Fusion, score & decision

**Fusion (`fusion.py`)** — an LLM merges verification + forensics (+ cross-doc) into one
verdict. Prompted to: treat deterministic checks as hard evidence; field-weight
(identity/money > structural > cosmetic); down-weight lone scan pixel-anomalies when
content verifies (false-positive control); corroborate signals flagged by both pipelines.

Score is inverted twice:
1. Fusion LLM emits **risk**: 0 = clean, 100 = fraud.
2. Backend → **authenticity** `risk_score = 100 − fusion_risk`, then decides:

   | risk_score | decision | route |
   |---|---|---|
   | ≥ 80 | auto_approve | route_1 |
   | 60–79 | human_review | route_2 |
   | < 60 | auto_reject | route_3 |

3. Frontend shows it as a **trust score** (same direction), banded to match the decision
   and **clamped to [15, 95]** so the UI never shows absolute certainty. Gauge colours:
   genuine ≥ 70, review ≥ 40, else high-risk.

---

## 7. API

**Frozen single-doc** (don't change its schema/enums):
- `POST /verify` → `{risk_score, route_taken, decision, reasons[], blockchain_tx,
  heatmap_url, field_verification{status, issuer, matched_fields}}`
- `GET /verify/{applicant_id}/history`

**Additive async batch** (what the frontend uses):
- `POST /verify/batch {applicant_id?, documents[]}` → `{job_id}`
- `GET /verify/batch/{job_id}` → `{status, progress, overall, documents[], cross_document[], error}`;
  each `documents[]` entry = single-doc fields + `filename`, `document_type`,
  `extracted_fields`, and `revision_evidence` (edited PDFs).

---

## 8. Real vs mocked

- **Real:** all AI extraction, forensics, verification, cross-doc, fusion — live on Gemini.
- **Mocked — the government DB.** Real land records are public but access is API/consent-
  gated (DigiLocker / CERSAI); we mock that source with realistic records in SQLite.
  Production swaps in the DigiLocker Requester API. We never scrape real portals.
- **Not a real blockchain.** `_log_blockchain()` inserts a row into a SQLite
  `blockchain_log` table with a mock `0x…` (sha256) hash. It's an append-only **audit log
  of verdicts**, not a chain — intentional, since there's no authoritative document hash
  to anchor.

---

## 9. Key decisions (the why)

- **Two pipelines, not one model** — "file edited?" and "data correct?" need different
  techniques; keeping them separate lets them corroborate.
- **Deterministic checks alongside the AI** — math (checksums, arithmetic) is certain,
  can't hallucinate, and works with no DB record.
- **Payslips have no DB** — no authoritative source exists for a private payslip, so they're
  verified by arithmetic + cross-check against the ITR (by design).
- **False-positive control** — legit docs are constantly re-scanned/re-saved; fusion
  down-weights lone scan artifacts so the product is usable in reality.
- **Trust score + evidence, human-in-the-loop** — banks must justify decisions; the system
  recommends, the human decides.
- **Score clamped 15–95** — no automated system should project absolute certainty.
- **Provider-agnostic (litellm)** — model set by one env var; swappable.

---

## 10. Data (`verichain.db`, SQLite; built by `init_db.py` from `extracted/*.json`)

- **land_records** (15 rows: 5 MH, 5 KA, 5 TN) — `record_key, state_form, parcel_id, state,
  district, taluka, village, survey_number, owner_name, area_hectare (owner's HOLDING, not
  total parcel), encumbrance, encumbrance_present, digitally_signed, source_file`.
- **itr_records** (1 row, PAN ABKPG7842M) — `record_key, pan, name, assessment_year,
  gross_total_income, total_tax_paid, employer_name, acknowledgement_number`. Columns match
  `schemas.py` so verification compares like-for-like.
- **blockchain_log** — `id, applicant_id, doc_hash, risk_score, decision, timestamp,
  tx_hash`. Append-only audit log; read by the history endpoint.

Salary slips / sale deeds are intentionally NOT in the DB. `schemas.py` defines per doc
type: `label`, `db_collection`, `key_fields`, `fields`, `forgery_hints`.

---

## 11. Frontend (`frontend/`, React + Vite + TS + Tailwind)

Layered so the UI never depends on the wire shape:
- **`api/types.ts`** — UI data model (richer than the wire: multi-doc, `trust_score`,
  signals, `revision_evidence`).
- **`api/adapter.ts`** — backend wire types + mapping: decision→verdict,
  authenticity→trust (banded + clamped), reasons→signals, field_verification→fields table,
  revision_evidence→before/after panel, batch job→result.
- **`api/realClient.ts`** — drives the batch contract (base64, submit, poll, build).
- **`lib/risk.ts`** — trust thresholds + verdict colours.

Pages: NewVerification, Processing (polling + progress creep), Results (trust gauge,
verdict, recommended-action buttons, cross-doc findings, doc cards), DocumentDetail
(viewer, evidence cards, BeforeAfterPanel, fields), History, Settings.

---

## 12. Tech stack

Frontend: React 18, Vite, TypeScript, Tailwind, react-router. Backend: Python 3.12,
FastAPI, uvicorn, pydantic v2. LLM: litellm → Vertex AI `gemini-3.1-pro-preview`.
Forensics: PyMuPDF, OpenCV, NumPy, SciPy, pikepdf, Pillow. Data: SQLite.

---

## 13. Config & run

`backend/.env` (gitignored): `LLM_MODEL=vertex_ai/gemini-3.1-pro-preview`,
`VERTEXAI_PROJECT`, `VERTEXAI_LOCATION=global`, `VERICHAIN_DB=../verichain.db`; auth via
gcloud ADC. Run: `cd backend && uvicorn main:app --reload` (:8000);
`cd frontend && npm run dev` (:5173, `.env.local` → `VITE_API_BASE_URL`).

---

## 14. Repo layout

```
backend/       main.py, jobs.py, routes/verify.py (frozen + process_document), routes/batch.py
pipeline2/     pipeline, extract, db, verify, validators, discrepancy, fusion, schemas, llm_client, config
ai/pipeline1/  classifier; provenance/tier0; structure/tier1 + revision_recovery; pixel_forensics/tier2
frontend/src/  api/, pages/, components/, lib/
init_db.py     builds verichain.db from extracted/*.json
mock_data/     5 demo docs (committed) · verichain.db (committed) · extracted/, raw_docs/ (gitignored)
```

---

## 15. Demo scenarios

| App | Document(s) | Result | Signal |
|---|---|---|---|
| APP001 | Genuine ITR | auto_approve | fields match tax record |
| APP002 | Tampered ITR | auto_reject | income/tax/ack mismatch |
| APP003 | Genuine Marathi 7/12 | auto_approve | verifies; scan artifacts treated as benign |
| APP004 | Tampered salary slip | auto_reject | recovered PDF edit (80,000→2,00,000) + arithmetic fails |
| APP005 | Fraud ITR + genuine salary (**together**) | auto_reject | cross-doc income mismatch |

APP005 needs both files in one submission (triggers the cross-doc check). ~30–60s per doc.

---

## 16. Known limitations

- Batch job state is in-memory — lost on server restart (being addressed by persistent
  history).
- Pixel forensics over-fire on scans; fusion reasons past them but the detector is
  uncalibrated.
- DB matching is exact-string on the composite key (brittle to spelling/script variants).
- ~30–60s per doc; no offline mode.
