# VeriChain — Frontend

A clean, trustworthy UI for a bank's loan-underwriting team to verify applicant
documents (bank statements, land records / 7-12 extracts, ITRs, salary slips)
for **tampering, forgery and content mismatches**.

This is the **frontend**. It talks to the live VeriChain backend through a typed
API layer (`src/api/`), pointed at the backend via `VITE_API_BASE_URL`.

---

## Quick start

```bash
npm install
npm run dev
```

Open the URL Vite prints (default http://localhost:5173). Make sure the backend
is running and `VITE_API_BASE_URL` points at it (see below).

Other scripts:

```bash
npm run build      # type-check + production build
npm run preview    # preview the production build
npm run typecheck  # types only
```

---

## The flow

**New Verification → drop any PDF/JPG/PNG → Verify → processing → results
dashboard → open a document → evidence view.** Each submission is verified live
by the backend.

---

## Backend connection

The API client lives in **`src/api/index.ts`** and is configured by one env var:

```bash
# .env.local
VITE_API_BASE_URL=http://localhost:8000  # base URL of the running backend
```

`RealVeriChainApi` (`src/api/realClient.ts`) calls that base URL and implements
the `VeriChainApi` interface (`src/api/types.ts`). Restart the dev server after
editing `.env.local`.

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
> image box (0–100)** so overlay boxes scale responsively.

---

## Architecture & conventions

The two-pipeline architecture is reflected in the UI: **Forensics is teal**,
**Verification is indigo** — so the interface teaches the officer *why*
something was flagged.

Trust score color scale — HIGHER = more genuine (tokens in `tailwind.config.js`,
thresholds in `src/lib/risk.ts`):

- `70–100` → green · Genuine
- `40–69` → amber · Needs review
- `0–39` → red · High risk / Likely forged

Every color is paired with a text label and icon — meaning never relies on
color alone (WCAG AA).

### Project structure

```
src/
  api/            API client (realClient), adapter, types
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
> (`src/lib/placeholders.ts`) for documents without a real preview image (e.g.
> PDF cards). The backend returns real image URLs in the same fields.
