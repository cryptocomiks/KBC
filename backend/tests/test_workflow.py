"""Four-eyes validation workflow, case checklist (documents, diligences) and dashboard queues."""

import pytest
from fastapi.testclient import TestClient

from app import store as store_mod
from app import workflow as wf
from app.main import app
from app.settings import get_settings

client = TestClient(app)
PW = {"X-KBC-Password": "s3cret"}
ANSWERS = {
    "relationship": "ongoing",
    "sector": "standard",
    "structure": "complex",
    "ubo": "verified",
    "pep": "no",
    "countries": ["FR"],
    "channel": "face_to_face",
    "volume": "lt_150k",
    "cash": "none",
    "funds": "documented",
    "behaviour": "consistent",
}


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
    return client.post(
        "/api/cases", json={"record_ids": ["demo_fr_registry:900100101"], "depth": 1}, headers=PW
    ).json()


def _act(cid, action, by, comment=""):
    return client.post(
        f"/api/cases/{cid}/workflow",
        json={"action": action, "by": by, "comment": comment},
        headers=PW,
    )


def test_full_four_eyes_cycle_with_checklist():
    cid = _case()["id"]
    view = client.get(f"/api/cases/{cid}", headers=PW).json()
    assert view["workflow"]["state"] == "to_complete"
    assert view["checklist"]["documents"] and view["checklist"]["diligences"]
    required = [d for d in view["checklist"]["documents"] if d["required"]]
    assert required

    # Nothing answered, nothing received: cannot be sent.
    r = _act(cid, "submit", "Alice")
    assert r.status_code == 409 and "questionnaire" in r.json()["detail"]

    client.put(f"/api/cases/{cid}/questionnaire", json={"answers": ANSWERS}, headers=PW)
    for d in required:
        r = client.put(
            f"/api/cases/{cid}/checklist/{d['key']}", json={"done": True, "by": "Alice"}, headers=PW
        )
        assert r.status_code == 200
    assert r.json()["missing_required"] == []

    assert _act(cid, "submit", "Alice").json()["state"] == "pending_validation"
    # Four eyes: the sender cannot validate.
    r = _act(cid, "validate", "alice")
    assert r.status_code == 409 and "Four-eyes" in r.json()["detail"]
    # Sending back needs a comment.
    assert _act(cid, "reject", "Bob").status_code == 409
    assert _act(cid, "reject", "Bob", "Kbis older than 3 months").json()["state"] == "rejected"
    assert _act(cid, "submit", "Alice").json()["state"] == "pending_validation"
    done = _act(cid, "validate", "Bob").json()
    assert done["state"] == "validated" and done["validated_by"] == "Bob"
    assert [h["action"] for h in done["history"]] == ["validate", "submit", "reject", "submit"]
    # No action from a state that does not allow it.
    assert _act(cid, "validate", "Carol").status_code == 409

    board = client.get("/api/cases", headers=PW).json()
    assert board["queues"]["validated"] + board["queues"]["review_due"] == 1

    pdf = client.post(
        "/api/reports/pdf",
        json={"record_ids": ["demo_fr_registry:900100101"], "depth": 1, "case_id": cid},
        headers=PW,
    )
    assert pdf.status_code == 200


def test_diligences_add_remove_and_suggestions_follow_the_level():
    cid = _case()["id"]
    dil = client.get(f"/api/cases/{cid}", headers=PW).json()["checklist"]["diligences"]
    r = client.post(f"/api/cases/{cid}/diligences", json={"label": "Call the CFO"}, headers=PW)
    custom = next(d for d in r.json()["diligences"] if d["custom"])
    assert custom["label"] == "Call the CFO"
    r = client.delete(f"/api/cases/{cid}/diligences/{custom['key']}", headers=PW)
    assert not any(d["custom"] for d in r.json()["diligences"])
    r = client.delete(f"/api/cases/{cid}/diligences/{dil[0]['key']}", headers=PW)
    assert dil[0]["key"] not in {d["key"] for d in r.json()["diligences"]}

    enhanced = wf.suggested_diligences(
        {"level": "enhanced", "triggers": ["politically exposed person"]}, {}, {"ubo_discrepancy"}
    )
    standard = wf.suggested_diligences({"level": "standard", "triggers": []}, {}, set())
    assert len(enhanced) > len(standard)
    assert any("source of wealth" in d for d in enhanced)
    assert any("Reconcile" in d for d in enhanced)


def test_monitoring_hit_reopens_a_validated_case():
    case = {"workflow": {"state": "validated", "validated_by": "Bob", "history": []}}
    reopened = wf.auto_reopen(
        case, [{"severity": "critical", "description": "New screening hit: X"}], "2026-01-01"
    )
    assert reopened["state"] == "to_complete" and "validated_by" not in reopened
    assert reopened["history"][-1]["by"] == "monitoring"
    assert wf.auto_reopen(case, [{"severity": "info", "description": "x"}], "t") is None


def test_queues():
    base = {"questionnaire": {}, "factors": []}
    assert wf.queue_of({**base, "factors": ["pep_match"]}, "2026-01-01") == "sensitive"
    assert wf.queue_of({**base, "workflow": {"state": "pending_validation"}}, "x") == "to_validate"
    assert wf.queue_of(base, "x") == "to_complete"
    val = {"workflow": {"state": "validated"}, "questionnaire": {"next_review": "2026-02-01"}}
    assert wf.queue_of(val, "2026-03-01") == "review_due"
    assert wf.queue_of(val, "2026-01-01") == "validated"
    assert wf.queue_of({**base, "import_state": "pending"}, "x") is None
