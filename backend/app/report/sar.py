"""Draft of a suspicious activity / transaction report (SAR/STR), pre-filled from an investigation.

The draft follows the structure of the national financial intelligence unit's
form so the analyst can transfer it into the official channel (ERMES for
TRACFIN, goAML for MROS and the Luxembourg CRF). It is a working document:
facts must be checked and completed (bank transactions, measures taken) before
filing, and the tipping-off prohibition applies from the moment it is drafted.
"""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.models import EntityType, ListType, RelationType
from app.report.pdf import MARGIN, PAGE, _esc, _styles, _table
from app.schemas import Investigation

FIU = {
    "tracfin": {
        "name": "TRACFIN (France)",
        "channel": "ERMES portal — https://www.economie.gouv.fr/tracfin",
        "basis": "Déclaration de soupçon — art. L561-15 du Code monétaire et financier",
        "tipping_off": "Interdiction de divulgation : art. L561-18 CMF — ne pas informer le client ni des tiers.",
        "lang": "fr",
    },
    "mros": {
        "name": "MROS — Money Laundering Reporting Office Switzerland",
        "channel": "goAML — https://www.fedpol.admin.ch/fedpol/en/home/kriminalitaet/geldwaescherei.html",
        "basis": "Report under art. 9 AMLA (duty to report) / art. 305ter para. 2 SCC (right to report)",
        "tipping_off": "Prohibition of information: art. 10a AMLA — do not inform the client or third parties.",
        "lang": "en",
    },
    "lu_crf": {
        "name": "CRF — Cellule de renseignement financier (Luxembourg)",
        "channel": "goAML — https://justice.public.lu/fr/organisation-justice/crf.html",
        "basis": "Report under art. 5 of the law of 12 November 2004 on the fight against money laundering",
        "tipping_off": "Prohibition of disclosure: art. 5(5) of the law of 12 November 2004.",
        "lang": "en",
    },
}

TEXT = {
    "fr": {
        "title": "Projet de déclaration de soupçon",
        "draft": "BROUILLON — NON TRANSMIS. Document de travail à vérifier et compléter avant toute déclaration.",
        "s1": "1. Déclarant",
        "s2": "2. Personne ou entité objet de la déclaration",
        "s3": "3. Personnes et entités liées",
        "s4": "4. Motifs du soupçon",
        "s5": "5. Chronologie des faits",
        "s6": "6. Opérations",
        "s7": "7. Mesures prises",
        "s8": "8. Pièces jointes",
        "declarant": [
            "Établissement déclarant",
            "Correspondant / déclarant Tracfin",
            "Coordonnées",
            "Référence interne du dossier",
        ],
        "ops_hint": "Compléter avec les opérations bancaires concernées (dates, montants, comptes, contreparties).",
        "measures": [
            "☐ Relation d'affaires suspendue / refusée",
            "☐ Opération non exécutée / reportée",
            "☐ Vigilance renforcée mise en place",
            "☐ Fonds gelés (sanctions) — information de la DG Trésor",
        ],
        "attachments": [
            "Rapport de vigilance KYC 1 CLICK (PDF) — mêmes paramètres",
            "Pièces KYC collectées (identité, extrait Kbis, déclaration des bénéficiaires effectifs…)",
            "Relevés des opérations concernées",
        ],
        "none": "Aucun élément.",
    },
    "en": {
        "title": "Draft suspicious activity report",
        "draft": "DRAFT — NOT SUBMITTED. Working document to check and complete before any filing.",
        "s1": "1. Reporting entity",
        "s2": "2. Subject of the report",
        "s3": "3. Related persons and entities",
        "s4": "4. Grounds for suspicion",
        "s5": "5. Chronology of facts",
        "s6": "6. Transactions",
        "s7": "7. Measures taken",
        "s8": "8. Attachments",
        "declarant": [
            "Reporting institution",
            "Compliance officer / reporter",
            "Contact details",
            "Internal case reference",
        ],
        "ops_hint": "Complete with the bank transactions concerned (dates, amounts, accounts, counterparties).",
        "measures": [
            "☐ Business relationship suspended / refused",
            "☐ Transaction not executed / postponed",
            "☐ Enhanced monitoring in place",
            "☐ Assets frozen (sanctions) — competent authority informed",
        ],
        "attachments": [
            "KYC 1 CLICK due diligence report (PDF) — same parameters",
            "KYC documents collected (ID, register extract, UBO declaration…)",
            "Statements of the transactions concerned",
        ],
        "none": "None.",
    },
}


