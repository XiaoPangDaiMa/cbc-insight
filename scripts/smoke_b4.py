"""B4 实机冒烟：筛选、按条件导出、异常清单导出（打临时端口，不动用户的 8000/5173）。

用法（backend 下）：
    .venv\\Scripts\\python.exe ..\\scripts\\smoke_b4.py --port 8010 --user xiaopang --password '...'

它验证的是四件在单测里也验过、但只有在真服务上才成立的契约：
1. 页面上的命中数 == 导出文件的行数（T-29 的另一半）；
2. 预览表头 == 下载文件的首行（同一份列定义，NFR-M-06）；
3. 异常清单只含异常样本，且按异常指标数降序（FR-18）；
4. 看不懂的筛选条件必须报错，而不是"当作没写"把全量数据导出去。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from urllib.parse import quote

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--dataset", default=None, help="dataset_id 前缀；缺省取第一个有 gender 的数据集")
    args = parser.parse_args()

    base = args.base.rstrip("/")
    client = httpx.Client(base_url=base, timeout=120.0)

    health = client.get("/healthz")
    print(f"healthz: {health.status_code} {health.json()}")

    login = client.post("/api/v1/auth/login", json={"username": args.user, "password": args.password})
    if login.status_code != 200:
        print(f"登录失败: {login.status_code} {login.text[:200]}")
        return 1
    token = login.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    print(f"登录成功: {args.user}（响应字段 {sorted(login.json())}）")

    datasets = client.get("/api/v1/datasets").json()["items"]
    if not datasets:
        print("没有数据集，先跑 scripts/import_local.py")
        return 1
    target = None
    for item in datasets:
        if args.dataset and item["dataset_id"].startswith(args.dataset):
            target = item
            break
    if target is None and not args.dataset:
        target = datasets[0]
    if target is None:
        print(f"没找到匹配 {args.dataset} 的数据集")
        return 1
    dataset_id = target["dataset_id"]
    print(f"数据集: {dataset_id} rows={target['rows']} name={target['name']}")

    filters = [{"metric": "hgb", "op": "lt", "value": 130}]
    body = {
        "filters": filters,
        "gender": None,
        "age_min": None,
        "age_max": None,
        "page": 1,
        "size": 20,
        "stage": "cleaned",
    }
    query = client.post(f"/api/v1/datasets/{dataset_id}/query", json=body)
    print(f"\n[1] 筛选 hgb<130: {query.status_code}")
    if query.status_code != 200:
        print(query.text[:400])
        return 1
    payload = query.json()
    matched = payload.get("matched", payload["total"])
    print(f"    matched={matched} total={payload['total']} rows={len(payload['rows'])}")
    hgb_at = payload["headers"].index("实测值") if "实测值" in payload["headers"] else None
    if hgb_at is not None:
        values = [row[hgb_at] for row in payload["rows"]]
        print(f"    前 5 个 hgb: {values[:5]}（都应 < 130）")

    filters_raw = quote(json.dumps(filters, ensure_ascii=False))
    preview = client.get(
        f"/api/v1/datasets/{dataset_id}/export/preview"
        f"?kind=filtered&scope=filtered&filters={filters_raw}"
    )
    print(f"\n[2] 导出预览（同条件）: {preview.status_code}")
    preview_payload = preview.json()
    print(f"    total={preview_payload['total']} filename={preview_payload['filename']}")
    print(f"    total == matched: {preview_payload['total'] == matched}")

    download = client.get(f"/api/v1/datasets/{dataset_id}/export/filtered?scope=filtered&filters={filters_raw}")
    print(f"\n[3] 下载（同条件）: {download.status_code} bytes={len(download.content)}")
    bom = download.content.startswith(b"\xef\xbb\xbf")
    text = download.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    print(f"    BOM={bom} 表头={rows[0][:4]}… 数据行={len(rows) - 1}（应等于 matched={matched}）")
    print(f"    预览表头 == 下载表头: {preview_payload['headers'] == rows[0]}")

    summary_preview = client.get(f"/api/v1/datasets/{dataset_id}/export/preview?kind=summary&only_abnormal=true")
    print(f"\n[4] 异常清单预览: {summary_preview.status_code}")
    summary_payload = summary_preview.json()
    headers = summary_payload["headers"]
    print(f"    total={summary_payload['total']} 表头={headers}")
    if "异常指标数" in headers:
        at = headers.index("异常指标数")
        counts = [row[at] for row in summary_payload["rows"]]
        print(f"    异常指标数前 5: {counts[:5]}（应全部 ≥ 1 且降序）")
        print(f"    全部 ≥1: {all(isinstance(c, int) and c >= 1 for c in counts)}")
        print(f"    降序: {counts == sorted(counts, reverse=True)}")

    bad = client.get(f"/api/v1/datasets/{dataset_id}/export/preview?kind=filtered&filters=not-json")
    bad_code = bad.json().get("code") if "json" in bad.headers.get("content-type", "") else ""
    print(f"\n[5] 非法筛选条件: {bad.status_code} {bad_code}")

    empty_filters = [{"metric": "hgb", "op": "gt", "value": 9999}]
    empty_raw = quote(json.dumps(empty_filters))
    empty = client.get(f"/api/v1/datasets/{dataset_id}/export/filtered?scope=filtered&filters={empty_raw}")
    print(f"[6] 空结果导出: {empty.status_code}（应 422/42201，不生成空文件）")

    client.close()
    ok = (
        preview_payload["total"] == matched
        and bom
        and len(rows) - 1 == matched
        and preview_payload["headers"] == rows[0]
        and bad.status_code == 422
        and empty.status_code == 422
    )
    print(f"\n结论: {'全部通过' if ok else '有检查项未通过'}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
