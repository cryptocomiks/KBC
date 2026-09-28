"""Periodic review pack: only what changed and only what is missing.

Every KYC file is reviewed again after 1 to 3 years (sooner under enhanced vigilance). Done
by hand, the review repeats the whole onboarding and asks the client again for documents
the bank already holds. The pack does the comparison instead:

* what changed since the last validation (screening hits, owners, officers, registers,
  risk score): from the monitoring history;
* screening alerts still open;
* documents that are expired or too old to rely on (register extracts over 12 months,
  identity documents past their expiry date, statements over 12 months) and those never
  received;
* whether the vigilance level would change today, and the questionnaire answers to confirm;
* the beneficial-ownership forms to sign again when the ownership changed;
* the source of wealth when enhanced vigilance applies and it is not yet explained;

and drafts the e-mail to the client asking only for what is needed.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

REGISTER = re.compile(
    r"extract|register|registre|handelsregister|incorporation|incumbency|kbis|statut|articles", re.I
)
IDENTITY = re.compile(r"passport|identity|id card|carte d.identit|pass\b|ausweis", re.I)
FINANCIAL = re.compile(
    r"statement|accounts|financial|bilan|comptes|jahresrechnung|tax return", re.I
)
DATE_PATTERNS = (
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), lambda m: (int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})"), lambda m: (int(m[3]), int(m[2]), int(m[1]))),
)
OWNERSHIP_KINDS = ("new_link", "ended_link")


def _day(v: Any) -> date | None:
    try:
        return datetime.fromisoformat(str(v)[:19]).date() if v else None
    except ValueError:
        return None


def _expiry(note: str) -> date | None:
    """An expiry date written in the tick note ("expires 2027-03-31", "valid until 31.03.2027")."""
    if not re.search(r"expir|valid|until|jusqu|gültig|bis", note or "", re.I):
        return None
    for rx, parts in DATE_PATTERNS:
        m = rx.search(note)
        if m:
            try:
                return date(*parts(m))
            except ValueError:
                return None
    return None


def document_status(doc: dict[str, Any], today: date) -> dict[str, Any]:
    label = doc["label"]
    got = _day(doc.get("at")) if doc.get("done") else None
    out = {
        "label": label,
        "received_on": got.isoformat() if got else None,
        "required": doc.get("required", False),
    }
    if not got:
        return {
            **out,
            "status": "missing" if doc.get("required") else "not_received",
            "why": "never received" + (" (required)" if doc.get("required") else ""),
        }
    if IDENTITY.search(label):
        exp = _expiry(doc.get("note") or "")
        if exp and exp < today:
            return {**out, "status": "expired", "why": f"expired on {exp.isoformat()}"}
        if exp and exp < today + timedelta(days=90):
            return {**out, "status": "expiring", "why": f"expires on {exp.isoformat()}"}
        if not exp and got < today - timedelta(days=5 * 365):
            return {
                **out,
                "status": "stale",
                "why": "received over 5 years ago, expiry date not recorded",
            }
        return {
            **out,
            "status": "ok",
            "why": f"valid until {exp.isoformat()}" if exp else "no expiry date recorded",
        }
    months = 12 if (REGISTER.search(label) or FINANCIAL.search(label)) else 36
    if got < today - timedelta(days=months * 30):
        return {**out, "status": "stale", "why": f"older than {months} months"}
    return {**out, "status": "ok", "why": f"received {got.isoformat()}"}


def build_pack(
    case: dict[str, Any],
    changes: list[dict[str, Any]],
    checklist: dict[str, Any],
    kyc_view: dict[str, Any],
    workflow: dict[str, Any],
    open_alerts: list[dict[str, Any]],
    sow: dict[str, Any] | None,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    reviews = case.get("reviews") or []
    last = (
        workflow.get("validated_at")
        or next(
            (
                r.get("previous_validation")
                for r in reversed(reviews)
                if r.get("previous_validation")
            ),
            None,
        )
        or case.get("created_at")
    )
    saved_q = case.get("questionnaire") or {}
    a = kyc_view.get("assessment")
    due = saved_q.get("next_review") or (a or {}).get("next_review")
    due_day = _day(due)
    days_left = (due_day - today).days if due_day else None
    status = (
        "not_set"
        if due_day is None
        else "overdue"
        if days_left < 0
        else "due"
        if days_left <= 30
        else "not_due"
    )

    since = [c for c in changes if not last or str(c["run_at"]) > str(last)]
    by_sev = {s: [c for c in since if c["severity"] == s] for s in ("critical", "warning", "info")}
    docs = [document_status(d, today) for d in checklist.get("documents") or []]
    renew = [d for d in docs if d["status"] in ("missing", "expired", "expiring", "stale")]

    actions: list[dict[str, str]] = []
    if by_sev["critical"]:
        actions.append(
            {
                "severity": "critical",
                "tab": "history",
                "text": f"{len(by_sev['critical'])} critical change(s) since the last validation: review them first.",
            }
        )
    if open_alerts:
        actions.append(
            {
                "severity": "warning",
                "tab": "alerts",
                "text": f"{len(open_alerts)} screening alert(s) still open: confirm or rule out.",
            }
        )
    own = [
        c
        for c in since
        if c["kind"] in OWNERSHIP_KINDS
        and re.search(r"sharehold|beneficial|owner|%", c["description"], re.I)
    ]
    if own:
        actions.append(
            {
                "severity": "warning",
                "tab": "cdb",
                "text": f"Ownership changed ({len(own)} change(s)): have the beneficial-ownership form (CDB 20) signed again.",
            }
        )
    if renew:
        actions.append(
            {
                "severity": "warning",
                "tab": "kyc",
                "text": f"{len(renew)} document(s) to renew or obtain.",
            }
        )
    level_now = (a or {}).get("level")
    level_saved = saved_q.get("vigilance")
    if a and level_saved and level_now != level_saved:
        actions.append(
            {
                "severity": "warning",
                "tab": "kyc",
                "text": f"Vigilance level would change: {level_saved} → {level_now}.",
            }
        )
    answered = _day(saved_q.get("answered_at"))
    if not a:
        actions.append(
            {
                "severity": "warning",
                "tab": "kyc",
                "text": "The KYC questionnaire was never answered.",
            }
        )
    elif answered and answered < today - timedelta(days=365):
        actions.append(
            {
                "severity": "info",
                "tab": "kyc",
                "text": f"Questionnaire answered on {answered.isoformat()}: confirm the answers with the client.",
            }
        )
    if level_now == "enhanced" and (
        not sow or not sow.get("sources") or sow.get("verdict") not in ("plausible",)
    ):
        actions.append(
            {
                "severity": "warning",
                "tab": "sow",
                "text": "Enhanced vigilance: the source of wealth is not established yet.",
            }
        )
    if not actions:
        actions.append(
            {
                "severity": "info",
                "tab": "kyc",
                "text": "Nothing changed and nothing is missing: the review can be validated as is.",
            }
        )

    return {
        "last_review": last,
        "last_review_basis": "opening" if last == case.get("created_at") else "validation",
        "next_review": due,
        "days_left": days_left,
        "status": status,
        "changes": since[:100],
        "changes_count": {k: len(v) for k, v in by_sev.items()},
        "open_alerts": open_alerts[:50],
        "documents": docs,
        "to_renew": renew,
        "vigilance": {"saved": level_saved, "now": level_now},
        "actions": actions,
        "email": email(case, renew, own, a),
        "reviews": list(reversed(reviews))[:20],
        "workflow_state": workflow.get("state"),
    }


def email(
    case: dict[str, Any], renew: list[dict[str, Any]], own: list[dict[str, Any]], a: dict | None
) -> dict[str, str]:
    lines = [
        "Dear Sir or Madam,",
        "",
        f"As part of the regular update of our client files, we are reviewing the file of {case['subject_name']}.",
    ]
    if renew:
        lines += ["", "Could you please send us the following documents:"]
        lines += [
            f"- {d['label']}" + (f" ({d['why']})" if d["status"] != "missing" else "")
            for d in renew
        ]
    lines += ["", "Could you also confirm that the following information is still accurate:"]
    lines += [
        "- the purpose and intended nature of our business relationship;",
        "- the beneficial owner(s) / controlling person(s)"
        + (
            ": our records show changes in the ownership, a new declaration will be needed;"
            if own
            else ";"
        ),
        "- your registered address and the persons authorised to sign.",
    ]
    if a and a.get("level") == "enhanced":
        lines.append("- the origin of the assets deposited with us (source of wealth and funds).")
    lines += [
        "",
        "Documents we already hold and that are still valid are not needed again.",
        "",
        "Thank you in advance.",
        "Kind regards,",
    ]
    return {"subject": f"Periodic review of your file: {case['title']}", "body": "\n".join(lines)}
