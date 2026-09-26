"""Case workflow (four-eyes validation) and case checklist (documents received, diligences).

Workflow: a case is *to complete* while the analyst gathers the documents and
answers the questionnaire, then *sent for validation*; a second person
*validates* it (never the one who sent it) or *sends it back* with a comment.
A validated case goes back to *to complete* when its periodic review is
reopened, or automatically when the monitoring finds a new sanctions / PEP /
leak hit. Every step is kept (who, when, comment) for the audit trail.

Checklist: the documents the findings call for, ticked when received, and the
additional diligences suggested by the vigilance level and the red flags —
optional controls the analyst ticks when done, plus their own.
"""

from __future__ import annotations

import hashlib
from typing import Any

STATES = ("to_complete", "pending_validation", "validated", "rejected")
STATE_LABELS = {
    "to_complete": "To complete",
    "pending_validation": "Awaiting validation",
    "validated": "Validated",
    "rejected": "Sent back",
}
ACTIONS = {
    # action: (allowed from, new state)
    "submit": ({"to_complete", "rejected"}, "pending_validation"),
    "validate": ({"pending_validation"}, "validated"),
    "reject": ({"pending_validation"}, "rejected"),
    "reopen": ({"validated", "pending_validation"}, "to_complete"),
}
SENSITIVE_FACTORS = {"sanctions_match", "pep_match", "sanctioned_counterparty", "watchlist_match"}


class WorkflowError(ValueError):
    """The action is not possible in the current state (message shown to the analyst)."""


def key(text: str) -> str:
    return hashlib.sha1(text.strip().lower().encode()).hexdigest()[:12]


def state_of(case: dict[str, Any]) -> str:
    return (case.get("workflow") or {}).get("state") or "to_complete"


# ------------------------------------------------------------- diligences
BASE = [
    "Check that the register extract and the articles of association are less than 3 months "
    "old and match the registers.",
    "Compare the declared beneficial owners with the beneficial owners register and with the "
    "ownership computed in this case.",
]
BY_LEVEL = {
    "standard": [
        "Check on a sample of 5 transactions that amounts and counterparties match the "
        "client's activity.",
    ],
    "enhanced": [
        "Check on a sample of 10 transactions that amounts, counterparties and countries match "
        "the client's profile.",
        "Obtain and check the evidence of the source of funds of the largest incoming payments.",
        "Compare the payment methods used with the client's usual practice (cash, "
        "crypto-assets, payments by third parties).",
        "Look for repeated low-value payments (splitting) on a sample of 5 counterparties.",
        "Record the senior management approval of the relationship.",
    ],
}
BY_TRIGGER = {
    "politically exposed person": "Obtain the source of wealth of the politically exposed "
    "person and record the senior management approval.",
    "close to a politically exposed person": "Document the link with the politically exposed "
    "person and apply the same measures.",
    "high-risk third country": "List every transaction with the high-risk country and "
    "document its purpose.",
    "sanctions match in the screening": "Clear the sanctions hit (date of birth, nationality, "
    "identifiers) before any transaction, and record the decision in the case.",
    "significant use of cash": "Check that the 10 largest cash deposits or withdrawals match "
    "the activity and are supported by documents.",
    "reluctant client or inconsistent documents": "Note every inconsistency between the "
    "client's statements and the documents supplied.",
    "opaque legal structure": "Obtain the trust deed / foundation charter or the nominee "
    "agreement, and identify the persons behind it.",
}
BY_FACTOR = {
    "ubo_discrepancy": "Reconcile the declared beneficial owners with the computed ones and ask "
    "for an updated declaration.",
    "offshore_jurisdiction": "Obtain a signed group structure chart down to the natural persons.",
    "long_ownership_chain": "Obtain a signed group structure chart down to the natural persons.",
    "circular_ownership": "Obtain a signed group structure chart down to the natural persons.",
    "adverse_media": "Read the press articles found and record whether they concern the client.",
    "insolvency_proceedings": "Check the status of the insolvency proceedings and their effect "
    "on the relationship.",
    "leak_appearance": "Ask for the purpose of the structures named in leaked data and record "
    "the answer.",
    "shell_company_indicators": "Ask for the latest accounts and an explanation of the "
    "activity (large assets, almost no revenue).",
    "nominee_director": "Ask for the nominee agreement or a declaration of the person on "
    "whose behalf the director acts.",
}


def suggested_diligences(
    assessment: dict[str, Any] | None, answers: dict[str, Any], factors: set[str]
) -> list[str]:
    out = list(BASE)
    level = (assessment or {}).get("level") or "standard"
    out += BY_LEVEL.get(level, [])
    for t in (assessment or {}).get("triggers", []):
        if t in BY_TRIGGER:
            out.append(BY_TRIGGER[t])
    if answers.get("sector") == "cash" and BY_TRIGGER["significant use of cash"] not in out:
        out.append(BY_TRIGGER["significant use of cash"])
    if answers.get("behaviour") == "doubts":
        out.append(BY_TRIGGER["reluctant client or inconsistent documents"])
    for f in sorted(factors):
        if f in BY_FACTOR:
            out.append(BY_FACTOR[f])
    return list(dict.fromkeys(out))


