"""Alert triage (likely / to verify / namesake) and the memory of ruled-out hits."""

from fastapi.testclient import TestClient

from app import store as store_mod
from app.main import app
from app.models import Entity, EntityType, ListType, Provenance, ScreeningHit
from app.triage import apply_triage, triage

PROV = Provenance(source="x", source_label="X")


def hit(explanation, score=95.0, list_type=ListType.SANCTION):
    return ScreeningHit(
        entity_id="e",
        list_type=list_type,
        dataset="EU",
        matched_name="Ivan Petrov",
        score=score,
        explanation=explanation,
        provenance=PROV,
    )


PERSON = Entity(id="e", type=EntityType.PERSON, name="Ivan Petrov", birth_date="1960-01-01")


def test_contradicted_hit_is_a_namesake():
    label, why = triage(
        hit(["name 100%", "date of birth conflict (1960 vs 1975) [-30]"], 65), PERSON
    )
    assert label == "namesake" and "different date of birth" in why


def test_corroborated_hit_is_likely():
    label, why = triage(hit(["name 100%", "same date of birth (1960-01-01) [+8]"], 100), PERSON)
    assert label == "likely" and "same date of birth" in why


def test_uncorroborated_hit_is_to_verify_with_reason():
    nodob = Entity(id="e", type=EntityType.PERSON, name="Ivan Petrov")
    label, why = triage(hit(["name 100%"], 92), nodob)
    assert label == "verify" and "no date of birth on our side to compare" in why


def test_weak_name_is_namesake_and_order():
    hits = apply_triage(
        [
            hit(["name 72%"], 72),
            hit(["name 100%", "same date of birth (1960) [+8]"], 100),
            hit(["name 90%"], 90),
        ],
        {"e": PERSON},
    )
    assert [h.triage for h in hits] == ["likely", "verify", "namesake"]


def test_ruled_out_hit_is_remembered_across_investigations(monkeypatch, tmp_path):
    from app.settings import get_settings

    monkeypatch.setenv("STORE_PATH", str(tmp_path / "s.db"))
    monkeypatch.setenv("APP_PASSWORD", "pw")
    get_settings.cache_clear()
    store_mod.reset_store()
    client = TestClient(app)
    try:
        body = {"record_ids": ["demo_fr_registry:P-001"], "depth": 3, "max_nodes": 60}
        case = client.post("/api/cases", json=body, headers={"X-KBC-Password": "pw"}).json()
        inv = client.post("/api/investigations", json=body).json()
        names = {e["id"]: e["name"] for e in inv["entities"]}
        pep = next(h for h in inv["hits"] if h["list_type"] == "pep" and h["score"] >= 85)
        key = f"hit|{names[pep['entity_id']]}|{pep['dataset']}|{pep['matched_name']}"
        client.put(
            f"/api/cases/{case['id']}/decisions",
            headers={"X-KBC-Password": "pw"},
            json={
                "item_key": key,
                "decision": "false_positive",
                "comment": "other person",
                "author": "ana",
            },
        )
        again = client.post(
            "/api/investigations", json=body
        ).json()  # a new, unrelated investigation
        same = next(h for h in again["hits"] if h["matched_name"] == pep["matched_name"])
        assert same["triage"] == "dismissed" and "other person" in same["triage_reasons"]
        assert not any(f["key"] == "pep_match" for f in again["risk"]["factors"])
    finally:
        store_mod.reset_store()
        get_settings.cache_clear()
