"""Decision memo as a signed-ready PDF (portrait A4, same look as the report)."""

from __future__ import annotations

import io
import re
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

from app.report.pdf import BRAND, DARK, INK, MUTED, _draw_logo, _esc

MARGIN = 18 * mm


def _inline(text: str) -> str:
    """Escape, then show [placeholders] in amber so nothing is signed half-written."""
    return re.sub(r"\[([^\]]*)\]", r"<font color='#b54708'>[\1]</font>", _esc(text))


def _kpis(o: dict[str, Any], width: float):
    from app.report import charts

    docs = o["documents"]
    sow = o.get("sow")
    return charts.kpi_row(
        [
            {
                "label": "Risk score",
                "value": f"{o['risk']['score']:.0f}",
                "sub": o["risk"]["level"],
                "tone": charts.LEVEL_TONE.get(o["risk"]["level"], "neutral"),
                "meter": (o["risk"]["score"], 100),
            },
            {
                "label": "Vigilance",
                "value": (o.get("vigilance") or "-").capitalize(),
                "tone": {"enhanced": "critical", "standard": "warning", "simplified": "good"}.get(
                    o.get("vigilance") or "", "neutral"
                ),
            },
            {
                "label": "Open alerts",
                "value": o["alerts"]["open"],
                "tone": "critical" if o["alerts"]["open"] else "good",
            },
            {
                "label": "Documents",
                "value": f"{docs['received']}/{docs['total']}",
                "tone": "warning" if docs["required_missing"] else "good",
                "meter": (docs["received"], max(1, docs["total"])),
            },
            {
                "label": "Source of wealth",
                "value": f"{round((sow['coverage'] or 0) * 100)} %"
                if sow and sow.get("coverage") is not None
                else "-",
                "tone": {"plausible": "good", "partial": "warning", "gap": "critical"}.get(
                    (sow or {}).get("verdict", ""), "neutral"
                ),
            },
        ],
        width,
    )


def build_memo_pdf(memo: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    body = ParagraphStyle("b", fontName="DejaVu", fontSize=9.5, leading=13.5, textColor=INK)
    st = {
        "title": ParagraphStyle("t", parent=body, fontName="DejaVu-Bold", fontSize=17, leading=21),
        "meta": ParagraphStyle("m", parent=body, fontSize=8, textColor=MUTED, spaceAfter=6),
        "h2": ParagraphStyle(
            "h2", parent=body, fontName="DejaVu-Bold", fontSize=11.5, leading=15,
            spaceBefore=10, spaceAfter=2, textColor=colors.HexColor("#0f2a44"),
        ),
        "li": ParagraphStyle("li", parent=body, leftIndent=10, bulletIndent=0, spaceAfter=1.5),
        "li2": ParagraphStyle("li2", parent=body, leftIndent=24, bulletIndent=14, fontSize=9, spaceAfter=1),
        "p": body,
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
        canvas.drawString(MARGIN + 10 * mm, A4[1] - 6.6 * mm, "KYC 1 CLICK: Decision memo")
        canvas.setFont("DejaVu", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, 9 * mm, "CONFIDENTIAL: compliance use only")
        canvas.drawRightString(A4[0] - MARGIN, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    story: list[Any] = []
    kpis = memo.get("kpis")
    head_done = False
    for raw in memo["text"].splitlines():
        if kpis and not head_done and raw.startswith("## "):
            # Key figures of the file, between the title block and the first section.
            story.append(Spacer(1, 4))
            story.append(_kpis(kpis, A4[0] - 2 * MARGIN))
            story.append(Spacer(1, 4))
            head_done = True
        line = raw.rstrip()
        if not line.strip():
            story.append(Spacer(1, 3))
        elif line.startswith("# "):
            story.append(Paragraph(_esc(line[2:]), st["title"]))
        elif line.startswith("## "):
            story.append(Paragraph(_esc(line[3:]), st["h2"]))
            story.append(HRFlowable(width="100%", thickness=0.6, color=BRAND, spaceAfter=4))
        elif line.startswith("  - "):
            story.append(Paragraph(_inline(line[4:]), st["li2"], bulletText="–"))
        elif line.startswith("- "):
            story.append(Paragraph(_inline(line[2:]), st["li"], bulletText="•"))
        elif not story:
            story.append(Paragraph(_inline(line), st["p"]))
        else:
            style = st["meta"] if len(story) == 1 else st["p"]
            story.append(Paragraph(_inline(line), style))
    if memo.get("updated_by"):
        story.append(Spacer(1, 8))
        story.append(
            Paragraph(
                f"Last edited by {_esc(memo['updated_by'])} on {str(memo.get('updated_at'))[:16].replace('T', ' ')} UTC",
                st["meta"],
            )
        )
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN + 6 * mm,
        bottomMargin=MARGIN,
        title=f"Decision memo: {memo.get('title', '')}",
        author="KYC 1 CLICK",
    )
    doc.build(story, onFirstPage=chrome, onLaterPages=chrome)
    return buf.getvalue()
