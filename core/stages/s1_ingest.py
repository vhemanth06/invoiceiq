"""Stage 1 - Ingest: save the file, hash it, count pages, reject unreadable documents early."""
from __future__ import annotations

import pymupdf

from core import config
from core.events import StageResult, StageStatus
from core.models import Finding, Severity

NAME = "Ingest"
UPLOADS = config.DATA_DIR / "uploads"


def run(ctx) -> StageResult:
    UPLOADS.mkdir(parents=True, exist_ok=True)
    path = UPLOADS / f"{ctx.run_id}.pdf"
    path.write_bytes(ctx.file_bytes)
    ctx.norm["file_path"] = str(path)
    details = {"file_name": ctx.file_name, "size_kb": round(len(ctx.file_bytes) / 1024, 1),
               "sha256": ctx.file_hash, "source": ctx.source, "file_path": str(path)}

    problem = None
    if not ctx.file_bytes.startswith(b"%PDF"):
        problem = "file is not a PDF"
    else:
        try:
            doc = pymupdf.open(stream=ctx.file_bytes, filetype="pdf")
            if doc.needs_pass:
                problem = "PDF is password-protected"
            elif doc.page_count == 0:
                problem = "PDF has no pages"
            else:
                ctx.page_count = doc.page_count
                ctx.page_texts = [p.get_text() for p in doc]
                ctx.text = "\n".join(ctx.page_texts)
            doc.close()
        except Exception as e:
            problem = f"PDF could not be opened ({e})"

    if problem:
        ctx.findings.append(Finding(rule_id="R00_READABLE", stage=NAME, severity=Severity.BLOCK, passed=False,
                                    title="Unreadable document", detail=problem))
        return StageResult(StageStatus.FAIL, f"Unreadable document: {problem}", details, halt=True)
    details["pages"] = ctx.page_count
    return StageResult(StageStatus.OK, f"{ctx.file_name} - {ctx.page_count} page(s), "
                                       f"{details['size_kb']} KB, sha256 {ctx.file_hash[:10]}...", details)
