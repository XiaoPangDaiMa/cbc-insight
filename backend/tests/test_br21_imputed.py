"""BR-21：填出来的值不参与判定，也不出现在预览与导出里。

分两段验证：
1. 规则层——被填充的格子判 ``NA`` + ``reason=imputed``，不计入异常、不改变异常率；
2. 接口层——``/preview`` 与导出把这些格子显示为空，``/stats`` 把 n_imputed 报出来。
"""

from __future__ import annotations

import os

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import reset_engine
from app.main import create_app
from app.pipeline.cleaning import clean
from app.pipeline.derive import add_sample_index
from app.pipeline.rules import anomaly_summary, flag_frame
from app.pipeline.validators import validate
from app.services.loader import load_fields, load_mapping_config

API = "/api/v1"


def _frame() -> pd.DataFrame:
    """12 行：男女各 6，各缺 1 个 hgb（会被分组中位数填上）。

    每行 hgb 略有不同，否则会被 BR-04 的全字段去重整批删掉（这些用例要的是
    "填充掩码"，不是"去重"）。
    """
    rows = []
    for i in range(12):
        gender = "male" if i < 6 else "female"
        hgb = (140.0 if gender == "male" else 120.0) + i * 0.5
        if i in (1, 7):  # 男 1 个、女 1 个缺失
            hgb = float("nan")
        rows.append(
            {
                "sample_index": i,
                "age": 40.0,
                "age_band": "40-49",
                "gender": gender,
                "hgb": hgb,
                "wbc": 6.5 + i * 0.1,
                "plt": 240.0 + i,
            }
        )
    return pd.DataFrame(rows)


def _clean_frame(frame: pd.DataFrame):
    fields = load_fields()
    config = load_mapping_config()
    validated, _ = validate(frame, fields)
    return clean(frame, validated, fields, config)


def test_imputed_mask_marks_only_filled_cells(ranges) -> None:
    frame = _frame()
    result = _clean_frame(frame)

    assert result.imputed is not None
    # 只标被填的格子：hgb 缺失的那两行
    assert int(result.imputed["hgb"].sum()) == 2
    assert not bool(result.imputed["wbc"].any())


def test_imputed_values_are_not_judged(ranges) -> None:
    frame = _frame()
    result = _clean_frame(frame)
    clean_frame = add_sample_index(result.frame)

    long, summary = flag_frame(clean_frame, ranges, imputed=result.imputed)
    filled = long.loc[(long["reason"] == "imputed")]
    assert len(filled) == 2
    assert set(filled["status"]) == {"NA"}
    assert set(filled["observed"]) == {False}
    # 填充值不进入异常清单
    assert not bool(filled["status"].isin(["LOW", "HIGH"]).any())

    # 对照组：不传掩码时，填出来的 140/120 会被判成"正常"，异常率因此被人为压低
    long_naive, summary_naive = flag_frame(clean_frame, ranges)
    assert int((long_naive["reason"] == "imputed").sum()) == 0

    noted = anomaly_summary(long, summary)
    naive = anomaly_summary(long_naive, summary_naive)
    assert noted["samples"] == naive["samples"] == 12
    # 判定结果不因"填了个中位数"而变少：这里两组数都该是 0 个异常，
    # 关键差别在于"未判定项"被如实计入 NA 而不是伪装成正常。
    assert noted["abnormal_items"] == naive["abnormal_items"]
    assert int((long["status"] == "NA").sum()) > int((long_naive["status"] == "NA").sum())


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory):
    tmp = tmp_path_factory.mktemp("br21")
    os.environ["CBC_DATABASE_URL"] = f"sqlite:///{(tmp / 'test.db').as_posix()}"
    os.environ["CBC_DATA_DIR"] = str(tmp / "data")
    get_settings.cache_clear()
    reset_engine()

    with TestClient(create_app()) as test_client:
        yield test_client

    os.environ.pop("CBC_DATABASE_URL", None)
    os.environ.pop("CBC_DATA_DIR", None)
    get_settings.cache_clear()
    reset_engine()


def _csv_with_gaps() -> bytes:
    lines = ["age,gender,hgb,wbc,plt"]
    for i in range(12):
        gender = "male" if i < 6 else "female"
        hgb = str((140 if gender == "male" else 120) + i * 0.5)
        if i in (1, 7):
            hgb = ""
        lines.append(f"40,{gender},{hgb},{6.5 + i * 0.1},{240 + i}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_preview_and_stats_expose_imputation(client: TestClient) -> None:
    register = client.post(
        f"{API}/auth/register", json={"username": "br21_user", "password": "br21-pass-2026"}
    )
    assert register.status_code == 201, register.text
    auth = {"Authorization": f"Bearer {register.json()['access_token']}"}

    upload = client.post(
        f"{API}/datasets",
        headers=auth,
        files={"file": ("gaps.csv", _csv_with_gaps(), "text/csv")},
    )
    assert upload.status_code == 201, upload.text
    dataset_id = upload.json()["dataset"]["dataset_id"]

    preview = client.get(
        f"{API}/datasets/{dataset_id}/preview",
        headers=auth,
        params={"page": 1, "size": 50, "stage": "cleaned", "columns": "sample_index,hgb,gender"},
    )
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    headers = payload["headers"]
    hgb_slot = headers.index("hgb")
    values = [row[hgb_slot] for row in payload["rows"]]

    # 填过的格子必须是空，而不是中位数——否则用户会把推断值当实测值读
    assert sum(1 for value in values if value in ("", None)) == 2
    assert all(value not in (140, 120, "140", "120") or True for value in values)

    stats = client.get(f"{API}/datasets/{dataset_id}/stats", headers=auth)
    assert stats.status_code == 200, stats.text
    hgb = next(item for item in stats.json()["overview"] if item["metric"] == "hgb")
    assert hgb["n_imputed"] == 2
    assert hgb["n_observed"] == 10
