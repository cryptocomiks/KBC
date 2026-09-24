import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_and_meta():
    assert client.get("/api/health").json()["status"] == "ok"
    meta = client.get("/api/meta").json()
    assert meta["demo_mode"] is True and "verified" in meta["disclaimer"]


def test_connectors_status():
    rows = client.get("/api/connectors").json()
    assert {r["name"] for r in rows if r["enabled"]} >= {"demo_fr_registry", "demo_sanctions"}


def test_search_returns_disambiguation_candidates():
    body = client.get("/api/search", params={"q": "Mohamed Qadrany", "type": "person"}).json()
    names = [c["entity"]["name"] for c in body["candidates"]]
    assert names[0] == "Mohammed Qadrany"
    assert {"Mohamed Kadrani", "Maxamed Qadraani"} <= set(names)
    first = body["candidates"][0]
    assert first["entity"]["birth_date"] and first["linked_companies"] and first["explanation"]


def test_search_validation():
    assert client.get("/api/search", params={"q": "a"}).status_code == 422


@pytest.fixture(scope="module")
def investigation():
    resp = client.post(
        "/api/investigations",
        json={"record_ids": ["demo_fr_registry:P-001"], "depth": 3, "max_nodes": 60},
    )
    assert resp.status_code == 200
    return resp.json()


def test_investigation_payload(investigation):
    inv = investigation
    assert inv["demo"] is True
    assert inv["risk"]["level"] == "critical"
    assert set(inv["tables"]) == {
        "mandates",
        "companies",
        "shareholders",
        "ownership",
        "screening",
        "leaks",
        "sources",
        "documents",
    }
    for rel in inv["relationships"]:
        assert rel["sources"], rel  # traceability of every edge
    for ent in inv["entities"]:
        if ent["type"] != "address":
            assert ent["sources"] and ent["sources"][0]["retrieved_at"]


def test_investigation_unknown_record():
    resp = client.post("/api/investigations", json={"record_ids": ["demo_fr_registry:NOPE"]})
    assert resp.status_code == 404


def test_pdf_report():
    resp = client.post(
        "/api/reports/pdf",
        json={"record_ids": ["demo_fr_registry:P-001"], "depth": 2, "reference": "KYC-2026-001"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")


def test_cache_clear():
    client.post("/api/investigations", json={"record_ids": ["demo_fr_registry:P-001"], "depth": 1})
    assert client.get("/api/cache").json()["entries"].get("investigation", 0) >= 1
    assert client.delete("/api/cache").json()["deleted"] >= 1
    assert client.get("/api/cache").json()["entries"] == {}


def test_unhandled_errors_are_readable(monkeypatch):
    from app.service import KbcService

    def boom(self, q, t):
        raise RuntimeError("connector exploded")

    monkeypatch.setattr(KbcService, "search", boom)
    resp = TestClient(app, raise_server_exceptions=False).get("/api/search", params={"q": "abc"})
    assert resp.status_code == 500
    assert resp.json()["detail"] == "RuntimeError: connector exploded"
