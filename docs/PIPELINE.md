# Pipeline

Eight stages, each `run(ctx) -> StageResult(status, summary, details, halt)`.

## 1 Ingest (`s1_ingest.py`)
- **Does:** saves the file to `data/uploads/{run_id}.pdf`, SHA-256, page count, page text.
- **Fails:** not a PDF, encrypted, or zero pages → BLOCK finding `R00_READABLE`, halt → **REJECT**.
- **Event:** `{"file_name", "size_kb", "sha256", "source", "file_path", "pages"}`

## 2 Classify (`s2_classify.py`)
- **Does:** text characters per page: `>200` with invoice keywords → digital (text route); `<50` → scanned
  (vision route); otherwise hybrid (vision). Detects credit notes, quotations, statements and PDFs with
  several "Invoice No." blocks.
- **Event:** `{"doc_type": "scanned", "route": "vision", "text_density": 0.0, "document_kind": "invoice"}`

## 3 Extract (`s3_extract.py`, `core/llm/`)
- **Does:** text route sends page text; vision route sends 200-DPI page images. The router tries providers
  in `LLM_PROVIDER_ORDER`, skipping those not configured or without vision for scans. Output is validated
  against `ExtractedInvoice`; a validation failure gets one repair retry with the error fed back. Then
  confidence is **verified**: if the total disagrees with lines + tax, `total` confidence is capped at 0.5.
- **Fallbacks:** next provider → Tesseract OCR + text model (if installed) → "manual entry needed"
  (processing error, halt → **REVIEW**).
- **Event:** `{"provider": "groq (cached)", "attempts": [...], "confidence_adjustments": [...], "extraction": {...}}`

## 4 Normalise (`s4_normalize.py`)
- **Does:** amounts (`Rs. 1,18,000/-` → `118000.0`), dates (many formats; ambiguous DD/MM recorded as
  `N01_DATE_AMBIGUOUS`), invoice key (`INV/1042-R` → `1042`), PO key (`#1052` → `PO-2026-1052`), GSTIN
  format and state code, vendor resolution (GSTIN exact, then name/alias `token_set_ratio ≥ 88`).
- **Event:** before → after table, vendor match method and score.

## 5 Validate (`s5_validate.py`)
- **Does:** checks the invoice against itself: R03 line math, R04 subtotal, R05 total (tax-inclusive aware),
  R06 GST structure (intra-state CGST = SGST, inter-state IGST), R08 date sanity, R01 required fields,
  R02 critical-field confidence. If R05 fails but the correct total is printed on the page, it concludes the
  extractor misread it and lowers that field's confidence instead of blaming the vendor.

## 6 Match PO (`s6_match.py`)
- **Explicit:** the normalised reference exists → match (even if closed or another vendor's; rules judge that).
- **Inferred:** score every OPEN PO of the vendor:
  `0.45 × amount_similarity + 0.35 × line_similarity + 0.20 × date_plausibility`.
  Accept only if `≥ 0.75` and ahead of the runner-up by `≥ 0.15`; otherwise list the top 3 and match none.
- Loads the invoice ledger and the amount already billed against the matched PO (non-rejected invoices).

## 7 Rules (`s7_rules.py`)
- Fifteen pure rule functions (R09–R23), see [RULES.md](RULES.md). A rule that raises becomes a WARN
  "Rule could not be evaluated" finding; it never crashes the run.

## 8 Decide & explain (`s8_decide.py`)
- **Decide:** deterministic matrix (any BLOCK → REJECT; any WARN → REVIEW; inferred/no PO or processing
  error → REVIEW; else APPROVE). Confidence = min(critical-field confidence, PO match score).
- **Explain:** a template explanation is always built from findings. If enabled, an LLM rewrites it from the
  findings only; the text is discarded if it contains any number not present in those facts.
