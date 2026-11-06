"""All database reads/writes. Stages never touch SQL directly."""
from __future__ import annotations

import json
from datetime import date, datetime

from sqlmodel import Session, select

from core.db.schema import (ExtractedRecord, FindingRow, LedgerEntry, POLine, PurchaseOrder, Run, RunEvent,
                            Vendor, get_engine)


def _s() -> Session:
    return Session(get_engine(), expire_on_commit=False)


def _dump(obj) -> str:
    return json.dumps(obj, default=str)


# ---- master data ----------------------------------------------------------
def vendors() -> list[dict]:
    with _s() as s:
        return [v.model_dump() for v in s.exec(select(Vendor))]


def purchase_orders() -> list[dict]:
    with _s() as s:
        return [p.model_dump() for p in s.exec(select(PurchaseOrder))]


def po_lines(po_number: str | None = None) -> list[dict]:
    with _s() as s:
        q = select(POLine).order_by(POLine.po_number, POLine.line_no)
        if po_number:
            q = q.where(POLine.po_number == po_number)
        return [l.model_dump() for l in s.exec(q)]


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and v != v) or (isinstance(v, str) and not v.strip())


def po_line_rows(edited, known_pos: set[str]) -> tuple[list[dict], list[str]]:
    """Clean PO lines edited on the Master Data page. Returns (rows to save, errors).

    Fully empty rows are dropped; a blank amount becomes quantity x unit_price; a blank line_no
    becomes the next number on that PO.
    """
    raw = edited.to_dict("records") if hasattr(edited, "to_dict") else list(edited)
    rows, errors, next_no = [], [], {}
    for i, r in enumerate(raw, 1):
        if all(_blank(r.get(k)) for k in ("po_number", "description", "quantity", "unit_price", "amount")):
            continue
        po = str(r.get("po_number") or "").strip()
        desc = str(r.get("description") or "").strip()
        if po not in known_pos:
            errors.append(f"Row {i}: PO '{po}' does not exist; add it under Purchase orders first.")
            continue
        if not desc:
            errors.append(f"Row {i}: description is required.")
            continue
        try:
            qty, price = float(r.get("quantity")), float(r.get("unit_price"))
        except (TypeError, ValueError):
            errors.append(f"Row {i} ({po}): quantity and unit price must be numbers.")
            continue
        amount = round(qty * price, 2) if _blank(r.get("amount")) else float(r["amount"])
        if abs(amount - qty * price) > 1:
            errors.append(f"Row {i} ({po}): amount {amount:,.2f} is not quantity x unit price ({qty * price:,.2f}).")
            continue
        rows.append({"po_number": po, "line_no": None if _blank(r.get("line_no")) else int(r["line_no"]),
                     "description": desc, "quantity": qty, "unit_price": price, "amount": amount})
    for r in rows:
        next_no[r["po_number"]] = max(next_no.get(r["po_number"], 0), r["line_no"] or 0)
    for r in rows:
        if r["line_no"] is None:
            next_no[r["po_number"]] += 1
            r["line_no"] = next_no[r["po_number"]]
    return rows, errors


def subtotal_gaps(rows: list[dict], pos: list[dict]) -> list[tuple[str, tuple[float, float]]]:
    """POs whose lines do not add up to the PO subtotal (a warning, not an error)."""
    sums: dict[str, float] = {}
    for r in rows:
        sums[r["po_number"]] = sums.get(r["po_number"], 0) + r["amount"]
    return [(p["po_number"], (round(sums[p["po_number"]], 2), p["subtotal"])) for p in pos
            if p["po_number"] in sums and abs(sums[p["po_number"]] - p["subtotal"]) > 1]


def save_master(model, rows: list[dict]) -> None:
    """Replace one master table with edited rows (Master Data page)."""
    with _s() as s:
        for obj in s.exec(select(model)):
            s.delete(obj)
        s.flush()
        for r in rows:
            s.add(model.model_validate(r))
        s.commit()


# ---- runs & events --------------------------------------------------------
def create_run(ctx) -> None:
    with _s() as s:
        s.add(Run(id=ctx.run_id, source=ctx.source, file_name=ctx.file_name, file_hash=ctx.file_hash))
        s.commit()


def add_event(run_id: str, ev) -> None:
    with _s() as s:
        s.add(RunEvent(run_id=run_id, seq=ev.seq, stage=ev.stage, status=ev.status.value, summary=ev.summary,
                       details_json=_dump(ev.details), duration_ms=ev.duration_ms, ts=ev.ts))
        s.commit()


def ledger(exclude_run: str | None = None) -> list[dict]:
    with _s() as s:
        rows = [l.model_dump() for l in s.exec(select(LedgerEntry))]
    return [r for r in rows if r["run_id"] != exclude_run]


