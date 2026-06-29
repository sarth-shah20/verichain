# VeriChain — Handoff Notes

> Read this first. It is the single source of truth for the current state of the
> project, the API contract, what changed recently, and where to pick up.
> Written for a teammate (and their Claude) joining mid-build.

**Last updated:** 2026-06-30
**Branch this work lives on:** `feature/frontend`
**What this branch contains:** the React frontend **plus** the backend `/verify`
+ async `/verify/batch` endpoints, pipeline-2 DB wiring, and the demo data setup.

---

## 0. TL;DR — what state are we in?

The end-to-end seam is wired and runs:

```
Frontend (React)  ──►  Backend FastAPI  ──►  Pipeline 1 (forensics)
  upload / dashboard      /verify            + Pipeline 2 (extract + DB verify)
                          /verify/batch       + Fusion  ──►  risk score + evidence
                                              + cross-document check (batch only)
```

- **Backend** serves the frozen single-doc `POST /verify` **and** a new async,
  multi-document `POST /verify/batch` (+ `GET /verify/batch/{job_id}` polling).
- **Frontend** talks to the real backend via an adapter layer; also runs fully
  on built-in mock data with a one-line env toggle.
- Everything **builds and typechecks**; single-doc and batch flows were tested
  live against the backend in mock-LLM mode.
- It has **only been exercised with `LLM_MOCK=1`** (deterministic fake LLM). The
  real per-document fraud verdicts need a real LLM configured — see §6.

---

## 1. Critical constraints (do not violate)

These are the project "golden rules". The full versions live in `CLAUDE.md`
(gitignored — get it from the repo owner; see §8).

1. **Decision support, not auto-decisioning.** Output is a risk score + evidence
   for a human underwriter.
2. **The single-doc `/verify` request/response schema is FROZEN.** Do not change
   field names or the `route_1|route_2|route_3` / `auto_approve|human_review|auto_reject`
   enums without telling the team. The new `/verify/batch` was added *alongside*
   it (additive) — the frozen schema was not touched.
3. **Government DB is mocked.** Never scrape MahaBhulekh or hit a real govt portal.
4. **No naive hash-comparison** for the govt-DB check or "blockchain integrity".
   The blockchain layer is an audit log of verdicts, not a tamper oracle.
5. **False-positive control is make-or-break.** Don't flag benign re-saves/scans.
6. **Git:** never push to `main` or `dev` (both protected). Branch off `dev`,
   PR back to `dev`. Commit format `feat:|fix:|chore:|docs:`.

---

## 2. ⚠️ Score direction — the #1 thing to understand

The API field is called `risk_score`, but it is an **AUTHENTICITY / confidence
score: higher = MORE genuine.**

| Backend `risk_score` | `decision`     | `route_taken` |
|----------------------|----------------|---------------|
| `>= 80`              | `auto_approve` | `route_1`     |
| `60 – 79`            | `human_review` | `route_2`     |
| `< 60`               | `auto_reject`  | `route_3`     |

Internally the fusion LLM emits the *opposite* convention (0 = clean, 100 =
fraud); the backend inverts it (`risk_score = 100 - fusion_risk`) before
returning. The frontend gauge expects "higher = riskier", so the frontend
adapter inverts **again** and clamps into the band matching `decision` so the
gauge colour can never disagree with the verdict pill. If you touch scoring,
keep these two inversions consistent.

---

## 3. Repo layout & where things are

```
backend/
  main.py            FastAPI app; registers routers; sys.path shim for `routes`
  jobs.py            in-memory async job store (batch verification)   [NEW]
  routes/
    verify.py        POST /verify (frozen) + shared process_document() [MODIFIED]
    batch.py         POST /verify/batch, GET /verify/batch/{id}        [NEW]
pipeline2/           content extraction + DB verify + fusion + cross-doc
  pipeline.py        verify_document_file() — extract → DB fetch → verify
  extract.py         VLM/OCR extraction (mock or real LLM)
  verify.py          field-by-field comparison vs authoritative record
  discrepancy.py     cross-document consistency (used by batch)
  fusion.py          merges verification + forensics → holistic risk
  db.py              authoritative-DB adapter (reads verichain.db)     [MODIFIED]
  llm_client.py      litellm wrapper + deterministic MOCK responses    [MODIFIED]
  config.py          LLM env config; is_mock()
ai/                  Pipeline 1 forensics (classify → tier0/1/2)
frontend/            React + Vite + TS + Tailwind                      [NEW]
  src/api/
    types.ts         UI data model (internal contract)
    adapter.ts       backend wire types + backend→UI mapping           [NEW]
    realClient.ts    drives /verify/batch (async job + poll)           [NEW]
    mock/            built-in offline mock data + client
    index.ts         mock/real switch (VITE_USE_MOCK)
init_db.py           builds verichain.db from extracted/*.json         [NEW]
mock_data/           the 5 demo applicant documents (committed)
verichain.db         the authoritative mock DB (gitignored — see §8)
extracted/           per-doc JSON used to build the DB (gitignored)
raw_docs/            source scans (gitignored)
```

