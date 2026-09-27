"""Reuse terms of the sources and the commercial-use mode."""

from app.connectors.registry import ConnectorRegistry, _connector_classes
from app.licences import LICENCES
from app.settings import Settings


def test_every_real_connector_has_a_licence_entry():
    names = {c.name for c in _connector_classes() if not c.is_demo}
    assert names - set(LICENCES) == set()
    assert set(LICENCES) - names == set()


def test_commercial_mode_switches_off_non_commercial_sources():
    base = dict(live_sources=True, demo_mode=False, guardian_api_key="k")
    free = ConnectorRegistry(Settings(**base))
    assert free.connectors["open_watchlists"].enabled
    assert free.connectors["guardian"].enabled

    reg = ConnectorRegistry(Settings(**base, commercial_mode=True))
    for name in ("open_watchlists", "open_watchlists_extended", "guardian"):
        enabled, message = reg.connectors[name].status()
        assert not enabled and "commercial mode" in message
    # Open and official sources stay on.
    assert reg.connectors["official_sanctions"].enabled
    assert reg.connectors["gleif"].enabled


def test_licensed_sources_are_kept_in_commercial_mode():
    reg = ConnectorRegistry(
        Settings(
            live_sources=True,
            demo_mode=False,
            commercial_mode=True,
            licensed_sources="open_watchlists, Guardian",
        )
    )
    assert reg.connectors["open_watchlists"].enabled
    assert not reg.connectors["open_watchlists_extended"].enabled
    status = {s["name"]: s for s in reg.statuses()}
    assert status["open_watchlists"]["licence"]["commercial_licence_held"] is True
    assert status["open_watchlists"]["licence"]["category"] == "non_commercial"
    assert status["gleif"]["licence"] == {
        "category": "open",
        "label": "Open licence",
        "name": "CC0 1.0",
        "note": "",
        "commercial_licence_held": False,
    }
