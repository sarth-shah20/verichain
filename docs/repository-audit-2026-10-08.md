# VeriChain execution audit — 8 October 2026

The repository has a working document-verification prototype. Real Gemini extraction, local database comparison, forensic revision recovery, deterministic salary checks, fusion, asynchronous batch processing, and cross-document income checks all completed successfully on synthetic inputs. This is evidence of functional integration, not a measured fraud-detection accuracy rate or readiness for automated underwriting.

No application code was changed. The existing modified `verichain.db` was preserved. Local sample inspection used a database copy; live calls used a fresh database containing invented records only. Automated approval review blocked sending repository demo documents to Gemini because they may contain financial/identity data; those files were tested locally instead.

## Executed checks

- `PYTHONPATH=ai:pipeline2 .venv/bin/python -m pytest -q`: **27 passed in 0.80 seconds** (21 validator, 2 revision-recovery, 4 heatmap/JPEG-ghost tests).
- `npm run build` in `frontend`: TypeScript and Vite production build passed.
- Real Gemini text connectivity: passed using the configured `gemini/gemini-3.1-flash-lite` model and existing key. No credential values were printed or copied into this report.
- Five synthetic documents passed through the real FastAPI handlers using TestClient and real Gemini calls. No model responses were mocked in those runs; all five fusion reports had no fallback flag.
- The frontend adapter was bundled and executed against the live batch result. Browser upload/render interactions were not exercised.
- Additional local checks generated QR images, incremental PDFs, a signature dictionary fixture, a nine-page PDF, and explicit failure-injection inputs. Failure-injection checks are not counted as live model successes.

## Live results

Scores below are backend authenticity scores, where higher means more trustworthy. They are observations from one run, not fixed expected outputs.

| Synthetic case | HTTP / outcome | Backend score | Evidence |
|---|---|---:|---|
| ITR matching a seeded record | 200 / auto_approve | 100 | OCR, field derivation, PAN checks, DB lookup, semantic verification and fusion succeeded; seven fields matched |
| Salary PDF incrementally edited from 80,000 to 200000 | 200 / auto_reject | 5 | Original value recovered; gross minus deductions disagreed with net; heatmap URL generated |
| Rasterized English Maharashtra land record | 200 / auto_approve | 85 | Local parcel lookup matched; pixel anomalies remained advisory |
| ITR with income reduced from 960000 to 370000 | Batch document / auto_reject | 15 | Income discrepancy against synthetic DB record; verification's partial_match was mapped to API mismatch |
| Clean salary slip, no DB record | Batch document / human_review | 75 | Arithmetic passed; unverified rather than fraud |
| Altered ITR + clean salary slip | Batch done / auto_reject | 15 overall | Detected 370000 annual ITR versus 80000 × 12 = 960000 annual salary; high-severity discrepancy |

Single-document durations were 11.60 seconds (ITR), 7.26 seconds (edited salary), and 14.27 seconds (land scan). The two-document concurrent batch, including cross-document analysis, took 12.08 seconds. These small synthetic fixtures do not establish latency for real documents.

Batch submission returned a job ID; polling observed processing and completion. Removing that job from the in-memory dictionary and polling again successfully loaded the persisted result with the same overall verdict. PDF export returned 200 and PDF bytes. Recording a human review decision returned 200. History contained the two system verdicts and the human decision. This proves the persistence fallback, not a full process-restart/browser test.

## Intended implementation versus observed behavior

| Area | Assessment |
|---|---|
| Python 3.11 | Tested runtime is **3.12.3**. Python 3.11 compatibility was not tested. Modern type hints are used. Future annotations are not universal: 9 of 53 Python files lack the import, including empty package initializers and `schema.py`. |
| Pydantic | Pipeline 1's declared schema classes and API request/response models use BaseModel. Pipeline 2 extraction, verification, schemas, and fusion use ordinary dictionaries and prompt-defined JSON, without equivalent Pydantic validation. |
| PyMuPDF / pikepdf | Installed and exercised through real parsing, rendering, metadata/font analysis, signature dictionary detection, and revision recovery. |
| pyHanko / certvalidator | **Not installed.** A synthetic signature dictionary was detected and produced explicit unavailable warnings; cryptographic integrity and trust-chain results were null. Real signed-byte and certificate validation remain unverified. |
| Classification | Born-digital supplied PDFs and a scanned JPEG classified correctly for routing. A synthetic signature dictionary routed to signed_pdf; this is not proof of a valid signature. |
| Tier 0 / QR | OpenCV fallback decoded a generated QR payload. Registry verification remains a local JSON/mock integration, not a live issuer check. |
| Tier 1 / revision recovery | Strongest directly verified forensic feature. Supplied APP004 recovered 80,000 → 2,00,000 and Tier 1 scored 50. A metadata-only incremental re-save recovered no material changes. |
| Tier 2 / OpenCV, NumPy, SciPy | Supplied Marathi JPEG ran copy-move, DCT, ELA, noise and JPEG ghost, with all five ran flags true and no warnings; 57 suspect regions were emitted. This proves execution, not that those 57 regions are tampering. |
| Tier 3 / heatmaps | Already wired into the backend, beyond the described Tier 0–2 flow. Spectral analysis and heatmap generation ran. Page localization has a reproduced bug described below. |
| Two-pass extraction | Real vision OCR then text field derivation worked. Full text was populated. Live regional-script translation and transliteration accuracy were not validated; the synthetic land scan was English. |
| Authoritative DB | SQLite lookup works; existing DB contains 15 land records and 1 ITR record. Data is locally seeded from extracted document JSON; there is no live government/issuer verification. Labels such as CBDT/CERSAI do not establish a live connection. |
| Deterministic validators | PAN, Aadhaar, GSTIN and salary arithmetic unit tests pass. A no-DB malformed salary becomes mismatch; a reconciled salary stays unverified. End-to-end identifier coverage depends on what extraction schemas preserve. |
| Cross-document | Live annual-income conflict detected. Current code includes a deterministic annualized-income check in addition to the LLM, beyond the description. PAN/GSTIN helper logic exists, but payslip PAN is lost during extraction. Cross-document analysis includes successfully processed unverified documents; it does not require DB-matched documents. |
| Fusion / routing | Real fusion produced useful decisions in all tested cases. Score inversion and 80/60 boundaries work. Hard-evidence enforcement and provider-failure handling have critical gaps. |
| Frontend | Build and adapter execution pass. Backend 100 approval becomes UI 95; backend 5 rejection becomes UI 15; backend 75 review becomes UI 69. Both pipeline display scores are copies of the fused score, not independent pipeline scores. |
| Audit / blockchain | SQLite audit insertion and history work. Transaction hashes are locally generated mock values; no blockchain network, chained ledger, or tamper-evident verification was demonstrated or implemented in this flow. |

