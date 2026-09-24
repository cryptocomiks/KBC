"""Read client documents (register extracts, UBO declarations) and compare them with the registries.

Rules only — no AI, nothing sent to a third party, nothing stored: the file is
read in memory and forgotten. Supported: text PDFs and plain text (scanned
PDFs need OCR and are reported as unreadable). Formats recognised by their
labels: French Kbis / RBE, UK Companies House (officers, PSC), Swiss and
Luxembourg register extracts, and generic "name … %" ownership lines.

Extraction is heuristic, so the result is returned as editable rows: the
analyst corrects them in the UI before the comparison, which is exact.
"""

from __future__ import annotations

import io
import re
from typing import Any

import networkx as nx
from pydantic import BaseModel, Field

from app.graph.expander import Network
from app.graph.ownership import ownership_graph
from app.insights import _best_paths
from app.matching.names import name_similarity
from app.models import EntityType, RelationType

MAX_BYTES = 10 * 1024 * 1024
PCT = re.compile(r"(\d{1,3}(?:[.,]\d{1,2})?)\s?%")

# Role words (FR / EN / DE / IT) -> normalised English role
ROLE_WORDS = [
    (r"pr[ée]sident(?:e)? du conseil|chair(?:man|person)?|präsident des verwaltungsrates", "Chair"),
    (r"directeur g[ée]n[ée]ral d[ée]l[ée]gu[ée]", "Deputy CEO"),
    (r"directeur g[ée]n[ée]ral|chief executive|ceo|generaldirektor", "CEO"),
    (r"pr[ée]sident(?:e)?", "President"),
    (r"g[ée]rant(?:e)?|managing director|geschäftsführer(?:in)?", "Managing director"),
    (r"administrat(?:eur|rice)|director|verwaltungsrat|mitglied des verwaltungsrates", "Director"),
    (r"secr[ée]taire|secretary", "Secretary"),
    (r"commissaire aux comptes|auditor|revisionsstelle", "Auditor"),
]
ROLE_RE = re.compile("|".join(f"(?:{p})" for p, _ in ROLE_WORDS), re.I)
NAME_LABELS = re.compile(
    r"^(?:nom,?\s*pr[ée]noms?|nom\s+d'usage|nom|name|full name|surname and forenames?)\s*[:\-]?\s*(.+)$",
    re.I,
)
COMPANY_LABELS = re.compile(
    r"^(?:d[ée]nomination(?:\s+sociale)?|raison sociale|company name|name of company|firma|firm name|"
    r"denominazione)\s*[:\-]?\s*(.+)$",
    re.I,
)
REG_PATTERNS = [
    (re.compile(r"\b(\d{3}\s?\d{3}\s?\d{3})\s+R\.?C\.?S\.?", re.I), "SIREN"),
    (re.compile(r"R\.?C\.?S\.?\s+[A-ZÀ-Ü][\w\-' ]+?\s+(\d{3}\s?\d{3}\s?\d{3})", re.I), "SIREN"),
    (re.compile(r"\b(CHE[-\s]?\d{3}\.\d{3}\.\d{3})\b"), "UID"),
    (re.compile(r"company number[:\s]+([A-Z]{0,2}\d{6,8})", re.I), "Company number"),
    (re.compile(r"\bR\.?C\.?S\.?\s*Luxembourg\s*[:\-]?\s*(B\s?\d{3,7})", re.I), "RCS Luxembourg"),
    (re.compile(r"\b([A-Z0-9]{18}\d{2})\b"), "LEI"),
]
ADDRESS_LABELS = re.compile(
    r"^(?:adresse du si[èe]ge|si[èe]ge social|registered office(?: address)?|domicile|sitz|adresse)\s*[:\-]?\s*(.+)$",
    re.I,
)
UBO_SECTION = re.compile(
    r"b[ée]n[ée]ficiaire|beneficial owner|persons? with significant control|psc|wirtschaftlich berechtigt",
    re.I,
)
# Lines that describe a holding rather than name a holder
NOT_A_NAME = re.compile(
    r"^(d[ée]tention|d[ée]tient|holding|ownership|nature of control|voting rights|droits de vote|part(s)? "
    r"|capital|pourcentage|percentage|total|dont|of which|soit)",
    re.I,
)
CONTROL_PSC = re.compile(r"(\d{2})\s?%\s?or more|more than (\d{2})\s?%", re.I)


