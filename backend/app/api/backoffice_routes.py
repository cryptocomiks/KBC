"""Back office API: tasks, outgoing e-mails and document receptions across all cases.
Behind the same password as the cases."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.cases_routes import cases, require_access
from app.backoffice import BackOffice

router = APIRouter(
    prefix="/backoffice", tags=["back office"], dependencies=[Depends(require_access)]
)


def bo() -> BackOffice:
    return BackOffice(cases())


def _run(fn, *args: Any) -> Any:
    try:
        return fn(*args)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class TaskIn(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    detail: str | None = Field(default=None, max_length=4000)
    status: str | None = Field(default=None, pattern="^(todo|doing|waiting|done)$")
    priority: str | None = Field(default=None, pattern="^(high|medium|low)$")
    assignee: str | None = Field(default=None, max_length=120)
    due: str | None = Field(default=None, max_length=10)
    case_id: str | None = Field(default=None, max_length=40)
    by: str = Field(default="", max_length=120)


class MailIn(BaseModel):
    to: str | None = Field(default=None, max_length=254)
    subject: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=20000)
    case_id: str | None = Field(default=None, max_length=40)
    by: str = Field(default="", max_length=120)


class ReceivedIn(BaseModel):
    case_id: str = Field(max_length=40)
    key: str = Field(max_length=40)
    received: bool
    by: str = Field(default="", max_length=120)


@router.get("")
def board(lang: str = "en") -> dict:
    """Everything the team has to do, has sent and is waiting for."""
    return bo().board("fr" if lang == "fr" else "en")


@router.post("/tasks")
def add_task(t: TaskIn) -> dict:
    if not (t.title or "").strip():
        raise HTTPException(status_code=422, detail="A task needs a title")
    data = t.model_dump(exclude_none=True, exclude={"by"})
    return _run(bo().save_task, data, t.by)


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, t: TaskIn) -> dict:
    return _run(bo().save_task, t.model_dump(exclude_none=True, exclude={"by"}), t.by, task_id)


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str) -> dict:
    _run(bo().delete_task, task_id)
    return {"deleted": task_id}


@router.post("/mails")
def new_mail(m: MailIn) -> dict:
    return _run(bo().new_mail, m.model_dump(), m.by)


@router.patch("/mails/{mail_id}")
def edit_mail(mail_id: str, m: MailIn) -> dict:
    return _run(bo().edit_mail, mail_id, m.model_dump(exclude_none=True, exclude={"by", "case_id"}))


@router.post("/mails/{mail_id}/sent")
def mail_sent(mail_id: str, m: MailIn) -> dict:
    """The analyst sent the e-mail from their mail app: the documents it asks for are now awaited."""
    return _run(bo().mark_sent, mail_id, m.by)


@router.delete("/mails/{mail_id}")
def delete_mail(mail_id: str) -> dict:
    _run(bo().delete_mail, mail_id)
    return {"deleted": mail_id}


@router.post("/receptions")
def received(r: ReceivedIn) -> dict:
    _run(bo().mark_received, r.case_id, r.key, r.received, r.by)
    return {"case_id": r.case_id, "key": r.key, "received": r.received}
