"""S8 图注（SRS FR-32、BR-16）。

一句话结论 = 模板 + 槽位填充。**分支选择写在代码里，文案写在 YAML 里**：

* 代码负责"这个前提成不成立"（n 够不够、p 是否显著、|rho| 是否太弱、有没有性别）；
* YAML 负责"成立时怎么说"，便于逐字审校。

这样做的理由是 BR-16 的四条退化规则必须能被测试钉死：只要分支判断进了代码，
``test_captions.py`` 就能针对每条分支断言"响应里没有 p 值、没有'显著'"。

**红线**：本模块任何输出都不得含 4.4.6 的禁用词。出现即抛 :class:`ForbiddenWordError`，
宁可让接口 500，也不能让系统批量生产"疑似某某病"的结论。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

TEMPLATES_PATH = Path(__file__).resolve().parents[2] / "resources" / "caption_templates.yaml"

#: 出图所需的最小有效样本量（4.3 约定：n < 5 不出图）
MIN_PLOT_N = 5
#: 组间检验所需的最小分组样本量（BR-11）
MIN_GROUP_N = 10
#: |rho| 低于此值不作解读（BR-10）
WEAK_RHO = 0.3
#: 显著性水平（BR-16）
ALPHA = 0.05


class ForbiddenWordError(RuntimeError):
    """文案里出现了 4.4.6 禁用词——属于实现缺陷，不是数据问题。"""


@dataclass(frozen=True)
class Caption:
    text: str
    branch: str
    template: str
    supporting: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {"text": self.text, "branch": self.branch, "supporting": dict(self.supporting)}


_cache: tuple[float, dict[str, Any]] | None = None


def load_templates(path: Path | None = None) -> dict[str, Any]:
    """读取模板（按 mtime 缓存，便于改文案后免重启）。"""
    global _cache
    target = Path(path) if path else TEMPLATES_PATH
    mtime = target.stat().st_mtime
    if _cache and _cache[0] == mtime and path is None:
        return _cache[1]
    with target.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    forbidden = tuple(data.get("forbidden_words", ()))
    data["_forbidden"] = forbidden
    if path is None:
        _cache = (mtime, data)
    return data


def fmt(value: float | None, decimals: int = 2) -> str:
    """按指标小数位格式化；去掉无意义的尾零，缺失记为 ``—``（4.4.6）。"""
    if value is None:
        return "—"
    text = f"{float(value):.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def fmt_p(value: float | None) -> str:
    """p 值格式化：小于 0.001 时不写 ``0.000``（那会被读成"p 等于 0"）。"""
    if value is None:
        return "—"
    p = float(value)
    if p < 0.001:
        return "< 0.001"
    return fmt(p, 3)


def guard(text: str, templates: Mapping[str, Any] | None = None) -> str:
    """扫描禁用词；命中即抛异常（BR-16 的实现底线）。"""
    words = (templates or load_templates()).get("_forbidden", ())
    hit = [w for w in words if w in text]
    if hit:
        raise ForbiddenWordError(f"图注含禁用词 {hit}: {text}")
    return text


def render(templates: Mapping[str, Any], group: str, branch: str, **slots: Any) -> tuple[str, str]:
    template = templates[group][branch]
    return template.format(**slots), template


# --------------------------------------------------------------------------- box


def caption_box(
    *,
    metric_cn: str,
    unit: str,
    groups: Mapping[str, Mapping[str, Any]],
    comparison: Mapping[str, Any] | None = None,
    decimals: int = 2,
    unit_note: str = "",
    unified_bands: tuple[float, float] | None = None,
    templates: Mapping[str, Any] | None = None,
) -> Caption:
    """箱线图结论。

    ``groups`` 形如 ``{"male": {"n": 120, "mean": 152.3}, "female": {...}}``；
    数据没有性别列时传 ``{"all": {...}}``（只画一组）。
    ``comparison`` 是 :func:`app.pipeline.stats.compare_groups` 的原样输出。
    ``unified_bands`` 仅用于"无性别 + 用户显式按统一区间判定"（FR-16）：给出
    ``(low, high)``，句式改为统一区间口径，绝不说"按性别各自判定"。
    """
    tpl = templates or load_templates()

    # 单组模式（数据没有性别列）
    single = groups.get("all") or {}
    if single:
        total = int(single.get("n") or 0)
        if total < MIN_PLOT_N:
            text, template = render(tpl, "box", "no_data", n=total)
            return Caption(guard(text, tpl), "no_data", template, {"n": total})
        if unified_bands:
            low, high = unified_bands
            text, template = render(
                tpl,
                "box",
                "unified",
                cn=metric_cn,
                median=fmt(single.get("median"), decimals),
                unit=unit,
                low=fmt(low, decimals),
                high=fmt(high, decimals),
                n=total,
            )
            return Caption(
                guard(text + unit_note, tpl),
                "unified",
                template,
                {"n": total, "low": low, "high": high, "ri_source": "unified"},
            )
        text, template = render(
            tpl,
            "box",
            "no_gender",
            cn=metric_cn,
            median=fmt(single.get("median"), decimals),
            unit=unit,
            n=total,
        )
        return Caption(guard(text + unit_note, tpl), "no_gender", template, {"n": total})

    male = groups.get("male") or {}
    female = groups.get("female") or {}
    n_male = int(male.get("n") or 0)
    n_female = int(female.get("n") or 0)
    total = n_male + n_female

    if total < MIN_PLOT_N:
        text, template = render(tpl, "box", "no_data", n=total)
        return Caption(guard(text, tpl), "no_data", template, {"n": total})

    if not n_male or not n_female:
        # BR-17：没有性别就没有"男女"这两个词，改用总体中位数
        merged = male if n_male else female
        text, template = render(
            tpl,
            "box",
            "no_gender",
            cn=metric_cn,
            median=fmt(merged.get("median"), decimals),
            unit=unit,
            n=total,
        )
        return Caption(guard(text, tpl), "no_gender", template, {"n": total})

    mean_m = float(male.get("mean") or 0.0)
    mean_f = float(female.get("mean") or 0.0)
    abs_diff = abs(mean_f - mean_m)
    dir_word = "高" if mean_f > mean_m else "低"

    comparison = comparison or {}
    performed = bool(comparison.get("performed"))
    # compare_groups 的字段名是 ``p``；早期图表侧写的是 ``p_value``，这里两种都认，
    # 否则会出现"检验做了、却有 p 值不显示写成 —"的假文案（B1 真实数据体检发现）
    p_value = comparison.get("p_value", comparison.get("p"))

    if min(n_male, n_female) < MIN_GROUP_N or not performed:
        small_group, n_small = ("男性", n_male) if n_male <= n_female else ("女性", n_female)
        text, template = render(
            tpl,
            "box",
            "small_n",
            small_group=small_group,
            n_small=n_small,
            cn=metric_cn,
            male_mean=fmt(mean_m, decimals),
            female_mean=fmt(mean_f, decimals),
            unit=unit,
        )
        return Caption(
            guard(text + unit_note, tpl),
            "small_n",
            template,
            {"n_male": n_male, "n_female": n_female, "p_value": None},
        )

    if p_value is not None and float(p_value) >= ALPHA:
        text, template = render(
            tpl,
            "box",
            "grouped_ns",
            cn=metric_cn,
            male_mean=fmt(mean_m, decimals),
            female_mean=fmt(mean_f, decimals),
            unit=unit,
            n_male=n_male,
            n_female=n_female,
            p_text=fmt_p(p_value),
        )
        return Caption(
            guard(text + unit_note, tpl),
            "grouped_ns",
            template,
            {"n_male": n_male, "n_female": n_female, "p_value": float(p_value)},
        )

    text, template = render(
        tpl,
        "box",
        "grouped",
        cn=metric_cn,
        female_mean=fmt(mean_f, decimals),
        male_mean=fmt(mean_m, decimals),
        dir_word=dir_word,
        abs_diff=fmt(abs_diff, decimals),
        unit=unit,
        n_male=n_male,
        n_female=n_female,
        p_text=fmt_p(p_value),
    )
    return Caption(
        guard(text + unit_note, tpl),
        "grouped",
        template,
        {"n_male": n_male, "n_female": n_female, "p_value": p_value},
    )


# -------------------------------------------------------------------------- hist


def caption_hist(
    *,
    metric_cn: str,
    unit: str,
    n: int,
    median: float | None,
    low: float | None,
    high: float | None,
    pct_normal: float | None,
    decimals: int = 2,
    unit_note: str = "",
    bands_text: str = "",
    unified: bool = False,
    templates: Mapping[str, Any] | None = None,
) -> Caption:
    tpl = templates or load_templates()
    if n <= 0:
        text, template = render(tpl, "hist", "no_data", cn=metric_cn)
        return Caption(guard(text, tpl), "no_data", template, {"n": 0})
    if n < MIN_PLOT_N:
        text, template = render(tpl, "hist", "small_n", n=n)
        return Caption(guard(text, tpl), "small_n", template, {"n": n})

    pct = 100.0 * float(pct_normal or 0.0)
    if unified:
        # 无性别 + 用户显式按统一区间判定：句式必须说明"统一区间"，不得写成"按性别各自"
        text, template = render(
            tpl,
            "hist",
            "unified",
            cn=metric_cn,
            median=fmt(median, decimals),
            unit=unit,
            pct_normal=fmt(pct, 1),
            low=fmt(low, decimals),
            high=fmt(high, decimals),
            n=n,
        )
        return Caption(
            guard(text + unit_note, tpl),
            "unified",
            template,
            {"n": n, "pct_normal": round(pct, 2), "low": low, "high": high, "ri_source": "unified"},
        )
    if bands_text:
        # 性别相关指标：不能拿一条区间套所有人，句式必须换（BR-17）
        text, template = render(
            tpl,
            "hist",
            "main_gender",
            cn=metric_cn,
            median=fmt(median, decimals),
            unit=unit,
            pct_normal=fmt(pct, 1),
            bands=bands_text,
            n=n,
        )
        return Caption(
            guard(text + unit_note, tpl),
            "main_gender",
            template,
            {"n": n, "pct_normal": round(pct, 2), "bands": bands_text},
        )
    text, template = render(
        tpl,
        "hist",
        "main",
        cn=metric_cn,
        median=fmt(median, decimals),
        unit=unit,
        pct_normal=fmt(pct, 1),
        low=fmt(low, decimals),
        high=fmt(high, decimals),
        n=n,
    )
    return Caption(
        guard(text + unit_note, tpl),
        "main",
        template,
        {"n": n, "pct_normal": round(pct, 2), "low": low, "high": high},
    )


# -------------------------------------------------------------------------- corr


def caption_corr(
    *,
    a: str,
    b: str,
    rho: float | None,
    n: int,
    coupling: bool = False,
    label_a: str | None = None,
    label_b: str | None = None,
    templates: Mapping[str, Any] | None = None,
) -> Caption:
    """相关性图注。``coupling`` 为真时必须说明"数学耦合，非独立发现"（BR-12）。"""
    tpl = templates or load_templates()
    name_a = label_a or a
    name_b = label_b or b
    if n < 2 or rho is None:
        text, template = render(tpl, "corr", "insufficient", n=n)
        return Caption(guard(text, tpl), "insufficient", template, {"n": n})

    branch = "coupled" if coupling else ("weak" if abs(float(rho)) < WEAK_RHO else "strong")
    slots: dict[str, Any] = {"a": name_a, "b": name_b, "rho": fmt(rho, 2), "n": n}
    text, template = render(tpl, "corr", branch, **slots)
    return Caption(guard(text, tpl), branch, template, {"n": n, "rho": float(rho)})


# ------------------------------------------------------------------------ health


def caption_health(
    *,
    rows: int,
    duplicate_rows: int = 0,
    nulled_cells: int = 0,
    unit_note: str = "",
    templates: Mapping[str, Any] | None = None,
) -> Caption:
    """上传后的"数据健康度"摘要（4.2.0 约定 2）。"""
    tpl = templates or load_templates()
    if not duplicate_rows and not nulled_cells:
        text, template = render(tpl, "health_summary", "no_issues", n=rows)
        return Caption(guard(text, tpl), "no_issues", template, {"rows": rows})

    text, template = render(
        tpl,
        "health_summary",
        "with_issues",
        n=rows,
        dup=duplicate_rows,
        nulled=nulled_cells,
        unit_note=unit_note,
    )
    return Caption(
        guard(text, tpl),
        "with_issues",
        template,
        {"rows": rows, "duplicate_rows": duplicate_rows, "nulled_cells": nulled_cells},
    )


def unit_note_for(metric: str, original_unit: str, target_unit: str, factor: float) -> str:
    """单位归一提示，挂在图注尾部（BR-02 留痕要求在界面上可见）。"""
    if not original_unit or factor == 1.0:
        return ""
    return f"；{metric} 原单位 {original_unit} 已按 ×{fmt(factor, 4)} 归一为 {target_unit}"
