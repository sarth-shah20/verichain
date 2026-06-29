import type { VerificationResult } from "@/api/types";
import { docPlaceholder, heatmapPlaceholder } from "@/lib/placeholders";

// ---------------------------------------------------------------------------
// Three sample applications that tell a story for the demo:
//   1. APP-10231 — clean, genuine (green)
//   2. APP-10544 — needs review (amber)
//   3. APP-10987 — clearly forged (red), with heatmap region + cross-doc mismatch
// All thumbnail/heatmap URLs are inline SVG data URIs so the demo runs offline.
// ---------------------------------------------------------------------------

const GENUINE: VerificationResult = {
  application_id: "APP-10231",
  submitted_at: "2026-06-24T09:14:00Z",
  overall: {
    risk_score: 12,
    verdict: "genuine",
    confidence: 0.96,
    summary:
      "All documents are physically genuine and content cross-validates. Safe to proceed.",
  },
  documents: [
    {
      doc_id: "doc_g1",
      filename: "hdfc_statement_apr_jun.pdf",
      doc_type: "bank_statement",
      thumbnail_url: docPlaceholder("bank_statement"),
      risk_score: 9,
      verdict: "genuine",
      pipeline1: {
        score: 7,
        heatmap_url: null,
        signals: [
          {
            family: "provenance",
            label: "Valid issuer digital signature",
            severity: "info",
            reason:
              "The PDF carries a valid PKCS#7 signature chaining to HDFC Bank's certificate.",
            region: null,
          },
          {
            family: "image",
            label: "No compression anomalies",
            severity: "info",
            reason:
              "Error-level analysis is uniform across the page; no localised re-saves detected.",
            region: null,
          },
        ],
      },
      pipeline2: {
        score: 11,
        extracted_fields: [
          { key: "Account Holder", value: "A. Sharma", status: "ok" },
          { key: "Account Number", value: "XXXX4421", status: "ok" },
          { key: "Period", value: "Apr–Jun 2026", status: "ok" },
          { key: "Closing Balance", value: "₹2,48,300", status: "ok" },
          { key: "Avg. Monthly Credit", value: "₹82,000", status: "ok" },
        ],
        signals: [
          {
            family: "content",
            label: "Balances reconcile",
            severity: "info",
            reason:
              "Opening + credits − debits equals the printed closing balance for every month.",
            region: null,
          },
        ],
      },
    },
    {
      doc_id: "doc_g2",
      filename: "salary_slip_may2026.pdf",
      doc_type: "salary_slip",
      thumbnail_url: docPlaceholder("salary_slip", "#4f46e5"),
      risk_score: 14,
      verdict: "genuine",
      pipeline1: {
        score: 12,
        heatmap_url: null,
        signals: [
          {
            family: "structure",
            label: "Consistent embedded fonts",
            severity: "info",
            reason: "A single embedded font family is used throughout the slip.",
            region: null,
          },
        ],
      },
      pipeline2: {
        score: 15,
        extracted_fields: [
          { key: "Employee", value: "Anil Sharma", status: "ok" },
          { key: "Employer", value: "Infotech Solutions Pvt Ltd", status: "ok" },
          { key: "Net Pay", value: "₹82,000", status: "ok" },
          { key: "PAN", value: "ABCPS1234K", status: "ok" },
        ],
        signals: [
          {
            family: "triangulation",
            label: "Net pay matches bank credit",
            severity: "info",
            reason:
              "Net pay (₹82,000) matches the recurring salary credit in the bank statement.",
            region: null,
          },
        ],
      },
    },
  ],
  cross_document: [],
  flag_history_notes: [
    "Issuer HDFC Bank has a clean history with this officer's branch — no prior false positives.",
  ],
};

const REVIEW: VerificationResult = {
  application_id: "APP-10544",
  submitted_at: "2026-06-23T15:42:00Z",
  overall: {
    risk_score: 54,
    verdict: "review",
    confidence: 0.74,
    summary:
      "Mostly consistent, but a metadata gap and one unverified field warrant a closer look.",
  },
  documents: [
    {
      doc_id: "doc_r1",
      filename: "712_extract_pune.pdf",
      doc_type: "land_record",
      thumbnail_url: docPlaceholder("land_record"),
      risk_score: 58,
      verdict: "review",
      pipeline1: {
        score: 55,
        heatmap_url: heatmapPlaceholder("land_record"),
        signals: [
          {
            family: "provenance",
            label: "Missing QR / e-Satbara stamp",
            severity: "medium",
            reason:
              "The extract has no scannable QR code linking to the Maharashtra land-records portal; authenticity could not be confirmed online.",
            region: { x: 60, y: 8, w: 30, h: 10 },
          },
          {
            family: "structure",
            label: "Re-saved after scan",
            severity: "low",
            reason:
              "Metadata shows the file was opened and re-saved in an image editor after scanning — common but worth noting.",
            region: null,
          },
        ],
      },
      pipeline2: {
        score: 52,
        extracted_fields: [
          { key: "Survey No.", value: "142/2B", status: "ok" },
          { key: "Holder Name", value: "Anil Sharma", status: "ok" },
          { key: "Area (Ha)", value: "0.81", status: "ok" },
          { key: "Mutation Entry", value: "—", status: "missing" },
        ],
        signals: [
          {
            family: "content",
            label: "Mutation entry not found",
            severity: "medium",
            reason:
              "The latest mutation entry field is blank, so ownership transfer history could not be validated.",
            region: { x: 12, y: 64, w: 50, h: 6 },
          },
        ],
      },
    },
    {
      doc_id: "doc_r2",
      filename: "itr_ay2025_26.pdf",
      doc_type: "itr",
      thumbnail_url: docPlaceholder("itr", "#4f46e5"),
      risk_score: 41,
      verdict: "review",
      pipeline1: {
        score: 30,
        heatmap_url: null,
        signals: [
          {
            family: "provenance",
            label: "No e-filing acknowledgement signature",
            severity: "low",
            reason:
              "The ITR copy lacks the income-tax department's digital acknowledgement signature.",
            region: null,
          },
        ],
      },
      pipeline2: {
        score: 47,
        extracted_fields: [
          { key: "Assessee", value: "Anil Sharma", status: "ok" },
          { key: "PAN", value: "ABCPS1234K", status: "ok" },
          { key: "Gross Income", value: "₹11,40,000", status: "ok" },
          { key: "Declared Tax", value: "₹1,32,000", status: "mismatch" },
        ],
        signals: [
          {
            family: "content",
            label: "Declared tax slightly off slab",
            severity: "medium",
            reason:
              "Declared tax is ~6% lower than the computed tax for the stated gross income; could be deductions, verify supporting proofs.",
            region: null,
          },
        ],
      },
    },
  ],
  cross_document: [
    {
      label: "Name consistent, income plausible",
      reason:
        "Holder name matches across land record, ITR and salary records; income supports the requested loan band.",
      severity: "low",
    },
  ],
  flag_history_notes: [
    "Missing-QR on Maharashtra 7/12 extracts produced 2 false positives last quarter; treated as medium, not high.",
  ],
};

