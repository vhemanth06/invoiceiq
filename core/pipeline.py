"""Pipeline orchestrator. UI-free: the Streamlit app, CLI, email poller and tests all call run_pipeline().

Each stage is `run(ctx) -> StageResult`. Every stage emits a running and a finished StageEvent,
which is stored in SQLite and passed to `on_event` for the live view. A stage that raises does
not crash the run: the error is recorded and the decision becomes REVIEW (never APPROVE).
"""
from __future__ import annotations

from time import perf_counter
from typing import Callable

from loguru import logger

from core import config
from core.context import RunContext
from core.db import repo
from core.db.seed import ensure_seeded
from core.events import StageEvent, StageResult, StageStatus
from core.stages import (s1_ingest, s2_classify, s3_extract, s4_normalize, s5_validate, s6_match, s7_rules,
                         s8_decide)

STAGES = [s1_ingest, s2_classify, s3_extract, s4_normalize, s5_validate, s6_match, s7_rules, s8_decide]
STAGE_NAMES = [s.NAME for s in STAGES]


def _emit(ev: StageEvent, ctx: RunContext, on_event: Callable) -> None:
    ev.seq = len(ctx.events) + 1
    ctx.events.append(ev)
    repo.add_event(ctx.run_id, ev)
    try:
        on_event(ev)
    except Exception as e:  # a UI glitch must never break processing
        logger.warning(f"on_event failed: {e}")


def run_pipeline(file_bytes: bytes, file_name: str, source: str = "upload",
                 on_event: Callable[[StageEvent], None] = lambda e: None, rules: dict | None = None) -> RunContext:
    ensure_seeded()
    rules = rules or config.load_rules()
    ctx = RunContext.new(file_bytes, file_name, source, rules, config.reference_date(rules))
    repo.create_run(ctx)
    t_run = perf_counter()
    halted = False
    for stage in STAGES:
        if halted and stage is not s8_decide:  # the decision stage always runs
            _emit(StageEvent(stage.NAME, StageStatus.SKIPPED, "Skipped (earlier stage halted)"), ctx, on_event)
            continue
        _emit(StageEvent(stage.NAME, StageStatus.RUNNING, "Running..."), ctx, on_event)
        t0 = perf_counter()
        try:
            result = stage.run(ctx)
        except Exception as e:
            logger.exception(f"stage {stage.NAME} failed")
            ctx.processing_errors.append((stage.NAME, f"{type(e).__name__}: {e}"))
            result = StageResult.error(e)
            if stage is s8_decide:
                raise
            result.halt = stage in (s1_ingest, s2_classify, s3_extract, s4_normalize)  # later stages need these
        _emit(StageEvent(stage.NAME, result.status, result.summary, result.details,
                         duration_ms=int((perf_counter() - t0) * 1000)), ctx, on_event)
        halted = halted or result.halt
    repo.finish_run(ctx, ctx.norm.get("file_path", ""), int((perf_counter() - t_run) * 1000))
    return ctx
