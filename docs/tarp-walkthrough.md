# VeriChain TARP walkthrough

This is a college decision-support prototype for identifying altered loan documents and explaining findings. It checks land records, ITRs, salary slips and INR bank statements. A human records the final decision with a required reason. Local reference data and synthetic demo records are not connections to government or bank portals.

## Run locally

Use the existing virtual environment or install `backend/requirements.txt` in a Python 3.11+ environment. The validated runtime for this upgrade was Python 3.12.3; Python 3.11 was not separately exercised.

Configure `backend/.env` (environment variables take precedence):

```dotenv
LLM_MODEL=gemini/gemini-3.1-flash-lite
GEMINI_API_KEY=your_key_here
LLM_CONCURRENCY=1
LLM_RETRIES=2
```

The model is configurable. The successful checks used Gemini 3.1 Flash Lite through the configured Gemini API key, not Vertex AI or Gemini Pro. No offline mode is used for document analysis. Requests still expose locally available evidence and an incomplete/review outcome if the provider fails.

From the repository root:

```bash
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. `VITE_API_BASE_URL` defaults to `http://localhost:8000`. To isolate course demonstrations from your normal history, set `VERICHAIN_DB=/tmp/verichain-tarp.db` when starting the backend. A fresh database now initializes verification and audit tables automatically.

## Presentation sequence

1. Open **New verification** and select **Consistent applicant pack**. This fills the normal upload form with four clearly marked, invented PDFs. Click **Verify**; stages and elapsed time reflect actual work.
2. Show the report: ITR and land match their explicitly synthetic reference records; payslip and bank are unverified without issuer records. Open the money trail: net pay INR 70,000 equals the identified salary credit, difference zero. An unverified document is not automatically fraud.
3. Run **Edited salary figure**. Open the evidence workspace and click **Original value recovered**. The original gross pay 80,000 is recovered from the prior PDF revision; the current value is 200,000. Gross minus deductions also fails. The source region opens on page 1.
4. Run **Broken bank balance**. Show the transaction table and failed arithmetic. Whole-statement and adjacent-row checks use Decimal amounts with INR 1 rounding tolerance; unreadable/missing rows do not produce invented certainty.
5. Run **Conflicting applicant PAN**. Both PAN structures pass, but identity differs across documents. This deterministic conflict remains available even if the semantic comparison call fails.
6. Record a decision with a reviewer note, reload, reopen from **Verification history**, and download the report. Notes, structured findings, original page previews and reconciliation are persisted.

The demo selector only generates documents; it does not precompute or substitute verification results. Reserved demo identifiers have invented in-code reference records, labeled `synthetic_demo_reference` by the database adapter. Uploaded ordinary documents continue to use local SQLite records.

## Measured live results — 8 October 2026

All six scenarios completed using real Gemini calls, invented documents, an isolated database and no response mocks. These are one-run observations, not accuracy measurements or guaranteed future scores.

| Pack | Expected key evidence | Observed recommendation | Authenticity /100 | Time |
|---|---|---|---:|---:|
| Consistent four-document pack | ITR/land reference matches, salary credit match, issuer-unverified payslip/bank | human_review | 75 | 93 s |
| Edited salary | Recover 80,000 → 200,000; failed payslip arithmetic | auto_reject | 5 | 16 s |
| Inflated ITR | 2,400,000 versus 960,000 reference income | auto_reject | 15 | 19 s |
| Broken bank balance | Running balance / statement total mismatch | auto_reject | 5 | 11 s |
| Inflated land area | 12.5 versus 2.5 hectares | auto_reject | 15 | 17 s |
| PAN conflict | Structurally valid PANs disagree across documents | auto_reject | 40 | 30 s |

All six reported complete analysis with no provider warnings. A further salary-edit run through the browser's actual submit → polling → report flow again returned complete / auto_reject / 5. See [machine-readable evidence](tarp-live-demo-results.json). The original [repository audit](repository-audit-2026-10-08.md) describes the pre-fix behavior and should not be mistaken for the current implementation.

## Implemented priorities

- Final decisions are constrained outside the model. Definitive failed checks, high material recovered edits, material reference discrepancies and definitive identity conflicts cap authenticity at 40. Incomplete analysis and missing issuer records alone produce review, without overriding existing hard evidence.
- Fusion scores use a Pydantic integer/range contract. Invalid responses or outages are explicitly incomplete. Cross-document deterministic checks execute before the model; model failure preserves checks and per-document results.
- PAN is extracted from salary slips and bank statements. Land lookup requires an exact parcel identifier or unique full locality/survey/subdivision match; unrelated first candidates are never selected.
- Public source pages are consistently one-based. Preview pages persist, and forensic regions stay on their source page. Revision boxes are attached to recovered-value findings to avoid duplicate findings.
- PDFs over eight pages, encrypted PDFs, invalid formats and files over 25 MB are rejected before jobs start. OCR temporary files are removed after calls.
- Bank transactions retain structured typed rows. Adjacent balances and fully captured statement totals are checked independently. Incomplete extraction skips unverifiable totals.
- Salary reconciliation compares net pay to one identifiable payroll/employer credit in the pay month plus seven days, requires matching account suffixes and coverage, and uses max(INR 100, 1%) tolerance. Missing, multiple, split or ambiguous credits require review. Amount disagreement alone is advisory, not conclusive fraud.
- Monthly salary ×12 versus ITR is explicitly an annual estimate with medium severity; it cannot alone establish fraud.
- The frontend uses one raw authenticity scale throughout: approve ≥80, review 60–79, reject <60. There is no invented confidence percentage or 15–95 remapping. Forensics and content have separate status/evidence summaries, not duplicate scores.
- The new navy/teal navigation and light reading canvas support responsive review. The workspace offers document selection, originals/heatmaps, page/zoom controls, clickable findings, recovered values, fields and transaction rows. A shared decision dialog requires a note.
- Reports include score direction, coverage warnings, source references, financial comparisons, recovered values, the human decision/note and original pages.
- Live model calls default to concurrency one with at most two transient retries. Provider Retry-After delays up to 30 seconds are honored; longer delays surface as incomplete analysis.

## Validation

```bash
.venv/bin/python -m pytest pipeline2 backend ai/pipeline1 -q
cd frontend
npm run build
npm test
```

Final result: **65 Python tests passed**, production TypeScript/Vite build passed, and frontend adapter regression checks passed. TestClient emits a dependency deprecation warning; it does not fail the suite.

Browser checks covered 1440px desktop, 1024px tablet and 390px mobile layouts, both themes, actual demo selection/submission/polling, original-page preview, bank transactions, salary-credit source selection, disabled save without a note, persisted decision/note after reload, Tab navigation and Escape dismissal. The evidence workspace had no horizontal page overflow. Report pages were rendered and visually inspected.

![Evidence workspace](evidence-workspace.jpg)

## Course-scale boundaries

Pixel anomalies are advisory and have not been calibrated on a labeled fraud benchmark. The clean and altered born-digital files in the initial audit demonstrate why content comparison is necessary alongside file forensics. Live Marathi translation accuracy remains unmeasured. Cryptographic signature trust validation remains untested because optional pyHanko dependencies are absent; a signature dictionary or QR payload is not proof of authenticity.

Most pipeline-2 extraction/semantic verification data still uses dictionary contracts; fusion and bank transaction boundaries are now Pydantic-validated. This upgrade does not claim all schemas are Pydantic. Job execution remains in memory while running; completed results persist, but a server restart interrupts active work. The audit trail uses local database records and mock transaction hashes, not a deployed blockchain. These are reasonable demo limitations, and should be stated in the presentation.
