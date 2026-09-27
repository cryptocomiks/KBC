"""Swiss CDB 20 beneficial-ownership forms (A, K, S, T), pre-filled from the registers.

Swiss banks identify beneficial owners with the forms of the Agreement on the Swiss banks'
code of conduct with regard to the exercise of due diligence (CDB 20 / VSB 20):

* Form K — controlling persons of an *operating* legal entity or partnership: persons
  holding 25 % or more of the capital or votes; failing that, persons controlling it in
  another way; failing that, the managing person (CDB 20, art. 20).
* Form A — beneficial owner of the assets, required notably for *domiciliary companies*
  (no operating activity of their own) and whenever the contracting party is not the
  beneficial owner.
* Form T — trusts (settlor, trustees, protector, beneficiaries).
* Form S — foundations and similar constructs (founder, board, beneficiaries).

We choose the form from the structure found in the registers, pre-fill every person we can
(name, date of birth, nationality, address, stake and chain of ownership, source) and list
what is missing. The analyst completes and corrects the draft; the contracting party signs
the official form. This module never decides alone: each choice is explained.
"""

from __future__ import annotations

import re
from typing import Any

from app.models import Entity, EntityType, RelationType
from app.risk.config import get_jurisdictions
from app.schemas import Investigation

TITLES = {
    "K": "Form K — Establishment of the controlling person (operating legal entities and partnerships)",
    "A": "Form A — Establishment of the beneficial owner's identity",
    "T": "Form T — Trusts",
    "S": "Form S — Foundations and similar constructs",
}
ROLE_LABEL = {
    "controlling": "Controlling person",
    "beneficial_owner": "Beneficial owner",
    "settlor": "Settlor",
    "trustee": "Trustee",
    "protector": "Protector",
    "beneficiary": "Beneficiary",
    "founder": "Founder",
    "board": "Member of the foundation board",
}
PERSON_FIELDS = ("last_name", "first_name", "birth_date", "nationality", "address", "country")
FIELD_LABEL = {
    "last_name": "Last name",
    "first_name": "First name(s)",
    "birth_date": "Date of birth",
    "nationality": "Nationality",
    "address": "Actual address of domicile",
    "country": "Country of domicile",
}
REQUIRED = {
    "K": ("last_name", "first_name", "address", "country"),
    "A": ("last_name", "first_name", "birth_date", "nationality", "address", "country"),
    "T": ("last_name", "first_name", "birth_date", "nationality", "address", "country"),
    "S": ("last_name", "first_name", "birth_date", "nationality", "address", "country"),
}
DECLARATION = (
    "The contracting party undertakes to inform the bank of any change on its own initiative. "
    "The intentional provision of false information on this form is a criminal offence "
    "(forgery of documents, art. 251 Swiss Criminal Code)."
)
DRAFT_NOTE = (
    "Draft pre-filled by KYC 1 CLICK from public registers, for the analyst to verify and "
    "complete. It follows the content of the CDB 20 forms; the contracting party signs the "
    "bank's official form."
)

TRUST = re.compile(r"\b(trust|treuhandschaft|trustees?)\b", re.I)
TRUST_CO = re.compile(
    r"\btrust\s+(company|co\b|corp|corporation|bank|services|ltd|limited|sa\b|ag\b|inc|gmbh)", re.I
)
FOUNDATION = re.compile(
    r"\b(stiftung|foundation|fondation|fondazione|fundaci[oó]n|stichting|fundação)\b", re.I
)
MANAGER = re.compile(
    r"director|managing|manager|ceo|chief exec|g[ée]rant|gesch[äa]ftsf[üu]hr|pr[ée]sident|"
    r"administrat|board|verwaltungsrat|conseil|chair|partner|associ[ée] g[ée]rant",
    re.I,
)


