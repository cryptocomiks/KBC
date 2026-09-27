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
    story: list[Any] = [*_summary(data, st, width), PageBreak()]
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


def _summary(data: dict[str, Any], st: dict[str, ParagraphStyle], width: float) -> list[Any]:
    """First page: which forms, who, how complete, and the ownership chart."""
    from app.report import charts

    required = {"K": 4, "A": 6, "T": 6, "S": 6}
    people = [(f, p) for f in data["forms"] for p in f["persons"]]
    need = sum(required[f["code"]] * len(f["persons"]) + len(f["structure"]) for f in data["forms"])
    done = need - data["missing_total"]
    party = data["contracting_party"]
    out: list[Any] = [
        Paragraph("Beneficial ownership — summary", st["title"]),
        Paragraph(
            f"{_esc(party.get('name'))} · {_esc(party.get('legal_form'))} · {_esc(party.get('country'))}",
            st["small"],
        ),
        Spacer(1, 10),
        charts.kpi_row(
            [
                {"label": "Forms to sign", "value": " + ".join(f["code"] for f in data["forms"])},
                {
                    "label": "Persons identified",
                    "value": len(people),
                    "sub": f"{sum(1 for _, p in people if p.get('source'))} from the registers",
                },
                {
                    "label": "Completeness",
                    "value": f"{round(100 * done / max(1, need))} %",
                    "sub": f"{data['missing_total']} field(s) to complete",
                    "tone": "warning" if data["missing_total"] else "good",
                    "meter": (done, max(1, need)),
                },
                {
                    "label": "Flags on persons",
                    "value": sum(1 for _, p in people if p.get("flags")),
                    "sub": "sanctioned / PEP / leaks",
                    "tone": "critical" if any(p.get("flags") for _, p in people) else "good",
                },
            ],
            width,
        ),
        Spacer(1, 12),
    ]
    owners = sorted(
        [(f, p) for f, p in people if p.get("pct") is not None], key=lambda fp: -fp[1]["pct"]
    )
    if owners:
        out += [
            Paragraph("Effective ownership of the persons declared", st["h2"]),
            charts.bar_list(
                [
                    (
                        f"{p['first_name']} {p['last_name']} ({f['code']})".replace(
                            "  ", " "
                        ).strip(),
                        p["pct"],
                        f"{p['pct']:.1f} %",
                        charts.TONES["critical"] if p.get("flags") else charts.TONES["accent"],
                    )
                    for f, p in owners
                ],
                width,
                100,
                marker=25,
                marker_label="25 % — controlling person / beneficial owner threshold",
            ),
            Spacer(1, 10),
        ]
    out.append(Paragraph("Forms", st["h2"]))
    for f in data["forms"]:
        filled = required[f["code"]] * len(f["persons"]) + len(f["structure"]) - f["missing_count"]
        total = required[f["code"]] * len(f["persons"]) + len(f["structure"])
        out.append(Paragraph(f"<b>{_esc(f['title'])}</b> — {_esc(f['entity'])}", st["cell"]))
        out.append(Paragraph(_esc(f["why"]), st["small"]))
        out.append(Spacer(1, 3))
        out.append(
            charts.meter(
                filled,
                max(1, total),
                charts.TONES["good" if not f["missing_count"] else "warning"],
                width * 0.6,
                5,
            )
        )
        out.append(Paragraph(f"{filled}/{total} required fields filled", st["small"]))
        out.append(Spacer(1, 8))
    if data.get("exemption"):
        out.append(Paragraph(f"<b>Exemption:</b> {_esc(data['exemption'])}", st["cell"]))
    return out


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
