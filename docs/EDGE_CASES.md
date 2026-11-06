# Edge cases

Run them with **Process Invoice → Reset & run all samples in order** or `python cli.py --all-samples --reset`.
Order matters: cases 1 and 2 depend on earlier runs in the ledger.

## 1. Split invoicing that silently over-bills a PO
- **Story:** BrightLine IT has PO-2026-1052 for ₹5,00,000 + 18% IGST (₹5,90,000), partial invoicing allowed.
  Three milestone invoices: ₹2,36,000, ₹2,12,400, ₹1,91,160.
- **Why naive automation fails:** each invoice alone is below the PO value.
- **Handling:** the invoice ledger keeps a running total per PO (non-rejected invoices only). R16 adds the
  new invoice to prior billing: ₹6,39,560 vs ₹5,90,000 = **+8.4%**, above tolerance but under the 10%
  hard-block line. R15 (remaining balance) and R18 (milestone 3 price above PO line) also fire.
- **Expected:** milestones 1 and 2 APPROVE; milestone 3 **REVIEW**, "request a credit note for ₹49,560 or a PO
  amendment". The dashboard's PO utilisation bar for PO-2026-1052 turns red.
- Samples: `02_`, `03_`, `04_split_brightline_m*.pdf`.

## 2. Disguised duplicate (resubmission)
- **Story:** Acme's INV-1042 (₹1,18,000) is approved. Three weeks later a re-scanned "reminder copy"
  `INV/1042-R` arrives with a new date.
- **Why naive automation fails:** the invoice number string differs and the file hash differs (re-scan).
- **Handling:** the normalised key strips separators, the `INV` prefix and resubmission suffixes
  (`-R`, `REV`, `COPY`, `DUPLICATE`): both become `1042`. R19 matches vendor + key → BLOCK, with a link to
  the original run. R20 covers fuzzier cases (amount ±0.5% and close date / similar number / identical lines).
- **Expected:** **REJECT** (exact key match); a fuzzy-only match would be REVIEW.
- Sample: `05_duplicate_acme_inv1042R_scanned.pdf` (image-only PDF, vision route).

## 3. Tax-inclusive vs tax-exclusive (a false alarm the system must not raise)
- **Story:** Deccan Packaging's PO is ₹84,000 + 12% GST (₹94,080). Their invoice prices include GST: lines sum
  to ₹94,080 with a footnote "prices inclusive of GST @12%".
- **Why naive automation fails:** invoice subtotal ₹94,080 vs PO subtotal ₹84,000 looks like a 12% overcharge.
- **Handling:** extraction sets `tax_inclusive=true`; R05 checks lines = total instead of subtotal + tax; R18
  divides unit prices by 1.12 before comparing; R21 computes ₹94,080 / 1.12 = ₹84,000 = PO and records an
  **INFO** finding. R06 still verifies the intra-state split (CGST 6% = SGST 6%).
- **Expected:** **APPROVE**, with the reconciliation in the explanation. If the inclusive total were also 4%
  high, R21 would report the unexplained ₹3,360 separately → REVIEW (unit test
  `test_tax_inclusive_reconciled_and_partly_unexplained`).
- Sample: `06_tax_inclusive_deccan.pdf`.

## 4. Scanned invoice, no PO reference, partly unreadable
- **Story:** Nimbus Cloud Hosting sends a rotated, noisy scan with a stain over the total and no PO number.
- **Why naive automation fails:** three problems at once: vision extraction, PO inference, and an uncertain
  critical field.
- **Handling:** Classify sees 0 text characters → vision route. The total is read with confidence 0.55.
  Match PO scores Nimbus's open POs: PO-2026-1071 scores 0.93, PO-2026-1075 0.33 → inferred match.
  R02 flags the low-confidence total; R12 flags the inferred PO; the matrix never auto-approves an inferred match.
- **Expected:** **REVIEW**: "Likely matches PO-2026-1071 (93% match score) … verify the total read as ₹70,800."
- Sample: `07_scanned_nopo_nimbus.pdf`.

## Bonus scenarios
| Sample | Scenario | Outcome |
|---|---|---|
| `08_bank_change_acme.pdf` | Bank account ending 9931 vs 4521 on file (payment-diversion fraud pattern) | REVIEW (R11) |
| `09_unapproved_orbit.pdf` | Vendor with KYC pending, PO reference does not exist | REJECT (R09) |
| `10_bundled_amc.pdf` | Single lump-sum "AMC as per agreement" line, no qty/rate | APPROVE |
| `11_credit_note_acme.pdf` | Credit note sent to AP | REVIEW (R23), kept out of the ledger |
| `01_happy_acme_inv1042.pdf` | Clean invoice, ambiguous date `05/10/2026` read as DD/MM | APPROVE |