def kind_of(e: Entity) -> str:
    """trust | foundation | company | person"""
    if e.type == EntityType.PERSON:
        return "person"
    text = f"{e.name} {e.legal_form or ''}"
    if TRUST.search(text) and not TRUST_CO.search(text):
        return "trust"
    if FOUNDATION.search(text):
        return "foundation"
    return "company"


def split_name(name: str) -> tuple[str, str]:
    """(last, first). Registers write "LAST, First", "First LAST" or "First Last"."""
    name = re.sub(r"\s+", " ", name).strip()
    if "," in name:
        last, first = name.split(",", 1)
        return last.strip(), first.strip()
    parts = name.split(" ")
    upper = [p for p in parts if len(p.strip(".")) > 1 and p.isupper()]
    if upper and len(upper) < len(parts):
        return " ".join(upper), " ".join(p for p in parts if p not in upper)
    if len(parts) == 1:
        return parts[0], ""
    return parts[-1], " ".join(parts[:-1])


def _src(e: Entity | None) -> str:
    if e is None or not e.sources:
        return ""
    return e.sources[0].source_label


def _person(
    e: Entity | None,
    role: str,
    basis: str,
    *,
    key: str,
    name: str | None = None,
    pct: float | None = None,
    path: list[str] | None = None,
    flags: list[str] | None = None,
) -> dict[str, Any]:
    jur = get_jurisdictions()
    if e is not None and e.type == EntityType.PERSON:
        last, first = split_name(e.name)
        fields = {
            "last_name": last,
            "first_name": first,
            "birth_date": e.birth_date or "",
            "nationality": ", ".join(jur.name(n) for n in e.nationalities),
            "address": e.address or "",
            "country": "",
        }
    else:
        fields = {f: "" for f in PERSON_FIELDS}
        if e is not None:  # a company or structure: only its name is known
            fields["last_name"] = e.name
    if name and not fields["last_name"]:
        fields["last_name"] = name
    return {
        "key": key,
        "entity_id": e.id if e is not None else None,
        "role": role,
        "role_label": ROLE_LABEL[role],
        "basis": basis,
        "pct": round(pct, 2) if pct is not None else None,
        "path": path or [],
        "flags": flags or [],
        "source": _src(e),
        "is_company": bool(e is not None and e.type != EntityType.PERSON),
        **fields,
    }


class _Net:
    def __init__(self, inv: Investigation) -> None:
        self.inv = inv
        self.ents = {e.id: e for e in inv.entities}
        self.subject = self.ents[inv.subject_id]

    def links_to(self, target: str, *types: RelationType) -> list[tuple[Any, Entity]]:
        out = []
        for r in self.inv.relationships:
            if (
                r.target_id == target
                and r.type in types
                and r.is_active
                and r.source_id in self.ents
            ):
                out.append((r, self.ents[r.source_id]))
        return out

    def managers(self, target: str) -> list[tuple[Any, Entity]]:
        return [
            (r, e)
            for r, e in self.links_to(target, RelationType.OFFICER)
            if e.type == EntityType.PERSON and MANAGER.search(r.role or "director")
        ]