---

## 4. API contract

### 4.1 `POST /verify` — single document (FROZEN, unchanged)

Request:
```json
{
  "applicant_id": "string",
  "document_type": "itr | salary_slip | land_record | legal_doc | bank_statement",
  "file_base64": "string",
  "digilocker_uri": "string | null",
  "ulpin": "string | null",
  "has_qr": true
}
```
Response:
```json
{
  "risk_score": 95,
  "route_taken": "route_1 | route_2 | route_3",
  "decision": "auto_approve | human_review | auto_reject",
  "reasons": ["All fields match DB-of-record"],
  "blockchain_tx": "0x...",
  "heatmap_url": "string | null",
  "field_verification": {
    "status": "verified | mismatch | unverifiable",
    "issuer": "CBDT | CERSAI | mock_registry",
    "matched_fields": ["pan", "gross_total_income"]
  }
}
```
`risk_score` semantics: see §2.

### 4.2 `POST /verify/batch` — async, multi-document (NEW, additive)

Submit a whole applicant file at once so the backend can run **cross-document**
checks (e.g. income on the salary slip vs the ITR) that a per-document call
cannot. Returns immediately; processing runs in a background thread and the
per-document pipelines run concurrently.

Request:
```json
{
  "applicant_id": "string | null",
  "documents": [
    {
      "document_type": "itr | salary_slip | land_record | legal_doc | bank_statement",
      "file_base64": "string",
      "filename": "string | null",
      "digilocker_uri": "string | null",
      "ulpin": "string | null",
      "has_qr": false
    }
  ]
}
```
(`applicant_id` omitted → server generates `APP-XXXXXX`.)

Response: `{ "job_id": "job_abc123" }`

### 4.3 `GET /verify/batch/{job_id}` — poll until done

```json
{
  "job_id": "job_abc123",
  "status": "processing | done | error",
  "progress": 0,
  "applicant_id": "string",
  "submitted_at": "2026-06-30T10:23:00Z",
  "document_count": 2,
  "overall":  { "risk_score": 41, "route_taken": "route_3", "decision": "auto_reject", "reasons": ["..."] },
  "documents": [
    {
      "filename": "itr.pdf", "document_type": "itr",
      "risk_score": 95, "route_taken": "route_1", "decision": "auto_approve",
      "reasons": ["All fields match DB-of-record"],
      "heatmap_url": null,
      "field_verification": { "status": "verified", "issuer": "CBDT", "matched_fields": ["pan"] },
      "extracted_fields": { "pan": "ABKPG7842M", "gross_total_income": 910000 }
    }
  ],
  "cross_document": [ { "label": "income differs across documents", "reason": "...", "severity": "high" } ],
  "error": null
}
```
- Each `documents[]` entry reuses the single-doc verdict fields + `filename`,
  `document_type`, and raw `extracted_fields`.
- `cross_document` is populated only when **2+** documents verify successfully.
- Job state is held **in memory for the process lifetime** (a polled results
  page survives reload while the server is up; lost on restart).

### 4.4 Other endpoints

- `GET /verify/{applicant_id}/history` — verdict events from the blockchain
  audit log table (frozen).
- `GET /health` — `{ "status": "ok" }`.

---

## 5. What changed recently (this session)

### Frontend (`frontend/` — entire app is new on this branch)
- `src/api/adapter.ts` **(new)** — declares the real backend wire types and all
  backend→UI mapping: `decision`→verdict, authenticity→risk inversion with
  band-clamping, `reasons[]`→signals (keyword-routed to Pipeline 1 vs 2),
  `field_verification`→extracted-fields table, batch job → `VerificationResult`.
- `src/api/realClient.ts` **(rewritten)** — submits one `POST /verify/batch`,
  polls `GET /verify/batch/{id}`; real progress, real cross-doc, results survive
  reload; image uploads get real object-URL thumbnails (PDFs use a placeholder).
- `src/api/types.ts` — header comment clarified (this is the UI's internal
  model, richer than the wire contract; the real client adapts to it).
- `.env.example`, `.gitignore` added.

### Pipeline 2
- `db.py` — replaced fake sample data with a real `_MOCK_DB` (applicant
  `ABKPG7842M`, Mahadev Balu Gadade) and a SQLite path that reads `verichain.db`
  (`VERICHAIN_DB` env, falls back gracefully if the file is missing). Column
  names match `schemas.py` (`gross_total_income`, `total_tax_paid`).
- `llm_client.py` — mock responses now use the **real** demo data (PAN
  `ABKPG7842M`, income 910000) so the DB lookup succeeds, and the mock fusion
  scores off the verification `match_status` instead of a hardcoded 72.

### Backend
- `routes/verify.py` — extracted the per-document pipeline into a reusable
  `process_document()` + `_holistic_to_api()` (shared by single-doc and batch);
  the single-doc endpoint is now thin. (Also: pydantic **v1** here — use
  `.dict()`, not `.model_dump()`.)
