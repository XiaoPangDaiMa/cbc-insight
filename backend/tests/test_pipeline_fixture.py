"""S1–S6 端到端管线：10 行夹具的答案写死在这里（T-01 的离线版本）。

夹具答案：原始 10 行 → 去重 1 行 + 核心字段全空 1 行 → **n = 8**；
其中 **5 个样本异常**，异常项合计 **16 个**。改动夹具必须同步改本文件。
"""

from __future__ import annotations

import pytest


def test_fixture_shape(pipeline, clean_csv):
    result = pipeline(clean_csv)
    assert result.read.rows == 10
    assert result.read.n_columns == 11
    assert len(result.frame) == 8
    assert list(result.frame["sample_index"]) == list(range(8))


def test_all_nine_metrics_are_mapped(pipeline, clean_csv):
    result = pipeline(clean_csv)
    mapped = set(result.mapping.mapping.values())
    expected = {"age", "gender", "wbc", "rbc", "hgb", "hct", "mcv", "mch", "mchc", "plt", "neut_pct"}
    assert expected <= mapped
    assert result.mapping.needs_confirmation is False


def test_abnormal_item_and_sample_counts(pipeline, clean_csv):
    result = pipeline(clean_csv)
    flagged = result.long[result.long["status"].isin(["HIGH", "LOW"])]
    assert len(flagged) == 16
    assert int((result.summary["n_abnormal"] > 0).sum()) == 5


def test_pattern_distribution(pipeline, clean_csv):
    result = pipeline(clean_csv)
    counts = result.summary["pattern"].value_counts().to_dict()
    assert counts.get("NORMAL") == 3
    assert counts.get("MICRO") == 1  # S2：MCV↓ + MCHC 正常
    assert counts.get("POLYCYTHEMIA_SUSPECT") == 1  # S3：HGB↑ + RBC↑
    assert counts.get("THROMBOCYTOPENIA") == 1  # S4：PLT↓
    assert counts.get("MACRO") == 1  # S5：MCV↑
    assert counts.get("THROMBOCYTOSIS") == 1  # S6：PLT↑（WBC↑+NEUT↑ 同时命中 LEUKOCYTOSIS）


def test_severity_ordering_is_stable(pipeline, clean_csv):
    result = pipeline(clean_csv)
    ordered = result.summary.sort_values("severity", ascending=False)
    assert ordered["severity"].is_monotonic_decreasing
    assert ordered.iloc[0]["severity"] > 0


def test_quality_report_has_all_six_dq_metrics(pipeline, clean_csv):
    result = pipeline(clean_csv)
    dq = result.report.dq
    assert set(dq) == {"DQ-01", "DQ-02", "DQ-03", "DQ-04", "DQ-05", "DQ-06"}
    assert dq["DQ-02"] == pytest.approx(0.9)  # 10 行里 1 行重复
    assert dq["DQ-03"] == 1.0  # 夹具数值全部落在值域内
    assert dq["DQ-05"] == 1.0  # HCT 与 RBC×MCV/10 全部一致
    assert dq["DQ-06"] is None  # 异常率由 S6 之后计算


def test_cleaning_is_reported_before_and_after(pipeline, clean_csv):
    result = pipeline(clean_csv)
    payload = result.cleaned.to_payload()
    assert payload["before"]["rows"] == 10
    assert payload["after"]["rows"] == 8
    assert payload["removed_by_reason"] == {"duplicate": 1, "core_all_null": 1}
    assert payload["log"]


def test_units_are_already_normalized_in_fixture(pipeline, clean_csv):
    result = pipeline(clean_csv)
    assert all(decision.factor == 1.0 for decision in result.decisions)
    assert all(not decision.ambiguous for decision in result.decisions)
