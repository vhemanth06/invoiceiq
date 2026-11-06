# Demo script (10–12 minutes)

**Before:** Master Data → Reset demo data; check API keys (sidebar shows ready / not set per provider); pre-warm the
cache by running all samples once with a live provider; keep a terminal with `pytest` ready.

1. **Frame it (1 min).** "AP must never pay the wrong amount, the wrong vendor, or the same invoice twice,
   without slowing down the 80% that are fine. The LLM reads, deterministic rules decide, every step is visible."
2. **Happy path (1 min).** Process Invoice → sample "Happy path – Acme INV-1042" → eight stages go green →
   APPROVE. Expand Extract (provider, confidence) and Match PO.
3. **Edge 3, tax-inclusive (1½ min).** Deccan sample → APPROVE with the Info "Tax-inclusive pricing reconciled" pill.
4. **Edge 1, split invoices (2 min).** Run the three BrightLine milestones; the third is REVIEW (+8.4%).
   Dashboard → PO utilisation: PO-2026-1052 is red.
5. **Edge 2, disguised duplicate (1½ min).** `INV/1042-R` scan → REJECT. Findings tab → "Open original invoice run".
6. **Edge 4, scanned, no PO (2 min).** Vision route, total confidence 0.55 highlighted amber, inferred
   PO-2026-1071 with candidate scores, and why it is REVIEW, not APPROVE.
7. **Change a rule live (1 min).** Master Data → Rules → lower the auto-approval limit to ₹1,00,000 → save →
   rerun the Acme happy path (₹1,18,000): APPROVE becomes REVIEW ("Above auto-approval limit"). Set it back.
8. **Review queue (1 min).** Dashboard → Review queue → override the bank-change invoice with a comment →
   Run Detail shows the Override event.
9. **Close (1 min).** `pytest` passing; architecture; path to production (queue, Postgres, ERP integration,
   vendor templates, learning thresholds from overrides).
