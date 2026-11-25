"""把要写进 JSON 列 / 交给前端的对象洗成"合法 JSON"。

为什么需要这个模块（两条都是真实会出事的，不是洁癖）：

1. ``NaN`` / ``Infinity`` **不是合法 JSON**。PostgreSQL 的 ``jsonb`` 直接拒收，
   报 ``invalid input syntax for type json``；SQLite 只是当文本存下来。
   于是同一个 bug 在开发环境（SQLite）永远看不见，切到 PG 上线当天才炸，
   而且炸在"保存数据集"这种主链路上。
2. 浏览器的 ``JSON.parse`` 同样拒收 ``NaN``。带 NaN 的响应到了前端会变成
   *整个接口解析失败*，界面上只会显示一句笼统的"加载失败"。

NaN 从哪来：相关系数在某一列是常数时是 NaN；均值/分位数在空列上是 NaN；
``inf`` 来自除以 0。这些都属于"算不出来"，正确的表达是 ``null``，
不是 ``NaN``——前者前端显示 `—`，后者让整个响应挂掉。

约定：只处理"要出网关"的对象（写库的 JSON 列、导出的 meta、缓存的值）。
DataFrame 内部照常保留 NaN，pandas 语义与 SQL 语义不是一回事。
"""

from __future__ import annotations

import math
from typing import Any


def sanitize_json(value: Any) -> Any:
    """递归返回一个只含 ``dict/list/str/int/float/bool/None`` 的等价对象。"""
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): sanitize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize_json(item) for item in value]
    if isinstance(value, bool):  # 必须先于 int：bool 是 int 的子类
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value

    # numpy 标量（float64/int64）、pandas Timestamp、Decimal 之类
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return sanitize_json(item())
        except (TypeError, ValueError):  # pragma: no cover - 极少数标量不支持 item()
            return str(value)

    # 兜底：宁可写成字符串，也不要把不可序列化的对象塞进 JSON 列
    return str(value)


def is_json_safe(value: Any) -> bool:
    """测试与自检用：判断一个对象能否被严格 JSON 序列化（不允许 NaN）。"""
    import json

    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return False
    return True
