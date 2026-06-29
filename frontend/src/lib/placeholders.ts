// ---------------------------------------------------------------------------
// Self-contained placeholder image generators (inline SVG data URIs) so the
// mock demo renders fully offline with no external image hosting. The real
// backend returns real PNG/JPG URLs in the same fields.
// ---------------------------------------------------------------------------
import type { DocType } from "@/api/types";

function encode(svg: string): string {
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

const DOC_TITLES: Record<DocType, string> = {
  bank_statement: "BANK STATEMENT",
  land_record: "7/12 EXTRACT",
  itr: "INCOME-TAX RETURN",
  salary_slip: "SALARY SLIP",
  unknown: "DOCUMENT",
};

/** A simple, document-looking placeholder page. */
export function docPlaceholder(docType: DocType, accent = "#0d9488"): string {
  const title = DOC_TITLES[docType];
  const lines = Array.from({ length: 11 }, (_, i) => {
    const y = 150 + i * 34;
    const w = i % 3 === 0 ? 260 : i % 3 === 1 ? 380 : 320;
    return `<rect x="56" y="${y}" width="${w}" height="10" rx="5" fill="#e2e8f0"/>`;
  }).join("");
  const svg = `
  <svg xmlns="http://www.w3.org/2000/svg" width="600" height="780" viewBox="0 0 600 780">
    <rect width="600" height="780" fill="#ffffff"/>
    <rect x="0" y="0" width="600" height="96" fill="${accent}"/>
    <text x="56" y="58" font-family="Inter, sans-serif" font-size="26" font-weight="700" fill="#ffffff">${title}</text>
    <text x="544" y="58" text-anchor="end" font-family="Inter, sans-serif" font-size="14" fill="#d1fae5">VeriChain sample</text>
    <rect x="56" y="118" width="180" height="14" rx="7" fill="#cbd5e1"/>
    ${lines}
    <rect x="56" y="560" width="488" height="160" rx="8" fill="none" stroke="#e2e8f0" stroke-width="2"/>
    <text x="72" y="592" font-family="Inter, sans-serif" font-size="13" font-weight="600" fill="#94a3b8">Closing balance</text>
  </svg>`;
  return encode(svg);
}

/** Document page with a red "tamper" rectangle drawn over the balance area. */
export function heatmapPlaceholder(docType: DocType): string {
  const title = DOC_TITLES[docType];
  const lines = Array.from({ length: 11 }, (_, i) => {
    const y = 150 + i * 34;
    const w = i % 3 === 0 ? 260 : i % 3 === 1 ? 380 : 320;
    return `<rect x="56" y="${y}" width="${w}" height="10" rx="5" fill="#e2e8f0"/>`;
  }).join("");
  const svg = `
  <svg xmlns="http://www.w3.org/2000/svg" width="600" height="780" viewBox="0 0 600 780">
    <rect width="600" height="780" fill="#ffffff"/>
    <rect x="0" y="0" width="600" height="96" fill="#0d9488"/>
    <text x="56" y="58" font-family="Inter, sans-serif" font-size="26" font-weight="700" fill="#ffffff">${title}</text>
    <rect x="56" y="118" width="180" height="14" rx="7" fill="#cbd5e1"/>
    ${lines}
    <rect x="56" y="560" width="488" height="160" rx="8" fill="none" stroke="#e2e8f0" stroke-width="2"/>
    <text x="72" y="592" font-family="Inter, sans-serif" font-size="13" font-weight="600" fill="#94a3b8">Closing balance</text>
    <text x="360" y="690" font-family="Inter, sans-serif" font-size="34" font-weight="700" fill="#0f172a">1,15,000</text>
    <!-- tamper region -->
    <rect x="330" y="650" width="210" height="58" rx="6" fill="rgba(220,38,38,0.18)" stroke="#dc2626" stroke-width="3"/>
    <rect x="330" y="630" width="92" height="20" rx="4" fill="#dc2626"/>
    <text x="338" y="645" font-family="Inter, sans-serif" font-size="12" font-weight="700" fill="#ffffff">TAMPER</text>
  </svg>`;
  return encode(svg);
}