def build_sar(
    inv: Investigation,
    fiu: str = "tracfin",
    lang: str | None = None,
    reference: str | None = None,
    decisions: list[dict] | None = None,
) -> bytes:
    info = FIU.get(fiu, FIU["tracfin"])
    t = TEXT[lang or info["lang"]]
    st = _styles()
    ents = {e.id: e for e in inv.entities}
    subject = ents[inv.subject_id]
    name = lambda eid: ents[eid].name if eid in ents else eid  # noqa: E731
    rejected = {d["item_key"].lower() for d in decisions or [] if d["decision"] == "false_positive"}
    buf = io.BytesIO()

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("DejaVu", 7)
        canvas.setFillColor(colors.HexColor("#b91c1c"))
        canvas.drawString(MARGIN, PAGE[1] - 20, t["draft"])
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(MARGIN, 18, f"{info['name']} · {info['tipping_off']}")
        canvas.drawRightString(PAGE[0] - MARGIN, 18, f"{doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf,
        pagesize=PAGE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=f"{t['title']} — {subject.name}",
    )
    story: list[Any] = [
        Paragraph(f"{t['title']} — {_esc(subject.name)}", st["h1"]),
        Paragraph(
            f"<b>{_esc(info['name'])}</b> · {_esc(info['basis'])}<br/>{_esc(info['channel'])}",
            st["muted"],
        ),
        Spacer(1, 4),
        Spacer(1, 4),
        Paragraph(f"<b>{_esc(t['draft'])}</b><br/>{_esc(info['tipping_off'])}", st["warn"]),
        Spacer(1, 8),
    ]
    if inv.demo:
        story.append(Paragraph("DEMO — fictitious data, not for filing.", st["warn"]))
        story.append(Spacer(1, 8))

    # 1. Reporting entity (to fill in)
    story.append(Paragraph(t["s1"], st["h2"]))
    story.append(
        _table(
            [
                {
                    "k": k,
                    "v": (
                        reference if "reference" in k.lower() or "référence" in k.lower() else None
                    )
                    or " ",
                }
                for k in t["declarant"]
            ],
            [("k", "", 3), ("v", "", 7)],
            st,
            "",
            row_height=20,
        )
    )

    # 2. Subject
    story.append(Paragraph(t["s2"], st["h2"]))
    rows = [
        ("Name / Nom", subject.name),
        ("Type", subject.type.value),
        ("Aliases", ", ".join(subject.aliases)),
    ]
    if subject.type == EntityType.PERSON:
        rows += [
            ("Date of birth", subject.birth_date),
            ("Nationality", ", ".join(subject.nationalities)),
        ]
    else:
        rows += [
            ("Registration no.", subject.registration_number),
            ("Jurisdiction", subject.jurisdiction),
            ("Legal form", subject.legal_form),
            ("Status", subject.status.value if subject.status else None),
        ]
    rows += [
        ("Address", subject.address),
        ("Identifiers", ", ".join(f"{k}: {v}" for k, v in subject.identifiers.items())),
    ]
    story.append(
        _table([{"k": k, "v": v} for k, v in rows if v], [("k", "", 2.5), ("v", "", 7.5)], st)
    )

    # 3. Related persons and entities
    story.append(Paragraph(t["s3"], st["h2"]))
    related = []
    if inv.brief:
        for o in inv.brief.owners:
            related.append(
                {
                    "who": o.name,
                    "link": f"{'holding' if inv.brief.subject_type == 'person' else 'owner'} "
                    f"{o.pct:.1f} % ({' → '.join(o.path)})",
                    "flags": ", ".join(o.flags),
                }
            )
    for r in inv.relationships:
        if r.type == RelationType.OFFICER and r.target_id == subject.id and r.is_active:
            related.append({"who": name(r.source_id), "link": r.role or "officer", "flags": ""})
    flagged = {h.entity_id for h in inv.hits if h.score >= 85 and h.triage != "dismissed"}
    for eid in flagged:
        if eid != subject.id and not any(x["who"] == name(eid) for x in related):
            related.append(
                {
                    "who": name(eid),
                    "link": f"in the network ({inv.depth.get(eid, '?')} link(s))",
                    "flags": "screening hit",
                }
            )
    story.append(
        _table(
            related[:40],
            [("who", "Name", 3), ("link", "Link to the subject", 5), ("flags", "Flags", 2)],
            st,
            t["none"],
        )
    )

    # 4. Grounds for suspicion
    story.append(Paragraph(t["s4"], st["h2"]))
    grounds = []
    for f in sorted(inv.risk.factors, key=lambda f: -f.points):
        grounds.append({"flag": f.label, "evidence": "; ".join(f.evidence[:3])})
    for h in inv.hits:
        key = f"hit|{name(h.entity_id)}|{h.dataset}|{h.matched_name}".lower()
        if (
            h.score >= 85
            and key not in rejected
            and h.triage != "dismissed"
            and h.list_type in (ListType.SANCTION, ListType.ADVERSE)
        ):
            grounds.append(
                {
                    "flag": f"{h.list_type.value.upper()} — {h.dataset}",
                    "evidence": f"{name(h.entity_id)} ≈ {h.matched_name} ({h.score:.0f} %). {h.provenance.url or ''}",
                }
            )
    story.append(
        _table(
            grounds[:30],
            [("flag", "Indicator", 3), ("evidence", "Facts and sources", 7)],
            st,
            t["none"],
        )
    )
    story.append(
        Paragraph(
            "Analyst's narrative: why the facts, taken together, raise a suspicion (to write):",
            st["small"],
        )
    )
    story.append(_table([{"v": " "}], [("v", "", 10)], st, "", row_height=90))

    # 5. Chronology
    story.append(Paragraph(t["s5"], st["h2"]))
    keep = {"sanction", "legal_notice", "ownership", "role", "transfer", "company", "media"}
    events = [e for e in inv.timeline if e.kind in keep][:40]
    story.append(
        _table(
            [
                {"d": e.date, "e": e.title, "s": e.source or ""}
                for e in sorted(events, key=lambda e: e.date)
            ],
            [("d", "Date", 1.2), ("e", "Event", 6), ("s", "Source", 2.8)],
            st,
            t["none"],
        )
    )

    # 6. Transactions
    story.append(Paragraph(t["s6"], st["h2"]))
    flows = [
        {
            "from": name(r.source_id),
            "to": name(r.target_id),
            "amt": f"{r.amount:,.2f} {r.currency or ''}",
            "n": r.tx_count,
            "period": f"{r.start_date or '?'} → {r.end_date or '?'}",
        }
        for r in inv.relationships
        if r.type == RelationType.TRANSFER
    ]
    if flows:
        story.append(Paragraph("On-chain flows identified (public blockchain data):", st["small"]))
        story.append(
            _table(
                flows,
                [
                    ("from", "From", 3),
                    ("to", "To", 3),
                    ("amt", "Amount", 1.8),
                    ("n", "Tx", 0.6),
                    ("period", "Period", 2),
                ],
                st,
            )
        )
    story.append(Paragraph(t["ops_hint"], st["small"]))
    story.append(
        _table(
            [{"d": " ", "a": " ", "acc": " ", "c": " "} for _ in range(4)],
            [
                ("d", "Date", 1.5),
                ("a", "Amount", 1.5),
                ("acc", "Account", 3),
                ("c", "Counterparty", 4),
            ],
            st,
            "",
            row_height=18,
        )
    )

    # 7. Measures / 8. Attachments
    story.append(Paragraph(t["s7"], st["h2"]))
    for m in t["measures"]:
        story.append(Paragraph(m, st["body"]))
    story.append(Paragraph(t["s8"], st["h2"]))
    for a in t["attachments"]:
        story.append(Paragraph(f"• {_esc(a)}", st["body"]))
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
