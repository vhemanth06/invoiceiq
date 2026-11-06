"""Decision matrix over every severity combination, and the explanation number guardrail."""
import itertools

import pytest

from core.models import DecisionType, Finding, Severity
from core.stages.s8_decide import decide, numbers_grounded


def F(sev, passed):
    return Finding(rule_id="RX", stage="t", severity=sev, passed=passed, title="t")


@pytest.mark.parametrize("combo", list(itertools.product([None, "info", "warn", "block"], repeat=2)))
@pytest.mark.parametrize("method", ["explicit", "inferred", "none"])
def test_matrix(combo, method, make_ctx):
    findings = [F(Severity(s), passed=(s == "info")) for s in combo if s]
    ctx = make_ctx(match_method=method)
    got = decide(findings, ctx)
    if "block" in combo:
        assert got == DecisionType.REJECT
    elif "warn" in combo or method != "explicit":
        assert got == DecisionType.REVIEW
    else:
        assert got == DecisionType.APPROVE


def test_processing_error_never_approves(make_ctx):
    ctx = make_ctx(match_method="explicit", processing_errors=[("Extract", "boom")])
    assert decide([], ctx) == DecisionType.REVIEW


def test_number_guardrail():
    facts = '{"detail": "3 invoices total Rs 6,39,560.00 vs PO Rs 590,000.00 (+8.4%)"}'
    assert numbers_grounded("Billing of Rs 639,560 exceeds the PO of 5,90,000 by 8.4%.", facts)
    assert not numbers_grounded("Over-billed by Rs 42,000.", facts)
