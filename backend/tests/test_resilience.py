"""A source that is down is skipped (not called for every entity), warnings are grouped,
and a company on a sanctions list is identified by its register data, not a passport."""

import httpx
import pytest
import respx

from app.connectors.base import BaseConnector, ConnectorError, group_warnings
from app.doc_requests import _identity_evidence
from app.models import Entity, EntityType
from app.settings import Settings


class _Probe(BaseConnector):
    name = "probe_source"
    label = "Probe source"
    max_retries = 0


@respx.mock
def test_unreachable_source_is_skipped_after_the_first_failure():
    route = respx.get("https://down.example/api").mock(
        side_effect=httpx.ConnectError("Name or service not known")
    )
    conn = _Probe(Settings(live_sources=True))
    with pytest.raises(ConnectorError, match="unreachable"):
        conn.http_get_json("https://down.example/api", params={"q": "a"})
    with pytest.raises(ConnectorError, match="skipped for a few minutes"):
        conn.http_get_json("https://down.example/api", params={"q": "b"})
    assert route.call_count == 1


@respx.mock
def test_rate_limited_source_pauses():
    route = respx.get("https://busy.example/api").mock(return_value=httpx.Response(429))
    conn = _Probe(Settings(live_sources=True))
    with pytest.raises(ConnectorError, match="429"):
        conn.http_get_json("https://busy.example/api", params={"q": "a"})
    with pytest.raises(ConnectorError, match="skipped"):
        conn.http_get_json("https://busy.example/api", params={"q": "b"})
    assert route.call_count == 1


def test_warnings_are_grouped_by_source():
    out = group_warnings(
        ["Casino: source unreachable (x)"]
        + ["Casino: unreachable, skipped for a few minutes"] * 11
        + ["Wayback: network error (timeout)"] * 3
        + ["Node limit of 60 reached"]
    )
    assert out == [
        "Casino: source unreachable (x) (×12)",
        "Wayback: network error (timeout) (×3)",
        "Node limit of 60 reached",
    ]


def test_identity_evidence_for_companies_and_people():
    company = Entity(id="c", type=EntityType.COMPANY, name="Gazprom")
    person = Entity(id="p", type=EntityType.PERSON, name="Jane Doe")
    assert "Register extract of Gazprom" in _identity_evidence(company, "Gazprom")
    assert "Passport copy of Jane Doe" in _identity_evidence(person, "Jane Doe")


def test_casino_secrets_is_off_while_the_site_is_down():
    from app.connectors.casino_secrets import CasinoSecretsConnector

    enabled, message = CasinoSecretsConnector(Settings(live_sources=True)).status()
    assert not enabled and "Offline" in message
    assert CasinoSecretsConnector(Settings(live_sources=True, casino_secrets_enabled=True)).enabled
