"""BR-06 脏数据与异常分离（本项目最核心的规则，T-03 / T-04 长期回归）。"""

from __future__ import annotations


def test_outlier_999_is_treated_as_dirty_not_abnormal(pipeline, dirty_csv):
    """T-03：hgb = 999 校验报错、清洗后置空，**不进入异常清单**。"""
    result = pipeline(dirty_csv)

    assert not (result.frame["hgb"] == 999).any()
    codes = {issue.code for issue in result.report.issues if issue.field == "hgb"}
    assert "DQ-03" in codes

    row = result.long[(result.long["sample_index"] == 1) & (result.long["metric"] == "hgb")].iloc[0]
    assert row["value"] != 999
    assert row["status"] == "NORMAL"


def test_real_case_85_is_kept_and_flagged(pipeline, dirty_csv):
    """T-04：hgb = 85（男）→ 保留该行，判定 LOW，进入异常清单。"""
    result = pipeline(dirty_csv)

    kept = result.frame[result.frame["hgb"] == 85]
    assert len(kept) == 1

    row = result.long[(result.long["metric"] == "hgb") & (result.long["value"] == 85)].iloc[0]
    assert row["status"] == "LOW"

    sample = result.summary[result.summary["sample_index"] == int(row["sample_index"])].iloc[0]
    assert "hgb" in sample["abnormal_metrics"].split("|")


def test_dirty_rows_never_enter_abnormal_list(pipeline, dirty_csv):
    """异常清单里的取值必须全部落在 3.3 值域内——脏值不可能"漏"进异常统计。"""
    result = pipeline(dirty_csv)
    flagged = result.long[result.long["status"].isin(["HIGH", "LOW"])]
    assert (flagged["value"] <= 250).all(), "hgb 值域上限 250，超出说明脏值进了判定"
    assert (flagged["value"] > 0).all()


def test_dirty_and_clean_paths_are_recorded(pipeline, dirty_csv):
    result = pipeline(dirty_csv)
    reasons = result.cleaned.removed_by_reason
    assert reasons.get("duplicate") == 1
    assert reasons.get("core_all_null") == 1
    assert len(result.frame) == 5
