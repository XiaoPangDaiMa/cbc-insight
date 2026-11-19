"""FR-32 / BR-16 图注：四条退化规则必须被测试钉死。

这些用例守护的是"系统不许批量生产错误结论"——比某张图好不好看重要得多：
n < 10 不得给 p 值、p >= 0.05 不得说"显著"、|rho| < 0.3 不得解读、缺性别不得谈男女。
"""

from __future__ import annotations

import pytest

from app.pipeline.captions import (
    ForbiddenWordError,
    caption_box,
    caption_corr,
    caption_health,
    caption_hist,
    fmt,
    guard,
    load_templates,
    unit_note_for,
)

MALE = {"n": 120, "mean": 152.34, "median": 151.0}
FEMALE = {"n": 130, "mean": 131.02, "median": 130.0}


def _box(**kwargs):
    params = {
        "metric_cn": "血红蛋白",
        "unit": "g/L",
        "groups": {"male": MALE, "female": FEMALE},
        "comparison": {"performed": True, "p_value": 0.004},
    }
    params.update(kwargs)
    return caption_box(**params)


def test_grouped_caption_reports_p_and_group_sizes():
    caption = _box()
    assert caption.branch == "grouped"
    assert "p = 0.004" in caption.text
    assert "男 n=120" in caption.text and "女 n=130" in caption.text
    assert "比男性低" in caption.text  # 女性均值 131.02 < 男性 152.34
    assert "显著" not in caption.text


def test_small_n_branch_has_no_p_value():
    caption = _box(groups={"male": {"n": 7, "mean": 150.0, "median": 150.0}, "female": FEMALE})
    assert caption.branch == "small_n"
    assert "n = 7" in caption.text
    assert "p =" not in caption.text
    assert caption.supporting["p_value"] is None


def test_non_significant_branch_never_says_significant():
    caption = _box(comparison={"performed": True, "p_value": 0.31})
    assert caption.branch == "grouped_ns"
    assert "差异无统计学意义" in caption.text
    assert "p = 0.31" in caption.text
    assert "显著" not in caption.text


def test_no_gender_branch_never_mentions_sex():
    caption = _box(
        groups={
            "male": {"n": 0, "mean": None, "median": None},
            "female": {"n": 40, "mean": 130.0, "median": 130.0},
        }
    )
    assert caption.branch == "no_gender"
    assert "男" not in caption.text and "女" not in caption.text
    assert "未按性别分组" in caption.text


def test_box_with_too_few_samples_does_not_plot():
    caption = _box(groups={"male": {"n": 2, "mean": 150.0}, "female": {"n": 1, "mean": 130.0}})
    assert caption.branch == "no_data"
    assert "未出图" in caption.text


def test_histogram_caption_reports_share_inside_range():
    caption = caption_hist(
        metric_cn="血红蛋白", unit="g/L", n=250, median=140.0, low=130, high=175, pct_normal=0.812
    )
    assert caption.branch == "main"
    assert "81.2%" in caption.text and "130–175" in caption.text
    assert caption.supporting["n"] == 250


def test_histogram_caption_small_n():
    caption = caption_hist(metric_cn="血红蛋白", unit="g/L", n=3, median=140.0, low=130, high=175, pct_normal=1.0)
    assert caption.branch == "small_n"


def test_correlation_coupling_is_labelled_as_math_not_discovery():
    caption = caption_corr(a="mch", b="hgb", rho=0.93, n=400, coupling=True)
    assert caption.branch == "coupled"
    assert "数学耦合" in caption.text and "非独立发现" in caption.text


def test_weak_correlation_is_not_interpreted():
    caption = caption_corr(a="wbc", b="hgb", rho=0.12, n=400)
    assert caption.branch == "weak"
    assert "不作解读" in caption.text


def test_strong_correlation_without_coupling():
    caption = caption_corr(a="rbc", b="hgb", rho=0.71, n=400)
    assert caption.branch == "strong"
    assert "ρ = 0.71" in caption.text


def test_guard_rejects_forbidden_words():
    with pytest.raises(ForbiddenWordError):
        guard("该样本疑似疾病，建议复查")


def test_health_summary_mentions_dropped_rows():
    with_issues = caption_health(rows=12000, duplicate_rows=3, nulled_cells=12)
    assert with_issues.branch == "with_issues"
    assert "剔除 3 行重复" in with_issues.text and "12 个越界值" in with_issues.text

    clean = caption_health(rows=12000)
    assert clean.branch == "no_issues"
    assert "未发现需要处理的脏数据" in clean.text


def test_unit_note_is_visible_and_silent_when_factor_is_one():
    note = unit_note_for("hgb", "g/dL", "g/L", 10.0)
    assert "g/dL" in note and "×10" in note
    assert unit_note_for("hgb", "g/L", "g/L", 1.0) == ""


def test_fmt_trims_trailing_zeros():
    assert fmt(152.30, 2) == "152.3"
    assert fmt(152.0, 2) == "152"
    assert fmt(None) == "—"


def test_templates_declare_forbidden_words():
    templates = load_templates()
    assert "显著" in templates["_forbidden"]
    for group in ("box", "hist", "corr"):
        for branch, template in templates[group].items():
            assert template.strip(), f"{group}.{branch} 模板为空"