class DeclaredCompany(BaseModel):
    name: str | None = None
    registration_number: str | None = None
    address: str | None = None


class DeclaredPerson(BaseModel):
    name: str
    role: str | None = None
    pct: float | None = None
    birth: str | None = None


class Extraction(BaseModel):
    kind: str  # kbis | ubo | companies_house | generic
    pages: int = 0
    characters: int = 0
    company: DeclaredCompany = Field(default_factory=DeclaredCompany)
    officers: list[DeclaredPerson] = Field(default_factory=list)
    owners: list[DeclaredPerson] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def read_text(data: bytes, filename: str) -> tuple[str, int]:
    if len(data) > MAX_BYTES:
        raise ValueError("File too large (10 MB max).")
    if filename.lower().endswith(".pdf") or data[:5] == b"%PDF-":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages), len(reader.pages)
    return data.decode("utf-8", errors="replace"), 1


def _clean_name(raw: str) -> str:
    raw = re.split(r"\s{2,}|\t| né[e]? le | born | date de naissance", raw, maxsplit=1, flags=re.I)[
        0
    ]
    raw = re.sub(r"^(M\.|Mme|Mr\.?|Mrs\.?|Ms\.?|Monsieur|Madame)\s+", "", raw.strip(), flags=re.I)
    return raw.strip(" ,;:-")


def _role(text: str) -> str | None:
    for pattern, label in ROLE_WORDS:
        if re.search(pattern, text, re.I):
            return label
    return None


def _pct(text: str) -> float | None:
    m = PCT.search(text)
    if m:
        v = float(m.group(1).replace(",", "."))
        return v if 0 < v <= 100 else None
    m = CONTROL_PSC.search(text)  # Companies House bands: "75% or more", "more than 25%"
    if m:
        return float(m.group(1) or m.group(2))
    return None


