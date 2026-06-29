# VeriChain — Frontend

A clean, trustworthy UI for a bank's loan-underwriting team to verify applicant
documents (bank statements, land records / 7-12 extracts, ITRs, salary slips)
for **tampering, forgery and content mismatches**.

This repository is the **frontend only**. It ships with a typed **mock API
layer** so the whole app is demoable today with zero backend. Switching to the
real backend later is a one-line env change — no code changes.

---

## Quick start

```bash
npm install
npm run dev
```

Open the URL Vite prints (default http://localhost:5173). The app runs entirely
on mock data out of the box.

Other scripts:

```bash
npm run build      # type-check + production build
npm run preview    # preview the production build
npm run typecheck  # types only
```

---

## The demo story

Three sample applications are bundled and reachable from **History** (and each
fresh **New Verification** rotates through them):

| Application | Verdict        | What it shows                                                            |
| ----------- | -------------- | ------------------------------------------------------------------------ |
| `APP-10231` | 🟢 Genuine     | Low score, no high-severity signals, fields reconcile.                   |
| `APP-10544` | 🟠 Needs review | A missing QR + an unverified field; medium signals.                      |
| `APP-10987` | 🔴 High risk   | Edited closing balance with a **heatmap region**, font + triangulation signals, a field mismatch, and a **cross-document income mismatch**. |

To experience the full flow: **New Verification → drop any PDF/JPG/PNG →
Verify → processing → results dashboard → open a document → evidence view.**

---

## Mock ⇄ real backend switch

The single switch lives in **`src/api/index.ts`**, driven by env vars:

```bash
# .env
VITE_USE_MOCK=true                       # mock is ON unless this is exactly "false"
VITE_API_BASE_URL=http://localhost:8000  # used only when VITE_USE_MOCK=false
```

- `VITE_USE_MOCK=true` (default) → `MockVeriChainApi` (in-memory, sample data).
- `VITE_USE_MOCK=false` → `RealVeriChainApi`, calling `VITE_API_BASE_URL`.

Both classes implement the **same** `VeriChainApi` interface
(`src/api/types.ts`), so nothing else in the app changes. Restart the dev server
after editing `.env`.

---

## Backend contract (for the backend team)

Match these endpoints exactly and the real client (`src/api/realClient.ts`)
works with no frontend changes. Full TypeScript types are in
[`src/api/types.ts`](src/api/types.ts).

### `POST /api/verify`

Multipart form: one or more `files`, optional `application_id`.

```json
{ "job_id": "job_abc123" }
```

### `GET /api/verify/{job_id}`

```json
{
  "job_id": "job_abc123",
  "status": "processing | done | error",
  "progress": 0,
  "result": null
}
```

`result` is a `VerificationResult` when `status == "done"`.

### `VerificationResult` (abridged)

```jsonc
{
  "application_id": "APP-10231",
  "submitted_at": "2026-06-17T11:07:00Z",
  "overall": { "risk_score": 0, "verdict": "genuine|review|high_risk", "confidence": 0.0, "summary": "…" },
  "documents": [{
    "doc_id": "doc_1",
    "filename": "hdfc_statement.pdf",
    "doc_type": "bank_statement|land_record|itr|salary_slip|unknown",
    "thumbnail_url": "https://…",
    "risk_score": 0,
    "verdict": "genuine|review|high_risk",
    "pipeline1": { "score": 0, "heatmap_url": "https://…|null", "signals": [Signal] },
    "pipeline2": { "score": 0, "extracted_fields": [Field], "signals": [Signal] }
  }],
  "cross_document": [{ "label": "…", "reason": "…", "severity": "info|low|medium|high" }],
  "flag_history_notes": ["…"]
}
```

`Signal`:

```jsonc
{
  "family": "provenance|structure|image|content|triangulation",
  "label": "Font discontinuity in balance field",
  "severity": "info|low|medium|high",
  "reason": "Plain-English explanation.",
  "region": { "x": 0, "y": 0, "w": 0, "h": 0 } // OR null — percentages (0–100) of the document image
}
```

`Field`: `{ "key": "Closing Balance", "value": "₹1,15,000", "status": "ok|mismatch|missing" }`

> **Note on `region`:** the UI treats `x/y/w/h` as **percentages of the document
> image box (0–100)** so overlay boxes scale responsively. The mock
> `GET /api/history` endpoint returns an array of `HistoryItem` (see types).

---

## Architecture & conventions

The two-pipeline architecture is reflected in the UI: **Pipeline 1 (Authenticity
& Forensics) is teal**, **Pipeline 2 (Content Extraction & Validation) is
indigo** — so the interface teaches the officer *why* something was flagged.

Risk color scale (tokens in `tailwind.config.js`, thresholds in
`src/lib/risk.ts`):

- `0–39` → green · Genuine / Low risk
- `40–69` → amber · Needs review
- `70–100` → red · High risk / Likely forged

Every risk color is paired with a text label and icon — meaning never relies on
color alone (WCAG AA).

### Project structure

```
src/
  api/            client (mock/real switch), types, mock data
    mock/         in-memory backend + sample applications
  app/            router, layout/shell, theme, toast, client store
  components/     ScoreGauge, VerdictPill, SeverityBadge, SignalCard,
                  FileDropzone, DocumentCard, DocumentViewer, FieldsTable, …
  lib/            risk thresholds/colors, formatters, placeholders, useResult
  pages/          NewVerification, Processing, Results, DocumentDetail,
                  History, Settings, NotFound
```

### Screens

1. **New Verification** — drag-and-drop upload, multi-file, per-file type, optional Application ID.
2. **Processing** — progress + two-pipeline stepper, driven by polled `progress`.
3. **Results** — hero risk gauge & verdict, document cards, cross-document findings, flag-history notes, approve / review / reject actions.
4. **Document detail / Evidence** — heatmap with toggleable, clickable regions; signals grouped & color-coded by pipeline with a severity filter; extracted-fields table.
5. **History** — audit trail of past verifications.

Every screen implements **empty**, **loading (skeleton)** and **error** states.

---

## Tech stack

React 18 · Vite · TypeScript (strict, no `any`) · Tailwind CSS · React Router ·
lucide-react icons. Light/dark theme, keyboard-navigable, responsive.

> Placeholder thumbnails/heatmaps are generated as inline SVG data URIs
> (`src/lib/placeholders.ts`) so the mock demo renders fully offline. The real
> backend returns real image URLs in the same fields.
