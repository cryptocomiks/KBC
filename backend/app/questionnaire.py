"""KYC / AML-CFT client questionnaire (LCB-FT) and vigilance level.

The analyst answers a short set of client-risk questions (relationship, activity,
structure, beneficial owners, PEP, countries, channel, volumes, cash, source of
funds, behaviour). The answers are combined with the automatic screening of the
case (risk level and factors) into a vigilance level — simplified, standard or
enhanced — with the measures that level calls for and the next review date.

The questions follow the client risk factors of the EU AML directives (Annexes
II and III of Directive 2015/849) and the French Monetary and Financial Code
(art. L561-4-1, L561-9, L561-10 and L561-10-2). The wording is our own.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.risk.config import get_country_risk, get_jurisdictions, get_risk_config

LEVELS = ("simplified", "standard", "enhanced")
REVIEW_MONTHS = {"simplified": 36, "standard": 24, "enhanced": 12}
ENHANCED_POINTS = 10
SIMPLIFIED_MAX_POINTS = 1


def _o(value: str, label: str, points: int, enhanced: str | None = None) -> dict[str, Any]:
    return {"value": value, "label": label, "points": points, "enhanced": enhanced}


QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "relationship",
        "section": "Relationship",
        "label": "Nature of the business relationship",
        "type": "choice",
        "options": [
            _o("one_off", "One-off engagement or transaction", 0),
            _o("ongoing", "Ongoing business relationship", 1),
            _o(
                "unusual",
                "Set up in unusual conditions (urgency, no clear business reason)",
                4,
                "relationship set up in unusual conditions",
            ),
        ],
    },
    {
        "id": "purpose",
        "section": "Relationship",
        "label": "Purpose of the relationship and services provided",
        "type": "text",
        "help": "What the client expects from you, in a sentence (required by art. L561-5-1 CMF).",
    },
    {
        "id": "sector",
        "section": "Client",
        "label": "Client's field of activity",
        "type": "choice",
        "options": [
            _o(
                "low",
                "Regulated financial institution, listed company or public body",
                -1,
            ),
            _o("standard", "Ordinary commercial or professional activity", 0),
            _o(
                "sensitive",
                "Sensitive sector: real estate, construction, crypto-assets, art & luxury, "
                "precious metals, gambling, defence, extractive industries, charities",
                3,
            ),
            _o(
                "cash",
                "Cash-intensive business (restaurants, retail, car dealers, car wash, night-time economy…)",
                3,
            ),
        ],
    },
    {
        "id": "structure",
        "section": "Client",
        "label": "Legal structure",
        "type": "choice",
        "options": [
            _o("simple", "Individual or simple company, owners visible in one step", 0),
            _o("holding", "Group with a holding company", 1),
            _o("complex", "Several layers or countries between the company and its owners", 3),
            _o(
                "opaque",
                "Trust, foundation, nominee shareholders or bearer shares",
                4,
                "opaque legal structure",
            ),
        ],
    },
    {
        "id": "ubo",
        "section": "Client",
        "label": "Beneficial owners",
        "type": "choice",
        "options": [
            _o("verified", "Identified and verified (register extract + ID documents)", 0),
            _o("declared", "Declared by the client, not yet verified", 2),
            _o(
                "unidentified",
                "Not identified",
                5,
                "beneficial owners not identified",
            ),
        ],
    },
    {
        "id": "pep",
        "section": "Client",
        "label": "Politically exposed person (client, director or beneficial owner)",
        "type": "choice",
        "options": [
            _o("no", "No", 0),
            _o("unknown", "Not checked yet", 2),
            _o(
                "relative",
                "Family member or close associate of a PEP",
                3,
                "close to a politically exposed person",
            ),
            _o("yes", "Yes", 4, "politically exposed person"),
        ],
    },
    {
        "id": "countries",
        "section": "Geography",
        "label": "Countries involved (registration, owners, activity, counterparties, funds)",
        "type": "countries",
        "help": "ISO codes. High-risk third countries (FATF black list) require enhanced measures.",
    },
    {
        "id": "channel",
        "section": "Geography",
        "label": "How the client was met and identified",
        "type": "choice",
        "options": [
            _o("face_to_face", "Face to face, originals seen", 0),
            _o(
                "remote_verified",
                "Remotely, with a certified electronic identity or video check",
                1,
            ),
            _o("intermediary", "Through an intermediary or introducer", 2),
            _o("remote_unverified", "Remotely, without identity verification", 3),
        ],
    },
    {
        "id": "volume",
        "section": "Transactions",
        "label": "Expected annual amounts",
        "type": "choice",
        "options": [
            _o("lt_150k", "Under €150,000", 0),
            _o("150k_1m", "€150,000 – €1 million", 1),
            _o("1m_10m", "€1 – 10 million", 2),
            _o("gt_10m", "Over €10 million", 3),
        ],
    },
    {
        "id": "cash",
        "section": "Transactions",
        "label": "Use of cash",
        "type": "choice",
        "options": [
            _o("none", "None", 0),
            _o("occasional", "Occasional, small amounts", 1),
            _o("significant", "Significant", 4, "significant use of cash"),
        ],
    },
    {
        "id": "funds",
        "section": "Transactions",
        "label": "Source of funds and wealth",
        "type": "choice",
        "options": [
            _o("documented", "Known and documented", 0),
            _o("partial", "Known but partly documented", 2),
            _o("unknown", "Unknown or not documented", 4, "source of funds not documented"),
        ],
    },
    {
        "id": "behaviour",
        "section": "Transactions",
        "label": "Consistency and behaviour of the client",
        "type": "choice",
        "options": [
            _o("consistent", "Consistent with what is known of the client", 0),
            _o("doubts", "Some doubts (unexplained changes, vague answers)", 2),
            _o(
                "reluctant",
                "Reluctant to give information, or inconsistent documents",
                4,
                "reluctant client or inconsistent documents",
            ),
        ],
    },
    {
        "id": "comment",
        "section": "Conclusion",
        "label": "Analyst's comment",
        "type": "text",
    },
]
BY_ID = {q["id"]: q for q in QUESTIONS}
SCORED = [q["id"] for q in QUESTIONS if q["type"] in ("choice", "countries")]

MEASURES = {
    "simplified": [
        "Identify the client and check the identity from one reliable document.",
        "Keep the file up to date at each significant event; review every 3 years.",
    ],
    "standard": [
        "Identify and verify the client and its beneficial owners "
        "(register extract less than 3 months old, ID documents, beneficial owners register).",
        "Record the purpose and nature of the relationship and the expected transactions.",
        "Monitor transactions for consistency with the client's profile; review every 2 years.",
    ],
    "enhanced": [
        "Senior management approval before entering into or continuing the relationship.",
        "Obtain and verify evidence of the source of funds and of wealth.",
        "Verify the beneficial owners from independent sources, not only the client's declaration.",
        "Reinforced monitoring of transactions; review the file every year.",
        "Consider a suspicious transaction report (TRACFIN / FIU) if the doubts are not lifted.",
    ],
}
TRIGGER_MEASURES = {
    "politically exposed person": "PEP: approval by senior management, source of wealth, "
    "yearly review (art. L561-10 CMF).",
    "close to a politically exposed person": "Close to a PEP: same measures as for the PEP.",
    "beneficial owners not identified": "Do not start the relationship until the beneficial "
    "owners are identified (art. L561-8 CMF).",
    "source of funds not documented": "Ask for the documents supporting the origin of the "
    "funds (deeds, contracts, bank statements, tax returns).",
    "high-risk third country": "High-risk third country: enhanced measures required "
    "(art. L561-10 CMF) — document every transaction with this country.",
    "sanctions match in the screening": "Sanctions match: do not make funds available before "
    "the hit is cleared; if confirmed, freeze and report to the Treasury (DG Trésor).",
}


def _country_points(codes: list[str]) -> tuple[int, list[dict[str, Any]], list[str]]:
    jur = get_jurisdictions()
    risk = get_country_risk()
    thresholds = get_risk_config().thresholds
    points = 0
    reasons: list[dict[str, Any]] = []
    triggers: list[str] = []
    for code in sorted({c.strip().upper() for c in codes if c and c.strip()}):
        name = jur.name(code)
        c = risk.get(code)
        if code in jur.fatf_blacklist:
            reasons.append({"item": f"{name}", "detail": "FATF black list", "points": 5})
            points += 5
            triggers.append("high-risk third country")
        elif code in jur.fatf_greylist:
            reasons.append({"item": f"{name}", "detail": "FATF grey list", "points": 3})
            points += 3
        elif code in jur.eu_tax_blacklist or code in jur.offshore_centres:
            reasons.append(
                {"item": f"{name}", "detail": "offshore centre / EU tax list", "points": 2}
            )
            points += 2
        elif (c.get("basel_aml_score") or 0) >= thresholds.get("basel_high_score", 6.0):
            reasons.append(
                {
                    "item": f"{name}",
                    "detail": f"Basel AML Index {c['basel_aml_score']:.1f}/10",
                    "points": 2,
                }
            )
            points += 2
    return points, reasons, triggers


def suggest(case: dict[str, Any]) -> dict[str, Any]:
    """Answers the screening already supports; the analyst confirms or corrects them."""
    factors = set((case.get("snapshot") or {}).get("factors") or [])
    out: dict[str, Any] = {}
    if case.get("countries"):
        out["countries"] = list(case["countries"])
    if "pep_match" in factors:
        out["pep"] = "yes"
    elif "pep_relative" in factors:
        out["pep"] = "relative"
    if factors & {"circular_ownership", "long_ownership_chain", "offshore_jurisdiction"}:
        out["structure"] = "complex"
    if "ubo_discrepancy" in factors:
        out["ubo"] = "declared"
    return out


def assess(answers: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """Vigilance level from the answers and the automatic screening of the case."""
    points = 0
    reasons: list[dict[str, Any]] = []
    triggers: list[str] = []
    missing: list[str] = []
    no_simplified: list[str] = []
    for qid in SCORED:
        q = BY_ID[qid]
        value = answers.get(qid)
        if q["type"] == "countries":
            codes = value if isinstance(value, list) else []
            if not codes:
                missing.append(q["label"])
                continue
            p, r, t = _country_points(codes)
            points += p
            reasons += r
            triggers += t
            continue
        option = next((o for o in q["options"] if o["value"] == value), None)
        if option is None:
            missing.append(q["label"])
            continue
        if option["points"]:
            points += option["points"]
            reasons.append(
                {"item": q["label"], "detail": option["label"], "points": option["points"]}
            )
        if option["enhanced"]:
            triggers.append(option["enhanced"])
        if option["points"] > 0:
            no_simplified.append(q["label"])

    # Automatic screening of the case (network of companies and people).
    level = case.get("risk_level")
    factors = set((case.get("snapshot") or {}).get("factors") or [])
    screening = {"critical": 6, "high": 4, "medium": 2}.get(level or "", 0)
    if screening:
        points += screening
        reasons.append(
            {
                "item": "Automatic screening",
                "detail": f"network risk {level} ({case.get('risk_score') or 0:.0f}/100)",
                "points": screening,
            }
        )
    if level in ("critical", "high"):
        triggers.append(f"screening risk {level}")
    if "sanctions_match" in factors:
        triggers.append("sanctions match in the screening")
    if "pep_match" in factors and answers.get("pep") == "no":
        reasons.append(
            {
                "item": "Inconsistency",
                "detail": "the screening found a PEP match but the answer says “No”: "
                "rule it out in the case (false positive) or correct the answer",
                "points": 0,
            }
        )

    if triggers or points >= ENHANCED_POINTS:
        vigilance = "enhanced"
    elif (
        points <= SIMPLIFIED_MAX_POINTS
        and answers.get("sector") == "low"
        and level in (None, "low")
        and not no_simplified
    ):
        vigilance = "simplified"
    else:
        vigilance = "standard"

    measures = list(MEASURES[vigilance])
    for t in dict.fromkeys(triggers):
        if t in TRIGGER_MEASURES:
            measures.append(TRIGGER_MEASURES[t])
    if level == "incomplete":
        measures.insert(0, "The automatic screening is incomplete: re-check the case first.")

    answered = answers.get("_answered_at")
    try:
        start = datetime.fromisoformat(answered).date() if answered else date.today()
    except ValueError:
        start = date.today()
    return {
        "level": vigilance,
        "points": points,
        "reasons": reasons,
        "triggers": list(dict.fromkeys(triggers)),
        "measures": measures,
        "missing": missing,
        "complete": not missing,
        "review_months": REVIEW_MONTHS[vigilance],
        "next_review": (
            start + timedelta(days=round(REVIEW_MONTHS[vigilance] * 30.44))
        ).isoformat(),
    }


def clean(answers: dict[str, Any]) -> dict[str, Any]:
    """Keep known questions and valid values only."""
    out: dict[str, Any] = {}
    for qid, value in answers.items():
        q = BY_ID.get(qid)
        if q is None or value in (None, "", []):
            continue
        if q["type"] == "choice":
            if any(o["value"] == value for o in q["options"]):
                out[qid] = value
        elif q["type"] == "countries":
            if isinstance(value, list):
                codes = [str(c).strip().upper()[:2] for c in value if str(c).strip()]
                out[qid] = sorted({c for c in codes if len(c) == 2 and c.isalpha()})[:40]
        else:
            out[qid] = str(value)[:4000]
    return out


def answer_label(qid: str, value: Any) -> str:
    q = BY_ID[qid]
    if q["type"] == "choice":
        return next((o["label"] for o in q["options"] if o["value"] == value), str(value))
    if q["type"] == "countries":
        jur = get_jurisdictions()
        return ", ".join(f"{jur.name(c)} ({c})" for c in value or [])
    return str(value)
