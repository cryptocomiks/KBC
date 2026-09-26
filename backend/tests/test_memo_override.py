"""Decision memo (draft from the case, edit, PDF) and analyst override of the vigilance level."""

import pytest
from fastapi.testclient import TestClient

from app import store as store_mod
from app.main import app
from app.questionnaire import risk_axes
from app.settings import get_settings

client = TestClient(app)
PW = {"X-KBC-Password": "s3cret"}
ANSWERS = {
    "relationship": "ongoing",
    "purpose": "Holding company opening a custody account",
    "sector": "standard",
    "structure": "complex",
    "ubo": "verified",
    "pep": "no",
    "countries": ["FR", "LU"],
    "channel": "face_to_face",
    "volume": "1m_10m",
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
    cid = client.post(
        "/api/cases", json={"record_ids": ["demo_fr_registry:900100101"], "depth": 2}, headers=PW
    ).json()["id"]
    client.put(
        f"/api/cases/{cid}/questionnaire", json={"answers": ANSWERS, "author": "Alice"}, headers=PW
    )
    return cid


def test_memo_draft_edit_and_pdf():
    cid = _case()
    draft = client.get(f"/api/cases/{cid}/memo", headers=PW).json()
    assert draft["draft"] is True
    text = draft["text"]
    for section in (
        "## 1. Client",
        "## 2. Ownership",
        "## 3. Screening",
        "## 4. Risk",
        "## 5. Documents",
        "## 6. Conclusion",
        "## 7. Sign-off",
    ):
        assert section in text
    assert "Mohammed Qadrany" in text and "Holding company opening a custody account" in text
    assert "Proposal:" in text

    edited = text.replace("[to complete]", "Client known since 2019")
    saved = client.put(
        f"/api/cases/{cid}/memo", json={"text": edited, "by": "Alice"}, headers=PW
    ).json()
    assert saved["draft"] is False and saved["updated_by"] == "Alice"
    again = client.get(f"/api/cases/{cid}/memo", headers=PW).json()
    assert again["text"] == edited
    assert client.get(f"/api/cases/{cid}/memo?regenerate=true", headers=PW).json()["draft"] is True

    pdf = client.get(f"/api/cases/{cid}/memo.pdf", headers=PW)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert client.get(f"/api/cases/{cid}/memo").status_code == 401


def test_vigilance_override_needs_a_justification_and_is_traced():
    cid = _case()
    computed = client.get(f"/api/cases/{cid}", headers=PW).json()["questionnaire"]["assessment"]
    assert computed["axes"]["client"]["score"] > 0

    bad = client.put(
        f"/api/cases/{cid}/vigilance",
        json={"level": "standard", "justification": "ok", "by": "Bob"},
        headers=PW,
    )
    assert bad.status_code == 409
    ok = client.put(
        f"/api/cases/{cid}/vigilance",
        json={
            "level": "enhanced",
            "justification": "Group structure through Luxembourg and BVI",
            "by": "Bob",
        },
        headers=PW,
    ).json()
    a = ok["assessment"]
    assert a["level"] == "enhanced" and a["override"]["by"] == "Bob"
    assert a["computed_level"] == computed["computed_level"]
    assert ok["override_history"][0]["level"] == "enhanced"
    # Saving the answers again keeps the adjustment.
    client.put(f"/api/cases/{cid}/questionnaire", json={"answers": ANSWERS}, headers=PW)
    view = client.get(f"/api/cases/{cid}", headers=PW).json()
    assert view["questionnaire"]["assessment"]["level"] == "enhanced"
    assert "Adjusted by Bob" in client.get(f"/api/cases/{cid}/memo", headers=PW).json()["text"]
    # Back to the computed level (also justified and traced).
    back = client.put(
        f"/api/cases/{cid}/vigilance",
        json={
            "level": None,
            "justification": "BVI entity dissolved, structure simplified",
            "by": "Bob",
        },
        headers=PW,
    ).json()
    assert back["assessment"]["override"] is None and len(back["override_history"]) == 2


def test_risk_axes():
    axes = risk_axes(
        {"countries": ["KP"], "cash": "significant", "pep": "yes"}, {"sanctions_match"}
    )
    assert axes["geography"]["score"] > 50 and axes["transactions"]["score"] > 0
    assert axes["client"]["level"] == "high"
    assert any("sanctions" in i for i in axes["client"]["items"])
    assert risk_axes({}, set())["activity"]["score"] == 0
