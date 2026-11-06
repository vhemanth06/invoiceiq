import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["LLM_PROVIDER_ORDER"] = "sample_truth"   # deterministic, no network
os.environ["USE_LLM_EXPLANATIONS"] = "false"
os.environ["USE_LLM_CACHE"] = "false"

from datetime import date  # noqa: E402

from core import config  # noqa: E402
from core.context import RunContext  # noqa: E402
from core.models import ExtractedInvoice, LineItem, TaxBreakdown  # noqa: E402
from core.llm import router  # noqa: E402
from core.llm.base import Provider, ProviderError  # noqa: E402

TRUTH_DIR = config.SAMPLES_DIR / "truth"


class SampleTruthProvider(Provider):
    """Test-only fake: returns the generator's ground truth for the bundled sample PDFs."""
    name, supports_vision, model = "sample_truth", True, "ground-truth"

    def extract(self, payload):
        name = json.loads((TRUTH_DIR / "index.json").read_text()).get(payload.file_hash)
        if not name:
            raise ProviderError("not a bundled sample")
        return ExtractedInvoice.model_validate_json((TRUTH_DIR / name).read_text())

    def text(self, prompt):
        raise ProviderError("sample_truth cannot write explanations")


router.PROVIDERS["sample_truth"] = SampleTruthProvider

TODAY = date(2026, 11, 6)


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls a real LLM API (skipped unless RUN_LIVE=1)")


@pytest.fixture
def rules():
    r = config.load_rules()
    r["dates"]["reference_date"] = TODAY.isoformat()
    return r


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("INVOICEIQ_DB", str(tmp_path / "test.db"))
    from core.db.seed import seed
    seed()
    return tmp_path


def conf(v, c=0.97):
    return {"value": v, "confidence": c, "source": "text_layer"}


@pytest.fixture
def make_ctx(rules):
    """Build a RunContext by hand: no PDF, no LLM. Pass overrides for norm/vendor/po/etc."""
    def _make(lines=((None, None, 100000.0),), tax=None, total=118000.0, subtotal=100000.0, **kw):
        inv = ExtractedInvoice(
            vendor_name=conf("Acme Industrial Supplies Pvt Ltd"), invoice_number=conf("INV-1"),
            invoice_date=conf("01/11/2026"), total=conf(total), subtotal=conf(subtotal),
            line_items=[LineItem(description=d or "Item", quantity=q, unit_price=None if q is None else a / q,
                                 amount=a) for d, q, a in lines],
            tax=tax or TaxBreakdown(cgst=9000, sgst=9000, rate_percent=18))
        ctx = RunContext.new(b"%PDF-test", "t.pdf", "test", rules, TODAY)
        ctx.extraction = inv
        ctx.norm = {"total": total, "subtotal": subtotal, "tax_total": inv.tax.total,
                    "tax_inclusive": inv.tax.tax_inclusive, "invoice_date": date(2026, 11, 1),
                    "invoice_number": "INV-1", "invoice_key": "1", "gstin": "36AABCA1234F1Z5",
                    "gstin_valid": True, "bank_last4": "4521", "lines_sig": "x"}
        ctx.norm.update(kw.pop("norm", {}))
        for k, v in kw.items():
            setattr(ctx, k, v)
        return ctx
    return _make


ACME = {"vendor_id": "V001", "name": "Acme Industrial Supplies Pvt Ltd", "aliases": "Acme Industrial",
        "gstin": "36AABCA1234F1Z5", "state": "Telangana", "approved": True, "bank_last4": "4521",
        "payment_terms_days": 30}


def po(**kw):
    base = {"po_number": "PO-2026-1041", "vendor_id": "V001", "po_date": date(2026, 9, 2), "status": "OPEN",
            "subtotal": 100000.0, "tax_rate": 18.0, "tax_mode": "exclusive", "total": 118000.0,
            "allows_partial": False}
    base.update(kw)
    return base
