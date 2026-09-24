"""Connector registry: the single place listing available data sources."""

from __future__ import annotations

from app.connectors.base import BaseConnector
from app.settings import Settings, get_settings


def _connector_classes() -> list[type[BaseConnector]]:
    from app.connectors.demo import DEMO_CONNECTORS

    classes: list[type[BaseConnector]] = [*DEMO_CONNECTORS]
    return classes


class ConnectorRegistry:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.connectors: dict[str, BaseConnector] = {
            cls.name: cls(self.settings) for cls in _connector_classes()
        }

    def all(self) -> list[BaseConnector]:
        return list(self.connectors.values())

    def enabled(self, kind: str | None = None) -> list[BaseConnector]:
        return [c for c in self.connectors.values() if c.enabled and (kind is None or c.kind == kind)]

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
