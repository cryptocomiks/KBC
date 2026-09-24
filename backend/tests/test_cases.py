"""Cases: save, analyst decisions (false positives leave the score), monitoring diff, access control."""

import pytest
from fastapi.testclient import TestClient

from app import store as store_mod
from app.cases import diff
from app.main import app
from app.settings import get_settings

client = TestClient(app)
PW = {"X-KBC-Password": "s3cret"}


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_PASSWORD", "s3cret")
    monkeypatch.setenv("CRON_SECRET", "cron-token")
    monkeypatch.setenv("STORE_PATH", str(tmp_path / "store.db"))
    monkeypatch.delenv("VERCEL", raising=False)
    get_settings.cache_clear()
    store_mod.reset_store()
    yield
    store_mod.reset_store()
    get_settings.cache_clear()


def _create():
    resp = client.post(
        "/api/cases",
        json={
            "record_ids": ["demo_fr_registry:P-001"],
            "depth": 3,
            "max_nodes": 60,
            "title": "Qadrany file",
        },
        headers=PW,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_password_is_required():
    assert client.get("/api/cases").status_code == 401
    assert client.get("/api/cases", headers={"X-KBC-Password": "wrong"}).status_code == 401
    assert client.get("/api/cases", headers=PW).status_code == 200
    assert client.get("/api/meta").json()["cases"]["auth_required"] is True


def test_cases_disabled_on_vercel_without_password(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("APP_PASSWORD", "")
    get_settings.cache_clear()
    resp = client.get("/api/cases", headers=PW)
    assert resp.status_code == 503 and "APP_PASSWORD" in resp.json()["detail"]


def test_save_decide_and_dashboard():
    case = _create()
    assert case["title"] == "Qadrany file" and case["risk_level"] and case["monitor"] is True

    view = client.get(f"/api/cases/{case['id']}", headers=PW).json()
    inv = view["investigation"]
    names = {e["id"]: e["name"] for e in inv["entities"]}
    sanction = next(h for h in inv["hits"] if h["list_type"] == "sanction" and h["score"] >= 85)
    key = f"hit|{names[sanction['entity_id']]}|{sanction['dataset']}|{sanction['matched_name']}"
    before = inv["risk"]["score"]
    assert any(f["key"] == "sanctions_match" for f in inv["risk"]["factors"])

    resp = client.put(
        f"/api/cases/{case['id']}/decisions",
        json={
            "item_key": key,
            "item_label": "Terekhov hit",
            "decision": "false_positive",
            "comment": "Different date of birth",
            "author": "analyst",
        },
        headers=PW,
    )
    assert resp.status_code == 200 and resp.json()["decisions"][0]["decision"] == "false_positive"
    after = client.get(f"/api/cases/{case['id']}", headers=PW).json()
    assert not any(f["key"] == "sanctions_match" for f in after["investigation"]["risk"]["factors"])
    assert after["investigation"]["risk"]["score"] <= before
    assert after["decisions"][0]["comment"] == "Different date of birth"

    pdf = client.post(
        "/api/reports/pdf",
        json={
            "record_ids": ["demo_fr_registry:P-001"],
            "depth": 3,
            "max_nodes": 60,
            "case_id": case["id"],
        },
        headers=PW,
    )
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    dash = client.get("/api/cases", headers=PW).json()
    assert dash["cases"][0]["id"] == case["id"] and sum(dash["by_level"].values()) == 1
    assert client.delete(f"/api/cases/{case['id']}", headers=PW).status_code == 200
    assert client.get("/api/cases", headers=PW).json()["cases"] == []


def test_monitoring_records_changes():
    case = _create()
    st = store_mod.get_store()
    # Pretend an earlier run knew nothing about the sanctions hit and had a lower score.
    snap = st.get_case(case["id"])["snapshot"]
    snap["hits"] = {k: v for k, v in snap["hits"].items() if "Sanctions" not in v}
    snap["score"] = 10
    st.update_case(case["id"], snapshot=snap)

    assert client.post("/api/monitor/run").status_code == 401
    resp = client.post("/api/monitor/run", headers={"Authorization": "Bearer cron-token"})
    assert resp.status_code == 200 and resp.json()["refreshed"] == case["id"]
    kinds = {c["kind"] for c in resp.json()["changes"]}
    assert {"new_hit", "score"} <= kinds

    dash = client.get("/api/cases", headers=PW).json()
    assert dash["cases"][0]["unseen_changes"] >= 2 and dash["recent_changes"]
    client.post(f"/api/cases/{case['id']}/seen", headers=PW)
    assert client.get("/api/cases", headers=PW).json()["cases"][0]["unseen_changes"] == 0


def test_diff_first_run_is_silent():
    assert diff({}, {"hits": {"a": "x"}}) == []
    changes = diff(
        {"hits": {}, "links": {"l": "A — owner — B"}, "score": 20, "level": "medium"},
        {"hits": {"h": "B ≈ B (EU list)"}, "links": {}, "score": 60, "level": "high"},
    )
    assert [c["kind"] for c in changes] == ["new_hit", "ended_link", "score"]
