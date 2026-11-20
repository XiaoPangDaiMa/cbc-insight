"""报告与图表导出测试（FR-20 / FR-21、4.3.4、T-13 的导出分支）。

不 mock 数据库，不起 Docker：临时 sqlite + 临时数据目录，与 ``test_api_flow`` 同一套路。

报告是这个项目唯一"能拿出去给人看"的产物，所以断言盯三件事：
* 必须真的内嵌图片（base64），否则拷到 U 盘就缺图；
* 必须含免责声明（1.3 范围外：不做诊断）；
* 不许出现"显著"——报告的图注复用同一套模板，退化规则要一并生效（BR-16）。
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

#: 没有 gender 列的数据集：性别相关三指标必须降级为"未按性别分组"，且报告照常生成。
NO_GENDER_CSV = """age,hemoglobin,white_blood_cells,red_blood_cells,platelet_count,mcv,mch,mchc
31,148,6.2,4.9,240,90,30,330
42,132,7.1,4.6,301,88,29,318
55,121,5.4,4.2,188,86,28,322
27,160,8.3,5.4,265,92,31,335
63,110,4.9,3.9,150,84,27,310
38,145,6.8,5.0,278,89,30,326
49,138,7.6,4.7,255,91,29,320
24,152,6.0,5.2,295,93,30,332
"""


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    base = tmp_path_factory.mktemp("report")
    env = {
        "CBC_DATABASE_URL": f"sqlite:///{(base / 'test.db').as_posix()}",
        "CBC_DATA_DIR": str(base / "data"),
    }
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    get_settings.cache_clear()
    reset_engine()

    from app.main import create_app

    try:
        with TestClient(create_app()) as test_client:
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
        json={"username": "report_tester", "password": "report-2026", "password_confirm": "report-2026"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload(client: TestClient, auth: dict[str, str], name: str, content: bytes) -> dict:
    response = client.post(
        "/api/v1/datasets",
        files={"file": (name, io.BytesIO(content), "text/csv")},
        headers=auth,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


@pytest.fixture(scope="module")
def dataset(client: TestClient, auth: dict[str, str]) -> dict:
    return _upload(client, auth, "sample_clean.csv", CSV_PATH.read_bytes())["dataset"]


@pytest.fixture(scope="module")
def genderless(client: TestClient, auth: dict[str, str]) -> dict:
    return _upload(client, auth, "no_gender.csv", NO_GENDER_CSV.encode("utf-8"))["dataset"]


def test_report_is_generated(client: TestClient, auth: dict[str, str], dataset: dict) -> None:
    response = client.post(f"/api/v1/datasets/{dataset['dataset_id']}/report", headers=auth)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["size"] > 5000
    assert body["report_url"].endswith("/report.html")

    settings = get_settings()
    path = Path(settings.reports_dir) / f"{dataset['dataset_id']}.html"
    assert path.is_file(), "报告没有落盘"


def test_report_contains_images_and_disclaimer(client: TestClient, auth: dict[str, str], dataset: dict) -> None:
    response = client.get(f"/api/v1/datasets/{dataset['dataset_id']}/report.html", headers=auth)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    text = response.text

    assert text.count("data:image/png;base64,") >= 2, "报告里的图必须 base64 内嵌"
    assert "免责声明" in text
    assert "不能替代执业医师" in text
    assert "显著" not in text, "报告图注不得出现'显著'（BR-16）"
    # 图与屏幕同一句话：报告里的图注必须来自同一套模板
    assert "参考区间" in text


def test_report_includes_quality_figure(client: TestClient, auth: dict[str, str], dataset: dict) -> None:
    """FR-13 的报告版：完整率 / DQ / 剔除原因三块必须进报告。

    这条用例守的是"报告与页面各算一遍"这个经典退化路径：质量图的数字只能来自
    落库的 quality 与 clean_report，页面上是什么，报告里就得是什么。
    """
    response = client.get(f"/api/v1/datasets/{dataset['dataset_id']}/report.html", headers=auth)
    assert response.status_code == 200, response.text
    text = response.text

    assert "数据质量图" in text, "报告里没有质量图这一节"
    # 三块图的标题画在图里（位图），HTML 里只留图注，所以这里断言图注措辞
    assert "各字段完整率" in text and "DQ-01~06" in text and "剔除的原因分布" in text
    # 三张临床图 + 一张质量图；少一张就说明某个分支被悄悄跳过了
    assert text.count("data:image/png;base64,") >= 4


def test_report_without_gender_still_renders(
    client: TestClient, auth: dict[str, str], genderless: dict
) -> None:
    response = client.get(f"/api/v1/datasets/{genderless['dataset_id']}/report.html", headers=auth)
    assert response.status_code == 200, response.text
    assert "data:image/png;base64," in response.text


def test_chart_image_png(client: TestClient, auth: dict[str, str], dataset: dict) -> None:
    response = client.get(
        f"/api/v1/datasets/{dataset['dataset_id']}/charts/box/image",
        params={"metric": "hgb", "fmt": "png"},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert "filename*=UTF-8''" in response.headers["content-disposition"]


def test_chart_image_svg(client: TestClient, auth: dict[str, str], dataset: dict) -> None:
    response = client.get(
        f"/api/v1/datasets/{dataset['dataset_id']}/charts/corr/image",
        params={"fmt": "svg"},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in response.content[:2000]


def test_chart_image_unknown_kind(client: TestClient, auth: dict[str, str], dataset: dict) -> None:
    response = client.get(
        f"/api/v1/datasets/{dataset['dataset_id']}/charts/pie/image",
        headers=auth,
    )
    assert response.status_code == 422
    assert response.json()["code"] == 42201


def test_reports_require_auth(client: TestClient, dataset: dict) -> None:
    response = client.post(f"/api/v1/datasets/{dataset['dataset_id']}/report")
    assert response.status_code == 401