def extract(text: str, pages: int = 1) -> Extraction:
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    low = text.lower()
    kind = (
        "ubo"
        if "bénéficiaires effectifs" in low or "beneficial owner" in low and "declar" in low
        else "companies_house"
        if "companies house" in low
        else "kbis"
        if "kbis" in low or "registre du commerce" in low
        else "generic"
    )
    ex = Extraction(kind=kind, pages=pages, characters=len(text))
    if len(text.strip()) < 40:
        ex.warnings.append(
            "No text found: the document is probably a scan (image). Enter the data manually."
        )
        return ex

    for ln in lines:
        if ex.company.name is None and (m := COMPANY_LABELS.match(ln)):
            ex.company.name = m.group(1).strip()
        if ex.company.address is None and (m := ADDRESS_LABELS.match(ln)):
            ex.company.address = m.group(1).strip()
    for pattern, label in REG_PATTERNS:
        if m := pattern.search(text):
            ex.company.registration_number = (
                re.sub(r"\s", "", m.group(1)) if label != "UID" else m.group(1)
            )
            break

    in_ubo = kind == "ubo"
    current_role: str | None = None
    seen_officers: set[str] = set()
    seen_owners: set[str] = set()
    for i, ln in enumerate(lines):
        if UBO_SECTION.search(ln) and len(ln) < 80:
            in_ubo = True
        role_here = _role(ln) if len(ln) < 60 and ROLE_RE.search(ln) else None
        if role_here and not NAME_LABELS.match(ln):
            current_role = role_here
            # "Président : DUPONT Jean" on one line
            if ":" in ln and len(ln.split(":", 1)[1].strip()) > 3:
                name = _clean_name(ln.split(":", 1)[1])
                if name and name.lower() not in seen_officers and not in_ubo:
                    seen_officers.add(name.lower())
                    ex.officers.append(DeclaredPerson(name=name, role=current_role))
            continue
        m = NAME_LABELS.match(ln)
        if not m:
            # generic ownership line: "DUPONT Jean ........ 60 %"
            pct = _pct(ln)
            name_part = PCT.split(ln)[0] if pct is not None else ""
            name_part = re.sub(
                r"[.\-_]{3,}|\bdétient\b|\bholds?\b|\bshares?\b|\bdu capital\b",
                " ",
                name_part,
                flags=re.I,
            )
            name = _clean_name(name_part)
            if (
                pct is not None
                and 3 <= len(name) <= 80
                and re.search(r"[A-Za-zÀ-ÿ]{2,}\s+[A-Za-zÀ-ÿ]{2,}", name)
                and name.lower() not in seen_owners
                and not NOT_A_NAME.match(name)
            ):
                seen_owners.add(name.lower())
                ex.owners.append(
                    DeclaredPerson(
                        name=name, pct=pct, role="Beneficial owner" if in_ubo else "Shareholder"
                    )
                )
            continue
        name = _clean_name(m.group(1))
        if not name or len(name) < 3:
            continue
        window = " ".join(lines[i + 1 : i + 6])
        birth = re.search(r"(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+\w+\s+\d{4})", window)
        pct = _pct(window) if in_ubo else None
        if in_ubo or pct is not None:
            if name.lower() not in seen_owners:
                seen_owners.add(name.lower())
                ex.owners.append(
                    DeclaredPerson(
                        name=name,
                        role="Beneficial owner",
                        pct=pct,
                        birth=birth.group(1) if birth else None,
                    )
                )
        elif name.lower() not in seen_officers:
            seen_officers.add(name.lower())
            ex.officers.append(
                DeclaredPerson(
                    name=name,
                    role=current_role or _role(window) or "Officer",
                    birth=birth.group(1) if birth else None,
                )
            )
    if not ex.officers and not ex.owners:
        ex.warnings.append(
            "No officer or owner recognised: check the document type or enter the data manually."
        )
    return ex


# ------------------------------------------------------------------ comparison
class ComparisonRow(BaseModel):
    kind: str  # officer | owner | company
    name: str
    declared: str | None = None
    registry: str | None = None
    status: str  # match | mismatch | missing_in_registry | missing_in_document
    note: str | None = None
    entity_id: str | None = None


def _best(name: str, candidates: dict[str, str], kind: str = "person") -> tuple[str | None, float]:
    best, score = None, 0.0
    for eid, cname in candidates.items():
        s, _ = name_similarity(name, cname, kind)
        if s > score:
            best, score = eid, s
    return (best, score) if score >= 85 else (None, score)


