"""Connector registry: the single place listing available data sources."""

from __future__ import annotations

from app.connectors.base import BaseConnector
from app.settings import Settings, get_settings


def _connector_classes() -> list[type[BaseConnector]]:
    from app.connectors.aleph import AlephConnector
    from app.connectors.annuaire_fr import AnnuaireEntreprisesConnector
    from app.connectors.bodacc import BodaccConnector
    from app.connectors.chains import CHAIN_CONNECTORS
    from app.connectors.companies_house import CompaniesHouseConnector
    from app.connectors.demo import DEMO_CONNECTORS
    from app.connectors.gdelt import GdeltConnector
    from app.connectors.gleif import GleifConnector
    from app.connectors.icij import IcijLocalConnector, IcijReconcileConnector
    from app.connectors.official_sanctions import OfficialSanctionsConnector
    from app.connectors.open_datasets import OpenDatasetsConnector
    from app.connectors.opencorporates import OpenCorporatesConnector
    from app.connectors.opensanctions import OpenSanctionsConnector
    from app.connectors.pappers import PappersConnector
    from app.connectors.sec_edgar import SecEdgarConnector
    from app.connectors.wayback import WaybackConnector
    from app.connectors.wikidata import WikidataConnector, WikidataPepConnector
    from app.connectors.zefix import ZefixConnector

    # To add a source (e.g. Zefix for Switzerland, LBR for Luxembourg): implement
    # BaseConnector in a new module and append the class here.
    return [
        *DEMO_CONNECTORS,
        AnnuaireEntreprisesConnector,
        BodaccConnector,
        GleifConnector,
        PappersConnector,
        CompaniesHouseConnector,
        ZefixConnector,
        SecEdgarConnector,
        OpenCorporatesConnector,
        OpenSanctionsConnector,
        OfficialSanctionsConnector,
        OpenDatasetsConnector,
        WikidataConnector,
        WikidataPepConnector,
        GdeltConnector,
        WaybackConnector,
        IcijReconcileConnector,
        IcijLocalConnector,
        AlephConnector,
        *CHAIN_CONNECTORS,
    ]


class ConnectorRegistry:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.connectors: dict[str, BaseConnector] = {
            cls.name: cls(self.settings) for cls in _connector_classes()
        }

    def all(self) -> list[BaseConnector]:
        return list(self.connectors.values())

    def enabled(self, kind: str | None = None, demo: bool | None = None) -> list[BaseConnector]:
        """Enabled connectors, optionally restricted to one realm (demo or real data)."""
        return [
            c
            for c in self.connectors.values()
            if c.enabled
            and (kind is None or c.kind == kind)
            and (demo is None or c.is_demo == demo)
        ]

    def for_record(self, record_id: str) -> BaseConnector | None:
        prefix = record_id.split(":", 1)[0]
        conn = self.connectors.get(prefix)
        return conn if conn and conn.enabled else None

    def statuses(self) -> list[dict]:
        out = []
        for c in self.connectors.values():
            enabled, message = c.status()
            out.append(
                {
                    "name": c.name,
                    "label": c.label,
                    "kind": c.kind,
                    "enabled": enabled,
                    "message": message,
                    "demo": c.is_demo,
                    "homepage": c.homepage,
                    "jurisdictions": sorted(c.jurisdictions) if c.jurisdictions else None,
                }
            )
        return out
