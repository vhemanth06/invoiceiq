"""Generate the synthetic sample invoices used by the demo, the Sample Library and the golden tests.

Four visual layouts (tally, table, letter, minimal) plus "scanned" variants: the PDF page is
rendered to an image, rotated, blurred, noised, stained, and saved back as an image-only PDF.

For every sample we also write a ground-truth extraction (samples/truth/<name>.json) and an
index keyed by the PDF's SHA-256. The offline `sample_truth` provider uses it so the whole
pipeline can run (and be tested) without API keys. It only ever answers for these exact files.

Run:  python samples/generate_samples.py
"""
from __future__ import annotations

import hashlib
import io
import json
import random
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

HERE = Path(__file__).resolve().parent
OUT = HERE / "invoices"
TRUTH = HERE / "truth"

BUYER = ("Zamp Demo Buyer Pvt Ltd", "Plot 12, HITEC City, Hyderabad, Telangana 500081", "36AAACZ0001A1Z9")

VENDORS = {
    "acme": ("Acme Industrial Supplies Pvt Ltd", "Survey 44, Jeedimetla, Hyderabad, Telangana", "36AABCA1234F1Z5"),
    "blit": ("BrightLine IT Services LLP", "4th Floor, Koramangala, Bengaluru, Karnataka", "29AAKFB5678K1Z2"),
    "deccan": ("Deccan Packaging Co.", "IDA Uppal, Hyderabad, Telangana", "36AAFCD9012M1Z8"),
    "orbit": ("Orbit Office Solutions", "Andheri East, Mumbai, Maharashtra", "27AAGCO3456P1Z1"),
    "nimbus": ("Nimbus Cloud Hosting", "Okhla Phase II, New Delhi, Delhi", "07AAICN7788Q1Z4"),
}


def inr(x: float) -> str:
    """Indian digit grouping: 118000 -> 1,18,000.00"""
    neg, x = x < 0, abs(x)
    whole, frac = f"{x:.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return ("-" if neg else "") + whole + "." + frac


# Each spec describes exactly what is printed. Amount strings in the truth are copied as printed.
SAMPLES: list[dict] = [
    dict(file="01_happy_acme_inv1042.pdf", layout="tally", vendor="acme", title="TAX INVOICE",
         number="INV-1042", date="05/10/2026", due="04/11/2026", po="PO-2026-1041", bank="4521",
         lines=[("Industrial safety gloves (box of 100)", 40, 1500, "4015"),
                ("Hydraulic hose assembly 1/2 inch", 20, 2000, "4009")],
         gst=("intra", 18)),
    dict(file="02_split_brightline_m1.pdf", layout="table", vendor="blit", title="INVOICE",
         number="BLIT/2026/071", date="1-Sep-26", due="16-Oct-26", po="PO 1052", bank="8870",
         lines=[("Milestone 1 - Discovery and solution design", 1, 200000, "998313")],
         gst=("inter", 18), note="Milestone billing 1 of 3"),
    dict(file="03_split_brightline_m2.pdf", layout="table", vendor="blit", title="INVOICE",
         number="BLIT/2026/088", date="2026-10-01", due="2026-11-15", po="PO-2026-1052", bank="8870",
         lines=[("Milestone 2 - Build and integration", 1, 180000, "998313")],
         gst=("inter", 18), note="Milestone billing 2 of 3"),
    dict(file="04_split_brightline_m3.pdf", layout="table", vendor="blit", title="INVOICE",
         number="BLIT/2026/102", date="02 Nov 2026", due="17 Dec 2026", po="#1052", bank="8870",
         lines=[("Milestone 3 - Rollout and hypercare support", 1, 162000, "998313")],
         gst=("inter", 18), note="Milestone billing 3 of 3"),
    dict(file="05_duplicate_acme_inv1042R_scanned.pdf", layout="tally", vendor="acme", title="TAX INVOICE",
         number="INV/1042-R", date="26/10/2026", due="25/11/2026", po="PO-2026-1041", bank="4521",
         lines=[("Industrial safety gloves (box of 100)", 40, 1500, "4015"),
                ("Hydraulic hose assembly 1/2 inch", 20, 2000, "4009")],
         gst=("intra", 18), note="Reminder copy - payment pending", scanned=True),
    dict(file="06_tax_inclusive_deccan.pdf", layout="letter", vendor="deccan", title="INVOICE",
         number="DPC-5521", date="15 Oct 2026", due="14 Nov 2026", po="PO-2026-1063", bank="3302",
         lines=[("Corrugated shipping boxes 5-ply", 2000, 33.60, "4819"),
                ("Stretch wrap film roll", 120, 224, "3920")],
         gst=("intra", 12), inclusive=True),
    dict(file="07_scanned_nopo_nimbus.pdf", layout="minimal", vendor="nimbus", title="INVOICE",
         number="NCH-2026-1107", date="01/11/2026", due=None, po=None, bank="6650",
         lines=[("Hosting services - Oct 2026", 1, 60000, "998315")],
         gst=("inter", 18), scanned=True, stain_total=True),
    dict(file="08_bank_change_acme.pdf", layout="tally", vendor="acme", title="TAX INVOICE",
         number="INV-1088", date="20/10/2026", due="19/11/2026", po="PO-2026-1044", bank="9931",
         lines=[("Bearing kit SKF 6205", 50, 1000, "8482")],
         gst=("intra", 18), note="Please note our NEW bank account details below"),
    dict(file="09_unapproved_orbit.pdf", layout="minimal", vendor="orbit", title="INVOICE",
         number="OOS/778", date="25-Oct-2026", due="24-Nov-2026", po="PO-2026-1099", bank="1190",
         lines=[("Ergonomic office chairs", 10, 8500, "9401")],
         gst=("inter", 18)),
    dict(file="10_bundled_amc.pdf", layout="table", vendor="blit", title="INVOICE",
         number="BLIT/2026/095", date="12 Oct 2026", due="26 Nov 2026", po="PO-2026-1080", bank="8870",
         lines=[("Annual AMC - IT infrastructure (lump sum, services as per agreement)", None, 120000, "998713")],
         gst=("inter", 18)),
    dict(file="11_credit_note_acme.pdf", layout="letter", vendor="acme", title="CREDIT NOTE",
         number="CN-2026-014", date="30/10/2026", due=None, po="PO-2026-1041", bank="4521",
         lines=[("Return of damaged safety gloves against INV-1042", 5, 1500, "4015")],
         gst=("intra", 18), note="Credit note against invoice INV-1042", doc_type="credit_note"),
]


