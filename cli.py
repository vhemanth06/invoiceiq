"""Run the pipeline from the terminal and print the trace.

  python cli.py samples/invoices/01_happy_acme_inv1042.pdf
  python cli.py --all-samples --reset      # run the manifest in order on a fresh DB
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from core import config
from core.events import StageStatus
from core.pipeline import run_pipeline

ICON = {StageStatus.OK: "OK  ", StageStatus.WARN: "WARN", StageStatus.FAIL: "FAIL", StageStatus.ERROR: "ERR ",
        StageStatus.SKIPPED: "SKIP"}


def show(ev):
    if ev.status != StageStatus.RUNNING:
        print(f"  [{ICON[ev.status]}] {ev.stage:<10} {ev.duration_ms:>5} ms  {ev.summary}")


def run_file(path: Path, source: str) -> str:
    print(f"\n{path.name}")
    ctx = run_pipeline(path.read_bytes(), path.name, source, on_event=show)
    d = ctx.decision
    print(f"  => {d.outcome.value} (confidence {d.confidence:.2f}, run {ctx.run_id})\n     {d.headline}\n"
          f"     {d.explanation}\n     Action: {d.recommended_action}")
    for f in ctx.findings:
        if not f.passed or f.severity.value == "info":
            print(f"     - [{f.severity.value}] {f.rule_id}: {f.detail}")
    return d.outcome.value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--all-samples", action="store_true")
    ap.add_argument("--reset", action="store_true", help="reseed master data and clear run history first")
    args = ap.parse_args()
    if args.reset:
        from core.db.seed import seed
        seed()
    if args.all_samples:
        manifest = yaml.safe_load((config.SAMPLES_DIR / "manifest.yaml").read_text())
        bad = 0
        for item in manifest:
            got = run_file(config.SAMPLES_DIR / "invoices" / item["file"], "sample")
            ok = got == item["expected"]
            bad += not ok
            print(f"  expected {item['expected']}: {'PASS' if ok else 'MISMATCH'}")
        print(f"\n{len(manifest) - bad}/{len(manifest)} samples matched expectations")
        return 1 if bad else 0
    for f in args.files:
        run_file(f, "upload")
    return 0


if __name__ == "__main__":
    sys.exit(main())
