"""B5 实机冒烟：多数据集并排对比（FR-29 / BR-13）。

用法（backend 下）：
    .venv\\Scripts\\python.exe ..\\scripts\\smoke_b5.py --base http://127.0.0.1:8010 \
        --user xiaopang --password '...'

它验证四件在单测里也验过、但只有在真服务 + 真数据上才成立的事：
1. 两份真实数据集能并排，且每格都有 n；
2. 响应体里没有任何 p 值 / 检验字段（含嵌套）；
3. 只有 1 份、多于 4 份都被拒；
4. 不存在的数据集返回 404，而不是把别人那半边结果悄悄省略。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from typing import Any

import httpx

FORBIDDEN_KEYS = {"p_value", "p", "pval", "significant", "significance", "t_stat", "u_stat", "effect_size"}


def walk_keys(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_keys(item)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    client = httpx.Client(base_url=args.base.rstrip("/"), timeout=180.0)
    login = client.post("/api/v1/auth/login", json={"username": args.user, "password": args.password})
    if login.status_code != 200:
        print(f"登录失败: {login.status_code} {login.text[:200]}")
        return 1
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

    items = client.get("/api/v1/datasets").json()["items"]
    print(f"数据集 {len(items)} 份: " + ", ".join(f"{item['name']}({item['rows']})" for item in items))
    if len(items) < 2:
        print("需要至少 2 份数据集")
        return 1
    # 两份最小的，避免在冒烟里等十万行
    small = sorted(items, key=lambda item: item["rows"])[:2]
    ids = [item["dataset_id"] for item in small]

    response = client.post("/api/v1/compare/stats", json={"dataset_ids": ids})
    print(f"\n[1] 并排两份: {response.status_code}")
    if response.status_code != 200:
        print(response.text[:500])
        return 1
    payload = response.json()
    print(f"    数据集: {[item['name'] for item in payload['datasets']]}")
    print(f"    可比指标: {len(payload['side_by_side'])}  缺列提示: {len(payload['excluded'])}")
    for row in payload["side_by_side"][:3]:
        cells = row["cells"]
        summary = " | ".join(
            f"n={cell['n']} 中位={cell['median']} 正常={cell['pct_normal']}" for cell in cells
        )
        print(f"    {row['name_cn']}({row['unit']}): {summary}")
    print(f"    口径说明: {payload['notes']}")
    print(f"    disclaimer: {payload['disclaimer'][:40]}…")

    keys = {key.lower() for key in walk_keys(payload)}
    leaked = keys & FORBIDDEN_KEYS
    print(f"\n[2] 检验字段泄漏: {leaked or '无'}")
    body = {key: value for key, value in payload.items() if key != "disclaimer"}
    text = json.dumps(body, ensure_ascii=False)
    print(f"    正文含『显著』: {'显著' in text}")
    print(f"    正文含『p 值』: {'p 值' in text}")

    one = client.post("/api/v1/compare/stats", json={"dataset_ids": ids[:1]})
    print(f"\n[3] 只给 1 份: {one.status_code} {one.json().get('code')}")
    many = client.post("/api/v1/compare/stats", json={"dataset_ids": ids + ["a", "b", "c"]})
    print(f"    给 5 份: {many.status_code} {many.json().get('code')}")
    ghost = client.post("/api/v1/compare/stats", json={"dataset_ids": [ids[0], "0" * 32]})
    print(f"[4] 不存在的数据集: {ghost.status_code} {ghost.json().get('code')}")

    ok = (
        not leaked
        and one.status_code == 422
        and many.status_code == 422
        and ghost.status_code == 404
        and len(payload["side_by_side"]) > 0
    )
    print(f"\n结论: {'全部通过' if ok else '有检查项未通过'}")
    client.close()
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
