"""Small vector charts for the PDFs: KPI tiles, meters, stacked bars, ownership bars.

Same rules as the web app: thin marks, 2 pt gaps between touching segments, a light
same-family track under meters, values and labels in text ink (the colour sits on the mark
beside them), and a legend with the values so nothing depends on colour alone.
"""

from __future__ import annotations

from typing import Any

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Paragraph, Table, TableStyle

INK = colors.HexColor("#101828")
MUTED = colors.HexColor("#667085")
TRACK = colors.HexColor("#eaecf0")
AXIS = colors.HexColor("#98a2b3")
TONES = {
    "good": colors.HexColor("#12a150"),
    "warning": colors.HexColor("#e08a00"),
    "serious": colors.HexColor("#e5590c"),
    "critical": colors.HexColor("#d92d20"),
    "neutral": colors.HexColor("#98a2b3"),
    "accent": colors.HexColor("#1f9467"),
}
# Validated categorical order (light surface): identity of series, never status.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
LEVEL_TONE = {
    "none": "good",
    "low": "good",
    "medium": "warning",
    "high": "serious",
    "critical": "critical",
    "incomplete": "neutral",
}


def tone(name: str | None) -> colors.Color:
    return TONES.get(name or "neutral", TONES["neutral"])


def meter(
    value: float, maximum: float, color: colors.Color, width: float, height: float = 4
) -> Drawing:
    d = Drawing(width, height)
    d.add(
        Rect(0, 0, width, height, rx=height / 2, ry=height / 2, fillColor=TRACK, strokeColor=None)
    )
    frac = max(0.0, min(1.0, value / maximum)) if maximum else 0.0
    if frac > 0:
        w = max(height, width * frac)
        d.add(
            Rect(0, 0, w, height, rx=height / 2, ry=height / 2, fillColor=color, strokeColor=None)
        )
    return d


def kpi_row(
    tiles: list[dict[str, Any]], width: float, font: str = "DejaVu", bold: str = "DejaVu-Bold"
) -> Table:
    """tiles: {label, value, sub?, tone?, meter?: (value, max)}"""
    lab = ParagraphStyle("kl", fontName=font, fontSize=7, leading=9, textColor=MUTED)
    sub = ParagraphStyle("ks", fontName=font, fontSize=6.8, leading=8.5, textColor=MUTED)
    n = len(tiles)
    gap = 6
    cw = (width - gap * (n - 1)) / n
    cells = []
    size = 15.0
    for t in tiles:  # one value size for the whole row, small enough for the longest value
        while size > 9 and stringWidth(str(t["value"]), bold, size) > cw - 16:
            size -= 0.5
    val = ParagraphStyle("kv", fontName=bold, fontSize=size, leading=size * 1.2, textColor=INK)
    has_sub = any(t.get("sub") for t in tiles)
    has_meter = any(t.get("meter") for t in tiles)
    for t in tiles:
        col = tone(t.get("tone"))
        dot = f"<font color='{col.hexval().replace('0x', '#')}'>●</font> " if t.get("tone") else ""
        inner: list[Any] = [Paragraph(dot + str(t["label"]), lab), Paragraph(str(t["value"]), val)]
        if has_sub and not t.get("sub"):
            inner.append(Paragraph("&nbsp;", sub))
        if has_meter and not t.get("meter"):
            inner.append(Drawing(cw - 14, 4))
        if t.get("sub"):
            inner.append(Paragraph(str(t["sub"]), sub))
        if t.get("meter"):
            v, m = t["meter"]
            inner.append(meter(v, m, col, cw - 14))
        box = Table([[x] for x in inner], colWidths=[cw - 2])
        box.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, TRACK),
                    ("LINEBEFORE", (0, 0), (0, -1), 2.2, col if t.get("tone") else TRACK),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 1.2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
                    ("TOPPADDING", (0, 0), (-1, 0), 5),
                    ("BOTTOMPADDING", (0, -1), (-1, -1), 5),
                ]
            )
        )
        cells.append(box)
    row: list[Any] = []
    widths = []
    for i, c in enumerate(cells):
        if i:
            row.append("")
            widths.append(gap)
        row.append(c)
        widths.append(cw)
    t = Table([row], colWidths=widths)
    t.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return t


