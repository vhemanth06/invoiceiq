"""Optional: poll an IMAP inbox and run the pipeline on each PDF attachment (source="email").

Env: IMAP_HOST (default imap.gmail.com), IMAP_USER, IMAP_PASSWORD (a Gmail app password), IMAP_FOLDER.
Run:  python -m ingestion.email_poller            (one pass)
      python -m ingestion.email_poller --watch 60 (poll every 60 s)
"""
from __future__ import annotations

import argparse
import email
import imaplib
import time

from loguru import logger

from core import config
from core.pipeline import run_pipeline


def poll_once() -> int:
    host = config.env("IMAP_HOST", "imap.gmail.com")
    user, password = config.env("IMAP_USER"), config.env("IMAP_PASSWORD")
    if not user or not password:
        raise SystemExit("Set IMAP_USER and IMAP_PASSWORD in .env")
    n = 0
    with imaplib.IMAP4_SSL(host) as imap:
        imap.login(user, password)
        imap.select(config.env("IMAP_FOLDER", "INBOX"))
        _, ids = imap.search(None, "UNSEEN")
        for mid in ids[0].split():
            _, data = imap.fetch(mid, "(RFC822)")
            msg = email.message_from_bytes(data[0][1])
            for part in msg.walk():
                name = part.get_filename() or ""
                if name.lower().endswith(".pdf"):
                    ctx = run_pipeline(part.get_payload(decode=True), name, "email")
                    logger.info(f"{name} from {msg.get('From')}: {ctx.decision.outcome.value}")
                    n += 1
            imap.store(mid, "+FLAGS", "\\Seen")
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=int, default=0, help="poll interval in seconds (0 = once)")
    a = ap.parse_args()
    while True:
        logger.info(f"processed {poll_once()} attachment(s)")
        if not a.watch:
            break
        time.sleep(a.watch)