def compare(
    net: Network,
    company: DeclaredCompany,
    officers: list[DeclaredPerson],
    owners: list[DeclaredPerson],
) -> list[ComparisonRow]:
    ents = net.entities
    subject = ents[net.subject_id]
    rows: list[ComparisonRow] = []

    if company.name:
        s, _ = name_similarity(company.name, subject.name, "company")
        rows.append(
            ComparisonRow(
                kind="company",
                name=company.name,
                declared=company.name,
                registry=subject.name,
                status="match" if s >= 90 else "mismatch",
                note=f"name similarity {s:.0f}%",
            )
        )
    if company.registration_number and subject.registration_number:
        a = re.sub(r"\W", "", company.registration_number).upper()
        b = re.sub(r"\W", "", subject.registration_number).upper()
        rows.append(
            ComparisonRow(
                kind="company",
                name="Registration number",
                declared=company.registration_number,
                registry=subject.registration_number,
                status="match" if a == b else "mismatch",
            )
        )

    # Officers: active officer links towards the subject
    reg_officers: dict[str, str] = {}
    reg_roles: dict[str, str] = {}
    for r in net.relationships.values():
        if (
            r.type == RelationType.OFFICER
            and r.target_id == subject.id
            and r.is_active
            and r.source_id in ents
        ):
            reg_officers[r.source_id] = ents[r.source_id].name
            reg_roles[r.source_id] = r.role or "officer"
    matched: set[str] = set()
    for p in officers:
        eid, score = _best(p.name, {k: v for k, v in reg_officers.items() if k not in matched})
        if eid:
            matched.add(eid)
            rows.append(
                ComparisonRow(
                    kind="officer",
                    name=p.name,
                    declared=p.role,
                    registry=reg_roles[eid],
                    status="match",
                    note=f"name {score:.0f}%",
                    entity_id=eid,
                )
            )
        else:
            rows.append(
                ComparisonRow(
                    kind="officer",
                    name=p.name,
                    declared=p.role,
                    status="missing_in_registry",
                    note="Declared by the client, not found as an active officer in the registries",
                )
            )
    for eid, name in reg_officers.items():
        if eid not in matched and officers:
            rows.append(
                ComparisonRow(
                    kind="officer",
                    name=name,
                    registry=reg_roles[eid],
                    status="missing_in_document",
                    note="Active officer in the registries, absent from the document",
                    entity_id=eid,
                )
            )

    # Owners: computed effective stakes (persons or top companies) + declared UBOs in registries
    g = ownership_graph(net.relationships.values())
    computed: dict[str, float] = {}
    if subject.id in g:
        for node in nx.ancestors(g, subject.id):
            e = ents.get(node)
            if e is None:
                continue
            total, _ = _best_paths(g, node, subject.id)
            if total > 0:
                computed[node] = total
    for r in net.relationships.values():
        if (
            r.type == RelationType.BENEFICIAL_OWNER
            and r.target_id == subject.id
            and r.source_id in ents
        ):
            computed.setdefault(r.source_id, r.share_pct or 0.0)
    matched = set()
    names = {k: ents[k].name for k in computed}
    for p in owners:
        kind = (
            "company"
            if re.search(
                r"\b(ltd|limited|sa|sas|sarl|s\.à r\.l\.|gmbh|ag|bv|nv|inc|llc|holding)\b",
                p.name,
                re.I,
            )
            else "person"
        )
        eid, score = _best(p.name, {k: v for k, v in names.items() if k not in matched}, kind)
        if eid is None:
            rows.append(
                ComparisonRow(
                    kind="owner",
                    name=p.name,
                    declared=f"{p.pct:g} %" if p.pct is not None else "declared",
                    status="missing_in_registry",
                    note="Declared owner not found in the ownership chain of the registries",
                )
            )
            continue
        matched.add(eid)
        reg = computed[eid]
        if p.pct is None or reg == 0 or abs(p.pct - reg) <= 5:
            status, note = "match", f"name {score:.0f}%"
        else:
            status, note = (
                "mismatch",
                f"declared {p.pct:g} % vs {reg:.1f} % computed from the registries",
            )
        rows.append(
            ComparisonRow(
                kind="owner",
                name=p.name,
                declared=f"{p.pct:g} %" if p.pct is not None else None,
                registry=f"{reg:.1f} %" if reg else "listed",
                status=status,
                note=note,
                entity_id=eid,
            )
        )
    for eid, pct in computed.items():
        e = ents[eid]
        if eid not in matched and pct >= 25 and e.type == EntityType.PERSON:
            rows.append(
                ComparisonRow(
                    kind="owner",
                    name=e.name,
                    registry=f"{pct:.1f} %",
                    status="missing_in_document",
                    note="Holds ≥ 25 % according to the registries but is not declared: undeclared beneficial owner?",
                    entity_id=eid,
                )
            )
    return rows


def serialize(rows: list[ComparisonRow]) -> list[dict[str, Any]]:
    return [r.model_dump() for r in rows]
