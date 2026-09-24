import os

os.environ.setdefault("DEMO_MODE", "true")

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
