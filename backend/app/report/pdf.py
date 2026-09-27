"""Due diligence PDF report (ReportLab — pure Python, runs on serverless hosts).

Structure: header & disclaimer, executive summary with the explained score,
subject profile, ownership graph (PNG exported by the browser), detailed
tables, sources consulted with retrieval dates, methodology.
"""

from __future__ import annotations

import base64
import binascii
import io
from datetime import date, datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    CondPageBreak,
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.risk.config import get_jurisdictions
from app.schemas import Investigation

FONT_DIR = Path(__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont("DejaVu", str(FONT_DIR / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold")

INK = colors.HexColor("#101828")
NAVY = colors.HexColor("#0f2a44")
DARK = colors.HexColor("#0b0e11")
BRAND = colors.HexColor("#1f9467")
MUTED = colors.HexColor("#475467")
LINE = colors.HexColor("#d0d5dd")
HEAD_BG = colors.HexColor("#1b2733")
ZEBRA = colors.HexColor("#f6f8fa")
LEVEL_COLORS = {
    "low": colors.HexColor("#15803d"),
    "medium": colors.HexColor("#b45309"),
    "high": colors.HexColor("#c2410c"),
    "critical": colors.HexColor("#b91c1c"),
    "none": MUTED,
    "incomplete": colors.HexColor("#b45309"),
}

PAGE = landscape(A4)
MARGIN = 14 * mm
WIDTH = PAGE[0] - 2 * MARGIN


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "body",
        parent=base["Normal"],
        fontName="DejaVu",
        fontSize=8.5,
        leading=11,
        textColor=INK,
        alignment=TA_LEFT,
    )
    return {
        "body": body,
        "small": ParagraphStyle("small", parent=body, fontSize=7, leading=9),
        "muted": ParagraphStyle("muted", parent=body, fontSize=7.5, textColor=MUTED),
        "cell": ParagraphStyle("cell", parent=body, fontSize=7, leading=8.6),
        "head": ParagraphStyle(
            "head",
            parent=body,
            fontName="DejaVu-Bold",
            fontSize=7,
            leading=8.6,
            textColor=colors.white,
        ),
        "h1": ParagraphStyle(
            "h1", parent=body, fontName="DejaVu-Bold", fontSize=17, leading=21, textColor=NAVY
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=body,
            fontName="DejaVu-Bold",
            fontSize=11.5,
            leading=15,
            spaceBefore=12,
            spaceAfter=5,
            textColor=NAVY,
        ),
        "h3": ParagraphStyle(
            "h3",
            parent=body,
            fontName="DejaVu-Bold",
            fontSize=9.5,
            leading=12,
            spaceBefore=6,
            spaceAfter=3,
        ),
        "warn": ParagraphStyle(
            "warn",
            parent=body,
            fontSize=8,
            leading=10.5,
            textColor=colors.HexColor("#344054"),
            backColor=colors.HexColor("#f2f4f7"),
            borderPadding=6,
        ),
    }


def _esc(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, float):
        value = f"{value:g}"
    if isinstance(value, datetime):
        value = value.strftime("%Y-%m-%d %H:%M UTC")
    if isinstance(value, date):
        value = value.isoformat()
    if isinstance(value, bool):
        value = "yes" if value else "no"
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _table(
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str, float]],
    st: dict,
    empty: str = "No data.",
    row_height: float | None = None,
) -> Any:
    """columns: (key, header, relative width). row_height: fixed height (forms to fill in)."""
    if not rows:
        return Paragraph(empty, st["muted"])
    total = sum(w for _, _, w in columns)
    widths = [WIDTH * w / total for _, _, w in columns]
    data = [[Paragraph(h, st["head"]) for _, h, _ in columns]]
    for row in rows:
        data.append([Paragraph(_esc(row.get(k)), st["cell"]) for k, _, _ in columns])
    heights = [None] + [row_height] * (len(data) - 1) if row_height else None
    t = Table(data, colWidths=widths, repeatRows=1, rowHeights=heights)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
                ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE),
                ("BOX", (0, 0), (-1, -1), 0.3, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
                ("LINEBELOW", (0, 0), (-1, 0), 1.2, BRAND),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]
        )
    )
    return t


def _graph_image(b64: str | None) -> Image | None:
    if not b64:
        return None
    if "," in b64[:100]:
        b64 = b64.split(",", 1)[1]
    try:
        raw = base64.b64decode(b64, validate=False)
        reader = ImageReader(io.BytesIO(raw))
    except (binascii.Error, OSError, ValueError):
        return None
    w, h = reader.getSize()
    max_w, max_h = WIDTH, PAGE[1] - 2 * MARGIN - 30 * mm
    scale = min(max_w / w, max_h / h, 1.0 if w > 1200 else max_w / w)
    return Image(io.BytesIO(raw), width=w * scale, height=h * scale)


TITLES = {
    "full": "Due Diligence Report",
    "kyc": "Customer Due Diligence (KYC / KYB)",
    "edd": "Enhanced Due Diligence Report",
    "review": "Periodic Review",
}
# Sections left out of the shorter templates (their numbering prefix)
SKIPPED_SECTIONS = {
    "kyc": {"8.", "10b.", "11.", "11a.", "11b."},
    "review": {"8.", "11.", "11b."},
}


def _draw_logo(c, x: float, y: float, size: float, on_dark: bool = True) -> None:
    """The K1 monogram (same drawing as the web app), bottom-left corner at (x, y)."""
    k = size / 32.0
    c.saveState()
    c.setFillColor(DARK)
    c.setStrokeColor(BRAND)
    c.setLineWidth(1.5 * k)
    c.roundRect(x + 1 * k, y + 1 * k, 30 * k, 30 * k, 8 * k, stroke=1, fill=1)
    c.setLineWidth(2.3 * k)
    c.setLineCap(1)
    c.setLineJoin(1)

    def line(x1, y1, x2, y2, color):
        c.setStrokeColor(color)
        c.line(x + x1 * k, y + (32 - y1) * k, x + x2 * k, y + (32 - y2) * k)

    white = colors.HexColor("#eef2f4")
    line(9.5, 9, 9.5, 23, white)
    line(9.5, 16.2, 16, 9, white)
    line(12.2, 13.3, 16.4, 23, white)
    line(20.2, 11.6, 23.4, 9, BRAND)
    line(23.4, 9, 23.4, 23, BRAND)
    c.restoreState()


