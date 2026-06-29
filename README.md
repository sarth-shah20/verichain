# VeriChain

Real-time multi-modal document verification for loan underwriting.

SuRaksha Cyber Hackathon 2.0 — Theme 1: Real-Time Anomaly Detection

---

## What we're building

An intelligent document verification system that detects tampering, forgery, and cross-document fraud in loan applications using field-level digital signature verification, multi-modal AI, and a blockchain audit log.

---

## Repo structure

```
verichain/
├── backend/        FastAPI backend — routing engine, APIs, database
├── blockchain/     Audit log chain — hashing, Ganache, web3
├── ai/             Forensics + OCR — ELA, EXIF, LLM integration
├── frontend/       React dashboard — upload, results, heatmap
├── mock_data/      Test documents — genuine, tampered, vernacular, AI-generated
├── docs/           API contract, architecture notes
└── README.md
```

---

## Branching rules

- Never push directly to `main`
- Branch off `dev`, merge back to `dev`
- At least one reviewer must approve before merging to `main`
- Branch naming: `feature/what-you-are-building`

```
main                          stable, demo-ready only
dev                           integration branch
feature/backend-core
feature/blockchain-audit
feature/ai-forensics
feature/frontend-dashboard
feature/contradiction-engine
feature/vernacular-ocr
fix/description-of-bug
chore/description-of-task
```
## Setup

```
main    → stable/demo-ready code
dev     → active integration branch
feature/* → individual work branches
```

## Workflow
```
feature/backend-core
            \
feature/frontend ----> dev ----> main
            /
feature/ai
```

## Commit message format- examples

```
feat: add ELA pixel analysis for Route 3
fix: correct hash comparison in Route 1
chore: seed mock documents in database
docs: update API contract
```

---

## API contract - we can discuss over this

All integration is built around this. Do not change without informing each other.

### POST /verify

**Request**
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

**Response**
```json
{
  "risk_score": 78,
  "route_taken": "route_1 | route_2 | route_3",
  "decision": "auto_approve | human_review | auto_reject",
  "reasons": [
    "Income mismatch: ITR declares 4.2L, salary slip declares 11.8L. Gap: 7.6L.",
    "EXIF metadata shows file last modified in Adobe Acrobat 3 days after stated issue date."
  ],
  "blockchain_tx": "0xabc123...",
  "heatmap_url": "string | null",
  "field_verification": {
    "status": "verified | mismatch | unverifiable",
    "issuer": "CBDT | CERSAI | mock_registry",
    "matched_fields": ["owner_name", "survey_number", "area"]
  }
}
```

> `risk_score` is an **authenticity / confidence** score (higher = more genuine):
> `>=80` → `auto_approve` (`route_1`), `60-79` → `human_review` (`route_2`),
> `<60` → `auto_reject` (`route_3`). It is single-document only.

### POST /verify/batch  *(async, multi-document)*

Additive endpoint — the single-doc `POST /verify` schema above is **unchanged**.
Submits a whole applicant file at once so the backend can run **cross-document**
checks (e.g. income on the salary slip vs. the ITR) that a per-document call
cannot. Returns immediately with a `job_id`; processing runs in the background
and the per-document pipelines run concurrently.

**Request**
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
If `applicant_id` is omitted, the server generates one (`APP-XXXXXX`).

**Response**
```json
{ "job_id": "job_abc123" }
```

### GET /verify/batch/{job_id}

Poll until `status` is `done` or `error`.

**Response**
```json
{
  "job_id": "job_abc123",
  "status": "processing | done | error",
  "progress": 0,
  "applicant_id": "string",
  "submitted_at": "2026-06-29T10:23:00Z",
  "document_count": 2,
  "overall": {
    "risk_score": 41,
    "route_taken": "route_3",
    "decision": "auto_reject",
    "reasons": ["Income on salary slip does not reconcile with the ITR."]
  },
  "documents": [
    {
      "filename": "itr.pdf",
      "document_type": "itr",
      "risk_score": 95,
      "route_taken": "route_1",
      "decision": "auto_approve",
      "reasons": ["All fields match DB-of-record"],
      "heatmap_url": "string | null",
      "field_verification": {
        "status": "verified | mismatch | unverifiable",
        "issuer": "CBDT | CERSAI | mock_registry",
        "matched_fields": ["pan", "gross_total_income"]
      },
      "extracted_fields": { "pan": "ABKPG7842M", "gross_total_income": 910000 }
    }
  ],
  "cross_document": [
    { "label": "income differs across documents", "reason": "...", "severity": "high" }
  ],
  "error": null
}
```
Each entry in `documents` reuses the single-doc verdict fields, plus `filename`,
`document_type` and the raw `extracted_fields`. `cross_document` is populated
only when two or more documents verify successfully. Job state is held in memory
for the process lifetime (a polled results page survives reload).

### GET /verify/{applicant_id}/history

Returns all verification events for an applicant from the blockchain audit log.

**Response**
```json
{
  "applicant_id": "string",
  "events": [
    {
      "timestamp": "2025-06-01T10:23:00Z",
      "document_type": "itr",
      "risk_score": 78,
      "decision": "human_review",
      "blockchain_tx": "0xabc123..."
    }
  ]
}
```

### GET /mock/digilocker/{applicant_id}

Mock DigiLocker API — returns pre-seeded document hash and fields for an applicant.

### GET /mock/cersai/{ulpin}

Mock CERSAI API — returns lien status for a property.

---

## Environment setup

Copy `.env.example` to `.env` and fill in your own keys. Never commit `.env`.

```bash
cp .env.example .env
```

---

## Setup by module

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```
Runs at http://localhost:8000
API docs at http://localhost:8000/docs

### Frontend
```bash
cd frontend
npm install
npm run dev
```
Runs at http://localhost:5173

### Blockchain
```bash
npm install -g ganache
ganache --port 7545
cd blockchain
pip install web3
python chain.py
```

### AI
```bash
cd ai
pip install -r requirements.txt
```

---

## Demo test cases

All test documents are in `mock_data/documents/`. Pre-seeded applicant IDs:

| Applicant ID | Scenario | Expected score | Expected decision |
|---|---|---|---|
| `APP001` | Genuine ITR with DigiLocker URI | 96 | auto_approve |
| `APP002` | Tampered ITR (income altered) | 18 | auto_reject |
| `APP003` | Marathi 7/12 land record scan | 79 | human_review |
| `APP004` | AI-generated fake salary slip | 22 | auto_reject |
| `APP005` | Cross-doc fraud (ITR vs salary slip mismatch) | 41 | auto_reject |

---

## Integration checkpoint

Before the final third of the hackathon, every module must be working in isolation and tested against the mock data. The last section is integration + demo polish only.