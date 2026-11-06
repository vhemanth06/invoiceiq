# InvoiceIQ

**From invoice PDF to a reasoned, auditable Approve / Review / Reject decision.**

InvoiceIQ takes a vendor invoice PDF (digital or scanned), extracts its data with a free LLM, validates it,
matches it to a purchase order, applies procurement rules, and produces an **APPROVE / REVIEW / REJECT**
decision with a stage-by-stage explanation. A Streamlit app shows each run live, keeps a history dashboard
with a human review queue, and replays any past run.

> **The LLM reads; the rules decide.** The LLM only reads messy documents and writes prose. Every check and
> the final decision are deterministic Python, so they are testable, repeatable and auditable.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # optional: add free Gemini / Groq keys
python -m core.db.seed      # load vendors & POs
python samples/generate_samples.py
streamlit run Home.py
```

Add `GROQ_API_KEY` (and optionally `GEMINI_API_KEY`) to `.env`. Groq reads text PDFs with
`GROQ_MODEL` and scanned PDFs with `GROQ_VISION_MODEL`; Gemini is the fallback.

Terminal only:

```bash
python cli.py --all-samples --reset                  # run the manifest in order, check expectations
python cli.py samples/invoices/07_scanned_nopo_nimbus.pdf
pytest                                               # 119 tests; add RUN_LIVE=1 for a real Gemini call
```

## Features

- **8-stage pipeline**: Ingest → Classify → Extract → Normalise → Validate → Match PO → Rules → Decide.
  Each stage emits events, shown live and stored in SQLite for replay.
- **Messy input**: text vs scanned detection, multimodal extraction, Indian amount/date formats, per-field
  confidence that is cross-checked against arithmetic rather than trusted.
- **Procurement logic**: vendor master and approval, GSTIN and bank checks, explicit and inferred PO matching,
  amount tolerance, running PO ledger, duplicate detection, tax-inclusive reconciliation, authority limit.
- **Edge cases**: split invoicing that over-bills a PO, disguised duplicate resubmission, tax-inclusive
  pricing (a false alarm it must not raise), scanned invoice with no PO and an unreadable total.
- **UI**: live run view, dashboard (KPIs, charts, PO utilisation, runs table), review queue with
  comment-required overrides, run replay, editable master data and rule thresholds, "Reset demo data".
- **Resilience**: provider fallback chain (Groq → Gemini → OCR), disk cache for demo safety,
  fail-soft to REVIEW, template explanations with a numbers guardrail when the LLM is unavailable.

## Docs

| Doc | What it covers |
|---|---|
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Modules, data flow, event model |
| [PIPELINE](docs/PIPELINE.md) | Every stage: inputs, outputs, failure behaviour |
| [RULES](docs/RULES.md) | Rule catalogue, thresholds, decision matrix |
| [EDGE_CASES](docs/EDGE_CASES.md) | The four edge cases and the bonus scenarios |
| [DESIGN_DECISIONS](docs/DESIGN_DECISIONS.md) | Why it is built this way |
| [DEMO_SCRIPT](docs/DEMO_SCRIPT.md) | 10-minute walkthrough |

## Known limitations

- Without an LLM key, only the bundled samples can be extracted; other uploads become REVIEW
  ("manual entry needed"). Tesseract OCR is used as a last resort only if the binary is installed.
- Field-level highlighting on the page image (bounding boxes) is not implemented.
- SQLite + Streamlit is a prototype stack; production would be Postgres + an API + a queue.
- Saving rules from the Setup page rewrites `data/rules.yaml` without its comments
  (thresholds are documented in docs/RULES.md).
- Sample data uses fixed 2026 dates; tests freeze "today" at 2026-11-06 via `dates.reference_date`.
