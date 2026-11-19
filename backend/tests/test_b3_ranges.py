"""B3：三层区间、判定快照与重判（BR-18/19/20、FR-24/36/37、T-38~T-43）。

三个"看起来该做、但做了就错"的断言都写在这里：

* 改完区间**不得**自动重判——旧结论必须原样留着，并标成"陈旧"（BR-18/BT-20）。
* 重判**只能**重放 S6–S7，``sample_index`` 一个都不能变（BR-19、9.2）。
* 临时试算**不得**留下任何痕迹：不落库、不改快照、不进导出（FR-37、RK-26）。
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import reset_engine

FIXTURES = Path(__file__).parent / "fixtures"
CSV_PATH = FIXTURES / "sample_clean.csv"

EDITABLE_KEYS = ("low", "high", "female_low", "female_high")


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    base = tmp_path_factory.mktemp("b3")
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
        json={"username": "b3_tester", "password": "ranges-2026", "password_confirm": "ranges-2026"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="module")
def dataset(client: TestClient, auth: dict[str, str]) -> dict:
    content = CSV_PATH.read_bytes()
    response = client.post(
        "/api/v1/datasets",
        files={"file": ("sample_clean.csv", io.BytesIO(content), "text/csv")},
        headers=auth,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["dataset"]


def _ranges_from(items: dict) -> dict:
    """把 ``items_of()`` 的输出收敛成可再次提交的形状（只留四个数值键）。"""
    return {
        metric: {key: spec[key] for key in EDITABLE_KEYS if key in spec and spec[key] is not None}
        for metric, spec in items.items()
    }


# --------------------------------------------------------------------------- 无角色


def test_auth_payload_has_no_role(client: TestClient, auth: dict[str, str]) -> None:
    """2.2：v1.6 起不再分角色，响应体里连字段都不该有。"""
    me = client.get("/api/v1/auth/me", headers=auth).json()
    assert "role" not in me
    login = client.post("/api/v1/auth/login", json={"username": "b3_tester", "password": "ranges-2026"})
    assert login.status_code == 200
    assert "role" not in login.json()


# --------------------------------------------------------------------------- 我的区间


def test_default_ranges_payload(client: TestClient, auth: dict[str, str]) -> None:
    payload = client.get("/api/v1/me/reference-ranges", headers=auth).json()
    assert len(payload["metrics"]) == 15
    assert len(payload["default"]["items"]) == 15
    assert payload["default"]["source"].startswith("default@")
    assert len(payload["default"]["digest"]) == 12
    assert payload["mine"] is None
    assert payload["effective"]["source"] == payload["default"]["source"]


def test_save_requires_note(client: TestClient, auth: dict[str, str]) -> None:
    """3.5.1：改区间必须写理由，否则一个月后自己都不认。"""
    items = _ranges_from(client.get("/api/v1/me/reference-ranges", headers=auth).json()["default"]["items"])
    response = client.put(
        "/api/v1/me/reference-ranges", json={"ranges": items, "note": "   "}, headers=auth
    )
    assert response.status_code == 422
    assert response.json()["code"] == 42201


def test_save_requires_complete_set(client: TestClient, auth: dict[str, str]) -> None:
    """整份保存：少一项就拒绝，避免"没给的部分保留旧值"让版本号失去意义。"""
    response = client.put(
        "/api/v1/me/reference-ranges",
        json={"ranges": {"hgb": {"low": 125, "high": 175}}, "note": "只改一项"},
        headers=auth,
    )
    assert response.status_code == 422
    assert "缺少指标" in response.json()["message"] or "缺少指标" in str(response.json())


def test_reject_reversed_bounds(client: TestClient, auth: dict[str, str]) -> None:
    items = _ranges_from(client.get("/api/v1/me/reference-ranges", headers=auth).json()["default"]["items"])
    items["hgb"] = {"low": 175, "high": 125}
    response = client.put("/api/v1/me/reference-ranges", json={"ranges": items, "note": "故意写反"}, headers=auth)
    assert response.status_code == 422
    assert response.json()["code"] == 42201


# --------------------------------------------------------------------------- 快照与陈旧


def test_snapshot_is_written_on_upload(client: TestClient, auth: dict[str, str], dataset: dict) -> None:
    """BR-18：判定即快照——上传完就该有一份"当时用的是哪套区间"。"""
    payload = client.get(f"/api/v1/datasets/{dataset['dataset_id']}/ranges-snapshot", headers=auth).json()
    assert payload["snapshot"]["digest"] == payload["current"]["digest"]
    assert payload["stale"] is False
    assert len(payload["snapshot"]["items"]) == 15
    assert payload["judged_at"]


def test_saving_ranges_marks_dataset_stale_but_keeps_verdicts(
    client: TestClient, auth: dict[str, str], dataset: dict
) -> None:
    """BR-18/BR-20：改完区间**不自动重判**——旧结论留着并标陈旧，否则历史就对不上了。"""
    before = client.get(f"/api/v1/datasets/{dataset['dataset_id']}/stats", headers=auth).json()

    items = _ranges_from(client.get("/api/v1/me/reference-ranges", headers=auth).json()["default"]["items"])
    items["hgb"]["low"] = 125.0
    saved = client.put(
        "/api/v1/me/reference-ranges",
        json={"ranges": items, "note": "按本院检验科 HGB 下限 125 调整"},
        headers=auth,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1

    after = client.get(f"/api/v1/datasets/{dataset['dataset_id']}/stats", headers=auth).json()
    assert after["overview"] == before["overview"], "改区间不应自动重判（BR-18）"

    snapshot = client.get(f"/api/v1/datasets/{dataset['dataset_id']}/ranges-snapshot", headers=auth).json()
    assert snapshot["stale"] is True
    assert snapshot["current"]["source"].startswith("user#v1")
    assert snapshot["snapshot"]["digest"] != snapshot["current"]["digest"]


# --------------------------------------------------------------------------- 重判


def test_rejudge_only_reruns_s6_s7(client: TestClient, auth: dict[str, str], dataset: dict) -> None:
    """BR-19 / 9.2：只重放判定与统计，``sample_index`` 一个都不能动。"""

    def index_column() -> list:
        payload = client.get(
            f"/api/v1/datasets/{dataset['dataset_id']}/preview",
            params={"page": 1, "size": 100},
            headers=auth,
        ).json()
        position = payload["headers"].index("sample_index")
        return [row[position] for row in payload["rows"]]

    before_index = index_column()

    response = client.post(f"/api/v1/datasets/{dataset['dataset_id']}/rejudge", json={}, headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()

    stages = set(body["timings"])
    assert "S6_flag" in stages
    assert "S1_read" not in stages and "S4_clean" not in stages, "重判不得重跑清洗（9.2）"
    assert body["changed"]["comparable"] is True
    assert body["ri_source"].startswith("user#v1")

    assert index_column() == before_index

    snapshot = client.get(f"/api/v1/datasets/{dataset['dataset_id']}/ranges-snapshot", headers=auth).json()
    assert snapshot["stale"] is False
    assert snapshot["snapshot"]["digest"] == snapshot["current"]["digest"]


def test_rejudge_archives_previous_snapshot(client: TestClient, auth: dict[str, str], dataset: dict) -> None:
    """BR-20：旧快照必须归档，不能覆盖——否则"当时为什么这么判"永远说不清。"""
    settings = get_settings()
    history = settings.processed_dir / dataset["dataset_id"] / "history"
    files = sorted(history.glob("ranges.snapshot.*.json")) if history.exists() else []
    assert files, f"没有找到历史快照归档：{history}"


# --------------------------------------------------------------------------- 临时试算


def test_temp_ranges_leave_no_trace(client: TestClient, auth: dict[str, str], dataset: dict) -> None:
    """FR-37 / RK-26：试算只活在这一次图表请求里。"""
    versions_before = client.get("/api/v1/me/reference-ranges/versions", headers=auth).json()["items"]
    snapshot_before = client.get(
        f"/api/v1/datasets/{dataset['dataset_id']}/ranges-snapshot", headers=auth
    ).json()

    response = client.post(
        f"/api/v1/datasets/{dataset['dataset_id']}/charts/box",
        json={"metric": "hgb", "temp_ranges": {"hgb": {"low": 120, "high": 180}}},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ri_effective"]["trial"] is True
    assert body["ri_effective"]["source"].startswith("temp#")
    assert set(body["points"][0]) == {"sample_index", "status", "deviation_pct", "pct"}

    versions_after = client.get("/api/v1/me/reference-ranges/versions", headers=auth).json()["items"]
    assert len(versions_after) == len(versions_before), "试算不得写入版本历史"

    snapshot_after = client.get(f"/api/v1/datasets/{dataset['dataset_id']}/ranges-snapshot", headers=auth).json()
    assert snapshot_after["snapshot"]["digest"] == snapshot_before["snapshot"]["digest"]
    assert snapshot_after["current"]["digest"] == snapshot_before["current"]["digest"]


def test_temp_ranges_reject_bad_bounds(client: TestClient, auth: dict[str, str], dataset: dict) -> None:
    response = client.post(
        f"/api/v1/datasets/{dataset['dataset_id']}/charts/hist",
        json={"metric": "hgb", "temp_ranges": {"hgb": {"low": 180, "high": 120}}},
        headers=auth,
    )
    assert response.status_code == 422
    assert response.json()["code"] == 42201


# --------------------------------------------------------------------------- 重置


def test_reset_returns_to_default(client: TestClient, auth: dict[str, str]) -> None:
    """重置只删自己的版本，**不**写一行"等于默认值"的新记录。"""
    response = client.post("/api/v1/me/reference-ranges/reset", headers=auth)
    assert response.status_code == 200
    state = response.json()["state"]
    assert state["mine"] is None
    assert state["effective"]["source"] == state["default"]["source"]
    assert client.get("/api/v1/me/reference-ranges/versions", headers=auth).json()["items"] == []