def compute(spec: dict) -> dict:
    kind, rate = spec["gst"]
    amounts = [round((q or 1) * p, 2) for _, q, p, _ in spec["lines"]]
    lines_sum = round(sum(amounts), 2)
    if spec.get("inclusive"):
        total = lines_sum
        tax = round(total - total / (1 + rate / 100), 2)
        subtotal = lines_sum
    else:
        subtotal = lines_sum
        tax = round(subtotal * rate / 100, 2)
        total = round(subtotal + tax, 2)
    split = {"cgst": tax / 2, "sgst": tax / 2, "igst": 0} if kind == "intra" else {"cgst": 0, "sgst": 0, "igst": tax}
    return dict(amounts=amounts, subtotal=subtotal, tax=tax, total=total, rate=rate, **split)


def draw(spec: dict, path: Path) -> float:
    """Draw the invoice; return the y coordinate (PDF points) of the TOTAL line, for the stain."""
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    W, H = A4
    vname, vaddr, vgst = VENDORS[spec["vendor"]]
    m = compute(spec)
    layout = spec["layout"]
    y = H - 60

    def text(x, yy, s, size=10, bold=False, right=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        (c.drawRightString if right else c.drawString)(x, yy, s)

    # --- header, different per layout ---
    if layout == "tally":
        text(W / 2 - 50, y, spec["title"], 16, True)
        y -= 30
        c.rect(40, y - 70, W - 80, 85)
        text(50, y, vname, 12, True); text(50, y - 15, vaddr, 9); text(50, y - 30, f"GSTIN/UIN: {vgst}", 9)
        text(W - 50, y, f"Invoice No.: {spec['number']}", 10, right=True)
        text(W - 50, y - 15, f"Dated: {spec['date']}", 10, right=True)
        if spec["po"]:
            text(W - 50, y - 30, f"Buyer's Order No.: {spec['po']}", 10, right=True)
        if spec["due"]:
            text(W - 50, y - 45, f"Due Date: {spec['due']}", 10, right=True)
        y -= 100
        text(50, y, "Buyer (Bill to):", 9, True); text(50, y - 13, BUYER[0], 10)
        text(50, y - 26, BUYER[1], 9); text(50, y - 39, f"GSTIN/UIN: {BUYER[2]}", 9)
        y -= 70
    elif layout == "table":
        c.setFillColorRGB(0.12, 0.25, 0.45); c.rect(0, H - 90, W, 90, fill=1, stroke=0); c.setFillColorRGB(1, 1, 1)
        text(40, H - 50, vname, 18, True); text(40, H - 70, vaddr, 9)
        text(W - 40, H - 50, spec["title"], 22, True, right=True); c.setFillColorRGB(0, 0, 0)
        y = H - 120
        rows = [("Invoice #", spec["number"]), ("Invoice Date", spec["date"]), ("Due Date", spec["due"] or "-"),
                ("Purchase Order", spec["po"] or "-"), ("Supplier GSTIN", vgst)]
        for k, v in rows:
            text(W - 250, y, k, 9, True); text(W - 150, y, v, 9); y -= 14
        text(40, H - 120, "BILL TO", 9, True); text(40, H - 134, BUYER[0], 10); text(40, H - 148, BUYER[1], 8)
        text(40, H - 162, f"GSTIN {BUYER[2]}", 8)
        y -= 20
    elif layout == "letter":
        text(40, y, vname, 16, True); text(40, y - 16, vaddr, 9); text(40, y - 29, f"GSTIN: {vgst}", 9)
        y -= 70
        text(40, y, f"To: {BUYER[0]}, {BUYER[1]}", 9)
        y -= 25
        text(40, y, f"{spec['title']} {spec['number']}", 13, True)
        text(W - 40, y, f"Date: {spec['date']}", 10, right=True)
        y -= 18
        ref = f"Your Ref: {spec['po']}" if spec["po"] else ""
        text(40, y, ref, 10)
        if spec["due"]:
            text(W - 40, y, f"Payment due by {spec['due']}", 10, right=True)
        y -= 18
        text(40, y, "Dear Sir/Madam, please find below the details of supplies made to you.", 9)
        y -= 30
    else:  # minimal
        text(40, y, spec["title"], 26, True)
        y -= 30
        text(40, y, vname, 11, True); text(40, y - 14, vaddr, 9); text(40, y - 28, f"GST: {vgst}", 9)
        text(W - 40, y, f"No. {spec['number']}", 11, right=True)
        text(W - 40, y - 14, f"Date {spec['date']}", 10, right=True)
        if spec["po"]:
            text(W - 40, y - 28, f"P.O. {spec['po']}", 10, right=True)
        y -= 50
        text(40, y, f"Billed to: {BUYER[0]} ({BUYER[2]})", 9)
        y -= 30

    # --- line items ---
    cols = [40, 300, 360, 420, 480]
    heads = ["Description", "HSN/SAC", "Qty", "Rate", "Amount"]
    c.line(40, y + 12, W - 40, y + 12)
    for x, h in zip(cols, heads):
        text(x if h == "Description" else x, y, h, 9, True)
    y -= 6
    c.line(40, y, W - 40, y)
    y -= 15
    for (desc, q, p, hsn), amt in zip(spec["lines"], m["amounts"]):
        text(cols[0], y, desc[:48], 9)
        if len(desc) > 48:
            y -= 11
            text(cols[0], y, desc[48:], 9)
        text(cols[1], y, hsn, 9)
        text(cols[2], y, "" if q is None else f"{q:g}", 9)
        text(cols[3], y, "" if q is None else inr(p), 9)
        text(W - 45, y, inr(amt), 9, right=True)
        y -= 16
    c.line(40, y + 5, W - 40, y + 5)
    y -= 12

    # --- totals ---
    kind, rate = spec["gst"]
    if spec.get("inclusive"):
        text(360, y, "Total (incl. GST)", 10, True); total_y = y
        text(W - 45, y, f"Rs. {inr(m['total'])}", 10, True, right=True); y -= 16
        text(40, y, f"* Prices are inclusive of GST @{rate}% (CGST {rate/2:g}% Rs. {inr(m['cgst'])} + "
                    f"SGST {rate/2:g}% Rs. {inr(m['sgst'])})", 8)
        y -= 16
    else:
        text(360, y, "Sub Total", 10); text(W - 45, y, inr(m["subtotal"]), 10, right=True); y -= 15
        if kind == "intra":
            text(360, y, f"CGST @ {rate/2:g}%", 10); text(W - 45, y, inr(m["cgst"]), 10, right=True); y -= 15
            text(360, y, f"SGST @ {rate/2:g}%", 10); text(W - 45, y, inr(m["sgst"]), 10, right=True); y -= 15
        else:
            text(360, y, f"IGST @ {rate:g}%", 10); text(W - 45, y, inr(m["igst"]), 10, right=True); y -= 15
        c.line(360, y + 10, W - 40, y + 10)
        total_y = y - 4
        text(360, y - 4, "TOTAL", 11, True); text(W - 45, y - 4, f"Rs. {inr(m['total'])}/-", 11, True, right=True)
        y -= 30

    if spec.get("note"):
        text(40, y, f"Note: {spec['note']}", 9); y -= 16
    text(40, y, f"Bank: HDFC Bank, A/c No. XXXXXXXX{spec['bank']}, IFSC HDFC0001234", 9); y -= 14
    text(40, y, "Terms: Payment by NEFT/RTGS. Interest @18% p.a. on overdue invoices.", 8); y -= 30
    text(W - 40, y, f"For {vname}", 9, True, right=True)
    text(W - 40, y - 40, "Authorised Signatory", 8, right=True)
    c.showPage()
    c.save()
    return total_y


def scan(path: Path, total_y: float, stain_total: bool, seed: int) -> None:
    """Turn a digital PDF into an image-only 'scanned' PDF (rotation, noise, blur, stain)."""
    rnd = random.Random(seed)
    doc = pymupdf.open(path)
    dpi = 110
    pix = doc[0].get_pixmap(dpi=dpi)
    doc.close()
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
    scale = dpi / 72
    if stain_total:
        d = ImageDraw.Draw(img)
        y = img.height - total_y * scale
        cx, cy = img.width - 150, y - 4
        for _ in range(30):  # coffee-ring blotch over the total amount
            r = rnd.randint(18, 40)
            dx, dy = rnd.randint(-60, 60), rnd.randint(-12, 12)
            d.ellipse([cx + dx - r, cy + dy - r / 2, cx + dx + r, cy + dy + r / 2], fill=rnd.randint(110, 160))
    img = img.filter(ImageFilter.GaussianBlur(0.9))
    noise = Image.effect_noise(img.size, 18).point(lambda v: v - 128)
    img = Image.eval(Image.blend(img, Image.new("L", img.size, 225), 0.08), lambda v: v)
    img = Image.composite(img, noise.point(lambda v: 200), Image.new("L", img.size, 235))
    img = img.rotate(1.5, expand=True, fillcolor=210)
    img.convert("RGB").save(path, "PDF", resolution=dpi)


def truth(spec: dict) -> dict:
    """Ground-truth extraction as a perfect reader would return it (values copied as printed)."""
    m = compute(spec)
    src = "vision" if spec.get("scanned") else "text_layer"
    conf = 0.9 if spec.get("scanned") else 0.97

    def f(v, c=conf):
        return {"value": v, "confidence": c if v is not None else 0, "source": src if v is not None else "missing"}

    total_conf = 0.55 if spec.get("stain_total") else conf
    vname, _, vgst = VENDORS[spec["vendor"]]
    lines = []
    for (desc, q, p, hsn), amt in zip(spec["lines"], m["amounts"]):
        lines.append({"description": desc, "quantity": q, "unit_price": None if q is None else p, "amount": amt,
                      "hsn_sac": hsn, "is_bundled": q is None})
    return {
        "vendor_name": f(vname), "vendor_gstin": f(vgst), "invoice_number": f(spec["number"]),
        "invoice_date": f(spec["date"]), "due_date": f(spec["due"]), "po_reference": f(spec["po"]),
        "currency": f("INR"), "line_items": lines,
        "subtotal": f(inr(m["subtotal"])),
        "tax": {"cgst": m["cgst"], "sgst": m["sgst"], "igst": m["igst"], "other": 0, "rate_percent": m["rate"],
                "tax_inclusive": bool(spec.get("inclusive"))},
        "total": f(f"Rs. {inr(m['total'])}", total_conf),
        "bank_account_last4": f(spec["bank"]),
        "document_type": spec.get("doc_type", "invoice"),
        "notes": spec.get("note"),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    TRUTH.mkdir(parents=True, exist_ok=True)
    index = {}
    for i, spec in enumerate(SAMPLES):
        path = OUT / spec["file"]
        total_y = draw(spec, path)
        if spec.get("scanned"):
            scan(path, total_y, spec.get("stain_total", False), seed=i)
        (TRUTH / (path.stem + ".json")).write_text(json.dumps(truth(spec), indent=2))
        index[hashlib.sha256(path.read_bytes()).hexdigest()] = path.stem + ".json"
        print(f"  wrote {path.relative_to(HERE.parent)}")
    (TRUTH / "index.json").write_text(json.dumps(index, indent=2))
    print(f"{len(SAMPLES)} samples generated.")


if __name__ == "__main__":
    sys.exit(main())
