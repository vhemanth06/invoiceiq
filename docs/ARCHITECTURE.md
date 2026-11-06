# Architecture

```
                    ┌─────────────────────────────────────────────┐
  PDF upload ──────▶│                                             │
  Sample library ──▶│      PIPELINE ORCHESTRATOR (core/pipeline)  │──▶ Decision + explanation
  Email poller ────▶│   runs stages in order, emits StageEvents,  │
  CLI / tests ─────▶│   never crashes a run                       │
                    └───────────────┬─────────────────────────────┘
                                    │ events
        ┌───────────────────────────┼──────────────────────────────┐
        ▼                           ▼                              ▼
 ┌──────────────┐          ┌──────────────────┐           ┌──────────────────────┐
 │ Streamlit UI │          │ SQLite: runs,    │           │ LLM layer            │
 │ live stage   │          │ events, findings,│           │ Gemini → Groq →      │
 │ cards        │          │ ledger, masters  │           │ Ollama → sample_truth│
 └──────────────┘          └──────────────────┘           │ + OCR + disk cache   │
                                                          └──────────────────────┘
```

## Modules

| Path | Role |
|---|---|
| `core/pipeline.py` | `run_pipeline(file_bytes, file_name, source, on_event, rules)`: the only entry point |
| `core/context.py` | `RunContext`: everything a run has produced so far |
| `core/events.py` | `StageEvent`, `StageResult`, `StageStatus` |
| `core/models.py` | Pydantic models: `ExtractedInvoice`, `Finding`, `Decision`, fail titles |
| `core/config.py` | `.env` settings and `rules.yaml` (re-read every run) |
| `core/stages/s1..s8` | One module per stage; each exposes `NAME` and `run(ctx) -> StageResult` |
| `core/llm/` | Providers, fallback router, prompts, cache |
| `core/db/` | SQLModel tables, repository functions, CSV seeding |
| `ui/`, `Home.py`, `pages/` | Streamlit app; no business logic |
| `cli.py`, `ingestion/email_poller.py` | Other callers of the same pipeline |

## Data flow of one run

1. `RunContext.new` hashes the file; a `runs` row is created with status `running`.
2. For each stage: emit `running`, call `stage.run(ctx)`, emit the finished event with summary, details and
   duration. Each event is written to `run_events` and passed to `on_event` (the live UI).
3. A stage can `halt` the run (unreadable PDF, extraction impossible). Later stages are emitted as
   `skipped`, except **Decide, which always runs**.
4. An exception in a stage is caught, recorded in `ctx.processing_errors`, and the run continues or halts.
   The decision matrix turns any processing error into REVIEW.
5. `repo.finish_run` stores the decision, extraction, findings and a ledger entry (invoices only).

## Why the pipeline is UI-independent

The UI, CLI, email poller and tests all call `run_pipeline()`. This proves the process is real, makes
every stage unit-testable, and means the live view and the replay view render the same stored events.

## Event model

`StageEvent(stage, status, summary, details, duration_ms, seq, ts)` with status
`running | ok | warn | fail | error | skipped`. `details` holds stage-specific evidence (provider attempts,
before/after normalisation table, PO candidates, findings, decision). Reviewer overrides are appended as
an extra `Override` event, so the audit trail lives in one place.
