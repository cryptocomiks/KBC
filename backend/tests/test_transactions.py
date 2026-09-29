"""Bank statement analysis: parsing of bank exports and the red-flag detectors."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import ListType, Provenance, ScreeningHit
from app.transactions import _amount, analyse, parse

SAMPLE = (
    Path(__file__).resolve().parents[2] / "frontend" / "public" / "media" / "sample-statement.csv"
)


def rules(result):
    return {a["rule"]: a for a in result["alerts"]}


def test_amount_formats():
    assert _amount("1'234.50") == 1234.5
    assert _amount("1 234,50") == 1234.5
    assert _amount("1.234,50") == 1234.5
    assert _amount("1,234.50") == 1234.5
    assert _amount("(123.00)") == -123
    assert _amount("9800-") == -9800
    assert _amount("12,5") == 12.5


def test_english_csv_with_signed_amounts_and_iban_country():
    csv = (
        b"Booking date,Description,Counterparty,Counterparty IBAN,Amount,Currency\n"
        b"2026-01-02,Invoice 1,Acme Ltd,GB29NWBK60161331926819,1200.00,GBP\n"
        b"2026-01-05,Supplier,Beta GmbH,DE89370400440532013000,-450.00,GBP\n"
    )
    txs, mapping, _ = parse(csv, "s.csv")
    assert mapping["amount"] == "Amount" and len(txs) == 2
    assert txs[0]["direction"] == "in" and txs[1]["direction"] == "out" and txs[1]["amount"] == 450
    assert [t["country"] for t in txs] == ["GB", "DE"]


def test_unrecognised_file_is_refused():
    with pytest.raises(ValueError, match="Columns not recognised"):
        analyse(b"foo,bar\n1,2\n", "x.csv")


def test_sample_statement_raises_every_expected_flag():
    r = analyse(
        SAMPLE.read_bytes(), SAMPLE.name, {"country": "CH", "volume": "lt_150k", "cash": "none"}
    )
    found = rules(r)
    for rule in (
        "structuring",
        "cash",
        "round_amounts",
        "pass_through",
        "high_risk_geography",
        "crypto",
        "activity_spike",
        "profile_mismatch",
    ):
        assert rule in found, rule
    assert found["structuring"]["count"] == 3 and r["threshold"] == 15000
    assert found["cash"]["severity"] == "high"  # the profile declares no cash
    assert r["summary"]["currency"] == "CHF" and r["summary"]["transactions"] == 18
    assert any(c["iso"] == "VG" and "offshore centre" in c["risk"] for c in r["countries"])


def test_counterparty_screening_uses_the_given_screener():
    def screen(entities):
        hits = [
            ScreeningHit(
                entity_id=e.id,
                list_type=ListType.SANCTION,
                dataset="Test list",
                matched_name="TEREKHOV, Ruslan",
                score=97,
                provenance=Provenance(source="t", source_label="t"),
            )
            for e in entities
            if "Terekhov" in e.name
        ]
        return hits, []

    r = analyse(SAMPLE.read_bytes(), SAMPLE.name, {"country": "CH"}, screen)
    hit = rules(r)["counterparty_screening"]
    assert hit["severity"] == "critical" and "Ruslan Terekhov" in hit["title"]
    assert r["alerts"][0]["rule"] == "counterparty_screening"  # most severe first


def test_funnel_account():
    lines = ["Date;Contrepartie;Montant"]
    lines += [f"0{1 + i % 9}.02.2026;Sender {i};900" for i in range(12)]
    lines += ["20.02.2026;Collector SA;-10500"]
    r = analyse("\n".join(lines).encode(), "f.csv")
    assert "funnel" in rules(r)


def test_endpoint_never_stores_and_returns_the_analysis():
    client = TestClient(app)
    res = client.post(
        "/api/transactions/analyze",
        files={"file": (SAMPLE.name, SAMPLE.read_bytes(), "text/csv")},
        data={"profile": '{"country": "CH"}', "screen": "false"},
    )
    assert res.status_code == 200 and res.json()["summary"]["transactions"] == 18
    bad = client.post(
        "/api/transactions/analyze", files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")}
    )
    assert bad.status_code == 422


def test_statement_screening_asks_every_source_at_once_within_a_budget(registry):
    """All counterparties go to every screening source in parallel. A source still loading at
    the deadline is named, a source that is down is named, the other sources' hits are kept."""
    import time

    from app.connectors.base import BaseConnector, ConnectorError
    from app.models import Entity, EntityType
    from app.service import KbcService

    batches: list[int] = []

    class SlowList(BaseConnector):
        name, label, kind, is_demo = "slow_list", "Slow list", "screening", True

        def screen_many(self, entities):
            batches.append(len(entities))
            time.sleep(1.5)
            return []

    class BrokenList(BaseConnector):
        name, label, kind, is_demo = "broken_list", "Broken list", "screening", True

        def screen(self, entity):
            raise ConnectorError("down")

    registry.connectors["slow_list"] = SlowList(registry.settings)
    registry.connectors["broken_list"] = BrokenList(registry.settings)
    people = [
        Entity(id=f"stmt:{i}", type=EntityType.PERSON, name=n)
        for i, n in enumerate(["Ruslan Terekhov", "Jane Example"])
    ]
    start = time.monotonic()
    hits, notes = KbcService(registry).screen_entities(people, budget=0.5)
    assert time.monotonic() - start < 1.2  # the slow list does not hold the answer back
    assert batches == [2]  # one call with both names
    assert any("Not screened within" in n and "Slow list" in n for n in notes)
    assert any("unavailable" in n and "Broken list" in n for n in notes)
    assert any(h.entity_id == "stmt:0" for h in hits)  # the demo sanctions list answered
