"""CDB 20 forms (A / K / S / T) as a pre-filled PDF draft, one form per page."""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.cdb import FIELD_LABEL, PERSON_FIELDS
from app.report.pdf import BRAND, DARK, INK, MUTED, _draw_logo, _esc

MARGIN = 18 * mm
AMBER = colors.HexColor("#b54708")
LINE = colors.HexColor("#c9d1d9")


def _val(v: str) -> str:
    v = (v or "").strip()
    return _esc(v) if v else "<font color='#b54708'>[to complete]</font>"


def build_cdb_pdf(data: dict[str, Any], title: str) -> bytes:
    buf = io.BytesIO()
    body = ParagraphStyle("b", fontName="DejaVu", fontSize=9, leading=12, textColor=INK)
    st = {
        "title": ParagraphStyle("t", parent=body, fontName="DejaVu-Bold", fontSize=14, leading=18),
        "h2": ParagraphStyle("h2", parent=body, fontName="DejaVu-Bold", fontSize=10.5, leading=14,
                             spaceBefore=8, spaceAfter=3, textColor=colors.HexColor("#0f2a44")),
        "small": ParagraphStyle("s", parent=body, fontSize=7.5, leading=10, textColor=MUTED),
        "cell": ParagraphStyle("c", parent=body, fontSize=8.5, leading=11),
        "label": ParagraphStyle("l", parent=body, fontSize=7.5, leading=10, textColor=MUTED),
        "note": ParagraphStyle("n", parent=body, fontSize=8, leading=11, textColor=AMBER),
    }  # fmt: skip

    def chrome(canvas, doc):
        canvas.saveState()
        band = 11 * mm
        canvas.setFillColor(DARK)
        canvas.rect(0, A4[1] - band, A4[0], band, stroke=0, fill=1)
        canvas.setFillColor(BRAND)
        canvas.rect(0, A4[1] - band - 0.8, A4[0], 0.8, stroke=0, fill=1)
        _draw_logo(canvas, MARGIN, A4[1] - band + 1.8 * mm, 7.4 * mm)
        canvas.setFillColor(colors.white)
        canvas.setFont("DejaVu-Bold", 8.5)
        canvas.drawString(
            MARGIN + 10 * mm,
            A4[1] - 6.6 * mm,
            "KYC 1 CLICK — CDB 20 beneficial ownership forms (draft)",
        )
        canvas.setFont("DejaVu", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(
            MARGIN, 9 * mm, "DRAFT — to be verified and signed on the bank's official form"
        )
        canvas.drawRightString(A4[0] - MARGIN, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    width = A4[0] - 2 * MARGIN
    party = data["contracting_party"]
    story: list[Any] = []
    for i, form in enumerate(data["forms"]):
        if i:
            story.append(PageBreak())
        story.append(Paragraph(_esc(form["title"]), st["title"]))
        story.append(Paragraph(_esc(data["draft_note"]), st["small"]))
        story.append(Spacer(1, 6))
        story.append(Paragraph("Contracting party", st["h2"]))
        rows = [
            ("Name / company", party.get("name")),
            ("Legal form", party.get("legal_form")),
            ("Registration number", party.get("registration_number")),
            ("Country", party.get("country")),
            ("Address", party.get("address")),
            ("Relationship / account no.", party.get("relationship_no")),
        ]
        if form["entity"] != party.get("name"):
            rows.insert(0, ("Structure concerned", form["entity"]))
        story.append(_grid(rows, st, width))
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<b>Why this form:</b> {_esc(form['why'])}", st["cell"]))
        if data.get("exemption") and i == 0:
            story.append(Paragraph(f"<b>Exemption:</b> {_esc(data['exemption'])}", st["cell"]))
        if form["structure"]:
            story.append(Paragraph("Structure", st["h2"]))
            story.append(_grid([(x["label"], x["value"]) for x in form["structure"]], st, width))
        story.append(Paragraph("Persons", st["h2"]))
        for n, p in enumerate(form["persons"], 1):
            head = f"{n}. {_esc(p['role_label'])} — {_esc(p['basis'])}"
            block: list[Any] = [Paragraph(head, st["cell"])]
            block.append(_grid([(FIELD_LABEL[k], p.get(k, "")) for k in PERSON_FIELDS], st, width))
            extra = []
            if len(p.get("path") or []) > 2:
                extra.append("Chain: " + " → ".join(p["path"]))
            if p.get("flags"):
                extra.append("Flags: " + ", ".join(p["flags"]))
            if p.get("source"):
                extra.append("Source: " + p["source"])
            if extra:
                block.append(Paragraph(_esc(" · ".join(extra)), st["small"]))
            block.append(Spacer(1, 5))
            story.append(KeepTogether(block))
        for note in form["notes"]:
            story.append(Paragraph("• " + _esc(note), st["note"]))
        story.append(Spacer(1, 8))
        story.append(Paragraph(_esc(data["declaration"]), st["small"]))
        story.append(Spacer(1, 14))
        sig = Table(
            [["Place and date", "Signature(s) of the contracting party"], ["", ""]],
            colWidths=[width * 0.4, width * 0.6],
            rowHeights=[5 * mm, 16 * mm],
        )
        sig.setStyle(
            TableStyle(
                [
                    ("FONT", (0, 0), (-1, 0), "DejaVu", 7.5),
                    ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                    ("LINEBELOW", (0, 1), (-1, 1), 0.6, INK),
                    ("RIGHTPADDING", (0, 0), (0, -1), 12),
                ]
            )
        )
        story.append(sig)

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN + 6 * mm,
        bottomMargin=MARGIN,
        title=f"CDB 20 forms — {title}",
        author="KYC 1 CLICK",
    )
    doc.build(story, onFirstPage=chrome, onLaterPages=chrome)
    return buf.getvalue()


def _grid(rows: list[tuple[str, Any]], st: dict[str, ParagraphStyle], width: float) -> Table:
    data = [
        [Paragraph(_esc(k), st["label"]), Paragraph(_val(str(v or "")), st["cell"])]
        for k, v in rows
    ]
    t = Table(data, colWidths=[width * 0.3, width * 0.7])
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f4f6f8")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return t
