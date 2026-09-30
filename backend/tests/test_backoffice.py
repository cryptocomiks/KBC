"""Back office: generated tasks, e-mail drafts, the clock on document requests, receptions."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import store as store_mod
from app.main import app
from app.settings import get_settings

client = TestClient(app)
PW = {"X-KBC-Password": "s3cret"}


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_PASSWORD", "s3cret")
    monkeypatch.setenv("STORE_PATH", str(tmp_path / "store.db"))
    monkeypatch.delenv("VERCEL", raising=False)
    get_settings.cache_clear()
    store_mod.reset_store()
    yield
    store_mod.reset_store()
    get_settings.cache_clear()


def _case():
    resp = client.post(
        "/api/cases",
        json={
            "record_ids": ["demo_intl_registry:vg/1874412"],
            "depth": 2,
            "max_nodes": 60,
            "title": "Northgate",
        },
        headers=PW,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def board(lang="en"):
    resp = client.get(f"/api/backoffice?lang={lang}", headers=PW)
    assert resp.status_code == 200, resp.text
    return resp.json()


def rules(b):
    return {t["rule"]: t for t in b["tasks"] if t.get("source") == "auto"}


def test_password_is_required():
    assert client.get("/api/backoffice").status_code == 401


def test_request_send_receive_cycle():
    cid = _case()
    b = board()
    docs = [r for r in b["receptions"] if r["case_id"] == cid]
    assert docs and all(r["status"] == "to_request" for r in docs)
    assert {"questionnaire", "request", "escalate"} <= set(rules(b))  # Northgate is critical
    [draft] = [m for m in b["mails"] if m["type"] == "request"]
    assert draft["status"] == "draft" and len(draft["documents"]) == len(docs)
    assert docs[0]["document"] in draft["body"] and "Documents required" in draft["subject"]
    assert (
        "Documents requis"
        in [m for m in board("fr")["mails"] if m["type"] == "request"][0]["subject"]
    )

    # The analyst adds the address, sends from their mail app and marks it sent.
    edited = client.patch(
        f"/api/backoffice/mails/{draft['id']}", json={"to": "cfo@northgate.example"}, headers=PW
    ).json()
    assert edited["edited"] is True
    sent = client.post(
        f"/api/backoffice/mails/{draft['id']}/sent", json={"by": "Alice"}, headers=PW
    ).json()
    assert sent["status"] == "sent" and sent["sent_by"] == "Alice" and sent["follow_up"]
    b = board()
    docs = [r for r in b["receptions"] if r["case_id"] == cid]
    assert all(r["status"] == "awaited" and r["due_at"] for r in docs)
    done = [t for t in b["tasks"] if t.get("rule") == "request"]
    assert done[0]["status"] == "done" and done[0]["done_by"].startswith("Automatically")
    assert b["stats"]["mails_sent_week"] == 1 and b["stats"]["docs_awaited"] == len(docs)
    # the address is remembered for the next e-mails of the case
    assert all(m["to"] == "cfo@northgate.example" for m in b["mails"] if m["case_id"] == cid)
    assert (
        client.patch(
            f"/api/backoffice/mails/{draft['id']}", json={"body": "x"}, headers=PW
        ).status_code
        == 409
    )

    # One document arrives.
    first = docs[0]
    client.post(
        "/api/backoffice/receptions",
        json={"case_id": cid, "key": first["key"], "received": True, "by": "Bob"},
        headers=PW,
    )
    b = board()
    got = next(r for r in b["receptions"] if r["key"] == first["key"])
    assert got["status"] == "received" and got["received_by"] == "Bob"
    assert b["stats"]["docs_received"] == 1 and b["stats"]["median_days_to_receive"] == 0

    # The deadline passes: the others are overdue, a reminder is drafted and a chase task opens.
    store = store_mod.get_store()
    past = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    for log in store.bo_list("request"):
        store.bo_save("request", {**log, "due_at": past}, item_id=log["id"])
    b = board()
    assert b["stats"]["docs_overdue"] == len(docs) - 1
    assert rules(b)["chase"]["status"] == "todo"
    [reminder] = [m for m in b["mails"] if m["type"] == "reminder"]
    assert (
        reminder["reminder"] == 1
        and "Reminder" in reminder["subject"]
        and first["document"] not in reminder["body"]
    )
    client.post(f"/api/backoffice/mails/{reminder['id']}/sent", json={"by": "Alice"}, headers=PW)
    b = board()
    again = [r for r in b["receptions"] if r["case_id"] == cid and r["status"] != "received"]
    assert all(r["status"] == "awaited" and r["reminders"] == 1 for r in again)


def test_manual_tasks_and_generated_tasks():
    cid = _case()
    b = board()
    auto = rules(b)["questionnaire"]
    assert client.delete(f"/api/backoffice/tasks/{auto['id']}", headers=PW).status_code == 409
    moved = client.patch(
        f"/api/backoffice/tasks/{auto['id']}",
        json={"status": "doing", "assignee": "Alice"},
        headers=PW,
    ).json()
    assert moved["status"] == "doing" and moved["assignee"] == "Alice"
    assert rules(board())["questionnaire"]["status"] == "doing"  # kept across syncs

    t = client.post(
        "/api/backoffice/tasks",
        json={"title": "Call the CFO", "case_id": cid, "by": "Alice", "due": "2030-01-01"},
        headers=PW,
    ).json()
    assert t["status"] == "todo" and t["source"] == "manual" and t["created_by"] == "Alice"
    done = client.patch(
        f"/api/backoffice/tasks/{t['id']}", json={"status": "done", "by": "Bob"}, headers=PW
    ).json()
    assert done["done_by"] == "Bob" and done["done_at"]
    back = client.patch(
        f"/api/backoffice/tasks/{t['id']}", json={"status": "todo"}, headers=PW
    ).json()
    assert back["done_at"] is None
    assert client.post("/api/backoffice/tasks", json={"title": " "}, headers=PW).status_code == 422
    assert (
        client.patch(
            f"/api/backoffice/tasks/{t['id']}", json={"status": "later"}, headers=PW
        ).status_code
        == 422
    )
    assert client.delete(f"/api/backoffice/tasks/{t['id']}", headers=PW).status_code == 200
    assert (
        client.patch("/api/backoffice/tasks/nope", json={"status": "done"}, headers=PW).status_code
        == 404
    )


def test_custom_mail_and_dismissed_draft():
    cid = _case()
    m = client.post(
        "/api/backoffice/mails",
        json={"to": "a@b.example", "subject": "Hello", "body": "Text", "case_id": cid},
        headers=PW,
    ).json()
    assert m["type"] == "custom" and m["status"] == "draft"
    auto = next(x for x in board()["mails"] if x["type"] == "request")
    client.delete(f"/api/backoffice/mails/{auto['id']}", headers=PW)
    types = [x["type"] for x in board()["mails"]]
    assert "request" not in types and "custom" in types  # a dismissed draft is not drafted again
