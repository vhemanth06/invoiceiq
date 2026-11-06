# Rules

All thresholds live in `data/rules.yaml` and are editable on the Master Data page. Rules are re-read on
every run.

## Thresholds and rationale

| Setting | Default | Why |
|---|---|---|
| `tolerances.amount_pct` / `amount_abs_cap` | 2% / ₹5,000 | Absorbs rounding and freight differences; the cap stops 2% of a large PO becoming a large leak |
| `tolerances.line_price_pct` | 1% | Negotiated unit prices should not drift |
| `tolerances.arithmetic_rounding` | ₹1 | Paise rounding on sums |
| `tolerances.cumulative_block_pct` | 10% | Over-billing a PO by more than this is refused outright |
| `confidence.min_field_confidence` | 0.80 | Below this a human checks the field |
| `confidence.critical_fields` | vendor, invoice no., date, total | Fields a payment cannot be made without |
| `confidence.min_po_match_score` / `po_match_margin` | 0.75 / 0.15 | Inferred match must be good and clearly the best |
| `duplicates.date_window_days` / `amount_pct` / `invoice_no_similarity` | 15 / 0.5% / 85 | Fuzzy duplicate signal |
| `dates.max_age_days` / `allow_future_days` | 180 / 3 | Stale or post-dated invoices |
| `dates.reference_date` | null (today) | Freeze "today" for tests and demos |
| `approval.auto_approve_limit` | ₹3,00,000 | Segregation of duties |

## Catalogue

| ID | Rule | Fails as | Stage |
|---|---|---|---|
| R00 | Document readable | BLOCK | Ingest |
| R01 | Critical fields present | WARN (BLOCK if total missing) | Validate |
| R02 | Critical-field confidence ≥ threshold | WARN | Validate |
| R03 | qty × rate = amount (±₹1) | WARN | Validate |
| R04 | Σ lines = subtotal | WARN | Validate |
| R05 | Subtotal + tax = total (tax-inclusive aware) | WARN | Validate |
| R06 | GST split matches place of supply | WARN | Validate |
| R08 | Date not > 3 days future, not > 180 days old | WARN | Validate |
| R09 | Vendor in master and approved | BLOCK | Rules |
| R10 | GSTIN valid and matches master | WARN | Rules |
| R11 | Bank account matches master | WARN (always escalate) | Rules |
| R12 | PO found / inferred / missing | WARN unless explicit | Rules |
| R13 | PO is OPEN | BLOCK | Rules |
| R14 | PO vendor = invoice vendor | BLOCK | Rules |
| R15 | Invoice ≤ PO remaining balance + tolerance | WARN | Rules |
| R16 | Cumulative billing ≤ PO total + tolerance | WARN; BLOCK if > 10% over | Rules |
| R17 | Partial invoice only if PO allows it | WARN | Rules |
| R18 | Unit prices within 1% of PO (tax-inclusive adjusted) | WARN | Rules |
| R19 | Exact duplicate (vendor + normalised invoice no., or same file) | BLOCK | Rules |
| R20 | Probable duplicate (same vendor, amount ±0.5%, and close date / similar no. / identical lines) | WARN | Rules |
| R21 | Tax-inclusive pricing reconciled to PO | INFO if explained, WARN if not | Rules |
| R22 | Total ≤ auto-approval limit | WARN | Rules |
| R24 | Invoice currency is INR (POs and tolerances are INR) | WARN | Rules |
| R23 | Document is a payable invoice | WARN | Rules |

Notes:
- Only APPROVE and REVIEW invoices count against a PO balance and for duplicate checks; REJECTED ones do not.
  Reviewer overrides update the ledger, so overriding to REJECT frees the PO balance.
- An explicit PO reference must match exactly when it states a year (`PO-2025-1052` is not `PO-2026-1052`); a
  bare number (`#1052`) maps to the single PO ending in it.
- A reviewer approving a document that had no ledger row (e.g. misclassified as a credit note) creates one,
  so it still counts for duplicates and PO balance.
- R15–R17 and R19–R21 are skipped for credit notes and other non-invoices (R23 already routes them).

## Decision matrix

```python
if any failed BLOCK:                       REJECT
elif any failed WARN:                      REVIEW
elif match != explicit or processing error: REVIEW   # never auto-approve an inferred match
else:                                      APPROVE
```

## Changing rules

Edit `data/rules.yaml` or use **Master Data → Rules**. The next run uses the new values. Example for the
demo: lower `approval.auto_approve_limit` to 100000 and rerun the Acme happy path: APPROVE becomes REVIEW.
