"""B3 实机冒烟：三层区间 / 陈旧判定 / 重判 / 试算（对着真跑起来的后端起 HTTP）。

用法：先启动后端（端口 8010），然后

    backend\\.venv\\Scripts\\python.exe scripts\\smoke_b3.py --user xiaopang --password "..."

刻意不碰上传：它只在**已有**数据集上验证"换区间会怎样"，因为上传链路已经由
``smoke_local.py`` 与 pytest 覆盖；这里再加一次上传只会拖慢排查。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8010/api/v1"


def show(label: str, value: object) -> None:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    print(f"{label}: {text[:400]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default="xiaopang")
    parser.add_argument("--password", default="fdj8888!")
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--dataset", default="", help="按 dataset_id 前缀挑数据集（缺省取列表第一个）")
    parser.add_argument("--hgb-low", type=float, default=125.0, help="把我的区间里 hgb 下限改成这个值")
    parser.add_argument("--hgb-high", type=float, default=None, help="同时改 hgb 上限（用来制造可见的判定变化）")
    args = parser.parse_args(argv)

    client = httpx.Client(base_url=args.base, timeout=60)
    login = client.post("/auth/login", json={"username": args.user, "password": args.password})
    print("login:", login.status_code)
    if login.status_code != 200:
        print(login.text)
        return 1
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("role in login payload:", "role" in login.json())

    ranges = client.get("/me/reference-ranges", headers=headers)
    print("GET /me/reference-ranges:", ranges.status_code)
    if ranges.status_code != 200:
        print(ranges.text)
        return 1
    payload = ranges.json()
    show("  default source/digest", [payload["default"]["source"], payload["default"]["digest"]])
    print("  metrics:", len(payload["metrics"]))

    datasets = client.get("/datasets", headers=headers).json()["items"]
    print("datasets:", [(d["dataset_id"][:8], d["rows"]) for d in datasets])
    if args.dataset:
        datasets = [d for d in datasets if d["dataset_id"].startswith(args.dataset)]
    if not datasets:
        print("没有匹配的数据集，先跑 scripts/import_local.py")
        return 1
    dataset_id = datasets[0]["dataset_id"]

    before = client.get(f"/datasets/{dataset_id}/ranges-snapshot", headers=headers).json()
    show("snapshot before", {"source": before["snapshot"].get("source"), "stale": before["stale"]})

    draft = {
        metric: {key: spec[key] for key in ("low", "high", "female_low", "female_high") if spec.get(key) is not None}
        for metric, spec in payload["default"]["items"].items()
    }
    draft["hgb"]["low"] = args.hgb_low
    if args.hgb_high is not None:
        draft["hgb"]["high"] = args.hgb_high
    saved = client.put(
        "/me/reference-ranges",
        json={"ranges": draft, "note": f"实机冒烟：HGB 改成 {draft['hgb']['low']}–{draft['hgb']['high']} 试一版"},
        headers=headers,
    )
    print("PUT /me/reference-ranges:", saved.status_code)
    if saved.status_code != 200:
        print(saved.text)
        return 1
    print("  saved version:", saved.json()["version"])

    after_save = client.get(f"/datasets/{dataset_id}/ranges-snapshot", headers=headers).json()
    show("snapshot after save", {"stale": after_save["stale"], "current": after_save["current"]["source"]})

    rejudged = client.post(f"/datasets/{dataset_id}/rejudge", json={}, headers=headers)
    print("POST /rejudge:", rejudged.status_code)
    if rejudged.status_code != 200:
        print(rejudged.text)
        return 1
    body = rejudged.json()
    show("  timings", body["timings"])
    show("  changed", body["changed"])
    show("  ri_source", body["ri_source"])

    after_rejudge = client.get(f"/datasets/{dataset_id}/ranges-snapshot", headers=headers).json()
    show("snapshot after rejudge", {"stale": after_rejudge["stale"], "source": after_rejudge["snapshot"].get("source")})

    trial = client.post(
        f"/datasets/{dataset_id}/charts/box",
        json={"metric": "hgb", "temp_ranges": {"hgb": {"low": 120, "high": 180}}},
        headers=headers,
    )
    print("chart with temp_ranges:", trial.status_code)
    if trial.status_code == 200:
        show("  ri_effective", trial.json()["ri_effective"])
        show("  caption", trial.json()["caption"])

    history = Path(__file__).resolve().parents[1] / "backend" / "data" / "processed" / dataset_id / "history"
    print("history files:", len(list(history.glob("*.json"))) if history.exists() else 0)

    reset = client.post("/me/reference-ranges/reset", headers=headers)
    print("POST /me/reference-ranges/reset:", reset.status_code)
    if reset.status_code == 200:
        state = reset.json()["state"]
        print("  mine:", state["mine"], "effective:", state["effective"]["source"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
