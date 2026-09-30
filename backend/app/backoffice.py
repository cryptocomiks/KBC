"""Back office: the work of a KYC team across all its cases.

* Tasks: generated from the state of every case (a questionnaire to answer, documents to
  request or chase, alerts to review, a validation waiting for the second pair of eyes, a
  periodic review coming up), plus tasks the team adds itself. A generated task closes itself
  when its cause disappears, and stays in the log of work done, with who closed it and when.
* E-mails: the letters a client needs (document request, reminder, periodic review) are
  drafted automatically; the analyst edits, sends from their own mail app and marks them sent.
  Sending a request starts the clock on the documents it asks for.
* Receptions: every document of every case, to request, awaited, overdue or received, with
  the dates and the number of reminders.

Everything lives in the case store (SQLite or Postgres). Nothing is sent by the server.
"""

from __future__ import annotations

import statistics
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app import workflow as wf
from app.store import Store, now

REQUEST_DAYS = 14  # time given to the client after a document request
REMINDER_DAYS = 7  # after a reminder
REVIEW_HORIZON_DAYS = 30
STATUSES = ("todo", "doing", "waiting", "done")


def _today() -> date:
    return datetime.now(UTC).date()


def _plus(days: int) -> str:
    return (_today() + timedelta(days=days)).isoformat()


# ----------------------------------------------------------------- e-mail templates
TEMPLATES = {
    "request": {
        "en": (
            "Documents required: {name}",
            "Dear client,\n\nAs part of our customer due diligence obligations, we kindly ask you to "
            "provide the following documents by {due}:\n\n{items}\n\nRegister extracts and proofs of "
            "address should be less than 3 months old, and copies certified where applicable.\n\n"
            "Thank you for your cooperation.\nKind regards,",
        ),
        "fr": (
            "Documents requis : {name}",
            "Madame, Monsieur,\n\nDans le cadre de nos obligations de vigilance, nous vous remercions "
            "de nous transmettre les documents suivants d'ici au {due} :\n\n{items}\n\nLes extraits de "
            "registre et justificatifs de domicile doivent dater de moins de 3 mois, et les copies "
            "être certifiées le cas échéant.\n\nNous vous remercions de votre collaboration.\n"
            "Meilleures salutations,",
        ),
    },
    "reminder": {
        "en": (
            "Reminder: documents still awaited for {name}",
            "Dear client,\n\nFurther to our request of {requested}, we have not yet received the "
            "following documents:\n\n{items}\n\nCould you send them by {due}? Without them we cannot "
            "complete your file.\n\nKind regards,",
        ),
        "fr": (
            "Relance : documents en attente pour {name}",
            "Madame, Monsieur,\n\nSuite à notre demande du {requested}, nous n'avons pas encore reçu "
            "les documents suivants :\n\n{items}\n\nPourriez-vous nous les transmettre d'ici au {due} ? "
            "Sans eux, nous ne pouvons pas finaliser votre dossier.\n\nMeilleures salutations,",
        ),
    },
    "review": {
        "en": (
            "Periodic review of your file: {name}",
            "Dear client,\n\nOur regulatory obligations require us to review your file periodically "
            "(next review: {review}). Please confirm that the information we hold is still accurate "
            "(activity, beneficial owners, address, source of funds) and send us an updated register "
            "extract and the identity documents that have expired.\n\nKind regards,",
        ),
        "fr": (
            "Revue périodique de votre dossier : {name}",
            "Madame, Monsieur,\n\nNos obligations réglementaires nous imposent de revoir votre dossier "
            "périodiquement (prochaine revue : {review}). Merci de nous confirmer que les informations "
            "en notre possession sont toujours exactes (activité, ayants droit économiques, adresse, "
            "origine des fonds) et de nous transmettre un extrait de registre à jour ainsi que les "
            "pièces d'identité arrivées à échéance.\n\nMeilleures salutations,",
        ),
    },
}


def _fmt_date(iso: str | None, lang: str) -> str:
    if not iso:
        return ""
    y, m, d = str(iso)[:10].split("-")
    return f"{d}.{m}.{y}" if lang == "fr" else f"{d}/{m}/{y}"


def render(
    kind: str, lang: str, name: str, docs: list[str], **dates: str | None
) -> tuple[str, str]:
    subject, body = TEMPLATES[kind][lang if lang in ("en", "fr") else "en"]
    items = "\n".join(f"{i}. {d}" for i, d in enumerate(docs, 1))
    values = {k: _fmt_date(v, lang) for k, v in dates.items()}
    return subject.format(name=name), body.format(name=name, items=items, **values)


