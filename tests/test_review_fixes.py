"""Regression tests for the final-review findings (each failed before its fix)."""
import pytest

from core.llm import base, router
from core.llm.base import Payload, Provider, ProviderError
from core.models import ExtractedInvoice
from core.stages import s7_rules as R
from core.stages.s2_classify import detect_kind
from core.stages.s4_normalize import po_key
from tests.conftest import po


def test_foreign_currency_flagged(make_ctx, rules):
    f = R.currency_check(make_ctx(norm={"currency": "USD"}), rules)
    assert not f.passed and f.severity.value == "warn"
    assert R.currency_check(make_ctx(norm={"currency": "INR"}), rules).passed


def test_wrong_year_po_is_not_explicit():
    known = ["PO-2026-1052"]
    assert po_key("PO-2025-1052", known) == "PO-2025-1052"   # unknown, not silently remapped
    assert po_key("PO 1052", known) == "PO-2026-1052"         # no year given: trailing digits still map


def test_terms_mentioning_credit_note_stay_invoice():
    assert detect_kind("TAX INVOICE\nInvoice No. 55\nTerms: any credit note must quote this invoice.") == "invoice"
    assert detect_kind("CREDIT NOTE CN-1\nagainst INV-1") == "credit_note"


@pytest.mark.parametrize("raw", ["Invoice", "tax_invoice", " TAX INVOICE "])
def test_llm_document_type_normalised(raw):
    from core.stages.s3_extract import normalise_kind
    assert normalise_kind(raw) == "invoice"
    assert normalise_kind("Credit Note") == "credit_note"


def test_override_approve_creates_missing_ledger_row(fresh_db):
    """A non-invoice-looking doc approved by a human must still count for duplicates and PO balance."""
    from core.db import repo
    from core.db.schema import ExtractedRecord, Run, get_engine
    from sqlmodel import Session
    with Session(get_engine()) as s:
        s.add(Run(id="r1", outcome="REVIEW", original_outcome="REVIEW", vendor_id="V001", po_number="PO-2026-1041",
                  file_hash="h", total=118000))
        s.add(ExtractedRecord(run_id="r1", normalized_json='{"invoice_number": "INV-9", "invoice_key": "9", '
                                                          '"invoice_date": "2026-10-05", "total": 118000, "lines_sig": "x"}'))
        s.commit()
    repo.override("r1", "APPROVE", "checked")
    [row] = [l for l in repo.ledger() if l["run_id"] == "r1"]
    assert row["outcome"] == "APPROVE" and row["invoice_no_key"] == "9" and row["total"] == 118000


def test_override_reject_frees_po_balance(fresh_db):
    from core.config import SAMPLES_DIR
    from core.db import repo
    from core.pipeline import run_pipeline
    from core.stages.s6_match import billed_against
    ctx = run_pipeline((SAMPLES_DIR / "invoices" / "08_bank_change_acme.pdf").read_bytes(), "08", "test")
    assert billed_against("PO-2026-1044", repo.ledger()) == 59000
    repo.override(ctx.run_id, "REJECT", "fraud")
    assert billed_against("PO-2026-1044", repo.ledger()) == 0


def test_backoff_does_not_retry_non_rate_errors(monkeypatch):
    sleeps = []
    monkeypatch.setattr(base.time, "sleep", sleeps.append)
    calls = []

    def fail():
        calls.append(1)
        raise RuntimeError("models/x is not supported for generateContent")
    with pytest.raises(RuntimeError):
        base.with_backoff(fail)
    assert len(calls) == 1 and not sleeps


def test_repair_runs_when_first_call_raises():
    class P(Provider):
        n = 0

        def complete(self, prompt, images, history):
            self.n += 1
            if self.n == 1:
                raise RuntimeError("Failed to generate JSON")
            return ExtractedInvoice().model_dump_json()
    p = P()
    assert isinstance(p.extract(Payload("h", "text", text="x")), ExtractedInvoice) and p.n == 2


def test_router_falls_back_and_skips_text_only_for_vision(monkeypatch):
    class Bad(Provider):
        name, supports_vision = "bad", True

        def extract(self, payload):
            raise ProviderError("down")

    class TextOnly(Provider):
        name, supports_vision = "text", False

        def extract(self, payload):
            raise AssertionError("text-only provider must not get a scan")

    class Good(Provider):
        name, supports_vision = "good", True

        def extract(self, payload):
            return ExtractedInvoice()
    monkeypatch.setattr(router, "PROVIDERS", {"bad": Bad, "text": TextOnly, "good": Good})
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "bad,text,good")
    _, used, attempts = router.extract(Payload("h", "vision", images=[b""]), use_cache=False)
    assert used == "good" and any("skipped" in a for a in attempts)


def test_run_detail_handles_unfinished_run():
    from ui.components import decision_complete
    assert not decision_complete({"decision": {}})
    assert decision_complete({"decision": {"outcome": "APPROVE"}})
