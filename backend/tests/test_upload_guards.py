"""上传闸门验收：S1 文件层、S2 失败清理、S3 可用性闸、S5 NaN 消毒。

这些用例都刻意走**真实上传接口**（而不是直接调服务函数），因为它们守的是
"用户传错东西时系统怎么反应"，而这条路只有经过 HTTP 层才完整：错误码、
status 落库、清理产物、后续端点拒绝，四件事要一起成立。
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.jsonsafe import is_json_safe, sanitize_json
from app.db.session import reset_engine
from app.main import create_app
from app.pipeline.reading import read_csv

API = "/api/v1"
HEADER = "age,gender,hgb,wbc,plt\n"


def _csv(rows: int = 12, body: str = "40,male,140,7.0,250") -> bytes:
    lines = [HEADER.strip(), *([body] * rows)]
    return ("\n".join(lines) + "\n").encode("utf-8")


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory):
    """临时 sqlite + 临时数据目录，不碰开发库（同 test_api_flow.py 的做法）。"""
    tmp = tmp_path_factory.mktemp("upload-guards")
    os.environ["CBC_DATABASE_URL"] = f"sqlite:///{(tmp / 'test.db').as_posix()}"
    os.environ["CBC_DATA_DIR"] = str(tmp / "data")
    get_settings.cache_clear()
    reset_engine()

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    os.environ.pop("CBC_DATABASE_URL", None)
    os.environ.pop("CBC_DATA_DIR", None)
    get_settings.cache_clear()
    reset_engine()


@pytest.fixture(scope="module")
def auth(client: TestClient) -> dict[str, str]:
    response = client.post(f"{API}/auth/register", json={"username": "guard_user", "password": "guard-pass-2026"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload(client: TestClient, auth: dict[str, str], name: str, payload: bytes):
    return client.post(
        f"{API}/datasets",
        headers=auth,
        files={"file": (name, payload, "text/csv")},
    )


def test_excel_filename_is_rejected(client: TestClient, auth: dict[str, str]) -> None:
    response = _upload(client, auth, "血常规.xlsx", b"PK\x03\x04mock")
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 40003
    # 提示必须指向下一步动作，而不是只说"格式不对"
    assert "CSV" in body["detail"]


def test_zip_magic_behind_csv_name_is_rejected(client: TestClient, auth: dict[str, str]) -> None:
    response = _upload(client, auth, "data.csv", b"PK\x03\x04" + b"\x00" * 64)
    assert response.status_code == 400
    assert response.json()["code"] == 40003
    assert "二进制" in response.json()["detail"]


def test_png_magic_behind_csv_name_is_rejected(client: TestClient, auth: dict[str, str]) -> None:
    response = _upload(client, auth, "report.csv", b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    assert response.status_code == 400
    assert response.json()["code"] == 40003


def test_nul_bytes_are_rejected(client: TestClient, auth: dict[str, str]) -> None:
    response = _upload(client, auth, "data.csv", b"age,gender\n40,male\n\x00\x00,xx\n")
    assert response.status_code == 400
    assert "NUL" in response.json()["detail"]


def test_read_csv_enforces_row_and_column_limits(tmp_path) -> None:
    """配额闸：配置里写了上限而没人检查，等于没写（C-02）。"""
    path = tmp_path / "many.csv"
    path.write_text(_csv(rows=20).decode("utf-8"), encoding="utf-8")

    with pytest.raises(AppError) as row_error:
        read_csv(path, max_rows=10)
    assert row_error.value.code == 40002
    assert "20" in row_error.value.detail

    with pytest.raises(AppError) as column_error:
        read_csv(path, max_columns=3)
    assert column_error.value.code == 40002
    assert "5" in column_error.value.detail

    # 不超限时一切照旧（防止把闸门写成了无条件拒绝）
    assert len(read_csv(path, max_rows=100, max_columns=10).frame) == 20


def test_text_values_in_metric_columns_are_rejected(client: TestClient, auth: dict[str, str]) -> None:
    """表头对得上、值却是"正常/阴性"——最危险的一种错：会产出一份空壳报告。"""
    response = _upload(client, auth, "junk.csv", _csv(rows=12, body="40,male,正常,阴性,未见异常"))
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == 42201
    assert body["status"] == "rejected"
    assert body["dataset_id"]

    listed = client.get(f"{API}/datasets", headers=auth).json()["items"]
    record = next(item for item in listed if item["dataset_id"] == body["dataset_id"])
    assert record["status"] == "rejected"

    # 被拒的数据集不能再产出任何结论：预览、导出、图表都要拦住
    for path in (
        f"{API}/datasets/{body['dataset_id']}/preview",
        f"{API}/datasets/{body['dataset_id']}/export/preview?kind=items",
    ):
        blocked = client.get(path, headers=auth)
        assert blocked.status_code == 422, blocked.text
        assert blocked.json()["code"] == 42201


def test_failed_pipeline_leaves_no_files(client: TestClient, auth: dict[str, str]) -> None:
    """失败上传不能把 raw/{id}.csv 留在磁盘上——它没人会删。"""
    settings = get_settings()
    before = {p.name for p in settings.raw_dir.glob("*.csv")}
    response = _upload(client, auth, "broken.csv", b"age,gender\n")
    assert response.status_code in {400, 422}
    after = {p.name for p in settings.raw_dir.glob("*.csv")}
    assert after == before


def test_sanitize_json_removes_nan_and_inf() -> None:
    """S5：NaN/inf 不是合法 JSON——PG 的 jsonb 与浏览器 JSON.parse 都会拒收。"""
    payload = {
        "mean": float("nan"),
        "median": float("inf"),
        "nested": [1.0, float("-inf"), {"rho": float("nan")}],
        "kept": 0.93,
        "flag": False,
    }
    cleaned = sanitize_json(payload)
    assert cleaned["mean"] is None
    assert cleaned["median"] is None
    assert cleaned["nested"] == [1.0, None, {"rho": None}]
    assert cleaned["kept"] == 0.93
    assert cleaned["flag"] is False  # bool 不能被当成 int 后的 0
    assert is_json_safe(cleaned)
    json.dumps(cleaned, allow_nan=False)  # 不抛异常即通过
