"""Display helpers: rupee formatting, badges, durations."""
from __future__ import annotations

import html
from datetime import datetime, timezone

from ui.theme import COLORS

STATUS_LABELS = {"ok": "Done", "warn": "Warning", "fail": "Failed", "error": "Error", "running": "Running",
                 "skipped": "Skipped", "pending": "Waiting"}


LOCAL_TZ = datetime.now().astimezone().tzinfo


def local(dt: datetime) -> datetime:
    """DB timestamps are UTC (SQLite drops the tz); show them in the viewer's local time."""
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone()


def inr(x, paise: bool = True) -> str:
    """118000 -> ₹1,18,000.00 (Indian grouping)."""
    if x is None:
        return "—"
    neg, x = x < 0, abs(float(x))
    whole, frac = f"{x:.2f}".split(".")
    if len(whole) > 3:
        head, groups = whole[:-3], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join(([head] if head else []) + groups + [whole[-3:]])
    return f"{'-' if neg else ''}₹{whole}" + (f".{frac}" if paise else "")


def badge(outcome: str | None) -> str:
    if not outcome:
        return ""
    return f'<span class="iq-badge" style="--c:{COLORS.get(outcome, COLORS["neutral"])}">{outcome}</span>'


def ms(v) -> str:
    v = v or 0
    return f"{v} ms" if v < 1000 else f"{v / 1000:.1f} s"


def esc(s) -> str:
    return html.escape(str(s or ""))
