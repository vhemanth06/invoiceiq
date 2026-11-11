"""Golden end-to-end tests: every manifest sample, in order, on a fresh DB.

Extraction uses the offline `sample_truth` provider so these are deterministic and free.
"""
import os
import subprocess
import sys

import pytest
import yaml

from core import config
from core.pipeline import run_pipeline

MANIFEST = [m for m in yaml.safe_load((config.SAMPLES_DIR / "manifest.yaml").read_text()) if m.get("golden", True)]


@pytest.fixture(scope="module")
def results(tmp_path_factory, rules_module):
    if not (config.SAMPLES_DIR / "truth" / "index.json").exists():
        subprocess.run([sys.executable, str(config.SAMPLES_DIR / "generate_samples.py")], check=True)
    os.environ["INVOICEIQ_DB"] = str(tmp_path_factory.mktemp("db") / "golden.db")
    from core.db.seed import seed
    seed()
    out = {}
    for item in MANIFEST:
        path = config.SAMPLES_DIR / "invoices" / item["file"]
        out[item["file"]] = run_pipeline(path.read_bytes(), path.name, "sample", rules=rules_module)
    yield out
    del os.environ["INVOICEIQ_DB"]


@pytest.fixture(scope="module")
def rules_module():
    r = config.load_rules()
    r["dates"]["reference_date"] = "2026-11-06"
    return r


@pytest.mark.parametrize("item", MANIFEST, ids=[m["file"] for m in MANIFEST])
def test_sample(item, results):
    ctx = results[item["file"]]
    fired = {f.rule_id for f in ctx.findings if not f.passed or f.severity.value == "info"}
    assert ctx.decision.outcome.value == item["expected"], ctx.decision.explanation
    assert set(item.get("must_include_rules", [])) <= fired
    assert not ctx.processing_errors
    assert len([e for e in ctx.events if e.status.value != "running"]) == 8   # every stage reported


def test_duplicate_links_original(results):
    dup = next(f for f in results["05_duplicate_acme_inv1042R_scanned.pdf"].findings
               if f.rule_id == "R19_EXACT_DUPLICATE")
    assert dup.evidence["original_run"] == results["01_happy_acme_inv1042.pdf"].run_id


def test_split_invoice_overbilling_amount(results):
    f = next(f for f in results["04_split_brightline_m3.pdf"].findings if f.rule_id == "R16_CUMULATIVE_PO")
    assert f.evidence["over_pct"] == 8.4 and f.evidence["prior_invoices"] == 2


def test_scanned_routed_to_vision(results):
    assert results["07_scanned_nopo_nimbus.pdf"].route == "vision"
    assert results["07_scanned_nopo_nimbus.pdf"].match_method == "inferred"


def test_unknown_document_falls_back_to_review(fresh_db):
    """A PDF no provider can read (offline) must become REVIEW, never APPROVE."""
    import pymupdf
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Invoice No 77 Total 1000 GST " * 20)
    ctx = run_pipeline(doc.tobytes(), "unknown.pdf", "test")
    assert ctx.decision.outcome.value == "REVIEW" and ctx.processing_errors


def test_not_a_pdf_rejected(fresh_db):
    ctx = run_pipeline(b"hello, not a pdf", "x.txt", "test")
    assert ctx.decision.outcome.value == "REJECT"
    assert ctx.findings[0].rule_id == "R00_READABLE"


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 and GROQ_API_KEY to run")
def test_live_groq_extraction():
    from core.llm.base import Payload
    from core.llm.groq_client import GroqProvider
    import pymupdf
    path = config.SAMPLES_DIR / "invoices" / "01_happy_acme_inv1042.pdf"
    text = pymupdf.open(path)[0].get_text()
    inv = GroqProvider().extract(Payload("live", "text", text=text))
    assert "1042" in str(inv.invoice_number.value)