- `routes/batch.py` **(new)** — async batch endpoints + background processing
  (concurrent per-doc, then cross-document discrepancy, then overall fusion).
- `jobs.py` **(new)** — thread-safe in-memory job store.
- `main.py` — `sys.path` shim so `routes` imports work from repo root; registers
  the batch router.

### Data / setup
- `init_db.py` **(new)** — builds `verichain.db` (`land_records`, `itr_records`,
  `blockchain_log`) from `extracted/*.json`. Replaces the old `seed.py` +
  `load_authoritative.py`.
- `mock_data/` — the 5 demo applicant documents (APP001–APP005), incl. the
  tampered salary slip APP004. **These are committed.**
- `README.md` — API contract section updated with the batch endpoints + score-
  direction note.

---

## 6. How to run

### Backend (mock LLM — no credentials, deterministic)
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# from repo root the DB is ../verichain.db
VERICHAIN_DB=../verichain.db LLM_MOCK=1 uvicorn main:app --reload
# → http://localhost:8000  (docs at /docs)
```

### Backend (real LLM — needed for true fraud detection)
Mock mode returns canned data regardless of file contents, so tampered docs are
NOT actually detected under `LLM_MOCK=1`. For real verdicts, drop the flag and
configure litellm (defaults to Google Vertex/Gemini; any litellm provider works
by changing `LLM_MODEL` + creds — the extractor uses vision, so the model must
accept image/PDF input):
```bash
export LLM_MODEL="vertex_ai/gemini-2.0-flash"
export VERTEXAI_PROJECT="your-gcp-project"
export VERTEXAI_LOCATION="us-central1"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/sa.json"
cd backend && VERICHAIN_DB=../verichain.db uvicorn main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev            # → http://localhost:5173  (mock data by default)
# to hit the live backend:
cp .env.example .env.local   # sets VITE_USE_MOCK=false + VITE_API_BASE_URL
npm run dev
```
(Backend CORS already allows `http://localhost:5173`.)

### Rebuild the DB (only if you have `extracted/`)
```bash
python init_db.py      # writes verichain.db from extracted/*.json
```

---

## 7. Verified working / demo targets

Confirmed live (mock-LLM mode):
- `POST /verify` APP001 genuine ITR → `risk_score 95 / auto_approve`.
- `POST /verify/batch` with 2 docs → job completes, both docs verified
  concurrently, cross-document signal produced, overall fused, real
  `extracted_fields` returned.
- Frontend `tsc -b` + `npm run build` clean.

Demo invariants to keep passing (these need the **real LLM** to be truthful):

| App    | Scenario                         | Expect          | ~score |
|--------|----------------------------------|-----------------|--------|
| APP001 | Genuine ITR                      | auto_approve    | ~96    |
| APP002 | Tampered ITR (income altered)    | auto_reject     | ~18    |
| APP003 | Marathi 7/12 land scan           | human_review    | ~79    |
| APP004 | Tampered salary slip (gross↑)    | auto_reject     | ~22    |
| APP005 | Cross-doc fraud (ITR vs slip)    | auto_reject     | ~41    |

Note: APP004 is a *redaction-tampered* slip (gross 80,000→2,00,000). Its real
signal is **internal arithmetic inconsistency** (net pay, words, and the annual
line still say 80,000) — not a font mismatch as an old code comment claims.

---

## 8. Files you need from the repo owner (gitignored, NOT in git)

The repo intentionally ignores these. You need them to run end-to-end:

| File / dir                              | Why you need it                          |
|-----------------------------------------|------------------------------------------|
| `verichain.db`                          | the authoritative mock DB the backend reads |
| `extracted/` (19 JSONs)                 | only if you want to rebuild the DB via `init_db.py` |
| `CLAUDE.md`                             | the full golden-rules / agent instructions |
| `docs/project-context-fraud-detection.md` | full design context & rejected approaches |
| `raw_docs/`, `create_demo_docs.py`      | only to regenerate demo docs from source |

Get these from the owner out-of-band (or they may force-add `verichain.db` to
the branch — check `git log` for it). The 5 demo PDFs in `mock_data/` ARE
committed, so you can demo the flow once you have `verichain.db`.

---

## 9. Where to start / open work

- **Run with a real LLM** and re-validate the 5 demo invariants (mock can't
  detect tampering). This is the highest-value next step.
- **Pipeline 1 ↔ 2 cross-link:** field-level tamper localization (P1) on the
  same field that P2 flags as a data mismatch — the project's headline seam.
  Currently `heatmap_url` is always null and signals carry no regions.
- **Cross-document in mock mode** returns a canned address-mismatch; with a real
  LLM it surfaces the actual ITR-vs-salary income gap (APP005).
- **Frontend deep-link on reload** works only while the backend process is alive
  (jobs are in-memory). Persisting jobs would fix this.
- **Pipeline 1 needs PyMuPDF** (`fitz`); the verify route degrades gracefully if
  it's missing (`_P1_AVAILABLE = False`).