def _controlling(net: _Net, form: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Persons for Form K / A of the subject, with the CDB 20 cascade and the reasons."""
    notes: list[str] = []
    owners = net.inv.brief.owners if net.inv.brief else []
    role = "controlling" if form == "K" else "beneficial_owner"
    persons = []
    for o in owners:
        if o.pct < 25:
            continue
        e = net.ents.get(o.entity_id)
        if o.kind == "person":
            persons.append(
                _person(
                    e,
                    role,
                    f"Holds {o.pct:.1f} % of the capital or votes"
                    + (" (indirectly)" if len(o.path) > 2 else ""),
                    key=o.entity_id,
                    name=o.name,
                    pct=o.pct,
                    path=o.path,
                    flags=o.flags,
                )
            )
        else:
            persons.append(
                _person(
                    e,
                    role,
                    f"The chain stops at {o.name} ({o.pct:.1f} %): identify the natural persons "
                    "behind it",
                    key=o.entity_id,
                    name=o.name,
                    pct=o.pct,
                    path=o.path,
                    flags=o.flags,
                )
            )
            notes.append(
                f"{o.name} holds {o.pct:.1f} % but its own owners are not in the registers "
                "consulted: obtain its register of members or a signed group chart."
            )
    if persons:
        return persons, notes
    declared = [
        (r, e)
        for r, e in net.links_to(net.subject.id, RelationType.BENEFICIAL_OWNER)
        if e.type == EntityType.PERSON
    ]
    if declared:
        notes.append(
            "No shareholder of 25 % or more in the registers: the persons declared as beneficial "
            "owners / persons with significant control are retained (control by other means)."
        )
        return [
            _person(
                e,
                role,
                "Controls the company by other means (declared beneficial owner"
                + (f", {r.role}" if r.role else "")
                + ")",
                key=e.id,
                pct=r.share_pct,
            )
            for r, e in declared
        ], notes
    managers = net.managers(net.subject.id)
    if managers:
        notes.append(
            "No controlling person could be identified (no holding of 25 % or more, no other "
            "form of control found): by default the managing person is recorded (CDB 20, "
            "art. 20). Confirm with the client that nobody controls the company otherwise."
        )
        return [
            _person(e, role, f"Managing person ({r.role or 'director'}) — default rule", key=e.id)
            for r, e in managers[:3]
        ], notes
    notes.append(
        "The registers give neither the owners nor the managers: the whole form is to be "
        "completed with the client."
    )
    return [_person(None, role, "To be declared by the contracting party", key="new-1")], notes


def _trust_form(net: _Net, t: Entity, fid: str) -> dict[str, Any]:
    trustees = [
        _person(e, "trustee", f"Trustee ({r.role or 'officer'}) in the register", key=e.id)
        for r, e in net.links_to(t.id, RelationType.OFFICER)
    ]
    people = [
        *(
            trustees
            or [_person(None, "trustee", "To be declared (trust deed)", key=f"{fid}-trustee")]
        ),
        _person(None, "settlor", "To be declared (trust deed)", key=f"{fid}-settlor"),
        _person(None, "protector", "If any (trust deed)", key=f"{fid}-protector"),
        _person(
            None,
            "beneficiary",
            "Named beneficiaries or class (trust deed / letter of wishes)",
            key=f"{fid}-beneficiary",
        ),
    ]
    return {
        "id": fid,
        "code": "T",
        "title": TITLES["T"],
        "entity": t.name,
        "why": f"{t.name} is a trust: settlor, trustees, protector and beneficiaries must be identified.",
        "structure": [
            {"key": "trust_name", "label": "Name of the trust", "value": t.name},
            {
                "key": "trust_type",
                "label": "Type (discretionary / fixed interest; revocable / irrevocable)",
                "value": "",
            },
            {
                "key": "governing_law",
                "label": "Governing law",
                "value": get_jurisdictions().name(t.jurisdiction) if t.jurisdiction else "",
            },
        ],
        "persons": people,
        "notes": [
            "Request the trust deed, the letter of wishes and any deed of appointment of the trustees or protector."
        ],
    }


def _foundation_form(net: _Net, f: Entity, fid: str) -> dict[str, Any]:
    board = [
        _person(e, "board", f"Board member ({r.role or 'officer'}) in the register", key=e.id)
        for r, e in net.links_to(f.id, RelationType.OFFICER)
    ]
    people = [
        _person(None, "founder", "To be declared (deed of foundation)", key=f"{fid}-founder"),
        *(board or [_person(None, "board", "To be declared", key=f"{fid}-board")]),
        _person(
            None,
            "beneficiary",
            "Beneficiaries or class of beneficiaries (by-laws)",
            key=f"{fid}-beneficiary",
        ),
    ]
    return {
        "id": fid,
        "code": "S",
        "title": TITLES["S"],
        "entity": f.name,
        "why": f"{f.name} is a foundation: founder, board and beneficiaries must be identified.",
        "structure": [
            {"key": "foundation_name", "label": "Name of the foundation", "value": f.name},
            {"key": "revocable", "label": "Revocable (yes / no)", "value": ""},
            {
                "key": "seat",
                "label": "Seat",
                "value": get_jurisdictions().name(f.jurisdiction) if f.jurisdiction else "",
            },
        ],
        "persons": people,
        "notes": [
            "Request the deed of foundation, the by-laws and any regulations naming the beneficiaries."
        ],
    }


def _domiciliary(net: _Net) -> str | None:
    s = net.subject
    jur = get_jurisdictions()
    if s.is_offshore or (s.jurisdiction and s.jurisdiction in jur.offshore_centres):
        return (
            f"registered in {jur.name(s.jurisdiction) if s.jurisdiction else 'an offshore centre'}"
        )
    for f in net.inv.risk.factors:
        if f.key == "shell_company_indicators" and (not f.entities or s.id in f.entities):
            return "shell-company indicators in its accounts"
    return None


def _listed(s: Entity) -> bool:
    return any("isin" in k.lower() or "ticker" in k.lower() for k in s.identifiers) or bool(
        re.search(r"\blisted\b|\bcot[ée]e\b|börsenkotiert", s.legal_form or "", re.I)
    )


def build(inv: Investigation, saved: dict[str, Any] | None = None) -> dict[str, Any]:
    """Forms to sign for this client, pre-filled, with the analyst's edits applied."""
    saved = saved or {}
    net = _Net(inv)
    s = net.subject
    jur = get_jurisdictions()
    forms: list[dict[str, Any]] = []
    exemption = None
    kind = kind_of(s)

    if kind == "person":
        forms.append(
            {
                "id": "A",
                "code": "A",
                "title": TITLES["A"],
                "entity": s.name,
                "why": "Natural person: Form A confirms who the assets belong to. Needed when the "
                "client is not the sole beneficial owner or when there is a doubt.",
                "structure": [],
                "persons": [
                    _person(
                        s,
                        "beneficial_owner",
                        "Contracting party declared as beneficial owner",
                        key=s.id,
                    )
                ],
                "notes": [],
            }
        )
    elif kind == "trust":
        forms.append(_trust_form(net, s, "T"))
    elif kind == "foundation":
        forms.append(_foundation_form(net, s, "S"))
    else:
        dom = _domiciliary(net)
        code = "A" if dom else "K"
        persons, notes = _controlling(net, code)
        if _listed(s):
            exemption = (
                "The company appears to be listed on a stock exchange: listed companies and their "
                "majority-owned subsidiaries are exempt from establishing the controlling person "
                "(CDB 20). Keep the evidence of the listing in the file."
            )
        why = (
            f"Domiciliary company presumed ({dom}): the beneficial owner of the assets is "
            "established on Form A. If the company has real operations (premises, staff), use "
            "Form K instead."
            if dom
            else "Operating company: its controlling persons are established on Form K "
            "(25 % of capital or votes, otherwise control by other means, otherwise the "
            "managing person)."
        )
        forms.append(
            {
                "id": code,
                "code": code,
                "title": TITLES[code],
                "entity": s.name,
                "why": why,
                "structure": [],
                "persons": persons,
                "notes": notes,
            }
        )
        # Trusts and foundations inside the ownership chain need their own form.
        chain = {n for o in (inv.brief.owners if inv.brief else []) for n in o.path}
        for e in inv.entities:
            if e.id == s.id or e.name not in chain:
                continue
            k = kind_of(e)
            if k == "trust":
                forms.append(_trust_form(net, e, f"T-{e.id}"))
            elif k == "foundation":
                forms.append(_foundation_form(net, e, f"S-{e.id}"))

    _apply_edits(forms, saved)
    for f in forms:
        req = REQUIRED[f["code"]]
        total = 0
        for p in f["persons"]:
            p["missing"] = [FIELD_LABEL[k] for k in req if not str(p.get(k) or "").strip()]
            total += len(p["missing"])
        f["missing_count"] = total + sum(1 for x in f["structure"] if not str(x["value"]).strip())

    header_saved = saved.get("header") or {}
    party = {
        "name": s.name,
        "legal_form": s.legal_form or "",
        "registration_number": s.registration_number or "",
        "country": jur.name(s.jurisdiction) if s.jurisdiction else "",
        "address": s.address or "",
        "relationship_no": "",
        **{k: v for k, v in header_saved.items() if isinstance(v, str)},
    }
    return {
        "contracting_party": party,
        "primary": forms[0]["code"] if forms else None,
        "forms": forms,
        "exemption": exemption,
        "declaration": DECLARATION,
        "draft_note": DRAFT_NOTE,
        "missing_total": sum(f["missing_count"] for f in forms),
        "edited_by": saved.get("by"),
        "edited_at": saved.get("at"),
    }


def _apply_edits(forms: list[dict[str, Any]], saved: dict[str, Any]) -> None:
    edits = saved.get("persons") or {}
    added = saved.get("added") or {}
    removed = saved.get("removed") or {}
    structure = saved.get("structure") or {}
    for f in forms:
        fid = f["id"]
        f["persons"] = [p for p in f["persons"] if p["key"] not in set(removed.get(fid) or [])]
        for extra in added.get(fid) or []:
            role = (
                extra.get("role")
                if extra.get("role") in ROLE_LABEL
                else f["persons"][0]["role"]
                if f["persons"]
                else "beneficial_owner"
            )
            p = _person(None, role, extra.get("basis") or "Added by the analyst", key=extra["key"])
            f["persons"].append(p)
        for p in f["persons"]:
            for k, v in ((edits.get(fid) or {}).get(p["key"]) or {}).items():
                if k in (*PERSON_FIELDS, "basis") and isinstance(v, str):
                    p[k] = v[:300]
                    p.setdefault("edited", []).append(k)
        for x in f["structure"]:
            v = (structure.get(fid) or {}).get(x["key"])
            if isinstance(v, str):
                x["value"] = v[:300]


def merge_edit(saved: dict[str, Any], edit: dict[str, Any], by: str, at: str) -> dict[str, Any]:
    """Apply one analyst edit to the saved state: header / structure / person fields, add or
    remove a person."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in (saved or {}).items()}
    fid = str(edit.get("form") or "")
    if edit.get("header"):
        out["header"] = {
            **(out.get("header") or {}),
            **{k: str(v)[:300] for k, v in edit["header"].items()},
        }
    if edit.get("structure") and fid:
        st = dict(out.get("structure") or {})
        st[fid] = {**(st.get(fid) or {}), **{k: str(v)[:300] for k, v in edit["structure"].items()}}
        out["structure"] = st
    if edit.get("person") and fid:
        persons = dict(out.get("persons") or {})
        form = dict(persons.get(fid) or {})
        pk = str(edit["person"])
        form[pk] = {
            **(form.get(pk) or {}),
            **{k: str(v)[:300] for k, v in (edit.get("fields") or {}).items()},
        }
        persons[fid] = form
        out["persons"] = persons
    if edit.get("add") and fid:
        added = dict(out.get("added") or {})
        lst = list(added.get(fid) or [])
        lst.append(
            {
                "key": f"added-{len(lst) + 1}-{at[-8:].replace(':', '')}",
                "role": str(edit.get("role") or ""),
            }
        )
        added[fid] = lst[-20:]
        out["added"] = added
    if edit.get("remove") and fid:
        removed = dict(out.get("removed") or {})
        removed[fid] = sorted({*(removed.get(fid) or []), str(edit["remove"])})
        out["removed"] = removed
        added = dict(out.get("added") or {})
        added[fid] = [a for a in added.get(fid) or [] if a["key"] != edit["remove"]]
        out["added"] = added
    out["by"], out["at"] = by, at
    return out
