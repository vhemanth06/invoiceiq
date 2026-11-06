# Design decisions

1. **LLM reads, rules decide.** Extraction and prose come from an LLM; every check and the decision are
   deterministic Python. Decisions are repeatable, unit-tested and explainable to an auditor.
2. **Never auto-approve an inferred PO match.** A wrong payment costs far more than a two-minute human check.
3. **Confidence is verified, not self-reported.** Totals inconsistent with lines + tax have their confidence
   capped; a misread total that is visibly correct on the page is blamed on extraction, not the vendor.
4. **Fail soft to REVIEW.** Any processing error routes to a human. "I couldn't check this" never becomes an
   approval. Unreadable documents are rejected back to the vendor.
5. **Free-tier LLMs with a fallback chain and a cache.** Gemini (vision) → Groq (text) → Ollama (local) →
   OCR. Model names live in `.env`. Cached extractions keep a live demo alive without Wi-Fi or quota and are
   labelled "cached" in the UI.
6. **An offline `sample_truth` provider for the bundled samples.** It returns the generator's ground truth
   only for files whose SHA-256 it knows, so tests and keyless demos run deterministically. It is labelled
   as such everywhere and cannot read other documents.
7. **Explanations are guarded.** The LLM sees only findings, and its output is rejected if it introduces any
   number not in those findings; the template explanation is always available.
8. **SQLite + Streamlit.** Right for a prototype. The path to production is Postgres, an API (FastAPI) and a
   queue in front of the same `core/` package.
9. **Synthetic data only.** Free-tier LLM terms may allow providers to use inputs; no real invoices.
10. **Running ledger counts only APPROVE and REVIEW.** Rejected invoices never consume PO budget or block a
    legitimate resubmission; reviewer overrides update the ledger.
