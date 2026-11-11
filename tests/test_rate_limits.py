"""Free-tier quota handling: fail fast on daily quota, skip the blocked provider, cache explanations."""
import time

import pytest

from core.llm import base, router
from core.llm.base import Payload, Provider, RateLimited, retry_after, with_backoff
from core.models import ExtractedInvoice

DAILY_429 = ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota ... "
             "Generate content requests per day limit exceeded on Free Tier.\nPlease retry in 1h59m15.592689027s.'}}")


def test_retry_after_parses_both_formats():
    assert retry_after(DAILY_429) == pytest.approx(7155.59, abs=0.01)
    assert retry_after("""{'retryDelay': '38s'}""") == 38
    assert retry_after("boom") is None


def test_daily_quota_fails_fast_without_sleeping(monkeypatch):
    sleeps, calls = [], []
    monkeypatch.setattr(base.time, "sleep", sleeps.append)

    def quota():
        calls.append(1)
        raise RuntimeError(DAILY_429)
    with pytest.raises(RateLimited) as e:
        with_backoff(quota)
    assert len(calls) == 1 and not sleeps
    assert "daily free-tier quota" in str(e.value) and e.value.until > time.time() + 7000


def test_short_rate_limit_waits_server_delay(monkeypatch):
    sleeps = []
    monkeypatch.setattr(base.time, "sleep", sleeps.append)
    n = []

    def flaky():
        n.append(1)
        if len(n) < 2:
            raise RuntimeError("429 rate limit, retryDelay': '7s'")
        return "ok"
    assert with_backoff(flaky) == "ok" and sleeps == [7]


def test_no_repair_call_after_quota_error():
    class P(Provider):
        calls = 0

        def complete(self, prompt, images, history):
            self.calls += 1
            raise RuntimeError(DAILY_429)
    p = P()
    with pytest.raises(RateLimited):
        p.extract(Payload("h", "text", text="x"))
    assert p.calls == 1


def test_router_reports_quota_and_skips_provider_next_time(monkeypatch):
    calls = []

    class Gem(Provider):
        name, supports_vision = "gem", True

        def complete(self, prompt, images, history):
            calls.append(1)
            raise RuntimeError(DAILY_429)
    monkeypatch.setattr(router, "PROVIDERS", {"gem": Gem})
    monkeypatch.setattr(router, "_blocked", {})
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "gem")
    with pytest.raises(router.ExtractionFailed) as e1:
        router.extract(Payload("h1", "text", text="x"), use_cache=False)
    assert "daily free-tier quota" in " ".join(e1.value.attempts)
    with pytest.raises(router.ExtractionFailed) as e2:
        router.extract(Payload("h2", "text", text="x"), use_cache=False)
    assert len(calls) == 1 and "skipped" in " ".join(e2.value.attempts)   # no second wasted request


def test_explanations_are_cached(monkeypatch, tmp_path):
    from core.llm import cache
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    calls = []

    class Txt(Provider):
        name, model = "txt", "m1"

        def complete(self, prompt, images, history):
            calls.append(1)
            return '{"headline": "h"}'
    monkeypatch.setattr(router, "PROVIDERS", {"txt": Txt})
    monkeypatch.setattr(router, "_blocked", {})
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "txt")
    assert router.explain("same facts") == router.explain("same facts")
    assert len(calls) == 1


def test_extract_stage_says_why(monkeypatch, make_ctx):
    from core.stages import s3_extract

    def fail(payload):
        raise router.ExtractionFailed("x", ["groq: daily free-tier quota used up (retry in 1h59m)"])
    monkeypatch.setattr(router, "extract", fail)
    ctx = make_ctx()
    ctx.route = "text"
    res = s3_extract.run(ctx)
    assert "daily free-tier quota" in res.summary
