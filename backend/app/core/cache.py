"""结果缓存（NFR-P-07 / RK-11）。

**这个模块存在的唯一理由**：同一份数据集会被反复打开，统计与指标状态每次重算
要几十毫秒到几秒；而"缓存串了数据集"这类 bug 在界面上看起来**完全合理**
（数字都对、只是不是这份数据的），是最难查的一类。

因此三条约束写死在代码里：

1. **缓存键必须含 `dataset_id`**。缺了它，两个数据集的统计会互相覆盖——
   RK-11 记的就是这个，且 10 行数据时手动测根本发现不了。
2. **缓存键必须含判定口径**（`ri_source` + 判定时刻）。改了区间之后，
   旧结果必须自然失效，而不是靠某个 `invalidate()` 被人记得调用。
3. **Redis 不可用时自动退化为进程内缓存**。单机开发不该因为没装 Redis 就跑不起来；
   但此时缓存不跨进程，多 worker 部署会各缓存各的——这一点写进 `backend()` 的注释，
   比在文档里写一句"生产请配 Redis"更容易被看到。

缓存里只放**可重建的派生结果**（统计 JSON、图表 option）：丢了顶多慢一次，
不会丢数据。原始 CSV、清洗后的 parquet、报告文件一律不经过这里。
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any, Protocol

from app.core.config import Settings

logger = logging.getLogger("cbc.cache")

#: 统计/指标状态这类结果的默认存活时间。1 小时是"人还在看这个页面"的量级；
#: 真正的失效靠键里带判定口径，不靠 TTL 到期。
DEFAULT_TTL_SECONDS = 3600


class Cache(Protocol):
    """只想清楚两件事：按 key 取 JSON、按 key 存 JSON。"""

    def get_json(self, key: str) -> Any | None: ...

    def set_json(self, key: str, value: Any, *, ttl: int = DEFAULT_TTL_SECONDS) -> None: ...

    def delete(self, key: str) -> None: ...

    def describe(self) -> str: ...


class MemoryCache:
    """进程内 TTL 缓存（单机开发的默认实现）。

    用锁包住整个 dict 操作：FastAPI 的同步端点跑在线程池里，多个请求会并发进来；
    这里存的都是几十 KB 的 JSON，锁竞争可以忽略，省下的是"偶发 KeyError"。
    """

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get_json(self, key: str) -> Any | None:
        now = time.time()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at < now:
                self._data.pop(key, None)
                return None
            return value

    def set_json(self, key: str, value: Any, *, ttl: int = DEFAULT_TTL_SECONDS) -> None:
        with self._lock:
            self._data[key] = (time.time() + ttl, value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def describe(self) -> str:
        with self._lock:
            return f"memory({len(self._data)} keys)"


class RedisCache:
    """Redis 实现。连不上就抛异常，由 :func:`build_cache` 决定退不退化。"""

    def __init__(self, url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._client.ping()

    def get_json(self, key: str) -> Any | None:
        raw = self._client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:  # 缓存里是脏数据就当没有，不要炸掉请求
            logger.warning("缓存内容无法解析，已删除：%s", key)
            self._client.delete(key)
            return None

    def set_json(self, key: str, value: Any, *, ttl: int = DEFAULT_TTL_SECONDS) -> None:
        self._client.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ttl)

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def describe(self) -> str:
        return "redis"


_cache: Cache | None = None


def build_cache(settings: Settings) -> Cache:
    """按配置挑实现。**每次启动只决定一次**，之后不再探活。

    为什么不在每次读写时探活：Redis 抖一下就让请求路径多一次网络往返，
    比缓存不命中更慢。真断了就整进程退化成内存缓存，代价是重启后才知道——
    这个代价可以接受，因为缓存里只有可重建的派生结果。
    """
    global _cache
    if _cache is not None:
        return _cache

    if settings.redis_url:
        try:
            _cache = RedisCache(settings.redis_url)
            logger.info("缓存就绪：%s", _cache.describe())
            return _cache
        except Exception as exc:  # noqa: BLE001 - 任何连接问题都退化，不让应用起不来
            logger.warning("Redis 不可用，退化为进程内缓存：%s（%s）", settings.redis_url, exc)
    else:
        logger.info("未配置 Redis，使用进程内缓存")

    _cache = MemoryCache()
    logger.info("缓存就绪：%s", _cache.describe())
    return _cache


def reset_cache() -> None:
    """测试用：换配置后需要重新挑选实现。"""
    global _cache
    _cache = None


def cache_key(*parts: object) -> str:
    """把若干标识拼成稳定的键。

    长串（如区间快照 JSON）先哈希再拼，避免键长到没法看；
    短串原样保留，出问题时能直接从键名看出是哪个数据集。
    """
    chunks: list[str] = []
    for part in parts:
        text = "" if part is None else str(part)
        if len(text) > 48:
            text = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        chunks.append(text)
    return "cbc:" + ":".join(chunks)


def judgment_scope(dataset) -> tuple[str, str]:
    """一份数据的"判定口径"标识：口径 + 判定时刻。

    用它做缓存键的一部分：用户改了区间并重判之后 `judged_at` 变了，
    旧缓存自然不再命中——不需要谁去记得调 invalidate（RK-28 的反面）。
    """
    judged_at = getattr(dataset, "judged_at", None)
    if judged_at is None:
        stamp = "never"
    else:
        # 兼容 datetime 与已经序列化过的字符串（快照/测试里两种都出现过）
        stamp = judged_at.isoformat() if hasattr(judged_at, "isoformat") else str(judged_at)
    return str(getattr(dataset, "ri_source", "default") or "default"), stamp