def stacked_bar(
    segments: list[tuple[str, float, colors.Color]],
    width: float,
    fmt=lambda v: f"{v:g}",
    rest: tuple[str, float] | None = None,
    height: float = 9,
    font: str = "DejaVu",
    bold: str = "DejaVu-Bold",
) -> Drawing:
    """Part-to-whole bar with a 2 pt gap between segments, and a legend (label + value) below."""
    shown = [s for s in segments if s[1] > 0]
    total = sum(s[1] for s in shown) + (rest[1] if rest else 0)
    legend_items = [(lab, v, c) for lab, v, c in segments] + (
        [(rest[0], rest[1], None)] if rest and rest[1] else []
    )
    # legend layout: wrap items on lines
    lines: list[list[tuple[str, float, Any, float]]] = [[]]
    x = 0.0
    for lab, v, c in legend_items:
        w = 10 + stringWidth(lab, font, 7) + 4 + stringWidth(fmt(v), bold, 7) + 14
        if x + w > width and lines[-1]:
            lines.append([])
            x = 0
        lines[-1].append((lab, v, c, x))
        x += w
    lh = 11
    h = height + 6 + lh * len(lines)
    d = Drawing(width, h)
    y = h - height
    if total <= 0:
        d.add(Rect(0, y, width, height, rx=2, ry=2, fillColor=TRACK, strokeColor=None))
    else:
        parts = [(v, c) for _, v, c in shown] + ([(rest[1], None)] if rest and rest[1] else [])
        gaps = 2 * (len(parts) - 1)
        x = 0.0
        for v, c in parts:
            w = max(2.0, (width - gaps) * v / total)
            if c is None:
                d.add(
                    Rect(x, y, w, height, fillColor=colors.white, strokeColor=AXIS, strokeWidth=0.6)
                )
                step = 4
                k = 0.0
                while k < w + height:
                    x1, y1 = x + max(0.0, k - height), y + min(height, k)
                    x2, y2 = x + min(w, k), y + max(0.0, k - w)
                    d.add(Line(x1, y1, x2, y2, strokeColor=AXIS, strokeWidth=0.6))
                    k += step
            else:
                d.add(Rect(x, y, w, height, fillColor=c, strokeColor=None))
            x += w + 2
    for i, line in enumerate(lines):
        ly = h - height - 6 - lh * (i + 1) + 2
        for lab, v, c, lx in line:
            if c is None:
                d.add(Rect(lx, ly, 7, 7, fillColor=colors.white, strokeColor=AXIS, strokeWidth=0.6))
                d.add(Line(lx, ly, lx + 7, ly + 7, strokeColor=AXIS, strokeWidth=0.6))
            else:
                d.add(Rect(lx, ly, 7, 7, rx=1.5, ry=1.5, fillColor=c, strokeColor=None))
            d.add(String(lx + 10, ly + 0.5, lab, fontName=font, fontSize=7, fillColor=MUTED))
            d.add(
                String(
                    lx + 10 + stringWidth(lab, font, 7) + 4,
                    ly + 0.5,
                    fmt(v),
                    fontName=bold,
                    fontSize=7,
                    fillColor=INK,
                )
            )
    return d


def bar_list(
    rows: list[tuple[str, float, str, colors.Color]],
    width: float,
    maximum: float,
    marker: float | None = None,
    marker_label: str | None = None,
    font: str = "DejaVu",
    bold: str = "DejaVu-Bold",
) -> Drawing:
    """Horizontal thin bars: (label, value, display, colour), optional vertical threshold."""
    label_w = min(170.0, width * 0.34)
    value_w = 44.0
    track_w = width - label_w - value_w - 8
    rh = 15
    extra = 12 if marker is not None and marker_label else 0
    h = rh * len(rows) + extra + 2
    d = Drawing(width, h)
    for i, (lab, v, disp, col) in enumerate(rows):
        y = h - rh * (i + 1) + 4
        text = lab if len(lab) <= 38 else lab[:37] + "…"
        d.add(String(0, y, text, fontName=font, fontSize=7.5, fillColor=INK))
        d.add(Rect(label_w, y, track_w, 5, rx=2.5, ry=2.5, fillColor=TRACK, strokeColor=None))
        w = max(2.5, track_w * min(1.0, v / maximum)) if maximum else 0
        d.add(Rect(label_w, y, w, 5, rx=2.5, ry=2.5, fillColor=col, strokeColor=None))
        d.add(String(width, y, disp, fontName=bold, fontSize=7.5, fillColor=INK, textAnchor="end"))
    if marker is not None and maximum:
        mx = label_w + track_w * marker / maximum
        d.add(Line(mx, extra, mx, h, strokeColor=MUTED, strokeWidth=0.7))
        if marker_label:
            d.add(String(mx + 3, 1, marker_label, fontName=font, fontSize=6.5, fillColor=MUTED))
    return d
