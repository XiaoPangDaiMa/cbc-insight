"""接口级回归：注册 → 上传 → 统计/图表 → 导出 → 删除（T-01、T-13、T-16~T-19、T-29）。

这一层**不 mock 数据库**，用临时 sqlite 文件跑真实 SQLAlchemy 链路；不需要 Docker，
因此不带 ``integration`` 标记——`pytest -m "not integration"` 默认就会跑它。
标记成 integration 再因"没起容器"而跳过，正是 RK-24 那种最危险的假绿。
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import reset_engine

FIXTURES = Path(__file__).parent / "fixtures"
CSV_PATH = FIXTURES / "sample_clean.csv"


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    base = tmp_path_factory.mktemp("api")
    env = {
        "CBC_DATABASE_URL": f"sqlite:///{(base / 'test.db').as_posix()}",
        "CBC_DATA_DIR": str(base / "data"),
    }
    import os

    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    get_settings.cache_clear()
    reset_engine()

    from app.main import create_app

    application = create_app()
    try:
        with TestClient(application) as test_client:
            yield test_client
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        reset_engine()


@pytest.fixture(scope="module")
def token(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "api_tester", "password": "pipeline-2026", "password_confirm": "pipeline-2026"},
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def uploaded(client: TestClient, auth: dict[str, str]) -> dict:
    content = CSV_PATH.read_bytes()
    response = client.post(
        "/api/v1/datasets",
        files={"file": ("sample_clean.csv", io.BytesIO(content), "text/csv")},
        headers=auth,
    )
    assert response.status_code in (200, 201), response.text
    payload = response.json()
    assert payload["dataset"]["rows"] == 8
    return payload


def test_upload_runs_whole_pipeline(uploaded: dict) -> None:
    """T-01/T-05：上传后 S1–S7 自动跑完，8 个唯一样本、异常项与模式都在。"""
    anomaly = uploaded["anomaly"]
    assert anomaly["samples"] == 8
    assert anomaly["abnormal_samples"] >= 1
    assert "NORMAL" in anomaly["pattern_counts"]
    quality = uploaded["quality"]
    assert quality["dq"]["DQ-01"] is not None
    # 原始 10 行里有 1 行完全重复 → (10-1)/10 = 0.9（DQ-02 是唯一率）
    assert quality["dq"]["DQ-02"] == pytest.approx(0.9)


def test_unauthorized_without_token(client: TestClient) -> None:
    """T-13 / NFR-S-03：没令牌一律 401，而不是 403 或 200。"""
    assert client.get("/api/v1/datasets").status_code == 401
    assert client.get("/api/v1/datasets").json()["code"] == 40101


def test_duplicate_upload_conflicts(client: TestClient, auth: dict[str, str]) -> None:
    """T-17：同一文件重复上传返回 409/40901，并带上已存在的 dataset_id。"""
    content = CSV_PATH.read_bytes()
    response = client.post(
        "/api/v1/datasets",
        files={"file": ("sample_clean.csv", io.BytesIO(content), "text/csv")},
        headers=auth,
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == 40901
    assert body["dataset_id"]


def test_unknown_dataset_is_404(client: TestClient, auth: dict[str, str]) -> None:
    """别人的 / 不存在的数据集统一 40401，避免枚举（8.3 表）。"""
    response = client.get("/api/v1/datasets/not-a-real-id/stats", headers=auth)
    assert response.status_code == 404
    assert response.json()["code"] == 40401


def test_stats_and_metric_status(client: TestClient, auth: dict[str, str], uploaded: dict) -> None:
    dataset_id = uploaded["dataset"]["dataset_id"]

    stats = client.get(f"/api/v1/datasets/{dataset_id}/stats", headers=auth).json()
    names = {item["metric"] for item in stats["overview"]}
    assert {"hgb", "wbc", "plt"} <= names

    status = client.get(f"/api/v1/datasets/{dataset_id}/metric-status", headers=auth).json()
    hgb = next(item for item in status["metrics"] if item["metric"] == "hgb")
    # 性别相关指标不返回单一区间，改为给按性别的两组区间（BR-17）
    assert hgb["gender_dependent"] is True
    assert hgb["low"] is None and hgb["high"] is None
    assert {band["gender"] for band in hgb["ranges_by_gender"]} == {"male", "female"}
    shares = hgb["pct_low"] + hgb["pct_normal"] + hgb["pct_above"] + hgb["pct_na"]
    assert shares == pytest.approx(1.0)


def test_box_caption_and_points(client: TestClient, auth: dict[str, str], uploaded: dict) -> None:
    """T-12 + FR-32：箱线图每组标注 n、带参考带，图注不含禁用词。"""
    dataset_id = uploaded["dataset"]["dataset_id"]
    chart = client.post(
        f"/api/v1/datasets/{dataset_id}/charts/box",
        json={"metric": "hgb"},
        headers=auth,
    ).json()
    assert chart["caption"]
    assert "显著" not in chart["caption"]
    assert chart["points"] and len(chart["points"]) == 8
    assert set(chart["points"][0]) == {"sample_index", "status", "deviation_pct", "pct"}
    # 参考带必须两条（男女），不能只剩一条把女性全判成偏低
    assert len(chart["supporting"]["reference_bands"]) == 2


def test_missing_gender_does_not_break_charts(client: TestClient, auth: dict[str, str]) -> None:
    """T-34：没有 gender 列时箱线图降级为单组并标注，而不是 500。"""
    csv = "\n".join(
        [
            "age,hgb,wbc,plt,mcv,mch,mchc",
            "21,140,6.1,210,88,29.5,330",
            "34,132,5.4,190,90,30.1,334",
            "47,151,7.2,260,86,28.9,325",
        ]
    )
    upload = client.post(
        "/api/v1/datasets",
        files={"file": ("no_gender.csv", io.BytesIO(csv.encode()), "text/csv")},
        headers=auth,
    )
    assert upload.status_code in (200, 201), upload.text
    dataset_id = upload.json()["dataset"]["dataset_id"]
    chart = client.post(f"/api/v1/datasets/{dataset_id}/charts/box", json={"metric": "hgb"}, headers=auth)
    assert chart.status_code == 200
    body = chart.json()
    assert len(body["supporting"]["reference_bands"]) == 2
    assert len(body["points"]) == 3
    assert "按性别" not in body["caption"]


def test_export_preview_matches_download(client: TestClient, auth: dict[str, str], uploaded: dict) -> None:
    """T-29 / NFR-M-06：预览表头与下载文件表头逐列一致。"""
    dataset_id = uploaded["dataset"]["dataset_id"]
    preview = client.get(f"/api/v1/datasets/{dataset_id}/export/preview?kind=items", headers=auth).json()

    response = client.get(f"/api/v1/datasets/{dataset_id}/export/items", headers=auth)
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM，Excel 不乱码
    header_line = response.content.decode("utf-8-sig").splitlines()[0]
    assert header_line.split(",") == preview["headers"]
    assert preview["total"] > 0

    meta = json.loads(response.headers["X-Export-Meta"])
    assert meta["rows"] == preview["total"]


def test_sample_profile_bounds(client: TestClient, auth: dict[str, str], uploaded: dict) -> None:
    """8.3 的 40402：越界 sample_index 要说清"不在当前筛选结果中"。"""
    dataset_id = uploaded["dataset"]["dataset_id"]
    ok = client.get(f"/api/v1/datasets/{dataset_id}/samples/0/profile", headers=auth)
    assert ok.status_code == 200
    hgb = next(item for item in ok.json()["items"] if item["metric"] == "hgb")
    assert 0.0 <= hgb["pos"] <= 1.0 or hgb["pos"] is None

    bad = client.get(f"/api/v1/datasets/{dataset_id}/samples/999/profile", headers=auth)
    assert bad.status_code == 404
    assert bad.json()["code"] == 40402


def test_dashboard_lists_own_datasets(client: TestClient, auth: dict[str, str], uploaded: dict) -> None:
    """T-26：登录后首屏就是数据，不是欢迎语。"""
    body = client.get("/api/v1/dashboard", headers=auth).json()
    assert body["empty"] is False
    assert body["dataset_count"] >= 1
    ids = {item["dataset_id"] for item in body["datasets"]}
    assert body["latest"]["dataset_id"] in ids


def test_delete_removes_dataset_and_files(client: TestClient, auth: dict[str, str], uploaded: dict) -> None:
    """T-18：删除后接口 404，派生文件也清理掉。"""
    dataset_id = uploaded["dataset"]["dataset_id"]
    assert client.delete(f"/api/v1/datasets/{dataset_id}", headers=auth).status_code == 200
    assert client.get(f"/api/v1/datasets/{dataset_id}/stats", headers=auth).status_code == 404

    settings = get_settings()
    assert not (settings.processed_dir / dataset_id).exists()