class BackOffice:
    def __init__(self, cases: Any) -> None:
        self.cases = cases
        self.store: Store = cases.store

    # ------------------------------------------------------------ helpers
    def _live_cases(self) -> list[dict[str, Any]]:
        return [c for c in self.store.list_cases() if c.get("status") != "closed"]

    def _requests(self, case: dict[str, Any]) -> list[dict[str, Any]]:
        """Documents to ask the client for. Saved in the snapshot since the back office; for an
        older case they are read once from its (cached) investigation and saved."""
        if case.get("import_state"):
            return []
        if case.get("requests") is not None:
            return case["requests"]
        full = self.store.get_case(case["id"]) or {}
        try:
            inv = self.cases.service.investigate(self.cases._params(full))
        except Exception:  # noqa: BLE001 - a case that cannot be computed has no request list
            return []
        reqs = [
            {"document": r.document, "reason": r.reason, "priority": r.priority}
            for r in inv.requests
        ]
        snap = dict(full.get("snapshot") or {})
        snap["requests"] = reqs
        self.store.update_case(case["id"], snapshot=snap)
        return reqs

    def _logs(self) -> dict[str, dict[str, Any]]:
        return {r["auto_key"]: r for r in self.store.bo_list("request")}

    def contacts(self) -> dict[str, str]:
        return {r["case_id"]: r.get("email", "") for r in self.store.bo_list("contact")}

    def set_contact(self, case_id: str, email: str) -> None:
        existing = next((r for r in self.store.bo_list("contact") if r["case_id"] == case_id), None)
        self.store.bo_save(
            "contact",
            {"email": email.strip()[:254]},
            item_id=existing["id"] if existing else None,
            case_id=case_id,
            auto_key=case_id,
        )

    # --------------------------------------------------------- receptions
    def receptions(self, cases: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        cases = cases if cases is not None else self._live_cases()
        logs = self._logs()
        today = _today().isoformat()
        rows = []
        for c in cases:
            ticks = (c.get("checklist") or {}).get("ticks") or {}
            for r in self._requests(c):
                k = wf.key("doc|" + r["document"])
                tick = ticks.get(k) or {}
                log = logs.get(f"{c['id']}|{k}") or {}
                if tick.get("done"):
                    status = "received"
                elif log.get("requested_at"):
                    status = "overdue" if (log.get("due_at") or today) < today else "awaited"
                else:
                    status = "to_request"
                rows.append(
                    {
                        "case_id": c["id"],
                        "case_title": c["title"],
                        "key": k,
                        "document": r["document"],
                        "reason": r.get("reason", ""),
                        "required": r.get("priority") == "required",
                        "status": status,
                        "requested_at": log.get("requested_at"),
                        "due_at": log.get("due_at"),
                        "reminders": log.get("reminders", 0),
                        "last_reminder_at": log.get("last_reminder_at"),
                        "received_at": tick.get("at") if tick.get("done") else None,
                        "received_by": tick.get("by") if tick.get("done") else None,
                    }
                )
        return rows

    def mark_received(self, case_id: str, key: str, received: bool, by: str) -> None:
        case = self.store.get_case(case_id)
        if case is None:
            raise LookupError("Case not found")
        saved = dict(case.get("checklist") or {})
        ticks = dict(saved.get("ticks") or {})
        ticks[key] = {
            "done": received,
            "by": by,
            "at": now(),
            "note": "received" if received else "",
        }
        saved["ticks"] = ticks
        self.store.update_case(case_id, checklist=saved)

    def _log_request(self, case_id: str, key: str, reminder: bool) -> None:
        auto = f"{case_id}|{key}"
        log = self._logs().get(auto) or {}
        data = {k: v for k, v in log.items() if k not in ("id", "kind", "case_id", "auto_key")}
        if reminder and data.get("requested_at"):
            data["reminders"] = int(data.get("reminders") or 0) + 1
            data["last_reminder_at"] = now()
            data["due_at"] = _plus(REMINDER_DAYS)
        else:
            data.setdefault("requested_at", now())
            data["due_at"] = _plus(REQUEST_DAYS)
            data.setdefault("reminders", 0)
        self.store.bo_save("request", data, item_id=log.get("id"), case_id=case_id, auto_key=auto)

    # --------------------------------------------------------------- tasks
    def _wanted_tasks(
        self, cases: list[dict[str, Any]], receptions: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        by_case: dict[str, list[dict[str, Any]]] = {}
        for r in receptions:
            by_case.setdefault(r["case_id"], []).append(r)
        horizon = _plus(REVIEW_HORIZON_DAYS)
        today = _today().isoformat()
        out: dict[str, dict[str, Any]] = {}

        def add(
            kind: str, c: dict[str, Any], title: str, priority: str, tab: str, **extra: Any
        ) -> None:
            out[f"{kind}|{c['id']}"] = {
                "title": title,
                "case_id": c["id"],
                "case_title": c["title"],
                "priority": priority,
                "tab": tab,
                "source": "auto",
                "rule": kind,
                **extra,
            }

        for c in cases:
            state = c.get("import_state")
            if state in ("ambiguous", "not_found", "error"):
                add("import", c, "Pick the right company for this imported client", "medium", "kyc")
                continue
            if state:
                continue
            q = c.get("questionnaire") or {}
            wstate = wf.state_of(c)
            if c.get("risk_level") == "critical" and wstate != "validated":
                add(
                    "escalate",
                    c,
                    "Critical risk: escalate to the compliance officer (MLRO)",
                    "high",
                    "memo",
                )
            if c.get("unseen_changes"):
                n = c["unseen_changes"]
                add(
                    "changes",
                    c,
                    f"Review {n} change{'s' if n > 1 else ''} found by the monitoring",
                    "high",
                    "history",
                )
            if not q.get("vigilance"):
                add("questionnaire", c, "Answer the KYC questionnaire", "medium", "kyc")
            docs = by_case.get(c["id"], [])
            to_request = [d for d in docs if d["status"] == "to_request"]
            overdue = [d for d in docs if d["status"] == "overdue"]
            if to_request:
                add(
                    "request",
                    c,
                    f"Request {len(to_request)} document{'s' if len(to_request) > 1 else ''} from the client",
                    "medium",
                    "mail",
                )
            if overdue:
                add(
                    "chase",
                    c,
                    f"Chase {len(overdue)} overdue document{'s' if len(overdue) > 1 else ''}",
                    "high",
                    "mail",
                    due=min(d["due_at"] for d in overdue),
                )
            if wstate == "pending_validation":
                add("validate", c, "Validate the file (second pair of eyes)", "high", "kyc")
            nxt = str(q.get("next_review") or "")[:10]
            if wstate == "validated" and nxt and nxt <= horizon:
                add(
                    "review",
                    c,
                    "Periodic review " + ("overdue" if nxt < today else "due"),
                    "high" if nxt < today else "medium",
                    "review",
                    due=nxt,
                )
        return out

    def tasks(
        self, cases: list[dict[str, Any]], receptions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Sync the generated tasks with the saved ones, then return them all."""
        wanted = self._wanted_tasks(cases, receptions)
        saved = {t["auto_key"]: t for t in self.store.bo_list("task") if t.get("auto_key")}
        for key, task in wanted.items():
            old = saved.get(key)
            if old is None:
                self.store.bo_save(
                    "task", {**task, "status": "todo"}, case_id=task["case_id"], auto_key=key
                )
            else:
                data = {**old, **task}
                if old.get("status") == "done":  # the cause is back: the task reopens
                    data.update(status="todo", done_at=None, done_by=None, reopened=True)
                if data != old:
                    self.store.bo_save("task", data, item_id=old["id"])
        for key, old in saved.items():
            if key not in wanted and old.get("status") != "done":
                self.store.bo_save(
                    "task",
                    {
                        **old,
                        "status": "done",
                        "done_at": now(),
                        "done_by": "Automatically (resolved in the case)",
                    },
                    item_id=old["id"],
                )
        order = {"high": 0, "medium": 1, "low": 2}
        return sorted(
            self.store.bo_list("task"),
            key=lambda t: (
                order.get(t.get("priority"), 1),
                t.get("due") or "9999",
                t["created_at"],
            ),
        )

    def save_task(
        self, data: dict[str, Any], by: str, task_id: str | None = None
    ) -> dict[str, Any]:
        old = self.store.bo_get(task_id) if task_id else None
        if task_id and (old is None or old["kind"] != "task"):
            raise LookupError("Task not found")
        merged = {**(old or {"source": "manual", "priority": "medium", "status": "todo"}), **data}
        if merged.get("status") not in STATUSES:
            raise ValueError("Unknown status")
        if merged["status"] == "done" and (old or {}).get("status") != "done":
            merged.update(done_at=now(), done_by=by)
        if merged["status"] != "done":
            merged.update(done_at=None, done_by=None)
        if old is None:
            merged["created_by"] = by
        return self.store.bo_save("task", merged, item_id=task_id, case_id=merged.get("case_id"))

    def delete_task(self, task_id: str) -> None:
        task = self.store.bo_get(task_id)
        if task is None or task["kind"] != "task":
            raise LookupError("Task not found")
        if task.get("source") == "auto":
            raise ValueError(
                "A generated task closes itself when its cause is resolved in the case."
            )
        self.store.bo_delete(task_id)

    # --------------------------------------------------------------- mails
    def mails(
        self, cases: list[dict[str, Any]], receptions: list[dict[str, Any]], lang: str
    ) -> list[dict[str, Any]]:
        """Sync the automatic drafts with the state of the cases, then return every e-mail."""
        contacts = self.contacts()
        by_case: dict[str, list[dict[str, Any]]] = {}
        for r in receptions:
            by_case.setdefault(r["case_id"], []).append(r)
        wanted: dict[str, dict[str, Any]] = {}
        horizon = _plus(REVIEW_HORIZON_DAYS)
        for c in cases:
            docs = by_case.get(c["id"], [])
            name = c.get("subject_name") or c["title"]
            to_request = [d for d in docs if d["status"] == "to_request"]
            if to_request:
                subject, body = render(
                    "request",
                    lang,
                    name,
                    [d["document"] for d in to_request],
                    due=_plus(REQUEST_DAYS),
                )
                wanted[f"request|{c['id']}"] = {
                    "type": "request",
                    "subject": subject,
                    "body": body,
                    "documents": [d["key"] for d in to_request],
                    "case_id": c["id"],
                }
            overdue = [d for d in docs if d["status"] == "overdue"]
            if overdue:
                first = min(d["requested_at"] for d in overdue)
                n = max(d["reminders"] for d in overdue) + 1
                subject, body = render(
                    "reminder",
                    lang,
                    name,
                    [d["document"] for d in overdue],
                    requested=first,
                    due=_plus(REMINDER_DAYS),
                )
                wanted[f"reminder|{c['id']}|{n}"] = {
                    "type": "reminder",
                    "subject": subject,
                    "body": body,
                    "documents": [d["key"] for d in overdue],
                    "case_id": c["id"],
                    "reminder": n,
                }
            q = c.get("questionnaire") or {}
            nxt = str(q.get("next_review") or "")[:10]
            if wf.state_of(c) == "validated" and nxt and nxt <= horizon:
                subject, body = render("review", lang, name, [], review=nxt)
                wanted[f"review|{c['id']}|{nxt}"] = {
                    "type": "review",
                    "subject": subject,
                    "body": body,
                    "documents": [],
                    "case_id": c["id"],
                }
        titles = {c["id"]: c["title"] for c in cases}
        saved = {m["auto_key"]: m for m in self.store.bo_list("mail") if m.get("auto_key")}
        for key, mail in wanted.items():
            old = saved.get(key)
            if old is None:
                self.store.bo_save(
                    "mail",
                    {**mail, "status": "draft", "lang": lang},
                    case_id=mail["case_id"],
                    auto_key=key,
                )
            elif old.get("status") == "draft" and not old.get("edited"):
                data = {**old, **mail, "lang": lang}
                if data != old:
                    self.store.bo_save("mail", data, item_id=old["id"])
        for key, old in saved.items():
            if key not in wanted and old.get("status") == "draft" and not old.get("edited"):
                self.store.bo_delete(old["id"])  # nothing left to ask
        out = []
        for m in self.store.bo_list("mail"):
            m["to"] = m.get("to") or contacts.get(m.get("case_id") or "", "")
            m["case_title"] = titles.get(m.get("case_id") or "", m.get("case_title", ""))
            out.append(m)
        return sorted(
            out,
            key=lambda m: (m.get("status") != "draft", m.get("sent_at") or "", m["created_at"]),
            reverse=False,
        )

    def edit_mail(self, mail_id: str, data: dict[str, Any]) -> dict[str, Any]:
        old = self.store.bo_get(mail_id)
        if old is None or old["kind"] != "mail":
            raise LookupError("E-mail not found")
        if old.get("status") == "sent":
            raise ValueError("This e-mail has been sent: it can no longer be changed.")
        allowed = {k: str(v)[:20000] for k, v in data.items() if k in ("to", "subject", "body")}
        if "to" in allowed and old.get("case_id"):
            self.set_contact(old["case_id"], allowed["to"])
        return self.store.bo_save("mail", {**old, **allowed, "edited": True}, item_id=mail_id)

    def new_mail(self, data: dict[str, Any], by: str) -> dict[str, Any]:
        return self.store.bo_save(
            "mail",
            {
                "type": "custom",
                "status": "draft",
                "edited": True,
                "documents": [],
                "created_by": by,
                **{k: str(data.get(k) or "")[:20000] for k in ("to", "subject", "body")},
            },
            case_id=data.get("case_id") or None,
        )

    def mark_sent(self, mail_id: str, by: str) -> dict[str, Any]:
        mail = self.store.bo_get(mail_id)
        if mail is None or mail["kind"] != "mail":
            raise LookupError("E-mail not found")
        if mail.get("status") == "sent":
            return mail
        for key in mail.get("documents") or []:
            self._log_request(mail["case_id"], key, reminder=mail.get("type") == "reminder")
        return self.store.bo_save(
            "mail",
            {
                **mail,
                "status": "sent",
                "sent_at": now(),
                "sent_by": by,
                "follow_up": _plus(
                    REMINDER_DAYS if mail.get("type") == "reminder" else REQUEST_DAYS
                ),
            },
            item_id=mail_id,
        )

    def delete_mail(self, mail_id: str) -> None:
        mail = self.store.bo_get(mail_id)
        if mail is None or mail["kind"] != "mail":
            raise LookupError("E-mail not found")
        if mail.get("status") == "sent":
            raise ValueError("A sent e-mail stays in the log.")
        if mail.get("auto_key"):  # an automatic draft: kept aside so it is not drafted again
            self.store.bo_save(
                "mail", {**mail, "status": "dismissed", "edited": True}, item_id=mail_id
            )
        else:
            self.store.bo_delete(mail_id)

    # --------------------------------------------------------------- board
    def board(self, lang: str = "en") -> dict[str, Any]:
        cases = self._live_cases()
        receptions = self.receptions(cases)
        tasks = self.tasks(cases, receptions)
        mails = [m for m in self.mails(cases, receptions, lang) if m.get("status") != "dismissed"]
        week = (_today() - timedelta(days=7)).isoformat()
        month = (_today() - timedelta(days=30)).isoformat()
        delays = []
        for r in receptions:
            if r["status"] == "received" and r["requested_at"] and r["received_at"]:
                d = (
                    date.fromisoformat(r["received_at"][:10])
                    - date.fromisoformat(r["requested_at"][:10])
                ).days
                if d >= 0:
                    delays.append(d)
        count = lambda rows, **kv: sum(all(r.get(k) == v for k, v in kv.items()) for r in rows)  # noqa: E731
        stats = {
            "cases": len([c for c in cases if not c.get("import_state")]),
            "tasks_open": sum(t.get("status") != "done" for t in tasks),
            "tasks_high": sum(
                t.get("status") != "done" and t.get("priority") == "high" for t in tasks
            ),
            "tasks_done_week": sum(
                t.get("status") == "done" and (t.get("done_at") or "") >= week for t in tasks
            ),
            "mails_draft": count(mails, status="draft"),
            "mails_sent_week": sum(
                m.get("status") == "sent" and (m.get("sent_at") or "") >= week for m in mails
            ),
            "follow_ups_due": sum(
                m.get("status") == "sent"
                and (m.get("follow_up") or "9999") <= _today().isoformat()
                and any(
                    r["case_id"] == m.get("case_id")
                    and r["key"] in (m.get("documents") or [])
                    and r["status"] != "received"
                    for r in receptions
                )
                for m in mails
            ),
            "docs_total": len(receptions),
            "docs_received": count(receptions, status="received"),
            "docs_received_month": sum(
                r["status"] == "received" and (r["received_at"] or "") >= month for r in receptions
            ),
            "docs_awaited": count(receptions, status="awaited"),
            "docs_overdue": count(receptions, status="overdue"),
            "docs_to_request": count(receptions, status="to_request"),
            "median_days_to_receive": statistics.median(delays) if delays else None,
        }
        return {
            "generated_at": now(),
            "stats": stats,
            "tasks": tasks,
            "mails": mails,
            "receptions": receptions,
            "cases": [
                {"id": c["id"], "title": c["title"]} for c in cases if not c.get("import_state")
            ],
        }
