"""筛选与"按条件导出"的接口级回归（FR-14、FR-18、FR-35、T-29、RK-19）。

这里守的是一条很容易悄悄坏掉的约定：**用户在页面上看到的筛选结果、预览里的行数、
下载到的 CSV 行数，必须是同一批样本**。三处各写一遍筛选逻辑时，它们会各自"看起来正常"
地漂移，而且漂移当天看不出来——所以断言直接对数，不查实现。
"""

from __future__ import annotations

import io
import json
import os
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
    base = tmp_path_factory.mktemp("api_filter")
    env = {
        "CBC_DATABASE_URL": f"sqlite:///{(base / 'test.db').as_posix()}",
        "CBC_DATA_DIR": str(base / "data"),
    }
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
def auth(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "filter_tester", "password": "filter-2026-pass", "password_confirm": "filter-2026-pass"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="module")
def dataset_id(client: TestClient, auth: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/datasets",
        files={"file": ("sample_clean.csv", io.BytesIO(CSV_PATH.read_bytes()), "text/csv")},
        headers=auth,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["dataset"]["dataset_id"]


@pytest.fixture(scope="module")
def preview(client: TestClient, auth: dict[str, str], dataset_id: str) -> dict:
    response = client.get(f"/api/v1/datasets/{dataset_id}/preview?page=1&size=100", headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def _column(preview: dict, name: str) -> list:
    index = preview["headers"].index(name)
    return [row[index] for row in preview["rows"]]


def _query(client: TestClient, auth: dict[str, str], dataset_id: str, body: dict) -> dict:
    response = client.post(f"/api/v1/datasets/{dataset_id}/query", json=body, headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def test_query_filter_matches_manual_count(preview: dict, client: TestClient, auth: dict, dataset_id: str) -> None:
    """FR-14：按指标阈值筛出的条数，与手工数出来的条数一致。"""
    hgb = [float(v) for v in _column(preview, "hgb") if v is not None]
    expected = sum(1 for value in hgb if value < 130)
    payload = _query(
        client,
        auth,
        dataset_id,
        {"filters": [{"metric": "hgb", "op": "lt", "value": 130}], "page": 1, "size": 100},
    )
    assert payload["total"] == expected
    assert payload["matched"] == expected
    low_index = payload["headers"].index("hgb")
    assert all(float(row[low_index]) < 130 for row in payload["rows"])


def test_query_gender_and_age_combined(client: TestClient, auth: dict, dataset_id: str, preview: dict) -> None:
    """FR-14：性别与年龄是"与"关系，不是"或"关系。"""
    genders = _column(preview, "gender")
    ages = [float(v) for v in _column(preview, "age")]
    expected = sum(1 for g, a in zip(genders, ages, strict=True) if str(g).lower() == "female" and 20 <= a <= 60)
    payload = _query(client, auth, dataset_id, {"gender": "female", "age_min": 20, "age_max": 60, "size": 100})
    assert payload["total"] == expected
    gender_index = payload["headers"].index("gender")
    age_index = payload["headers"].index("age")
    for row in payload["rows"]:
        assert str(row[gender_index]).lower() == "female"
        assert 20 <= float(row[age_index]) <= 60


def test_export_filtered_uses_same_rows(client: TestClient, auth: dict, dataset_id: str) -> None:
    """FR-35 / NFR-M-06：带条件的导出，行数必须等于筛选结果的行数。"""
    filters = json.dumps([{"metric": "hgb", "op": "lt", "value": 130}])
    queried = _query(
        client,
        auth,
        dataset_id,
        {"filters": [{"metric": "hgb", "op": "lt", "value": 130}], "page": 1, "size": 100},
    )
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/export/filtered?scope=filtered&filters={filters}",
        headers=auth,
    )
    assert response.status_code == 200, response.text
    text = response.content.decode("utf-8-sig")
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) - 1 == queried["total"]
    assert text.startswith("\ufeff") or response.content.startswith(b"\xef\xbb\xbf")


def test_export_preview_headers_equal_download(client: TestClient, auth: dict, dataset_id: str) -> None:
    """T-29：预览表头与下载表头逐列相同（含带筛选的情况）。"""
    filters = json.dumps([{"metric": "wbc", "op": "between", "value": 4, "upper": 12}])
    query = f"?kind=summary&scope=filtered&filters={filters}"
    preview = client.get(f"/api/v1/datasets/{dataset_id}/export/preview{query}", headers=auth)
    assert preview.status_code == 200, preview.text
    download = client.get(f"/api/v1/datasets/{dataset_id}/export/summary{query}", headers=auth)
    assert download.status_code == 200, download.text
    header_line = download.content.decode("utf-8-sig").splitlines()[0]
    assert header_line.split(",") == preview.json()["headers"]


def test_export_summary_only_abnormal(client: TestClient, auth: dict, dataset_id: str) -> None:
    """FR-18：异常清单只含异常样本，且异常项多的在前。"""
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/export/preview?kind=summary&only_abnormal=true",
        headers=auth,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] >= 1
    n_abnormal_index = payload["headers"].index("异常指标数")
    counts = [int(row[n_abnormal_index]) for row in payload["rows"]]
    assert all(count > 0 for count in counts)
    assert counts == sorted(counts, reverse=True)


def test_bad_filters_json_is_rejected(client: TestClient, auth: dict, dataset_id: str) -> None:
    """看不懂的筛选条件必须报错——静默忽略等于把全量数据当筛选结果导出去。"""
    response = client.get(f"/api/v1/datasets/{dataset_id}/export/filtered?filters=not-json", headers=auth)
    assert response.status_code == 422
    assert response.json()["code"] == 42201 


def test_empty_selection_refuses_to_export(client: TestClient, auth: dict, dataset_id: str) -> None:
    """筛出 0 条时不生成空文件，而是给出可读的解释（8.3 的 42201）。"""
    filters = json.dumps([{"metric": "hgb", "op": "gt", "value": 9999}])
    response = client.get(f"/api/v1/datasets/{dataset_id}/export/filtered?filters={filters}", headers=auth)
    assert response.status_code == 422
    assert response.json()["code"] == 42201
