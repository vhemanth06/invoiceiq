"""Prompts. Bump PROMPT_VERSION whenever a prompt changes so the cache is invalidated."""
import json

from core.models import ExtractedInvoice

PROMPT_VERSION = "v1"

EXTRACTION_PROMPT = """You are an accounts-payable data extraction engine.
Extract the invoice into JSON matching the schema below. Rules:
- Copy values exactly as printed; do not calculate or guess.
- Every scalar field is an object {"value", "confidence" (0-1), "source"}; source is "text_layer" for text input
  and "vision" for images.
- If a field is absent, set value=null, source="missing", confidence=0.
- If a field is partly unreadable, give your best reading with confidence < 0.7.
- Line item numbers (quantity, unit_price, amount) are plain numbers without currency symbols or commas.
- If line prices include tax, set tax.tax_inclusive=true. Tax amounts are plain numbers.
- A single lump-sum line with no quantity/rate (e.g. "services as per agreement") has is_bundled=true.
- Treat "PO", "P.O.", "Order Ref", "Buyer's Order No.", "Your Ref" as possible PO references.
- document_type is one of: invoice, credit_note, quotation, statement.
- bank_account_last4 is the last 4 digits of the payee bank account.
Return JSON only.

JSON schema:
""" + json.dumps(ExtractedInvoice.model_json_schema())

REPAIR_PROMPT = "Your previous JSON failed validation with this error:\n{error}\nReturn corrected JSON only."

EXPLANATION_PROMPT = """Write an AP decision note for a busy reviewer. Use ONLY the facts below.
Decision: {outcome}
Facts (findings with evidence): {facts}
Return JSON: {{"headline": "<= 15 words", "explanation": "3-5 sentences citing exact amounts",
"recommended_action": "1 sentence"}}. Do not introduce any number not in the facts."""
