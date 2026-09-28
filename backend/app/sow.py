"""Source of wealth: how did the client (or its beneficial owner) build the wealth?

In Swiss private banking this is where analysts spend the most time: reconstruct how the
wealth was made, check it adds up, corroborate each source and write it down. This module:

1. takes the sources declared by the client (salary, sale of a company, dividends,
   inheritance...) with amounts and years;
2. computes what each source can plausibly explain (a salary is not saved in full) and the
   gap against the declared total;
3. looks for corroboration in the public records already gathered: board mandates for a
   career, a shareholding that ended for a company sale, current holdings for dividends;
4. lists the documents to request for what the registers cannot prove, raises the red flags
   (PEP, cash, crypto, high-risk countries, age, unexplained gap);
5. drafts the source-of-wealth narrative for the file.

It never concludes on its own: the analyst reads the evidence and signs.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.models import Entity, EntityType, ListType, RelationType
from app.risk.config import get_jurisdictions
from app.schemas import Investigation

TYPES: dict[str, dict[str, Any]] = {
    "employment": {
        "label": "Employment income (salary, bonus)",
        "mode": "annual",
        "rate": 0.3,
        "risk": "low",
        "docs": [
            "Employment contracts or employer letters",
            "Payslips or salary certificates (Lohnausweis)",
            "Tax returns for the period",
        ],
    },
    "business_income": {
        "label": "Business profits / dividends",
        "mode": "annual",
        "rate": 0.7,
        "risk": "low",
        "docs": [
            "Audited financial statements of the company",
            "Dividend resolutions and statements",
            "Tax returns showing the dividends",
        ],
    },
    "business_sale": {
        "label": "Sale of a company or shares",
        "mode": "lump",
        "risk": "medium",
        "docs": [
            "Share purchase agreement (SPA)",
            "Bank statement showing the sale proceeds",
            "Register extract before and after the sale",
        ],
    },
    "inheritance": {
        "label": "Inheritance",
        "mode": "lump",
        "risk": "medium",
        "docs": [
            "Certificate of inheritance or will",
            "Estate inventory / probate",
            "Bank statement showing the transfer",
        ],
    },
    "gift": {
        "label": "Gift / donation",
        "mode": "lump",
        "risk": "high",
        "docs": [
            "Deed of gift or letter from the donor",
            "Source of wealth of the donor",
            "Bank statement showing the transfer",
        ],
    },
    "real_estate": {
        "label": "Sale of real estate",
        "mode": "lump",
        "risk": "low",
        "docs": [
            "Notarial deed of sale",
            "Land register extract",
            "Bank statement showing the proceeds",
        ],
    },
    "investments": {
        "label": "Investment gains",
        "mode": "lump",
        "risk": "medium",
        "docs": [
            "Portfolio statements over the period",
            "Tax statements (état des titres / Wertschriftenverzeichnis)",
        ],
    },
    "crypto": {
        "label": "Crypto-assets",
        "mode": "lump",
        "risk": "high",
        "docs": [
            "Exchange account statements and KYC",
            "On-chain history of the addresses (acquisition to sale)",
            "Tax declarations of the crypto-assets",
        ],
    },
    "other": {
        "label": "Other (lottery, compensation, loan...)",
        "mode": "lump",
        "risk": "high",
        "docs": [
            "Documentary evidence of the event (contract, ruling, certificate)",
            "Bank statement showing the funds",
        ],
    },
}
PLAUSIBLE = 0.9
PARTIAL = 0.6
SIGNIFICANT = 5_000_000


def _num(v: Any) -> float:
    try:
        return max(0.0, float(str(v).replace("'", "").replace(" ", "").replace(",", "")))
    except (TypeError, ValueError):
        return 0.0


def _year(v: Any) -> int | None:
    try:
        y = int(str(v)[:4])
        return y if 1900 <= y <= 2100 else None
    except (TypeError, ValueError):
        return None


def money(v: float, cur: str) -> str:
    return f"{cur} {v:,.0f}".replace(",", "'")


def clean(saved: dict[str, Any]) -> dict[str, Any]:
    """Keep only known fields, with sane types (input comes from the browser)."""
    sources = []
    for i, s in enumerate((saved.get("sources") or [])[:30]):
        t = s.get("type") if s.get("type") in TYPES else "other"
        sources.append(
            {
                "id": str(s.get("id") or f"s{i + 1}")[:20],
                "type": t,
                "description": str(s.get("description") or "")[:500],
                "amount": _num(s.get("amount")),
                "annual": _num(s.get("annual")),
                "year_from": _year(s.get("year_from")),
                "year_to": _year(s.get("year_to")),
                "rate": min(1.0, _num(s.get("rate"))) if s.get("rate") not in (None, "") else None,
                "country": str(s.get("country") or "")[:2].upper(),
                "received": [str(d)[:200] for d in (s.get("received") or [])][:20],
            }
        )
    return {
        "person_id": str(saved.get("person_id") or "")[:300],
        "currency": (str(saved.get("currency") or "CHF")[:3] or "CHF").upper(),
        "declared_total": _num(saved.get("declared_total")),
        "sources": sources,
        "notes": str(saved.get("notes") or "")[:4000],
    }


def explained(s: dict[str, Any]) -> tuple[float, str]:
    """Amount a source can explain, and how it was computed."""
    spec = TYPES[s["type"]]
    if spec["mode"] == "annual" and s["annual"]:
        y0 = s["year_from"] or date.today().year
        y1 = s["year_to"] or date.today().year
        years = max(1, y1 - y0 + 1)
        rate = s["rate"] if s["rate"] is not None else spec["rate"]
        return s["annual"] * years * rate, f"{years} year(s) × annual amount × {rate:.0%} retained"
    return s["amount"], "amount declared"


def _roles(inv: Investigation, person: Entity) -> list[dict[str, Any]]:
    ents = {e.id: e for e in inv.entities}
    out = []
    for r in inv.relationships:
        if r.source_id != person.id or r.target_id not in ents:
            continue
        if r.type not in (
            RelationType.OFFICER,
            RelationType.SHAREHOLDER,
            RelationType.BENEFICIAL_OWNER,
        ):
            continue
        c = ents[r.target_id]
        out.append(
            {
                "company": c.name,
                "kind": r.type.value,
                "role": r.role or r.type.value.replace("_", " "),
                "share_pct": r.share_pct,
                "start": r.start_date.isoformat() if r.start_date else None,
                "end": r.end_date.isoformat() if r.end_date else None,
                "company_status": c.status.value if c.status else None,
                "dissolved": c.dissolution_date.isoformat() if c.dissolution_date else None,
                "jurisdiction": c.jurisdiction,
                "source": r.sources[0].source_label
                if r.sources
                else (c.sources[0].source_label if c.sources else ""),
            }
        )
    return out


def _overlap(role: dict[str, Any], y0: int | None, y1: int | None) -> bool:
    rs = _year(role["start"]) or 1900
    re_ = _year(role["end"]) or date.today().year
    return (y0 or 1900) <= re_ and rs <= (y1 or date.today().year)


def _matches(s: dict[str, Any], roles: list[dict[str, Any]]) -> list[str]:
    desc = s["description"].lower()

    def named(r: dict[str, Any]) -> bool:
        words = [w for w in re.findall(r"\w+", r["company"].lower()) if len(w) >= 4]
        return bool(words) and any(re.search(rf"\b{re.escape(w)}\b", desc) for w in words[:2])

    def fmt(r: dict[str, Any]) -> str:
        end = r["end"] or r["dissolved"]
        span = f"{(r['start'] or '?')[:4]}–{end[:4] if end else 'today'}"
        pct = f" {r['share_pct']:g} %" if r["share_pct"] is not None else ""
        gone = ", company dissolved" if r["dissolved"] and not r["end"] else ""
        return f"{r['role']}{pct} of {r['company']} ({span}{gone}): {r['source']}"

    t = s["type"]
    y0, y1 = s["year_from"], s["year_to"]
    if t == "employment":
        cands = [r for r in roles if r["kind"] == "officer" and _overlap(r, y0, y1)]
    elif t == "business_income":
        cands = [
            r
            for r in roles
            if r["kind"] in ("shareholder", "beneficial_owner") and _overlap(r, y0, y1)
        ]
    elif t == "business_sale":
        cands = [
            r
            for r in roles
            if r["kind"] in ("shareholder", "beneficial_owner")
            and (r["end"] or r["dissolved"])
            and (not y0 or abs((_year(r["end"] or r["dissolved"]) or 0) - y0) <= 1)
        ]
    else:
        cands = []
    if t in ("employment", "business_income", "business_sale"):
        # A company named in the description comes first.
        cands = sorted(cands, key=lambda r: not named(r))
        kinds = ("officer",) if t == "employment" else ("shareholder", "beneficial_owner")
        cands += [r for r in roles if named(r) and r["kind"] in kinds and r not in cands]
    return [fmt(r) for r in cands[:5]]


def people(inv: Investigation) -> list[dict[str, Any]]:
    """Whose wealth: the client if a person, else the beneficial owners first."""
    ents = {e.id: e for e in inv.entities}
    out = []
    subject = ents[inv.subject_id]
    if subject.type == EntityType.PERSON:
        out.append({"id": subject.id, "name": subject.name, "why": "client"})
    for o in inv.brief.owners if inv.brief else []:
        if o.kind == "person" and o.entity_id not in {p["id"] for p in out}:
            out.append(
                {"id": o.entity_id, "name": o.name, "why": f"beneficial owner {o.pct:.1f} %"}
            )
    for e in inv.entities:
        if e.type == EntityType.PERSON and e.id not in {p["id"] for p in out}:
            out.append({"id": e.id, "name": e.name, "why": "in the network"})
    return out[:40]


def assess(inv: Investigation, saved: dict[str, Any]) -> dict[str, Any]:
    data = clean(saved)
    ents = {e.id: e for e in inv.entities}
    candidates = people(inv)
    pid = (
        data["person_id"]
        if data["person_id"] in ents
        else (candidates[0]["id"] if candidates else "")
    )
    person = ents.get(pid)
    cur = data["currency"]
    jur = get_jurisdictions()
    roles = _roles(inv, person) if person else []
    flags: list[dict[str, str]] = []

    rows = []
    total = 0.0
    for s in data["sources"]:
        amount, how = explained(s)
        total += amount
        spec = TYPES[s["type"]]
        public = _matches(s, roles)
        docs = [{"label": d, "received": d in s["received"]} for d in spec["docs"]]
        corroborated = bool(public) or any(d["received"] for d in docs)
        rows.append(
            {
                **s,
                "label": spec["label"],
                "explained": round(amount, 2),
                "how": how,
                "public": public,
                "documents": docs,
                "corroborated": corroborated,
                "risk": spec["risk"],
            }
        )
        if spec["risk"] == "high":
            flags.append(
                {
                    "severity": "warning",
                    "text": f"{spec['label']}: higher-risk source: corroborate with independent documents.",
                }
            )
        if s["country"] and (
            s["country"] in jur.fatf_blacklist or s["country"] in jur.fatf_greylist
        ):
            flags.append(
                {
                    "severity": "critical" if s["country"] in jur.fatf_blacklist else "warning",
                    "text": f"{spec['label']} originates in {jur.name(s['country'])} (FATF list).",
                }
            )
        if person and person.birth_date and s["year_from"] and s["type"] == "employment":
            by = _year(person.birth_date)
            if by and s["year_from"] - by < 16:
                flags.append(
                    {
                        "severity": "warning",
                        "text": f"Career start in {s['year_from']} at age {s['year_from'] - by}: check the dates.",
                    }
                )

    declared = data["declared_total"]
    coverage = (total / declared) if declared else None
    if coverage is None:
        verdict, verdict_text = "incomplete", "Declared total wealth missing."
    elif coverage >= PLAUSIBLE:
        verdict, verdict_text = "plausible", "The declared sources explain the wealth."
    elif coverage >= PARTIAL:
        verdict, verdict_text = (
            "partial",
            "The declared sources explain part of the wealth: clarify the gap.",
        )
    else:
        verdict, verdict_text = (
            "gap",
            "Large unexplained part: the wealth is not explained by the declared sources.",
        )
    if declared >= SIGNIFICANT:
        flags.append(
            {
                "severity": "info",
                "text": f"Significant wealth ({money(declared, cur)}): corroborate each main source with independent documents.",
            }
        )
    if person:
        for h in inv.hits:
            if h.entity_id != person.id or h.triage in ("namesake", "dismissed"):
                continue
            if h.list_type == ListType.PEP:
                flags.append(
                    {
                        "severity": "warning",
                        "text": f"{person.name} may be a politically exposed person ({h.dataset}): source of wealth must be established and corroborated (enhanced due diligence).",
                    }
                )
            elif h.list_type == ListType.SANCTION:
                flags.append(
                    {
                        "severity": "critical",
                        "text": f"{person.name} matches a sanctions list ({h.dataset}): resolve the match before anything else.",
                    }
                )
    not_corr = [r for r in rows if not r["corroborated"]]
    if not_corr:
        flags.append(
            {
                "severity": "warning",
                "text": f"{len(not_corr)} source(s) not corroborated yet (no public record, no document received).",
            }
        )

    seen_flags: set[str] = set()
    flags = [f for f in flags if not (f["text"] in seen_flags or seen_flags.add(f["text"]))]
    result = {
        **data,
        "person_id": pid,
        "person": person.name if person else None,
        "people": candidates,
        "types": {
            k: {"label": v["label"], "mode": v["mode"], "rate": v.get("rate")}
            for k, v in TYPES.items()
        },
        "sources": rows,
        "explained_total": round(total, 2),
        "gap": round(max(0.0, declared - total), 2) if declared else None,
        "coverage": round(coverage, 3) if coverage is not None else None,
        "verdict": verdict,
        "verdict_text": verdict_text,
        "roles": roles,
        "flags": flags,
        "to_request": [
            d["label"]
            for r in rows
            for d in r["documents"]
            if not d["received"] and not r["public"]
        ],
        "by": saved.get("by"),
        "at": saved.get("at"),
    }
    result["narrative"] = narrative(result)
    return result


def narrative(a: dict[str, Any]) -> str:
    cur = a["currency"]
    who = a["person"] or "[person]"
    lines = []
    if a["declared_total"]:
        lines.append(f"{who} declares total wealth of {money(a['declared_total'], cur)}.")
    else:
        lines.append(f"{who}: total wealth [to be declared].")
    if not a["sources"]:
        lines.append("No source of wealth declared yet [to complete].")
        return " ".join(lines)
    parts = []
    for s in a["sources"]:
        years = ""
        if s["year_from"]:
            years = (
                f" ({s['year_from']}"
                + (f"–{s['year_to']}" if s["year_to"] and s["year_to"] != s["year_from"] else "")
                + ")"
            )
        desc = f": {s['description']}" if s["description"] else ""
        parts.append(f"{s['label'].lower()}{years}{desc}, explaining {money(s['explained'], cur)}")
    lines.append("Declared sources: " + "; ".join(parts) + ".")
    if a["coverage"] is not None:
        lines.append(
            f"Together they explain {money(a['explained_total'], cur)}, i.e. {a['coverage']:.0%} of the declared wealth"
            + (f"; {money(a['gap'], cur)} remain unexplained." if a["gap"] else ".")
        )
    corr = [s for s in a["sources"] if s["public"]]
    if corr:
        lines.append(
            "Public records corroborate: "
            + "; ".join(f"{s['label'].lower()}: {s['public'][0]}" for s in corr)
            + "."
        )
    docs = [
        f"{s['label'].lower()} ({', '.join(d['label'] for d in s['documents'] if d['received'])})"
        for s in a["sources"]
        if any(d["received"] for d in s["documents"])
    ]
    if docs:
        lines.append("Documents received: " + "; ".join(docs) + ".")
    missing = [s["label"].lower() for s in a["sources"] if not s["corroborated"]]
    if missing:
        lines.append("Not corroborated yet: " + ", ".join(missing) + " [documents requested].")
    lines.append(f"Assessment: {a['verdict_text']} [analyst conclusion].")
    return " ".join(re.sub(r"\s+", " ", x) for x in lines)
