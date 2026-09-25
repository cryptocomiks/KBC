import time
from concurrent.futures import ThreadPoolExecutor

from app.connectors.base import _pace


def test_parallel_calls_respect_the_source_rate_limit():
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: _pace("test-source", 0.05), range(4)))
    # 4 calls, 0.05 s apart at least: the last one starts ≥ 0.15 s after the first
    assert time.monotonic() - start >= 0.15
