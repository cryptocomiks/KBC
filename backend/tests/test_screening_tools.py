"""Batch screening of a list and the feed of new designations."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.connectors import official_sanctions as osl
from app.connectors.official_sanctions import ListedEntry
from app.main import app
from app.models import Entity, EntityType
from app.screening_tools import guess_type, recent_designations

client = TestClient(app)


def test_screen_a_list_of_names():
    rows = [
        {"name": "Ruslan Terekhov", "reference": "C-001"},
        {"name": "Solenne Holdings Ltd"},
        {"name": "Jane Example", "country": "ch"},
        {"name": "  "},
    ]
    res = client.post("/api/screen", json={"rows": rows}).json()
    assert res["screened"] == 3
    first, company, clear = res["results"]
    assert first["status"] == "strong" and first["reference"] == "C-001"
    assert first["matches"][0]["type"] == "sanction" and first["matches"][0]["score"] >= 85
    assert company["type"] == "company" and clear["country"] == "CH" and clear["status"] == "clear"
    assert client.post("/api/screen", json={"rows": []}).status_code == 422
    too_many = [{"name": f"N {i}"} for i in range(61)]
    assert client.post("/api/screen", json={"rows": too_many}).status_code == 422


def test_guess_type():
    assert guess_type("Gulf Star Trading FZE") == EntityType.COMPANY
    assert guess_type("Anna Muster") == EntityType.PERSON


class _Conn:
    def __init__(self, name, label, state):
        self.name, self.label, self.enabled, self._state = name, label, True, state
        self.prefetched = False

    def prefetch(self):
        self.prefetched = True


class _Registry:
    def __init__(self, connectors):
        self.connectors = {c.name: c for c in connectors}


def _entry(name, listed_on, dataset="UK Sanctions List (FCDO)", etype=EntityType.PERSON, eid=None):
    return ListedEntry(
        entity=Entity(id=eid or f"uk:{name}", type=etype, name=name),
        dataset=dataset,
        url="https://example.org",
        program="Russia",
        details={"listed_on": listed_on, "reference": "R1"},
    )


def test_recent_designations_newest_first_and_loading_lists():
    today = datetime.now(UTC).date()
    europe = osl._Index()
    for e in (
        _entry("Old Name", (today - timedelta(days=400)).isoformat()),
        _entry("New Bank", (today - timedelta(days=3)).isoformat(), etype=EntityType.COMPANY),
        _entry("Newer Person", (today - timedelta(days=1)).isoformat()),
        # the same untyped entry indexed as person and company appears once
        _entry("Dual", today.isoformat(), dataset="US Entity List", eid="csl:1"),
        _entry(
            "Dual",
            today.isoformat(),
            dataset="US Entity List",
            eid="csl:1",
            etype=EntityType.COMPANY,
        ),
    ):
        europe.add(e)
    empty = osl._Index()
    reg = _Registry(
        [
            _Conn(osl.EuropeanSanctionsConnector.name, "Europe", europe),
            _Conn(osl.OfficialSanctionsConnector.name, "OFAC and UN", empty),
        ]
    )
    res = recent_designations(reg, days=30)
    assert [x["name"] for x in res["items"]] == ["Dual", "Newer Person", "New Bank"]
    assert res["by_list"] == {"US Entity List": 1, "UK Sanctions List (FCDO)": 2}
    assert res["loading"] == ["OFAC and UN"]
    assert reg.connectors[osl.OfficialSanctionsConnector.name].prefetched
    assert client.get("/api/designations?days=30").status_code == 200
