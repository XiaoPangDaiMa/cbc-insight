"""缓存的三个约束（NFR-P-07 / RK-11 / RK-26）。

这些用例看起来很"小"，但它们守的是本项目最难查的一类 bug：
缓存串了数据集之后，页面上的数字**全都对，只是不是这份数据的**。

因此这里不测"缓存命中率高不高"，只测三件事：
1. 键里有没有 `dataset_id`；
2. 判定口径变了键会不会变（改了区间不能还拿旧结果）；
3. 没有 Redis 时会不会照常工作（本机开发不该被一个缓存服务卡住）。
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from app.core.cache import (
    MemoryCache,
    build_cache,
    cache_key,
    judgment_scope,
    reset_cache,
)
from app.core.config import Settings


def test_memory_cache_roundtrip_and_expiry() -> None:
    cache = MemoryCache()
    cache.set_json("k", {"a": 1}, ttl=0.05)
    assert cache.get_json("k") == {"a": 1}
    time.sleep(0.08)
    assert cache.get_json("k") is None, "过期的键必须自己消失，不能靠别人清理"


def test_cache_key_separates_datasets() -> None:
    first = cache_key("dataset-a", "metric-status", "default@2026.11.1", "2026-11-20T10:00:00")
    second = cache_key("dataset-b", "metric-status", "default@2026.11.1", "2026-11-20T10:00:00")
    assert first != second, "缺了 dataset_id 就会串数据（RK-11）"
    assert "dataset-a" in first


def test_cache_key_hashes_long_parts() -> None:
    long_part = "x" * 500
    key = cache_key("ds", long_part)
    assert len(key) < 80, "长串（如区间快照）要先哈希，否则键会长到没法看"


def test_judgment_scope_changes_after_rejudge() -> None:
    before = SimpleNamespace(ri_source="default@2026.11.1", judged_at=None)
    after = SimpleNamespace(ri_source="user#v2", judged_at=None)
    assert judgment_scope(before) != judgment_scope(after)

    stamped = SimpleNamespace(ri_source="default@2026.11.1", judged_at="2026-11-20T10:00:00")
    assert judgment_scope(stamped) != judgment_scope(before), "重判之后旧结果必须自然失效"


def test_build_cache_falls_back_to_memory(monkeypatch) -> None:
    reset_cache()
    settings = Settings(redis_url=None)
    cache = build_cache(settings)
    assert isinstance(cache, MemoryCache), "没配 Redis 时必须退化，而不是抛异常"
    reset_cache()


def test_build_cache_survives_dead_redis(monkeypatch) -> None:
    """配了 Redis 但连不上：应用照常启动，只是退化为进程内缓存。"""
    reset_cache()
    settings = Settings(redis_url="redis://127.0.0.1:6399/0")
    cache = build_cache(settings)
    assert isinstance(cache, MemoryCache)
    reset_cache()