# -------------------------------------------------------------- checklist
def checklist_view(
    case: dict[str, Any],
    requests: list[dict[str, Any]],
    assessment: dict[str, Any] | None,
) -> dict[str, Any]:
    saved = case.get("checklist") or {}
    ticks: dict[str, Any] = saved.get("ticks") or {}
    removed = set(saved.get("removed") or [])
    answers = (case.get("questionnaire") or {}).get("answers") or {}
    factors = set((case.get("snapshot") or {}).get("factors") or [])

    def item(k: str, **extra: Any) -> dict[str, Any]:
        t = ticks.get(k) or {}
        return {
            "key": k,
            "done": bool(t.get("done")),
            "by": t.get("by", ""),
            "at": t.get("at"),
            "note": t.get("note", ""),
            **extra,
        }

    documents = [
        item(
            key("doc|" + r["document"]),
            label=r["document"],
            reason=r.get("reason", ""),
            required=r.get("priority") == "required",
        )
        for r in requests
    ]
    diligences = [
        item(key("dil|" + text), label=text, custom=False)
        for text in suggested_diligences(assessment, answers, factors)
        if key("dil|" + text) not in removed
    ] + [item(c["key"], label=c["label"], custom=True) for c in saved.get("custom") or []]
    return {
        "documents": documents,
        "diligences": diligences,
        "missing_required": [d["label"] for d in documents if d["required"] and not d["done"]],
    }


def blockers(case: dict[str, Any], checklist: dict[str, Any], assessment: dict | None) -> list[str]:
    """What prevents sending the case for validation."""
    out = []
    if not assessment:
        out.append("Answer the KYC / AML-CFT questionnaire.")
    elif assessment.get("missing"):
        out.append(f"Questionnaire: {len(assessment['missing'])} question(s) unanswered.")
    if checklist["missing_required"]:
        out.append(f"{len(checklist['missing_required'])} required document(s) not received.")
    if case.get("risk_level") == "incomplete":
        out.append("The automatic screening is incomplete: re-check the case first.")
    return out


# --------------------------------------------------------------- workflow
def transition(
    case: dict[str, Any],
    action: str,
    who: str,
    comment: str,
    at: str,
    blocking: list[str],
) -> dict[str, Any]:
    if action not in ACTIONS:
        raise WorkflowError("Unknown action.")
    allowed, new_state = ACTIONS[action]
    wf = dict(case.get("workflow") or {})
    state = wf.get("state") or "to_complete"
    if state not in allowed:
        raise WorkflowError(f"Not possible while the case is “{STATE_LABELS[state]}”.")
    who = who.strip()
    if not who:
        raise WorkflowError("Give your name: every step is signed in the audit trail.")
    if action == "submit" and blocking:
        raise WorkflowError("Complete the case first: " + " ".join(blocking))
    if action == "validate" and who.lower() == (wf.get("submitted_by") or "").lower():
        raise WorkflowError(
            "Four-eyes principle: the case must be validated by someone other than "
            f"the person who sent it ({wf.get('submitted_by')})."
        )
    if action in ("reject", "reopen") and not comment.strip():
        raise WorkflowError("A comment is required to send back or reopen a case.")
    history = list(wf.get("history") or [])
    history.append({"at": at, "by": who, "action": action, "comment": comment.strip()[:2000]})
    wf.update(state=new_state, history=history[-200:])
    if action == "submit":
        wf["submitted_by"] = who
    if action == "validate":
        wf["validated_by"], wf["validated_at"] = who, at
    if action == "reopen":
        wf.pop("validated_by", None)
        wf.pop("validated_at", None)
    return wf


def auto_reopen(case: dict[str, Any], changes: list[dict[str, str]], at: str) -> dict | None:
    """A validated case whose monitoring finds a new hit goes back to the analyst."""
    critical = [c for c in changes if c.get("severity") == "critical"]
    if state_of(case) != "validated" or not critical:
        return None
    wf = dict(case.get("workflow") or {})
    history = list(wf.get("history") or [])
    history.append(
        {
            "at": at,
            "by": "monitoring",
            "action": "reopen",
            "comment": "Reopened automatically: "
            + "; ".join(c["description"] for c in critical[:3]),
        }
    )
    wf.update(state="to_complete", history=history[-200:])
    wf.pop("validated_by", None)
    wf.pop("validated_at", None)
    return wf


def queue_of(case: dict[str, Any], horizon: str) -> str | None:
    """Dashboard queue of a case: sensitive, to_validate, to_complete, review_due, validated.
    horizon: reviews due on or before this date (ISO) are shown as due."""
    if case.get("import_state"):
        return None
    state = state_of(case)
    factors = set(case.get("factors") or (case.get("snapshot") or {}).get("factors") or [])
    if state == "validated":
        due = (case.get("questionnaire") or {}).get("next_review")
        return "review_due" if due and due <= horizon else "validated"
    if factors & SENSITIVE_FACTORS or case.get("risk_level") == "critical":
        return "sensitive"
    return "to_validate" if state == "pending_validation" else "to_complete"
