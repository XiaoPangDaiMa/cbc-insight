"""本地冒烟：不起服务器，用 TestClient 走一遍注册 → 上传 → 图表 → 导出 → 删除。

用法（项目根目录）：backend/.venv/Scripts/python.exe scripts/smoke_local.py
只打印结果，不做断言；正式断言在 backend/tests/ 里。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient

from app.main import app

FIXTURE = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures" / "sample_clean.csv"


def main() -> None:
    print("app:", app.title)
    paths = sorted(
        {
            (route.path, tuple(sorted(m for m in getattr(route, "methods", set()) if m != "HEAD")))
            for route in app.routes
            if getattr(route, "path", None)
        }
    )
    for path, methods in paths:
        print(f"  {methods} {path}")

    with TestClient(app) as client:
        token = _auth(client)
        headers = {"Authorization": f"Bearer {token}"}

        files = {"file": ("sample_clean.csv", FIXTURE.read_bytes(), "text/csv")}
        created = client.post("/api/v1/datasets", files=files, headers=headers)
        print("upload:", created.status_code)
        if created.status_code == 409:
            dataset_id = created.json()["dataset_id"]
            print("reuse existing dataset:", dataset_id)
            body = {"dataset": client.get(f"/api/v1/datasets/{dataset_id}", headers=headers).json()["dataset"]}
        elif created.status_code != 201:
            print(json.dumps(created.json(), ensure_ascii=False, indent=2)[:2000])
            return
        else:
            body = created.json()
            dataset_id = body["dataset"]["dataset_id"]
        print("dataset:", dataset_id, "rows:", body["dataset"]["rows"], "health:", body["dataset"].get("health"))
        print("anomaly:", json.dumps(body.get("anomaly") or {}, ensure_ascii=False)[:400])

        for call in (
            ("GET", f"/api/v1/datasets/{dataset_id}/metric-status"),
            ("GET", f"/api/v1/datasets/{dataset_id}/stats"),
            ("GET", f"/api/v1/datasets/{dataset_id}/clean-report"),
            ("GET", f"/api/v1/datasets/{dataset_id}/preview?size=3"),
            ("GET", f"/api/v1/datasets/{dataset_id}/export/preview?kind=items"),
            ("GET", f"/api/v1/datasets/{dataset_id}/samples/0/profile"),
            ("GET", "/api/v1/dashboard"),
        ):
            response = client.request(call[0], call[1], headers=headers)
            print(call[1], "->", response.status_code, json.dumps(response.json(), ensure_ascii=False)[:220])

        for kind, payload in (
            ("box", {"metric": "hgb"}),
            ("hist", {"metric": "hgb"}),
            ("corr", {}),
            ("scatter", {"metric": "mch"}),
        ):
            response = client.post(f"/api/v1/datasets/{dataset_id}/charts/{kind}", json=payload, headers=headers)
            data = response.json() if response.status_code == 200 else {}
            points = len(data.get("points") or [])
            print(f"chart {kind}: {response.status_code} caption={data.get('caption')!r} points={points}")

        exported = client.get(f"/api/v1/datasets/{dataset_id}/export/items", headers=headers)
        name = exported.headers.get("x-export-filename")
        print("export:", exported.status_code, name, len(exported.content), "bytes")
        print("bom:", exported.content[:3] == b"\xef\xbb\xbf")
        print("csv head:", exported.content.decode("utf-8-sig").splitlines()[0][:160])

        deleted = client.delete(f"/api/v1/datasets/{dataset_id}", headers=headers)
        print("delete:", deleted.status_code)


def _auth(client: TestClient) -> str:
    name = "smoke_" + Path.home().name[:6]
    response = client.post(
        "/api/v1/auth/register",
        json={"username": name, "password": "smoke-pass-123", "password_confirm": "smoke-pass-123"},
    )
    if response.status_code == 409:
        response = client.post("/api/v1/auth/login", json={"username": name, "password": "smoke-pass-123"})
    if response.status_code >= 400:
        print("auth failed:", response.status_code, response.text[:500])
        raise SystemExit(1)
    return response.json()["access_token"]


if __name__ == "__main__":
    main()
