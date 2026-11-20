"""多数据集并排对比的接口级回归（FR-29、BR-13、T-19）。

这里的断言分两类，缺一不可：

1. **数字对不对**：并排表里每个数据集的 n / 中位数，与逐个数据集单独取统计量一致；
2. **不许出现什么**：响应体里不能有任何检验字段或"显著"措辞。

第 2 条比第 1 条重要。并排两个不同来源的数据集，读者天然会想问"这差别是真的吗"，
而系统一旦给了 p 值，就等于替用户做了一次方法上站不住脚的推断——所以干脆不给。
"""

from __future__ import annotations

import io
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import reset_engine

FIXTURES = Path(__file__).parent / "fixtures"
CLEAN_CSV = FIXTURES / "sample_clean.csv"
DIRTY_CSV = FIXTURES / "sample_dirty.csv"

FORBIDDEN_KEYS = {"p_value", "p", "pval", "p_val", "significant", "significance", "t_stat", "u_stat", "effect_size"}
FORBIDDEN_WORDS = ("显著", "统计学意义", "p =", "p 值")


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    base = tmp_path_factory.mktemp("api_compare")
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
        json={"username": "compare_tester", "password": "compare-2026-pass", "password_confirm": "compare-2026-pass"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload(client: TestClient, auth: dict[str, str], path: Path, name: str) -> str:
    response = client.post(
        "/api/v1/datasets",
        files={"file": (name, io.BytesIO(path.read_bytes()), "text/csv")},
        headers=auth,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["dataset"]["dataset_id"]


@pytest.fixture(scope="module")
def two_datasets(client: TestClient, auth: dict[str, str]) -> tuple[str, str]:
    first = _upload(client, auth, CLEAN_CSV, "sample_clean.csv")
    second = _upload(client, auth, DIRTY_CSV, "sample_dirty.csv")
    return first, second


def _compare(client: TestClient, auth: dict[str, str], ids: list[str], metrics: list[str] | None = None) -> Any:
    body: dict[str, Any] = {"dataset_ids": ids}
    if metrics is not None:
        body["metrics"] = metrics
    return client.post("/api/v1/compare/stats", json=body, headers=auth)


def _walk_keys(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from _walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_keys(item)


def test_compare_two_datasets(client: TestClient, auth: dict[str, str], two_datasets: tuple[str, str]) -> None:
    """FR-29：两份数据集并排，每个指标下两列都在。"""
    response = _compare(client, auth, list(two_datasets))
    assert response.status_code == 200, response.text
    payload = response.json()

    assert [item["dataset_id"] for item in payload["datasets"]] == list(two_datasets)
    assert payload["side_by_side"], "至少应有一个可对比指标"
    for row in payload["side_by_side"]:
        assert len(row["cells"]) == 2, "两份数据集各一列"
        assert {cell["dataset_id"] for cell in row["cells"]} == set(two_datasets)
    assert payload["disclaimer"]


def test_compare_numbers_match_single_dataset_stats(
    client: TestClient, auth: dict[str, str], two_datasets: tuple[str, str]
) -> None:
    """并排表里的 n 与中位数，和单独打开数据集得到的值一致。"""
    first, _ = two_datasets
    payload = _compare(client, auth, list(two_datasets), metrics=["hgb"]).json()
    cell = payload["side_by_side"][0]["cells"][0]

    stats = client.get(f"/api/v1/datasets/{first}/stats", headers=auth).json()
    overview = {item["metric"]: item for item in stats["overview"]}["hgb"]

    assert cell["n"] == overview["n"]
    assert cell["median"] == pytest.approx(overview["median"], abs=0.01)
    assert cell["pct_normal"] == pytest.approx(overview["pct_normal"], abs=0.001)


def test_compare_has_no_statistical_fields(
    client: TestClient, auth: dict[str, str], two_datasets: tuple[str, str]
) -> None:
    """BR-13：响应体里不能出现任何检验字段或"显著"措辞。

    ``disclaimer`` 本身要说明"不做检验、不给 p 值"，所以它一定含有"p 值"这三个字；
    检查时把它排除在外，其余每个字段（尤其 cells 与 notes）都不许出现。
    """
    response = _compare(client, auth, list(two_datasets))
    payload = response.json()
    keys = {key.lower() for key in _walk_keys(payload)}
    assert not (keys & FORBIDDEN_KEYS), f"出现了检验字段：{keys & FORBIDDEN_KEYS}"

    body = {key: value for key, value in payload.items() if key != "disclaimer"}
    text = json.dumps(body, ensure_ascii=False)
    for word in FORBIDDEN_WORDS:
        assert word not in text, f"出现了禁用措辞：{word}"


def test_compare_requires_at_least_two(client: TestClient, auth: dict[str, str], two_datasets: tuple[str, str]) -> None:
    response = _compare(client, auth, [two_datasets[0]])
    assert response.status_code == 422, response.text
    assert response.json()["code"] == 42201


def test_compare_rejects_too_many(client: TestClient, auth: dict[str, str], two_datasets: tuple[str, str]) -> None:
    response = _compare(client, auth, [two_datasets[0], two_datasets[1], "x", "y", "z"])
    assert response.status_code == 422, response.text
    assert response.json()["code"] == 42201


def test_compare_foreign_dataset_is_404(
    client: TestClient, auth: dict[str, str], two_datasets: tuple[str, str]
) -> None:
    """别人的/不存在的数据集一律 40401，不用 403 暴露"这个 id 存在"。"""
    response = _compare(client, auth, [two_datasets[0], "0" * 32])
    assert response.status_code == 404, response.text
    assert response.json()["code"] == 40401


def test_compare_unknown_metric_is_rejected(
    client: TestClient, auth: dict[str, str], two_datasets: tuple[str, str]
) -> None:
    response = _compare(client, auth, list(two_datasets), metrics=["no_such_metric"])
    assert response.status_code == 422, response.text
    assert response.json()["code"] == 42201


def test_compare_silently_skips_metric_nobody_has(
    client: TestClient, auth: dict[str, str], two_datasets: tuple[str, str]
) -> None:
    """两份数据都没有 rdw 时，既不出一行空表，也不刷 2 条"缺列"提示。

    这是刻意的：15 个指标 × 2 份数据，如果每个缺席都报一条，页面上会出现十几条
    "该数据集没有这一列"，把真正的缺列（一份有一份没有）埋掉。
    """
    response = _compare(client, auth, list(two_datasets), metrics=["rdw"])
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["side_by_side"] == []
    assert payload["excluded"] == []


def test_compare_reports_one_sided_missing_column(
    client: TestClient, auth: dict[str, str], two_datasets: tuple[str, str], tmp_path: Path
) -> None:
    """一份有 rdw、一份没有时，缺的那份进 excluded 并说明原因（不补 0）。"""
    base = CLEAN_CSV.read_text(encoding="utf-8-sig").splitlines()
    header = base[0] + ",rdw"
    rows = [header] + [f"{line},13.2" for line in base[1:]]
    enriched = tmp_path / "sample_with_rdw.csv"
    enriched.write_text("\n".join(rows) + "\n", encoding="utf-8-sig")
    with_rdw = _upload(client, auth, enriched, "sample_with_rdw.csv")

    response = _compare(client, auth, [with_rdw, two_datasets[0]], metrics=["rdw"])
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["side_by_side"] == [], "只有一份有该指标，不该硬凑成一行"
    reasons = {(item["dataset_id"], item["metric"]) for item in payload["excluded"]}
    assert reasons == {(two_datasets[0], "rdw")}
    assert payload["excluded"][0]["reason"]


def test_compare_notes_when_ranges_differ(
    client: TestClient, auth: dict[str, str], two_datasets: tuple[str, str]
) -> None:
    """口径一致时要明说"可以横向对照"，口径不一致时要明说"不可直接比"。"""
    payload = _compare(client, auth, list(two_datasets)).json()
    assert payload["notes"], "必须给出一句口径说明"
    joined = json.dumps(payload["notes"], ensure_ascii=False)
    assert ("相同" in joined) or ("不同" in joined)
