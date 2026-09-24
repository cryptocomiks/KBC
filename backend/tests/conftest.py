import os

os.environ.setdefault("DEMO_MODE", "true")
# Unit tests never reach real APIs: live connectors are tested with mocked HTTP (respx).
os.environ.setdefault("LIVE_SOURCES", "false")
# Cases / analyst memory: never touch the developer's store from tests.
os.environ.setdefault("STORE_PATH", ":memory:")

import pytest  # noqa: E402

from app.cache import Cache, set_cache  # noqa: E402
from app.connectors.registry import ConnectorRegistry  # noqa: E402


@pytest.fixture(autouse=True)
def memory_cache():
    cache = Cache(":memory:", ttl_hours=1)
    set_cache(cache)
    yield cache


@pytest.fixture
def registry() -> ConnectorRegistry:
    return ConnectorRegistry()