class _NumberedCanvas(pdf_canvas.Canvas):
    """Adds "Page X of Y" once the total number of pages is known."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved: list[dict] = []

    def showPage(self):  # noqa: N802 - ReportLab API
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            if self._pageNumber > 1:
                self.setFont("DejaVu", 7)
                self.setFillColor(MUTED)
                self.drawRightString(
                    PAGE[0] - MARGIN, 8 * mm, f"Page {self._pageNumber} of {total}"
                )
            super().showPage()
        super().save()


def _underline_headings(story: list[Any]) -> list[Any]:
    """A thin brand-coloured rule under every section title, and no title alone at a page bottom."""
    out: list[Any] = []
    for flow in story:
        if isinstance(flow, Paragraph) and getattr(flow.style, "name", "") == "h2":
            out.append(CondPageBreak(40 * mm))
            out.append(flow)
            out.append(
                HRFlowable(width="100%", thickness=0.8, color=BRAND, spaceBefore=0, spaceAfter=5)
            )
        else:
            out.append(flow)
    return out


def _drop_sections(story: list[Any], prefixes: set[str]) -> list[Any]:
    """Remove whole report sections (from their h2 title to the next h2)."""
    out, skipping = [], False
    for flow in story:
        if isinstance(flow, Paragraph) and getattr(flow.style, "name", "") == "h2":
            text = flow.getPlainText()
            skipping = any(text.startswith(p + " ") for p in prefixes)
        if not skipping:
            out.append(flow)
    return out


UBO_STATUS = {
    "ubo_both": "UBO, declared",
    "ubo_ownership": "UBO, NOT declared",
    "ubo_declared": "Declared UBO",
    "below_threshold": "Below threshold",
    "dead_end": "Chain stops here",
}


def refs_for(key: str) -> list[dict]:
    from app.legal import refs_for as _refs

    return _refs(key)


def _ownership_analysis(inv: Investigation, st: dict) -> list[Any]:
    """6a. Beneficial ownership analysis: owners, coverage, SMO fallback, 50 % rule, questions."""
    a = inv.ownership
    if a is None:
        return []
    out: list[Any] = [Paragraph("6a. Beneficial ownership analysis", st["h2"])]
    fmt = lambda v: "—" if v is None else f"{v:g} %"  # noqa: E731
    if not a.subject_is_company:
        out.append(Paragraph("Holdings of the subject (direct and indirect).", st["muted"]))
        out.append(
            _table(
                [
                    {
                        "name": h["name"],
                        "jur": h.get("jurisdiction") or "",
                        "pct": fmt(h.get("effective_pct")),
                        "how": "direct"
                        if h.get("direct")
                        else f"{h.get('layers')} intermediate(s)",
                    }
                    for h in a.holdings
                ],
                [
                    ("name", "Company", 3),
                    ("jur", "Country", 0.8),
                    ("pct", "Effective", 1),
                    ("how", "Held", 1.4),
                ],
                st,
                empty="No shareholding found.",
            )
        )
    else:
        ubos = [o for o in a.owners if o.status.startswith("ubo")]
        out.append(
            Paragraph(
                f"Capital traced to natural persons: <b>{fmt(a.traced_pct)}</b> · unexplained: {fmt(a.unexplained_pct)} · "
                f"beneficial owners: <b>{len(ubos)}</b> · threshold applied: {a.threshold_applied:g} %"
                + (" (enhanced, high risk)" if a.threshold_applied < a.threshold else "")
                + (
                    f" · part of the chain lies beyond the search depth ({a.max_depth})"
                    if a.depth_limited
                    else ""
                ),
                st["body"],
            )
        )
        out.append(
            _table(
                [
                    {
                        "name": o.name
                        + (" [SANCTIONS]" if o.sanctioned else "")
                        + (" [PEP]" if o.pep else ""),
                        "status": UBO_STATUS.get(o.status, o.status),
                        "eff": fmt(o.effective_pct),
                        "direct": fmt(o.direct_pct),
                        "declared": fmt(o.declared_pct) if o.declared else "no",
                        "route": " → ".join(o.countries) or "—",
                        "layers": str(o.layers),
                    }
                    for o in a.owners
                ],
                [
                    ("name", "Owner", 2.4),
                    ("status", "Status", 1.5),
                    ("eff", "Effective", 0.9),
                    ("direct", "Direct", 0.8),
                    ("declared", "Declared", 0.8),
                    ("layers", "Layers", 0.6),
                    ("route", "Countries crossed", 1.4),
                ],
                st,
                empty="No owner found above the subject.",
            )
        )
        if a.smo_reason:
            out.append(
                Paragraph(
                    "<b>Senior managing official (fallback).</b> " + _esc(a.smo_reason), st["muted"]
                )
            )
            if a.smo:
                out.append(
                    Paragraph(
                        _esc(", ".join(f"{s['name']} ({s['role']})" for s in a.smo)), st["muted"]
                    )
                )
        out.append(Paragraph("Ownership coverage, level by level", st["h3"]))
        out.append(
            _table(
                [
                    {
                        "name": c.name,
                        "jur": (c.jurisdiction or "") + (" · offshore" if c.offshore else ""),
                        "ident": fmt(c.identified_pct),
                        "unk": fmt(c.unexplained_pct),
                        "reason": c.reason or "",
                    }
                    for c in a.coverage
                ],
                [
                    ("name", "Company", 2.4),
                    ("jur", "Country", 1),
                    ("ident", "Identified", 0.9),
                    ("unk", "Unknown", 0.9),
                    ("reason", "Note", 3),
                ],
                st,
            )
        )
    out.append(
        Paragraph("Sanctions by ownership and control (OFAC 50 % rule, EU criteria)", st["h3"])
    )
    out.append(
        _table(
            [
                {
                    "name": s.name,
                    "pct": fmt(s.aggregate_pct),
                    "status": "BLOCKED (≥ 50 %)" if s.blocked else "Exposure",
                    "by": "; ".join(f"{o['name']} {o['pct']:g} %" for o in s.owners)
                    + (f"; sanctioned officer: {', '.join(s.control)}" if s.control else ""),
                }
                for s in a.sanctions
            ],
            [
                ("name", "Entity", 2.2),
                ("pct", "Aggregate", 0.9),
                ("status", "Status", 1.2),
                ("by", "Held / run by", 3.5),
            ],
            st,
            empty="No entity in the network is owned or run by a person on a sanctions list (confirmed matches).",
        )
    )
    if a.actions:
        out.append(Paragraph("Internal actions (not to be shared with the client)", st["h3"]))
        out.extend(Paragraph("• " + _esc(x), st["muted"]) for x in a.actions)
    if a.questions:
        out.append(Paragraph("Questions for the client", st["h3"]))
        out.extend(Paragraph(f"{i}. " + _esc(q), st["muted"]) for i, q in enumerate(a.questions, 1))
    return out


def build_pdf(
    inv: Investigation,
    graph_png_b64: str | None = None,
    analyst: str | None = None,
    reference: str | None = None,
    decisions: list[dict] | None = None,
    template: str = "full",
    changes: list[dict] | None = None,
    questionnaire: dict | None = None,
    case_file: dict | None = None,
) -> bytes:
    st = _styles()
    ents = {e.id: e for e in inv.entities}
    subject = ents[inv.subject_id]
    jur = get_jurisdictions()
    risk = inv.risk
    buf = io.BytesIO()

    title = TITLES.get(template, TITLES["full"])

    def on_page(canvas, doc):
        canvas.saveState()
        # Header band: logo, product, report and subject
        band = 11 * mm
        canvas.setFillColor(DARK)
        canvas.rect(0, PAGE[1] - band, PAGE[0], band, stroke=0, fill=1)
        canvas.setFillColor(BRAND)
        canvas.rect(0, PAGE[1] - band - 0.8, PAGE[0], 0.8, stroke=0, fill=1)
        _draw_logo(canvas, MARGIN, PAGE[1] - band + 1.8 * mm, 7.4 * mm)
        canvas.setFillColor(colors.white)
        canvas.setFont("DejaVu-Bold", 8.5)
        canvas.drawString(MARGIN + 10 * mm, PAGE[1] - 6.6 * mm, "KYC 1 CLICK")
        canvas.setFont("DejaVu", 7.5)
        canvas.setFillColor(colors.HexColor("#aab4be"))
        canvas.drawRightString(
            PAGE[0] - MARGIN, PAGE[1] - 6.6 * mm, f"{title} — {subject.name}"[:140]
        )
        # Footer
        canvas.setFont("DejaVu", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(
            MARGIN,
            8 * mm,
            f"CONFIDENTIAL — compliance use only — findings require human verification · "
            f"generated {inv.generated_at:%Y-%m-%d %H:%M} UTC",
        )
        if inv.demo:
            canvas.setFont("DejaVu-Bold", 60)
            canvas.setFillColor(colors.Color(0.8, 0.1, 0.1, alpha=0.06))
            canvas.translate(PAGE[0] / 2, PAGE[1] / 2)
            canvas.rotate(25)
            canvas.drawCentredString(0, 0, "DEMO — FICTITIOUS DATA")
        canvas.restoreState()

    def on_cover(canvas, doc):
        canvas.saveState()
        # Dark upper half with the brand, the report title and the subject
        top = PAGE[1] * 0.46
        canvas.setFillColor(DARK)
        canvas.rect(0, PAGE[1] - top, PAGE[0], top, stroke=0, fill=1)
        canvas.setFillColor(BRAND)
        canvas.rect(0, PAGE[1] - top - 1.5, PAGE[0], 1.5, stroke=0, fill=1)
        _draw_logo(canvas, MARGIN, PAGE[1] - 26 * mm, 13 * mm)
        canvas.setFillColor(colors.white)
        canvas.setFont("DejaVu-Bold", 13)
        canvas.drawString(MARGIN + 17 * mm, PAGE[1] - 19 * mm, "KYC 1 CLICK")
        canvas.setFont("DejaVu", 8)
        canvas.setFillColor(colors.HexColor("#aab4be"))
        canvas.drawString(MARGIN + 17 * mm, PAGE[1] - 23.5 * mm, "Due diligence & AML/KYC")
        canvas.drawRightString(
            PAGE[0] - MARGIN, PAGE[1] - 19 * mm, "CONFIDENTIAL — compliance use only"
        )
        canvas.setFillColor(colors.HexColor("#7fdcb0"))
        canvas.setFont("DejaVu-Bold", 10)
        canvas.drawString(MARGIN, PAGE[1] - 48 * mm, title.upper())
        canvas.setFillColor(colors.white)
        name = subject.name if len(subject.name) <= 48 else subject.name[:46] + "…"
        canvas.setFont("DejaVu-Bold", 28 if len(name) <= 32 else 21)
        canvas.drawString(MARGIN, PAGE[1] - 62 * mm, name)
        canvas.setFont("DejaVu", 9)
        canvas.setFillColor(colors.HexColor("#c3cad2"))
        ident = " · ".join(
            p
            for p in (
                subject.type.value.capitalize(),
                get_jurisdictions().name(subject.jurisdiction) if subject.jurisdiction else None,
                subject.registration_number,
                f"born {subject.birth_date}" if subject.birth_date else None,
            )
            if p
        )
        canvas.drawString(MARGIN, PAGE[1] - 70 * mm, ident)
        meta = [f"Generated {inv.generated_at:%d %B %Y, %H:%M} UTC"]
        if reference:
            meta.append(f"Reference {reference}")
        if analyst:
            meta.append(f"Analyst {analyst}")
        meta.append(f"Network depth {inv.params.depth} · {inv.stats.get('sources', 0)} sources")
        canvas.drawString(MARGIN, PAGE[1] - 77 * mm, "   ·   ".join(meta))
        if inv.demo:
            canvas.setFillColor(colors.HexColor("#fec84b"))
            canvas.setFont("DejaVu-Bold", 8)
            canvas.drawRightString(PAGE[0] - MARGIN, PAGE[1] - 77 * mm, "DEMO — FICTITIOUS DATA")
        canvas.setFont("DejaVu", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(
            MARGIN,
            8 * mm,
            "Analytical aid only — automated matches must be verified by a qualified analyst "
            "against primary sources before any decision.",
        )
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf,
        pagesize=PAGE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN + 6 * mm,
        bottomMargin=MARGIN,
        title=f"{title} — {subject.name}",
        author=analyst or "KYC 1 CLICK",
    )
    story: list[Any] = []

    # ----------------------------------------------------------------- cover
    level_color = LEVEL_COLORS.get(risk.level, INK)
    b = inv.brief
    story.append(Spacer(1, PAGE[1] * 0.46 - MARGIN - 6 * mm + 8 * mm))
    rating = Table(
        [
            [Paragraph("<font color='#667085'>RISK RATING</font>", st["small"])],
            [
                Paragraph(
                    f"<font size=22 color='{level_color.hexval()}'><b>{risk.level.upper()}</b></font>",
                    ParagraphStyle("lvl", parent=st["body"], leading=26),
                )
            ],
            [Paragraph(f"Score <b>{risk.score:g}</b> / 100", st["body"])],
        ],
        colWidths=[62 * mm],
    )
    rating.setStyle(
        TableStyle(
            [
                ("LINEBEFORE", (0, 0), (0, -1), 3, level_color),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("BACKGROUND", (0, 0), (-1, -1), ZEBRA),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
            ]
        )
    )
    verdict = []
    if b:
        verdict.append(
            Paragraph(
                f"<b>{_esc(b.headline)}</b>",
                ParagraphStyle("v", parent=st["body"], fontSize=11, leading=14),
            )
        )
        if b.action:
            verdict.append(Spacer(1, 4))
            verdict.append(Paragraph(f"<b>Recommended action:</b> {_esc(b.action)}", st["body"]))
        figs = [
            [
                Paragraph(f"<font color='#667085'>{_esc(f.label)}</font>", st["small"]),
                Paragraph(f"<b>{_esc(f.value)}</b>", st["body"]),
            ]
            for f in b.figures[:8]
        ]
        if figs:
            # two columns of key figures
            half = (len(figs) + 1) // 2
            rows = [
                figs[i] + (figs[i + half] if i + half < len(figs) else ["", ""])
                for i in range(half)
            ]
            grid = Table(rows, colWidths=[34 * mm, 48 * mm, 34 * mm, 48 * mm])
            grid.setStyle(
                TableStyle(
                    [
                        ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            verdict += [Spacer(1, 8), grid]
    cover = Table([[rating, verdict or ""]], colWidths=[70 * mm, WIDTH - 70 * mm])
    cover.setStyle(
        TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (1, 0), (1, 0), 14)])
    )
    story.append(cover)
    story.append(Spacer(1, 10))
    toc_index = len(story)  # the contents are filled in once every section is known
    story.append(PageBreak())

    # ------------------------------------------------------ executive summary
    story.append(Paragraph("1. Executive summary", st["h2"]))
    disclaimer = inv.disclaimer
    if inv.demo:
        disclaimer = (
            "DEMO MODE — all persons, companies and list entries in this report are fictitious. "
            + disclaimer
        )
    story.append(Paragraph(_esc(disclaimer), st["warn"]))
    story.append(Spacer(1, 8))
    if b:
        verdict_color = {
            "critical": "#991b1b",
            "high": "#9a3412",
            "medium": "#92400e",
            "incomplete": "#92400e",
        }.get(b.level, "#065f46")
        story.append(
            Paragraph(f"<font color='{verdict_color}'><b>{_esc(b.headline)}</b></font>", st["body"])
        )
        if b.action:
            story.append(Paragraph(f"<b>Recommended action:</b> {_esc(b.action)}", st["body"]))
        story.append(
            Paragraph(
                " · ".join(f"<b>{_esc(f.label)}</b>: {_esc(f.value)}" for f in b.figures),
                st["small"],
            )
        )
    if inv.truncated:
        story.append(
            Paragraph(
                "<font color='#b91c1c'>Network truncated at the node limit — results are partial.</font>",
                st["small"],
            )
        )
    if b and b.owners:
        story.append(
            Paragraph(
                "What the subject controls" if b.subject_type == "person" else "Ultimate owners",
                st["h3"],
            )
        )
        story.append(
            _table(
                [
                    {
                        "name": o.name,
                        "pct": f"{o.pct:.1f}%",
                        "path": " → ".join(o.path),
                        "flags": ", ".join(o.flags),
                    }
                    for o in b.owners
                ],
                [
                    ("name", "Name", 2),
                    ("pct", "Effective %", 0.8),
                    ("path", "Chain", 5),
                    ("flags", "Flags", 1.2),
                ],
                st,
                "",
            )
        )
    if b and b.flags:
        story.append(Paragraph("Red flags and next steps", st["h3"]))
        story.append(
            _table(
                [
                    {
                        "title": f.title,
                        "points": f"+{f.points:.0f}",
                        "evidence": f.evidence[0] if f.evidence else "",
                        "next": f.next_step or "",
                    }
                    for f in b.flags
                ],
                [
                    ("title", "Red flag", 2),
                    ("points", "Pts", 0.5),
                    ("evidence", "Evidence", 4),
                    ("next", "Next step", 4),
                ],
                st,
                "",
            )
        )
    if inv.summary:
        marks = {"critical": "#b91c1c", "warning": "#b45309", "info": "#475569"}
        story.append(Paragraph("Key findings", st["h3"]))
        for f in inv.summary:
            story.append(
                Paragraph(
                    f"<font color='{marks.get(f.severity, '#475569')}'>■</font> {_esc(f.text)}",
                    st["body"],
                )
            )

    # ---------------------------------------------------------- subject
    story.append(Paragraph("2. Subject profile", st["h2"]))
    prof = [
        ("Name", subject.name),
        ("Also known as", ", ".join(subject.aliases)),
    ]
    if subject.type.value == "person":
        prof += [
            ("Date of birth", subject.birth_date),
            ("Nationalities", ", ".join(jur.name(n) for n in subject.nationalities)),
        ]
    else:
        prof += [
            ("Jurisdiction", jur.name(subject.jurisdiction)),
            ("Registration no.", subject.registration_number),
            ("Legal form", subject.legal_form),
            ("Status", subject.status),
            ("Incorporated", subject.incorporation_date),
            ("Address", subject.address),
        ]
    prof.append(
        (
            "Sources",
            "; ".join(
                f"{p.source_label} ({p.record_id}) — retrieved {p.retrieved_at:%Y-%m-%d %H:%M}"
                for p in subject.sources
            ),
        )
    )
    story.append(
        _table([{"k": k, "v": v} for k, v in prof], [("k", "Field", 1), ("v", "Value", 5)], st)
    )

    # --------------------------------------------------------- risk factors
    story.append(Paragraph("3. Risk factors (explained score)", st["h2"]))
    rows = [
        {
            "label": f.label,
            "weight": f.weight,
            "distance": f.distance,
            "mult": f"×{f.multiplier:g}",
            "points": f.points,
            "evidence": " | ".join(f.evidence),
            "legal": ", ".join(r["short"] for r in refs_for(f.key)),
        }
        for f in risk.factors
    ]
    story.append(
        _table(
            rows,
            [
                ("label", "Factor", 2.2),
                ("weight", "Weight", 0.75),
                ("distance", "Hops", 0.7),
                ("mult", "Proximity", 0.9),
                ("points", "Points", 0.7),
                ("evidence", "Evidence", 5.4),
                ("legal", "Legal basis", 1.8),
            ],
            st,
            "No risk factor triggered.",
        )
    )
    story.append(Spacer(1, 3))
    story.append(Paragraph("<br/>".join(_esc(m) for m in risk.methodology), st["small"]))
    if inv.legal:
        story.append(Paragraph("Justifications for the file", st["h3"]))
        story.extend(
            Paragraph("• " + _esc(item["en"]), st["muted"]) for item in inv.legal if item.get("en")
        )
        story.append(
            Paragraph(
                "Legal references: an operational map to the texts (config/legal_basis.yaml), not legal advice; "
                "check the current version of each text and the institution's directives.",
                st["small"],
            )
        )

    # ------------------------------------------------------------- graph
    img = _graph_image(graph_png_b64)
    if img is not None:
        story.append(PageBreak())
        story.append(Paragraph("4. Ownership & control graph", st["h2"]))
        story.append(
            Paragraph(
                "Arrows point from the owner/officer to the company. Percentages are direct holdings. "
                "Node colour reflects the entity's own risk flags.",
                st["muted"],
            )
        )
        story.append(img)
        story.append(
            Paragraph(
                "Legend — shapes: ● person, ▬ company, ◆ offshore entity, ▸ registered address. "
                "Edges: solid = shareholding (%), dashed violet = declared beneficial owner, dotted = officer. "
                "Colours: grey = no flag, yellow = minor, amber = medium, orange = high, red = critical. "
                "Subject outlined in blue.",
                st["small"],
            )
        )

    # ------------------------------------------------------------ tables
    t = inv.tables
    story.append(PageBreak())
    story.append(
        Paragraph(
            "5. Positions held" if subject.type.value == "person" else "5. Officers", st["h2"]
        )
    )
    story.append(
        _table(
            t["mandates"],
            [
                ("name", "Entity", 2.5),
                ("jurisdiction", "Jur.", 0.5),
                ("relation", "Relation", 1),
                ("role", "Role", 2.2),
                ("share_pct", "%", 0.5),
                ("start_date", "From", 0.9),
                ("end_date", "To", 0.9),
                ("company_status", "Co. status", 0.9),
                ("sources", "Source", 2.5),
            ],
            st,
        )
    )

    story.append(Paragraph("6. Computed effective ownership", st["h2"]))
    story.append(
        Paragraph(
            "Sum over ownership paths of the product of direct percentages (circular paths cut). "
            "The 25% threshold is the EU AMLD beneficial-ownership reference.",
            st["muted"],
        )
    )
    story.append(
        _table(
            t["ownership"],
            [
                ("owner", "Owner", 2),
                ("company", "Company", 3),
                ("direct_pct", "Direct %", 1),
                ("effective_pct", "Effective %", 1),
                ("ubo_threshold_met", "≥ 25%", 0.8),
            ],
            st,
        )
    )

    story.extend(_ownership_analysis(inv, st))

    story.append(Paragraph("7. Shareholders and declared beneficial owners", st["h2"]))
    story.append(
        _table(
            t["shareholders"],
            [
                ("company", "Company", 2.5),
                ("owner", "Owner", 2.2),
                ("owner_type", "Type", 0.8),
                ("relation", "Relation", 1.4),
                ("share_pct", "%", 0.5),
                ("details", "Details", 2.5),
                ("sources", "Source", 2.3),
            ],
            st,
        )
    )

    story.append(Paragraph("8. Companies in the network", st["h2"]))
    story.append(
        _table(
            t["companies"],
            [
                ("name", "Company", 2.4),
                ("jurisdiction_name", "Jurisdiction", 1.2),
                ("registration_number", "Reg. no.", 1),
                ("status", "Status", 0.8),
                ("incorporation_date", "Incorporated", 1.05),
                ("last_accounts_date", "Last accounts", 1.05),
                ("depth", "Hops", 0.7),
                ("risk_level", "Risk", 0.7),
                ("flags", "Flags", 3),
            ],
            st,
        )
    )

    story.append(Paragraph("9. Sanctions & PEP screening", st["h2"]))
    story.append(
        _table(
            t["screening"],
            [
                ("entity", "Network entity", 1.8),
                ("matched_name", "Listed name", 1.8),
                ("list_type", "List", 0.6),
                ("dataset", "Dataset", 2),
                ("score", "Score", 0.5),
                ("status", "Status", 1.2),
                ("explanation", "Why", 3),
                ("details", "Details", 3),
            ],
            st,
            "No sanctions or PEP hit.",
        )
    )

    story.append(Paragraph("10. Appearances in leaks and investigative datasets", st["h2"]))
    story.append(
        _table(
            t["leaks"],
            [
                ("entity", "Network entity", 1.8),
                ("matched_name", "Name in dataset", 1.8),
                ("dataset", "Dataset", 2.2),
                ("score", "Score", 0.5),
                ("details", "Details", 4),
                ("url", "URL", 2.2),
            ],
            st,
            "No leak appearance.",
        )
    )

    if t.get("crypto"):
        story.append(Paragraph("10b. Crypto wallets and on-chain flows", st["h2"]))
        story.append(
            Paragraph(
                "Aggregated recent transfers per counterparty (one hop) from public explorers; "
                "wallets attributed to entities by sanctions lists or registries.",
                st["muted"],
            )
        )
        story.append(
            _table(
                t["crypto"],
                [
                    ("relation", "Relation", 1.2),
                    ("from", "From", 2.6),
                    ("to", "To", 2.6),
                    ("amount", "Amount", 0.9),
                    ("currency", "Cur.", 0.5),
                    ("tx_count", "Tx", 0.4),
                    ("since", "Since", 0.8),
                    ("sanctioned_party", "Sanctioned party", 2.2),
                ],
                st,
            )
        )

    dated = [d for d in t.get("documents", []) if d.get("date") or d.get("flags")]
    story.append(Paragraph("11. Linked documents (legal notices, filings)", st["h2"]))
    story.append(
        Paragraph(
            "Dated records from the sources; links to the official registers holding deeds, "
            "articles and filed accounts are listed in the application.",
            st["muted"],
        )
    )
    story.append(
        _table(
            dated[:80],
            [
                ("entity", "Entity", 2),
                ("date", "Date", 0.8),
                ("title", "Document", 2.6),
                ("summary", "Summary", 3.6),
                ("flags", "Flags", 0.8),
                ("url", "Link", 2.4),
            ],
            st,
            "No dated document.",
        )
    )

    if decisions:
        labels = {
            "confirmed": "Confirmed",
            "false_positive": "False positive",
            "to_review": "To review",
        }
        story.append(Paragraph("Analyst decisions (audit trail)", st["h2"]))
        story.append(
            Paragraph(
                "Hits marked as false positives are excluded from the score and the tables above.",
                st["muted"],
            )
        )
        story.append(
            _table(
                [
                    {
                        "item": d.get("item_label") or d["item_key"],
                        "decision": labels.get(d["decision"], d["decision"]),
                        "comment": d.get("comment", ""),
                        "by": d.get("author", ""),
                        "at": str(d.get("decided_at", ""))[:16].replace("T", " "),
                    }
                    for d in decisions
                ],
                [
                    ("item", "Item", 4),
                    ("decision", "Decision", 1.2),
                    ("comment", "Comment", 3.5),
                    ("by", "By", 1.2),
                    ("at", "When (UTC)", 1.4),
                ],
                st,
                "",
            )
        )

    if inv.timeline:
        story.append(Paragraph("11a. Timeline", st["h2"]))
        story.append(
            _table(
                [e.model_dump() for e in inv.timeline[:120]],
                [
                    ("date", "Date", 0.9),
                    ("kind", "Type", 0.9),
                    ("title", "Event", 4.2),
                    ("detail", "Detail", 3),
                    ("source", "Source", 2),
                ],
                st,
                "No dated event.",
            )
        )

    if inv.merges:
        story.append(Paragraph("11b. Cross-source entity resolution", st["h2"]))
        story.append(
            _table(
                [{**m, "explanation": "; ".join(m["explanation"])} for m in inv.merges],
                [
                    ("canonical_name", "Entity", 2),
                    ("merged_name", "Merged record", 2),
                    ("merged_source", "From source", 2.2),
                    ("score", "Score", 0.5),
                    ("explanation", "Evidence", 4),
                ],
                st,
            )
        )

    story.append(
        KeepTogether(
            [
                Paragraph("12. Sources consulted", st["h2"]),
                _table(
                    t["sources"],
                    [
                        ("source", "Source", 3),
                        ("queries", "Queries", 0.7),
                        ("records", "Records", 0.7),
                        ("errors", "Errors", 0.6),
                        ("first_retrieved", "First retrieval", 1.5),
                        ("last_retrieved", "Last retrieval", 1.5),
                    ],
                    st,
                ),
            ]
        )
    )
    if inv.warnings:
        story.append(Paragraph("Warnings", st["h2"]))
        for w in inv.warnings:
            story.append(Paragraph(f"• {_esc(w)}", st["small"]))

    # --------------------------------------------------- template sections
    if template == "review":
        story.append(Paragraph("Changes since the previous review", st["h2"]))
        story.append(
            _table(
                [
                    {
                        "when": str(c.get("run_at", ""))[:10],
                        "what": c["description"],
                        "sev": c["severity"],
                    }
                    for c in (changes or [])
                ],
                [("when", "Date", 1), ("sev", "Severity", 1), ("what", "Change", 8)],
                st,
                "No change recorded since the case was opened.",
            )
        )
    overview = (case_file or {}).get("overview")
    if overview:
        from app.report import charts

        story.append(CondPageBreak(60 * mm))
        story.append(Paragraph("Case file at a glance", st["h2"]))
        o = overview
        docs = o["documents"]
        sow_o = o.get("sow")
        story.append(
            charts.kpi_row(
                [
                    {
                        "label": "Risk score",
                        "value": f"{o['risk']['score']:.0f} / 100",
                        "sub": o["risk"]["level"],
                        "tone": charts.LEVEL_TONE.get(o["risk"]["level"], "neutral"),
                        "meter": (o["risk"]["score"], 100),
                    },
                    {
                        "label": "Vigilance",
                        "value": (o.get("vigilance") or "to assess").capitalize(),
                        "sub": "questionnaire",
                        "tone": {
                            "enhanced": "critical",
                            "standard": "warning",
                            "simplified": "good",
                        }.get(o.get("vigilance") or "", "neutral"),
                    },
                    {
                        "label": "Open alerts",
                        "value": o["alerts"]["open"],
                        "sub": f"{o['alerts']['total']} hit(s)",
                        "tone": "critical" if o["alerts"]["open"] else "good",
                    },
                    {
                        "label": "Documents",
                        "value": f"{docs['received']}/{docs['total']}",
                        "sub": f"{docs['required_missing']} required missing",
                        "tone": "warning" if docs["required_missing"] else "good",
                        "meter": (docs["received"], max(1, docs["total"])),
                    },
                    {
                        "label": "UBO form",
                        "value": " + ".join(o["cdb"]["forms"]) or "—",
                        "sub": f"{o['cdb']['missing']} field(s) to complete"
                        if o["cdb"]["missing"]
                        else "ready to sign",
                        "tone": "warning" if o["cdb"]["missing"] else "good",
                    },
                    {
                        "label": "Source of wealth",
                        "value": f"{round((sow_o['coverage'] or 0) * 100)} %"
                        if sow_o and sow_o.get("coverage") is not None
                        else "—",
                        "sub": sow_o["verdict"] if sow_o else "not documented",
                        "tone": {"plausible": "good", "partial": "warning", "gap": "critical"}.get(
                            (sow_o or {}).get("verdict", ""), "neutral"
                        ),
                    },
                    {
                        "label": "Ready for validation",
                        "value": f"{o['ready']}/{len(o['readiness'])}",
                        "sub": "conditions met",
                        "tone": "good" if o["ready"] == len(o["readiness"]) else "accent",
                        "meter": (o["ready"], len(o["readiness"])),
                    },
                ],
                WIDTH,
            )
        )
        story.append(Spacer(1, 8))
        t = o["alerts"]["triage"]
        story.append(Paragraph("Screening alerts by triage", st["h3"]))
        story.append(
            charts.stacked_bar(
                [
                    ("Likely match", t.get("likely", 0), charts.TONES["critical"]),
                    ("To check", t.get("verify", 0), charts.TONES["warning"]),
                    ("Probable namesake", t.get("namesake", 0), colors.HexColor(charts.SERIES[0])),
                    ("Silenced by memory", t.get("dismissed", 0), charts.TONES["neutral"]),
                ],
                WIDTH,
                fmt=lambda v: f"{v:.0f}",
            )
        )
    kyc = questionnaire or {}
    assessment = kyc.get("assessment")
    if assessment:
        from app.questionnaire import BY_ID, answer_label

        vigilance = {
            "simplified": "SIMPLIFIED",
            "standard": "STANDARD",
            "enhanced": "ENHANCED",
        }[assessment["level"]]
        story.append(Paragraph("KYC / AML-CFT questionnaire and vigilance level", st["h2"]))
        story.append(
            Paragraph(
                f"<b>Vigilance level: {vigilance}</b> — {assessment['points']} risk points"
                + (
                    f" · triggers: {_esc(', '.join(assessment['triggers']))}"
                    if assessment["triggers"]
                    else ""
                )
                + f" · next review by {assessment['next_review']}"
                + (
                    f"<br/>Adjusted by {_esc(assessment['override']['by'])} on "
                    f"{str(assessment['override']['at'])[:10]} from "
                    f"{assessment['computed_level'].upper()}: {_esc(assessment['override']['justification'])}"
                    if assessment.get("override")
                    else ""
                )
                + (
                    "<br/>Risk map: "
                    + " · ".join(
                        f"{v['label']} {v['score']}/100" for v in assessment["axes"].values()
                    )
                    if assessment.get("axes")
                    else ""
                ),
                st["warn"],
            )
        )
        story.append(Spacer(1, 6))
        answered = kyc.get("answered_at") or ""
        story.append(
            Paragraph(
                f"Answered {str(answered)[:16].replace('T', ' ')} UTC"
                + (f" by {_esc(kyc.get('author'))}" if kyc.get("author") else "")
                + (
                    f" · unanswered: {_esc(', '.join(assessment['missing']))}"
                    if assessment["missing"]
                    else ""
                ),
                st["muted"],
            )
        )
        story.append(
            _table(
                [
                    {"q": BY_ID[qid]["label"], "a": answer_label(qid, value)}
                    for qid, value in (kyc.get("answers") or {}).items()
                    if qid in BY_ID
                ],
                [("q", "Question", 4), ("a", "Answer", 7)],
                st,
                "",
            )
        )
        if assessment["reasons"]:
            story.append(Paragraph("What drives the level", st["h3"]))
            story.append(
                _table(
                    assessment["reasons"],
                    [("item", "Factor", 3.5), ("detail", "Detail", 6), ("points", "Points", 1)],
                    st,
                    "",
                )
            )
        story.append(Paragraph("Measures required", st["h3"]))
        for m in assessment["measures"]:
            story.append(Paragraph(f"☐ {_esc(m)}", st["body"]))
    checklist = (case_file or {}).get("checklist")
    if checklist:
        story.append(Paragraph("Case checklist", st["h2"]))
        story.append(Paragraph("Documents", st["h3"]))
        story.append(
            _table(
                [
                    {
                        "doc": ("☑ " if d["done"] else "☐ ") + d["label"],
                        "prio": "Required" if d["required"] else "Recommended",
                        "by": f"{d['by']} {str(d['at'] or '')[:10]}" if d["done"] else "",
                    }
                    for d in checklist["documents"]
                ],
                [
                    ("doc", "Document", 6),
                    ("prio", "Priority", 1.3),
                    ("by", "Received (by, on)", 2.2),
                ],
                st,
                "No document requested.",
            )
        )
        story.append(Paragraph("Additional diligences", st["h3"]))
        story.append(
            _table(
                [
                    {
                        "d": ("☑ " if d["done"] else "☐ ") + d["label"],
                        "by": f"{d['by']} {str(d['at'] or '')[:10]}" if d["done"] else "",
                    }
                    for d in checklist["diligences"]
                ],
                [("d", "Control", 7.5), ("by", "Done (by, on)", 2.2)],
                st,
                "",
            )
        )
    workflow = (case_file or {}).get("workflow")
    if workflow:
        actions = {
            "submit": "Sent for validation",
            "validate": "Validated",
            "reject": "Sent back",
            "reopen": "Reopened",
        }
        story.append(Paragraph("Validation (four-eyes principle)", st["h2"]))
        story.append(
            Paragraph(
                f"<b>Status: {_esc(workflow['label'])}</b>"
                + (
                    f" — validated by {_esc(workflow['validated_by'])} on "
                    f"{str(workflow['validated_at'])[:10]}"
                    if workflow.get("validated_by")
                    else ""
                ),
                st["warn"],
            )
        )
        story.append(Spacer(1, 6))
        story.append(
            _table(
                [
                    {
                        "at": str(h["at"])[:16].replace("T", " "),
                        "what": actions.get(h["action"], h["action"]),
                        "by": h["by"],
                        "comment": h.get("comment", ""),
                    }
                    for h in workflow["history"]
                ],
                [
                    ("at", "When (UTC)", 1.5),
                    ("what", "Step", 1.8),
                    ("by", "By", 1.5),
                    ("comment", "Comment", 5),
                ],
                st,
                "Not sent for validation yet.",
            )
        )
    cdb_data = (case_file or {}).get("cdb")
    if cdb_data and cdb_data.get("forms"):
        from app.report import charts

        story.append(CondPageBreak(50 * mm))
        story.append(Paragraph("Beneficial ownership forms (CDB 20)", st["h2"]))
        for f in cdb_data["forms"]:
            story.append(Paragraph(f"<b>{_esc(f['title'])}</b> — {_esc(f['entity'])}", st["body"]))
            story.append(Paragraph(_esc(f["why"]), st["muted"]))
            owners = [p for p in f["persons"] if p.get("pct") is not None]
            if owners:
                story.append(Spacer(1, 4))
                story.append(
                    charts.bar_list(
                        [
                            (
                                f"{p['first_name']} {p['last_name']}".strip(),
                                p["pct"],
                                f"{p['pct']:.1f} %",
                                charts.TONES["critical"]
                                if p.get("flags")
                                else charts.TONES["accent"],
                            )
                            for p in sorted(owners, key=lambda p: -p["pct"])
                        ],
                        WIDTH * 0.7,
                        100,
                        marker=25,
                        marker_label="25 % threshold",
                    )
                )
            story.append(Spacer(1, 4))
            story.append(
                _table(
                    [
                        {
                            "role": p["role_label"],
                            "name": f"{p['last_name']}, {p['first_name']}".strip(", "),
                            "birth": p.get("birth_date"),
                            "nat": p.get("nationality"),
                            "addr": ", ".join(x for x in (p.get("address"), p.get("country")) if x),
                            "basis": p["basis"],
                            "missing": ", ".join(p.get("missing") or []) or "complete",
                        }
                        for p in f["persons"]
                    ],
                    [
                        ("role", "Role", 1.4),
                        ("name", "Name", 2),
                        ("birth", "Born", 1),
                        ("nat", "Nationality", 1.4),
                        ("addr", "Domicile", 2.4),
                        ("basis", "Basis", 3),
                        ("missing", "To complete", 2),
                    ],
                    st,
                    "",
                )
            )
            for n in f.get("notes") or []:
                story.append(Paragraph("• " + _esc(n), st["muted"]))
            story.append(Spacer(1, 6))
    sow_data = (case_file or {}).get("sow")
    if sow_data and sow_data.get("sources"):
        from app.report import charts

        cur = sow_data["currency"]
        money = lambda v: f"{cur} {v:,.0f}".replace(",", "'")  # noqa: E731
        story.append(CondPageBreak(60 * mm))
        story.append(
            Paragraph(f"Source of wealth — {_esc(sow_data.get('person') or '')}", st["h2"])
        )
        story.append(
            charts.kpi_row(
                [
                    {"label": "Declared", "value": money(sow_data["declared_total"])},
                    {
                        "label": "Explained",
                        "value": money(sow_data["explained_total"]),
                        "tone": "accent",
                        "sub": f"{round((sow_data['coverage'] or 0) * 100)} % of declared"
                        if sow_data.get("coverage") is not None
                        else "",
                    },
                    {
                        "label": "Unexplained",
                        "value": money(sow_data["gap"] or 0),
                        "tone": "critical"
                        if sow_data["verdict"] == "gap"
                        else "warning"
                        if sow_data.get("gap")
                        else "good",
                    },
                    {
                        "label": "Corroborated",
                        "value": f"{sum(1 for x in sow_data['sources'] if x['corroborated'])}/{len(sow_data['sources'])}",
                        "sub": "sources with evidence",
                        "tone": "good"
                        if all(x["corroborated"] for x in sow_data["sources"])
                        else "warning",
                    },
                    {
                        "label": "Assessment",
                        "value": {
                            "plausible": "Plausible",
                            "partial": "Partial",
                            "gap": "Gap",
                            "incomplete": "Incomplete",
                        }[sow_data["verdict"]],
                        "tone": {"plausible": "good", "partial": "warning", "gap": "critical"}.get(
                            sow_data["verdict"], "neutral"
                        ),
                    },
                ],
                WIDTH,
            )
        )
        story.append(Spacer(1, 8))
        story.append(
            charts.stacked_bar(
                [
                    (x["label"], x["explained"], colors.HexColor(charts.SERIES[i % 8]))
                    for i, x in enumerate(sow_data["sources"])
                ],
                WIDTH,
                fmt=money,
                rest=("Unexplained gap", sow_data["gap"]) if sow_data.get("gap") else None,
                height=11,
            )
        )
        story.append(Spacer(1, 4))
        story.append(
            _table(
                [
                    {
                        "src": x["label"]
                        + (f" — {x['description']}" if x.get("description") else ""),
                        "amount": money(x["explained"]),
                        "how": x["how"],
                        "public": "; ".join(x["public"][:2]) or "no public record",
                        "docs": ", ".join(d["label"] for d in x["documents"] if d["received"])
                        or "none yet",
                    }
                    for x in sow_data["sources"]
                ],
                [
                    ("src", "Source", 3),
                    ("amount", "Explained", 1.4),
                    ("how", "Computation", 2),
                    ("public", "Public corroboration", 4),
                    ("docs", "Documents received", 2.4),
                ],
                st,
                "",
            )
        )
        for f in sow_data.get("flags") or []:
            story.append(Paragraph("• " + _esc(f["text"]), st["muted"]))
        story.append(Spacer(1, 4))
        story.append(Paragraph(_esc(sow_data["narrative"]), st["body"]))
    if inv.requests:
        story.append(Paragraph("Documents to request from the client", st["h2"]))
        story.append(
            _table(
                [
                    {
                        "doc": ("☐ " if template != "full" else "") + r.document,
                        "why": r.reason,
                        "prio": "Required" if r.priority == "required" else "Recommended",
                    }
                    for r in inv.requests
                ],
                [("doc", "Document", 5), ("prio", "Priority", 1.2), ("why", "Why", 4.5)],
                st,
                "",
            )
        )
    if template == "edd" and not (sow_data and sow_data.get("sources")):
        story.append(Paragraph("Source of wealth and source of funds assessment", st["h2"]))
        story.append(
            _table(
                [
                    {"item": item, "value": "\u00a0"}
                    for item in (
                        "Declared source of wealth (how the wealth was built)",
                        "Evidence received (documents, dates)",
                        "Plausibility of the source of wealth (analyst assessment)",
                        "Source of funds for this relationship (origin of the money deposited)",
                        "Evidence received for the source of funds",
                        "Expected activity (volumes, counterparties, countries)",
                        "Conclusion on source of wealth / funds",
                    )
                ],
                [("item", "Item", 4), ("value", "Analyst notes", 7)],
                st,
                "",
                row_height=34,
            )
        )
    if template in ("kyc", "edd", "review"):
        story.append(Paragraph("Decision and sign-off", st["h2"]))
        rows = [
            {"role": "Prepared by (analyst)", "name": analyst or "", "date": "", "sig": ""},
            {"role": "Reviewed by (second pair of eyes)", "name": "", "date": "", "sig": ""},
        ]
        if template == "edd":
            rows.append(
                {"role": "Approved by (senior management)", "name": "", "date": "", "sig": ""}
            )
        story.append(
            Paragraph(
                "Decision: ☐ Accept &nbsp;&nbsp; ☐ Accept with conditions / enhanced monitoring &nbsp;&nbsp; "
                "☐ Reject / exit the relationship &nbsp;&nbsp; ☐ Report to the financial intelligence unit",
                st["body"],
            )
        )
        story.append(Spacer(1, 4))
        story.append(
            _table(
                rows,
                [
                    ("role", "Role", 3),
                    ("name", "Name", 3),
                    ("date", "Date", 1.5),
                    ("sig", "Signature", 3),
                ],
                st,
                "",
            )
        )
        if template == "review":
            story.append(
                Paragraph(
                    f"Next review due: {assessment['next_review']} (vigilance level)"
                    if assessment
                    else "Next review due: ____ / ____ / ________ (per risk level)",
                    st["body"],
                )
            )

    skip = SKIPPED_SECTIONS.get(template, set())
    if skip:
        story = _drop_sections(story, skip)
    # Contents (on the cover), from the sections actually in this report
    sections = [
        f.getPlainText()
        for f in story
        if isinstance(f, Paragraph) and getattr(f.style, "name", "") == "h2"
    ]
    if sections:
        cols = 3
        per = (len(sections) + cols - 1) // cols
        toc = Table(
            [
                [
                    Paragraph(_esc(sections[c * per + r]), st["small"])
                    if c * per + r < len(sections)
                    else ""
                    for c in range(cols)
                ]
                for r in range(per)
            ],
            colWidths=[WIDTH / cols] * cols,
        )
        toc.setStyle(
            TableStyle(
                [("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]
            )
        )
        story[toc_index:toc_index] = [Paragraph("Contents", st["h3"]), toc]
    story = _underline_headings(story)
    doc.build(story, onFirstPage=on_cover, onLaterPages=on_page, canvasmaker=_NumberedCanvas)
    return buf.getvalue()