The supplied genuine and income-altered ITR PDFs both scored 100 in Tiers 0 and 1 and had no recovered prior revision. Pipeline 1 therefore did not distinguish that particular content fraud. That is a limitation of structural evidence, and demonstrates why Pipeline 2 is necessary.

## Reproduced gaps and priorities

1. **High: fusion failure can approve despite forensic tampering.** `pipeline2/fusion.py:190` and `:248` catch any model failure and derive fallback risk solely from content match status. Injecting a provider outage with content=match and forensic authenticity=0 plus a recovered material edit returned risk=10, then API authenticity=90 / auto_approve. Forensics and cross-document evidence are ignored by the fallback. Make incomplete fusion a review state and preserve hard evidence.

2. **High: definitive evidence is not enforced at final routing.** `backend/routes/verify.py:432` trusts the LLM risk integer. Feeding it mismatch evidence and risk=0 yielded auto_approve / 100 with field_verification=mismatch. Risk=-20 yielded authenticity=120. These are direct mapper probes, not observed live Gemini mistakes. Validate output ranges and enforce deterministic decision constraints outside the prompt.

3. **High: PAN on payslips is not extracted into fields.** `pipeline2/schemas.py:93` omits PAN from the payslip field list. In both live salary reports, PAN was present in full_text but absent from extracted fields. Validators and cross-document analysis consume fields, so a printed payslip PAN conflict can be missed. Add identifiers to appropriate schemas and exercise the full extraction-to-cross-check path.

4. **High: land lookup can select an unrelated parcel record.** `pipeline2/db.py:97` matches base survey numbers, returns a lone candidate regardless of locality, and falls back to the first candidate when locality overlap is zero. A lookup with an existing survey number but unrelated state, district, village and owner returned found=true. This proves unsafe entity selection, not that the downstream LLM necessarily approves it. Require locality/parcel identity and handle ambiguity explicitly.

5. **Medium: page numbering duplicates/misplaces edit overlays.** `backend/routes/verify.py:228` adds one only for page zero. `ai/pipeline1/tamper_map/heatmap.py:138` tries the preceding page's regions as fallback. A PDF edited only on its second page produced high-confidence revision-edit boxes on both page 1 and page 2. Normalize page indexes once and remove the ambiguous fallback.

6. **Medium: whole-document OCR silently stops at eight pages.** `pipeline2/utils.py:20` defaults to eight pages and `:48` breaks without surfacing truncation. A nine-page PDF produced only eight media objects. Fields or contradictions on later pages are unseen. Paginate OCR or mark incomplete input explicitly.

7. **Medium, source-traced: cross-document deterministic checks depend on LLM availability.** `pipeline2/discrepancy.py:258` calls the LLM before the deterministic helpers. A failure prevents the helpers and propagates to the batch's outer error handler, before documents are published as completed. Run deterministic checks first and preserve per-document results on a cross-analysis outage.

8. **Medium: displayed pipeline scores are misleadingly identical.** `frontend/src/api/adapter.ts:411` and `:420` assign the same fused trust score to both pipelines. Executing the adapter on the live result confirmed this. Either expose actual independent evidence/metrics or label these as the overall fused score.

Additional limitations: PDF page PNGs produced by `utils.load_media` are not cleaned up when `process_document` removes its temporary input; audit/store errors are often swallowed; active jobs remain process-local even though completed jobs persist; live cross-document income flags were duplicated by deterministic and model findings. These should be addressed before operational use.

## Scope and evidence

The audit establishes successful small-fixture integration. It does not establish detection sensitivity, false-positive rates, multilingual accuracy, resistance to document prompt injection, trusted issuer provenance, valid-signature verification, deployment resilience, or performance under load. No labeled evaluation corpus or broad end-to-end test suite was found among the collected tests.

Saved evidence: `docs/repository-audit-2026-10-08-evidence.json` contains synthetic live API results and synthetic edge checks. Temporary working artifacts and scripts are under `/tmp/verichain-audit/`; supplied-document forensic outputs remain local there. The existing repository sample files were never sent to Gemini during this audit.
