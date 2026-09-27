"""Alert memory with re-alerts, batch triage, CDB 20 forms, source of wealth, periodic review."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import alerts, cdb, review, sow
from app import store as store_mod
from app.main import app
from app.models import Entity, EntityType, ListType, Provenance, ScreeningHit
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
    return client.post(
        "/api/cases", json={"record_ids": ["demo_fr_registry:900100101"], "depth": 2}, headers=PW
    ).json()["id"]


def _hit(**details):
    return ScreeningHit(
        entity_id="p1",
        list_type=ListType.PEP,
        dataset="PEP list",
        matched_name="Jean Martin",
        score=82,
        details=details,
        provenance=Provenance(source="x", source_label="X"),
        triage="namesake",
        triage_reasons=["different date of birth", "confidence 82%"],
    )


PERSON = Entity(
    id="p1", type=EntityType.PERSON, name="Jean MARTIN", birth_date="1978-03", nationalities=["CH"]
)


# ------------------------------------------------------------------ alert memory
def test_evidence_fingerprint_changes_with_the_list_entry_only():
    a = alerts.evidence(
        _hit(birth_date="1962", nationalities=["FR"], opensanctions_score=0.8), PERSON
    )
    same = alerts.evidence(
        _hit(birth_date="1962", nationalities=["FR"], opensanctions_score=0.9), PERSON
    )
    moved = alerts.evidence(_hit(birth_date="1978", nationalities=["FR"]), PERSON)
    assert a["fingerprint"] == same["fingerprint"]  # scores are not evidence
    assert a["fingerprint"] != moved["fingerprint"]
    assert alerts.changed(a, moved) == ["list entry: birth date 1962 → 1978"]


def test_justification_is_written_from_the_evidence():
    text = alerts.justification(_hit(birth_date="1962", nationalities=["FR"]), PERSON)
    assert "date of birth differs (ours 1978-03, list 1962)" in text
    assert "nationality differs (ours CH, list FR)" in text
    assert text.startswith("Namesake: Jean MARTIN is not the listed")


def test_batch_triage_memory_and_realert():
    cid = _case()
    view = client.get(f"/api/cases/{cid}/alerts", headers=PW).json()
    assert view["batch_candidates"] >= 1
    namesakes = [a for a in view["alerts"] if a["triage"] == "namesake"]
    assert all(a["proposed"].startswith("Namesake:") for a in namesakes)

    assert (
        client.post(f"/api/cases/{cid}/alerts/batch", json={"by": ""}, headers=PW).status_code
        == 409
    )
    done = client.post(f"/api/cases/{cid}/alerts/batch", json={"by": "Alice"}, headers=PW).json()
    assert done["dismissed"] == len(namesakes)
    assert done["counts"].get("dismissed") == len(namesakes)
    assert done["minutes_saved"] == len(namesakes) * alerts.MINUTES_PER_ALERT

    memory = client.get("/api/cases/memory", headers=PW).json()["items"]
    assert len(memory) == len(namesakes) and all(m["tracked"] for m in memory)
    assert "[batch triage by Alice]" in memory[0]["comment"]

    # The list entry changes: the stored evidence no longer matches -> the alert comes back.
    st = store_mod.get_store()
    key = memory[0]["item_key"]
    st._exec(
        "UPDATE dismissals SET fingerprint = 'old', evidence = ? WHERE item_key = ?",
        ('{"list": {"birth_date": "1950"}, "ours": {}}', key),
    )
    view = client.get(f"/api/cases/{cid}/alerts", headers=PW).json()
    back = next(a for a in view["alerts"] if a["key"].lower() == key)
    assert back["triage"] == "verify" and back["realert"]
    assert back["reasons"][0].startswith("re-alert: ruled out on")
    assert back["decision"]["stale"] is True
    case = client.get(f"/api/cases/{cid}", headers=PW).json()
    assert any(d.get("stale") for d in case["decisions"])

    # Revoking a ruling removes it from the memory.
    left = client.delete("/api/cases/memory", params={"key": key}, headers=PW).json()["items"]
    assert key not in {m["item_key"] for m in left}


# ---------------------------------------------------------------------- CDB 20
def test_name_split_and_kind():
    assert cdb.split_name("MARTIN, Jean") == ("MARTIN", "Jean")
    assert cdb.split_name("Jean-Luc DUPONT") == ("DUPONT", "Jean-Luc")
    assert cdb.split_name("Sofia Marchetti") == ("Marchetti", "Sofia")
    trust = Entity(id="t", type=EntityType.COMPANY, name="Northgate Family Trust")
    trustco = Entity(id="t2", type=EntityType.COMPANY, name="Alpine Trust Company AG")
    fdn = Entity(id="f", type=EntityType.COMPANY, name="Stiftung Edelweiss")
    assert cdb.kind_of(trust) == "trust"
    assert cdb.kind_of(trustco) == "company"
    assert cdb.kind_of(fdn) == "foundation"


def test_cdb_forms_prefilled_edit_and_pdf():
    cid = _case()
    data = client.get(f"/api/cases/{cid}/cdb", headers=PW).json()
    form = data["forms"][0]
    assert form["code"] in ("A", "K")
    names = {p["last_name"] for p in form["persons"]}
    assert "Qadrany" in names and "Marchetti" in names
    assert all(p["basis"].startswith("Holds") for p in form["persons"])
    before = data["missing_total"]
    pk = form["persons"][0]["key"]
    assert (
        client.put(
            f"/api/cases/{cid}/cdb", json={"by": "", "form": form["id"]}, headers=PW
        ).status_code
        == 409
    )
    data = client.put(
        f"/api/cases/{cid}/cdb",
        json={
            "by": "Alice",
            "form": form["id"],
            "person": pk,
            "fields": {"address": "Bahnhofstrasse 1, Zürich", "country": "Switzerland"},
        },
        headers=PW,
    ).json()
    assert data["missing_total"] < before and data["edited_by"] == "Alice"
    data = client.put(
        f"/api/cases/{cid}/cdb", json={"by": "Alice", "form": form["id"], "add": True}, headers=PW
    ).json()
    added = [p for p in data["forms"][0]["persons"] if p["key"].startswith("added-")]
    assert len(added) == 1
    data = client.put(
        f"/api/cases/{cid}/cdb",
        json={"by": "Alice", "form": form["id"], "remove": added[0]["key"]},
        headers=PW,
    ).json()
    assert not [p for p in data["forms"][0]["persons"] if p["key"].startswith("added-")]
    pdf = client.get(f"/api/cases/{cid}/cdb.pdf", headers=PW)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


# ------------------------------------------------------------ source of wealth
def test_sow_explained_amounts_and_verdicts():
    emp = sow.clean(
        {
            "sources": [
                {"type": "employment", "annual": "200'000", "year_from": 2011, "year_to": 2020}
            ]
        }
    )["sources"][0]
    amount, how = sow.explained(emp)
    assert amount == 200_000 * 10 * 0.3 and "10 year(s)" in how
    lump = sow.clean({"sources": [{"type": "inheritance", "amount": "1,500,000"}]})["sources"][0]
    assert sow.explained(lump)[0] == 1_500_000


def test_sow_endpoint_corroborates_with_registers():
    cid = _case()
    base = client.get(f"/api/cases/{cid}/sow", headers=PW).json()
    assert base["person"] and base["roles"]
    out = client.put(
        f"/api/cases/{cid}/sow",
        json={
            "by": "Alice",
            "data": {
                "person_id": base["person_id"],
                "declared_total": 1_500_000,
                "sources": [
                    {"type": "employment", "annual": 300000, "year_from": 2014, "year_to": 2023},
                    {"type": "crypto", "amount": 500000},
                ],
            },
        },
        headers=PW,
    ).json()
    emp, crypto = out["sources"]
    assert emp["public"] and emp["corroborated"]
    assert not crypto["public"] and not crypto["corroborated"]
    assert out["explained_total"] == 1_400_000 and out["verdict"] == "plausible"  # 93 %
    assert any("higher-risk" in f["text"] for f in out["flags"])
    assert "Not corroborated yet: crypto-assets" in out["narrative"]
    memo = client.get(f"/api/cases/{cid}/memo", params={"regenerate": True}, headers=PW).json()
    assert "## Source of wealth" in memo["text"]


# ------------------------------------------------------------- periodic review
def test_document_status_rules():
    today = date(2026, 9, 1)

    def doc(label, at, note="", done=True):
        return {"label": label, "done": done, "at": at, "note": note, "required": True}

    assert (
        review.document_status(
            doc("Passport of the director", "2024-01-01", "expires 31.03.2026"), today
        )["status"]
        == "expired"
    )
    assert (
        review.document_status(
            doc("Passport of the director", "2024-01-01", "valid until 2026-10-15"), today
        )["status"]
        == "expiring"
    )
    assert (
        review.document_status(doc("Certified register extract", "2025-01-10"), today)["status"]
        == "stale"
    )
    assert (
        review.document_status(doc("Certified register extract", "2026-06-10"), today)["status"]
        == "ok"
    )
    assert (
        review.document_status(doc("Group chart", None, done=False), today)["status"] == "missing"
    )


def test_review_pack_and_start_reopens_a_validated_case():
    cid = _case()
    st = store_mod.get_store()
    case = st.get_case(cid)
    st.update_case(
        cid,
        workflow={
            "state": "validated",
            "validated_by": "Carol",
            "validated_at": "2025-01-01T00:00:00+00:00",
            "history": [],
        },
        questionnaire={**(case.get("questionnaire") or {}), "next_review": "2026-01-01"},
    )
    pack = client.get(f"/api/cases/{cid}/review", headers=PW).json()
    assert pack["status"] == "overdue" and pack["last_review"].startswith("2025-01-01")
    assert pack["email"]["subject"].startswith("Periodic review of your file")
    assert any(a["tab"] == "alerts" for a in pack["actions"])
    started = client.post(f"/api/cases/{cid}/review/start", json={"by": "Bob"}, headers=PW).json()
    assert started["reviews"][0]["previous_validation"].startswith("2025-01-01")
    assert started["workflow_state"] == "to_complete"
    assert started["last_review"].startswith("2025-01-01")  # still the last validation
