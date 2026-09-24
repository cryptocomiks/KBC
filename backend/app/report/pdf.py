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
from reportlab.platypus import (
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

INK = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#64748b")
LINE = colors.HexColor("#cbd5e1")
HEAD_BG = colors.HexColor("#e2e8f0")
LEVEL_COLORS = {
    "low": colors.HexColor("#15803d"),
    "medium": colors.HexColor("#b45309"),
    "high": colors.HexColor("#c2410c"),
    "critical": colors.HexColor("#b91c1c"),
    "none": MUTED,
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
            "head", parent=body, fontName="DejaVu-Bold", fontSize=7, leading=8.6
        ),
        "h1": ParagraphStyle("h1", parent=body, fontName="DejaVu-Bold", fontSize=18, leading=22),
        "h2": ParagraphStyle(
            "h2",
            parent=body,
            fontName="DejaVu-Bold",
            fontSize=12,
            leading=15,
            spaceBefore=10,
            spaceAfter=5,
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
            textColor=colors.HexColor("#7c2d12"),
            backColor=colors.HexColor("#ffedd5"),
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
) -> Any:
    """columns: (key, header, relative width)."""
    if not rows:
        return Paragraph(empty, st["muted"])
    total = sum(w for _, _, w in columns)
    widths = [WIDTH * w / total for _, _, w in columns]
    data = [[Paragraph(h, st["head"]) for _, h, _ in columns]]
    for row in rows:
        data.append([Paragraph(_esc(row.get(k)), st["cell"]) for k, _, _ in columns])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
                ("GRID", (0, 0), (-1, -1), 0.3, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
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


def build_pdf(
    inv: Investigation,
    graph_png_b64: str | None = None,
    analyst: str | None = None,
    reference: str | None = None,
    decisions: list[dict] | None = None,
) -> bytes:
    st = _styles()
    ents = {e.id: e for e in inv.entities}
    subject = ents[inv.subject_id]
    jur = get_jurisdictions()
    risk = inv.risk
    buf = io.BytesIO()

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("DejaVu", 7)
        canvas.setFillColor(MUTED)
        footer = f"KBC Corporate Mapping — Due diligence report on {subject.name} — generated {inv.generated_at:%Y-%m-%d %H:%M} UTC"
        canvas.drawString(MARGIN, 8 * mm, footer)
        canvas.drawRightString(PAGE[0] - MARGIN, 8 * mm, f"Page {doc.page}")
        canvas.drawString(
            MARGIN,
            PAGE[1] - 8 * mm,
            "CONFIDENTIAL — for compliance use only — findings require human verification",
        )
        if inv.demo:
            canvas.setFont("DejaVu-Bold", 60)
            canvas.setFillColor(colors.Color(0.8, 0.1, 0.1, alpha=0.07))
            canvas.translate(PAGE[0] / 2, PAGE[1] / 2)
            canvas.rotate(25)
            canvas.drawCentredString(0, 0, "DEMO — FICTITIOUS DATA")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf,
        pagesize=PAGE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=f"Due diligence report — {subject.name}",
        author=analyst or "KBC",
    )
    story: list[Any] = []

    # ---------------------------------------------------------------- header
    story.append(Paragraph(f"Due Diligence Report — {_esc(subject.name)}", st["h1"]))
    meta = [
        f"Subject type: <b>{subject.type.value}</b>",
        f"Generated: <b>{inv.generated_at:%Y-%m-%d %H:%M} UTC</b>",
        f"Network depth: <b>{inv.params.depth}</b> (node limit {inv.params.max_nodes})",
    ]
    if reference:
        meta.append(f"Reference: <b>{_esc(reference)}</b>")
    if analyst:
        meta.append(f"Analyst: <b>{_esc(analyst)}</b>")
    story.append(Paragraph(" &nbsp;·&nbsp; ".join(meta), st["muted"]))
    story.append(Spacer(1, 6))
    disclaimer = inv.disclaimer
    if inv.demo:
        disclaimer = (
            "DEMO MODE — all persons, companies and list entries in this report are fictitious. "
            + disclaimer
        )
    story.append(Paragraph(_esc(disclaimer), st["warn"]))
    story.append(Spacer(1, 8))

    # ------------------------------------------------------ executive summary
    level_color = LEVEL_COLORS.get(risk.level, INK)
    score_box = Table(
        [
            [
                Paragraph(
                    f"<font size=26><b>{risk.score:g}</b></font><font size=10> / 100</font>",
                    ParagraphStyle("score", parent=st["body"], leading=30),
                )
            ],
            [
                Paragraph(
                    f"<font color='{level_color.hexval()}'><b>{risk.level.upper()} RISK</b></font>",
                    st["body"],
                )
            ],
        ],
        colWidths=[45 * mm],
    )
    score_box.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1, level_color),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    s = inv.stats
    key_figures = Paragraph(
        f"Network: <b>{s['persons']}</b> persons, <b>{s['companies']}</b> companies, "
        f"<b>{s['addresses']}</b> addresses, <b>{s['relationships']}</b> relationships.<br/>"
        f"Screening: <b>{len(inv.tables['screening'])}</b> sanctions/PEP hits, "
        f"<b>{len(inv.tables['leaks'])}</b> leak appearances.<br/>"
        f"Sources: <b>{s['sources']}</b> sources, <b>{s['queries']}</b> queries. "
        f"Cross-source merges: <b>{len(inv.merges)}</b>."
        + (
            "<br/><font color='#b91c1c'>Network truncated at node limit — results are partial.</font>"
            if inv.truncated
            else ""
        ),
        st["body"],
    )
    top = (
        "".join(
            f"• <b>{_esc(f.label)}</b> (+{f.points:g}) — {_esc(f.evidence[0])}<br/>"
            for f in risk.factors[:6]
        )
        or "No risk factor triggered."
    )
    summary = Table(
        [[score_box, key_figures, Paragraph(top, st["small"])]],
        colWidths=[50 * mm, 80 * mm, WIDTH - 130 * mm],
    )
    summary.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(Paragraph("1. Executive summary", st["h2"]))
    b = inv.brief
    if b:
        verdict_color = {"critical": "#991b1b", "high": "#9a3412", "medium": "#92400e"}.get(
            b.level, "#065f46"
        )
        story.append(
            Paragraph(f"<font color='{verdict_color}'><b>{_esc(b.headline)}</b></font>", st["body"])
        )
        story.append(
            Paragraph(
                " · ".join(f"<b>{_esc(f.label)}</b>: {_esc(f.value)}" for f in b.figures),
                st["small"],
            )
        )
    story.append(summary)
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
        }
        for f in risk.factors
    ]
    story.append(
        _table(
            rows,
            [
                ("label", "Factor", 2.2),
                ("weight", "Weight", 0.75),
                ("distance", "Hops", 0.5),
                ("mult", "Proximity", 0.9),
                ("points", "Points", 0.7),
                ("evidence", "Evidence", 7),
            ],
            st,
            "No risk factor triggered.",
        )
    )
    story.append(Spacer(1, 3))
    story.append(Paragraph("<br/>".join(_esc(m) for m in risk.methodology), st["small"]))

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
                ("depth", "Hops", 0.55),
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

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