def finish_run(ctx, file_path: str, duration_ms: int) -> None:
    d = ctx.decision
    n = ctx.norm
    with _s() as s:
        run = s.get(Run, ctx.run_id)
        run.file_path = file_path
        run.doc_type = ctx.doc_type
        run.provider = ctx.provider
        run.status = "error" if ctx.processing_errors else "done"
        run.outcome = run.original_outcome = d.outcome.value
        run.confidence = d.confidence
        run.vendor_id = ctx.vendor["vendor_id"] if ctx.vendor else None
        run.vendor_name = ctx.vendor["name"] if ctx.vendor else n.get("vendor_name")
        run.invoice_number = n.get("invoice_number")
        run.po_number = ctx.po["po_number"] if ctx.po else None
        run.total = n.get("total")
        run.duration_ms = duration_ms
        run.headline = d.headline
        run.decision_json = d.model_dump_json()
        run.context_json = _dump({
            "doc_type": ctx.doc_type, "document_kind": ctx.document_kind, "route": ctx.route,
            "text_density": ctx.text_density, "page_count": ctx.page_count, "match_method": ctx.match_method,
            "match_score": ctx.match_score, "candidates": ctx.candidates, "po": ctx.po, "po_lines": ctx.po_lines,
            "po_billed_before": ctx.po_billed_before, "vendor": ctx.vendor, "vendor_match": ctx.vendor_match,
            "processing_errors": ctx.processing_errors,
        })
        s.add(run)
        if ctx.extraction:
            s.add(ExtractedRecord(run_id=ctx.run_id, extraction_json=ctx.extraction.model_dump_json(), normalized_json=_dump(n)))
        for f in ctx.findings:
            s.add(FindingRow(run_id=ctx.run_id, rule_id=f.rule_id, stage=f.stage, severity=f.severity.value,
                             passed=f.passed, title=f.title, detail=f.detail, evidence_json=_dump(f.evidence)))
        # Credit notes and unreadable documents are not payables; keep them out of the ledger.
        if ctx.vendor and n.get("invoice_key") and ctx.document_kind == "invoice":
            s.add(LedgerEntry(run_id=ctx.run_id, vendor_id=ctx.vendor["vendor_id"],
                              invoice_number=n.get("invoice_number") or "", invoice_no_key=n["invoice_key"],
                              invoice_date=n.get("invoice_date"), total=n.get("total") or 0,
                              po_number=ctx.po["po_number"] if ctx.po else None, file_hash=ctx.file_hash,
                              lines_sig=n.get("lines_sig", ""), outcome=d.outcome.value))
        s.commit()


def list_runs() -> list[dict]:
    with _s() as s:
        return [r.model_dump() for r in s.exec(select(Run).order_by(Run.created_at.desc()))]


def get_run(run_id: str) -> dict | None:
    with _s() as s:
        run = s.get(Run, run_id)
        if not run:
            return None
        out = run.model_dump()
        out["events"] = [e.model_dump() for e in s.exec(
            select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq))]
        out["findings"] = [f.model_dump() for f in s.exec(select(FindingRow).where(FindingRow.run_id == run_id))]
        ex = s.get(ExtractedRecord, run_id)
        out["extraction"] = json.loads(ex.extraction_json) if ex else None
        out["normalized"] = json.loads(ex.normalized_json) if ex else None
        out["decision"] = json.loads(run.decision_json)
        out["context"] = json.loads(run.context_json)
        return out


def all_findings() -> list[dict]:
    with _s() as s:
        return [f.model_dump() for f in s.exec(select(FindingRow))]


def override(run_id: str, outcome: str, comment: str, user: str = "AP reviewer") -> None:
    """Human-in-the-loop override: updates the run and ledger, logs an audit event."""
    with _s() as s:
        run = s.get(Run, run_id)
        prev = run.outcome
        run.outcome = outcome
        led = s.get(LedgerEntry, run_id)
        ex = s.get(ExtractedRecord, run_id)
        if not led and outcome == "APPROVE" and run.vendor_id and ex:
            # approved non-invoice-looking docs must still count for duplicates and PO balance
            n = json.loads(ex.normalized_json)
            led = LedgerEntry(run_id=run_id, vendor_id=run.vendor_id, invoice_number=n.get("invoice_number") or "",
                              invoice_no_key=n.get("invoice_key") or "", total=n.get("total") or 0,
                              invoice_date=date.fromisoformat(n["invoice_date"]) if n.get("invoice_date") else None,
                              po_number=run.po_number, file_hash=run.file_hash, lines_sig=n.get("lines_sig", ""))
        if led:
            led.outcome = outcome
            s.add(led)
        seq = len(list(s.exec(select(RunEvent).where(RunEvent.run_id == run_id)))) + 1
        s.add(RunEvent(run_id=run_id, seq=seq, stage="Override", status="ok",
                       summary=f"{user} changed {prev} -> {outcome}: {comment}",
                       details_json=_dump({"from": prev, "to": outcome, "comment": comment, "user": user,
                                           "at": datetime.now()})))
        s.add(run)
        s.commit()