const FORGED: VerificationResult = {
  application_id: "APP-10987",
  submitted_at: "2026-06-22T18:03:00Z",
  overall: {
    risk_score: 88,
    verdict: "high_risk",
    confidence: 0.93,
    summary:
      "Strong evidence of tampering: the closing balance was edited and income does not reconcile across documents.",
  },
  documents: [
    {
      doc_id: "doc_f1",
      filename: "axis_statement_doctored.pdf",
      doc_type: "bank_statement",
      thumbnail_url: docPlaceholder("bank_statement"),
      risk_score: 91,
      verdict: "high_risk",
      pipeline1: {
        score: 89,
        heatmap_url: heatmapPlaceholder("bank_statement"),
        signals: [
          {
            family: "image",
            label: "Font discontinuity in balance field",
            severity: "high",
            reason:
              "The closing-balance digits use a different embedded font than the rest of the table — a classic sign of digit editing.",
            region: { x: 55, y: 83, w: 35, h: 8 },
          },
          {
            family: "image",
            label: "Localised compression artefacts",
            severity: "high",
            reason:
              "Error-level analysis lights up only around the balance box, indicating that region was re-saved separately.",
            region: { x: 55, y: 80, w: 36, h: 12 },
          },
          {
            family: "structure",
            label: "Inconsistent PDF object stream",
            severity: "medium",
            reason:
              "The page content stream was modified after the original creation timestamp.",
            region: null,
          },
        ],
      },
      pipeline2: {
        score: 84,
        extracted_fields: [
          { key: "Account Holder", value: "R. Verma", status: "ok" },
          { key: "Account Number", value: "XXXX9087", status: "ok" },
          { key: "Closing Balance", value: "₹11,15,000", status: "mismatch" },
          { key: "Computed Balance", value: "₹1,15,000", status: "mismatch" },
          { key: "Avg. Monthly Credit", value: "₹40,000", status: "ok" },
        ],
        signals: [
          {
            family: "triangulation",
            label: "Closing balance does not reconcile",
            severity: "high",
            reason:
              "Printed closing balance (₹11,15,000) is ten times the value computed from the listed transactions (₹1,15,000).",
            region: { x: 55, y: 83, w: 35, h: 8 },
          },
        ],
      },
    },
    {
      doc_id: "doc_f2",
      filename: "salary_slip_generated.png",
      doc_type: "salary_slip",
      thumbnail_url: docPlaceholder("salary_slip", "#4f46e5"),
      risk_score: 79,
      verdict: "high_risk",
      pipeline1: {
        score: 81,
        heatmap_url: null,
        signals: [
          {
            family: "image",
            label: "Likely AI-generated layout",
            severity: "high",
            reason:
              "Texture and edge statistics match synthetic image generators; no scanner or camera noise profile present.",
            region: null,
          },
          {
            family: "provenance",
            label: "No content credentials",
            severity: "medium",
            reason: "The image carries no C2PA provenance or capture metadata.",
            region: null,
          },
        ],
      },
      pipeline2: {
        score: 76,
        extracted_fields: [
          { key: "Employee", value: "Rahul Verma", status: "ok" },
          { key: "Employer", value: "Globex Corp", status: "ok" },
          { key: "Net Pay", value: "₹80,000", status: "mismatch" },
          { key: "PAN", value: "—", status: "missing" },
        ],
        signals: [
          {
            family: "content",
            label: "PAN missing from salary slip",
            severity: "medium",
            reason: "No PAN is present, preventing identity cross-checks.",
            region: null,
          },
        ],
      },
    },
  ],
  cross_document: [
    {
      label: "Income mismatch across documents",
      reason:
        "Salary slip net pay (₹80,000) does not match the recurring bank credit (₹40,000) — declared income is overstated.",
      severity: "high",
    },
    {
      label: "Employer not corroborated",
      reason:
        "Employer 'Globex Corp' on the salary slip does not appear in any bank credit narration.",
      severity: "medium",
    },
  ],
  flag_history_notes: [
    "No prior history for this applicant; all high-severity signals are first-time and corroborated by triangulation.",
  ],
};

export const SAMPLE_RESULTS: VerificationResult[] = [GENUINE, REVIEW, FORGED];

/** Used to rotate which sample a freshly-submitted job resolves to. */
export const SAMPLE_BY_INDEX = SAMPLE_RESULTS;
