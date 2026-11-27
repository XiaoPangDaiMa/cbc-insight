"""单文件 HTML 报告（FR-21）+ 报告内嵌图表（FR-20、4.3.4）。

报告是"能交出去的东西"：答辩当场打开一个文件就能看，不需要后端在跑、不需要浏览器
插件、图片以 base64 内嵌（拷到 U 盘也不会丢图）。

三条约束：
* 图与文字必须来自**同一次计算**（图注 = 屏幕上那句话，不能另写一份）；
* 颜色全部来自 ``theme.json``（与屏幕一致，RK-22）；
* 只输出"与参考区间比较"的结果，不出现任何疾病名称（1.3 范围外）。
"""

from __future__ import annotations

import base64
import html
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import Settings, get_settings
from app.pipeline import captions as caption_mod
from app.pipeline import stats as stats_mod
from app.services import chart as chart_mod
from app.services import quality_chart as quality_chart_mod
from app.services import render
from app.services.loader import load_fields, load_reference_ranges
from app.services.pipeline_runner import load_artifacts

APP_VERSION = "0.1.0"
REPORT_VERSION = "1"
MAX_ANOMALY_ROWS = 20
BOX_METRIC_ORDER = ("hgb", "rbc", "wbc", "plt", "mcv", "mch", "hct", "mchc")

DQ_LABELS = {
    "DQ-01": "核心字段完整率",
    "DQ-02": "唯一率（1 − 重复率）",
    "DQ-03": "值域合规率",
    "DQ-04": "单位可判定率",
    "DQ-05": "逻辑一致性通过率",
    "DQ-06": "判定可执行率",
}

REMOVED_LABELS = {
    "duplicate": "全字段重复行",
    "core_all_null": "核心字段（hgb/wbc/plt）全空",
}

PATTERN_TEXT = {
    "MICRO_HYPO": "小细胞低色素倾向",
    "MICRO": "小细胞倾向",
    "MACRO": "大细胞倾向",
    "ANEMIA": "血红蛋白偏低",
    "POLYCYTHEMIA_SUSPECT": "红细胞与血红蛋白同时偏高",
    "THROMBOCYTOPENIA": "血小板偏低",
    "THROMBOCYTOSIS": "血小板偏高",
    "LEUKOCYTOSIS": "白细胞与中性粒比例同时偏高",
    "LEUKOPENIA": "白细胞偏低",
    "MULTI_ABNORMAL": "多项异常（3 项及以上，未匹配特定组合）",
    "SINGLE_ABNORMAL": "单项异常（1 项超出参考区间，未匹配特定组合）",
    "MIXED_ABNORMAL": "两项异常（2 项均超出，未匹配特定组合）",
    "UNCLASSIFIED": "其他异常组合（v1.8 之前落库的旧值）",
    "INSUFFICIENT_METRICS": "能判定的指标不足 3 个，未给模式",
    "NORMAL": "各项均在参考区间内",
}


def _fmt(value: Any, decimals: int = 2, suffix: str = "") -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number != number:
        return "—"
    text = f"{number:,.{decimals}f}".rstrip("0").rstrip(".")
    return f"{text}{suffix}"


def _age(value: Any) -> str:
    """年龄可能缺失（None / NaN / 空串），报告里统一显示破折号而不是 ``nan``。"""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number != number:
        return "—"
    return f"{number:.0f}"


def _pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _range_text(card: dict, decimals: int) -> str:
    by_gender = card.get("ranges_by_gender") or []
    if per_gender := [b for b in by_gender if b.get("low") is not None]:
        return " / ".join(
            f"{'男' if b['gender'] == 'male' else '女'} {_fmt(b['low'], decimals)}–{_fmt(b['high'], decimals)}"
            for b in per_gender
        )
    if card.get("low") is None:
        return "—"
    return f"{_fmt(card['low'], decimals)}–{_fmt(card['high'], decimals)}"


def _environment(settings: Settings) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(Path(settings.resources_dir))),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _image_block(title: str, caption: str, payload: bytes, note: str = "") -> dict:
    return {
        "title": title,
        "caption": caption,
        "mime": "image/png",
        "base64": base64.b64encode(payload).decode("ascii"),
        "note": note,
    }


def build_report(dataset, *, settings: Settings | None = None) -> str:
    """渲染整份报告，返回 HTML 文本（不落盘）。"""
    settings = settings or get_settings()
    fields = load_fields()
    ranges = load_reference_ranges()
    artifacts = load_artifacts(dataset.id)
    frame = artifacts["clean"]
    long = artifacts["flagged"]
    summary = artifacts["summary"]

    overview = (dataset.stats or {}).get("overview") or []
    cards = []
    for card in overview:
        decimals = int(card.get("decimals") or fields.decimals_of(card["metric"]))
        cards.append(
            {
                "name_cn": card.get("name_cn") or card["metric"],
                "unit": card.get("unit") or "",
                "n": f"{int(card.get('n') or 0):,}",
                "median": _fmt(card.get("median"), decimals),
                "range_text": _range_text(card, decimals),
                "pct_low": _pct(card.get("pct_low")),
                "pct_normal": _pct(card.get("pct_normal")),
                "pct_above": _pct(card.get("pct_above")),
                "max_deviation": (
                    _pct((card.get("max_deviation_pct") or 0) / 100) if card.get("max_deviation_pct") else "—"
                ),
            }
        )

    charts: list[dict] = []
    metric = next((m for m in BOX_METRIC_ORDER if m in long["metric"].unique()), None)
    if metric is not None:
        box = chart_mod.box_chart(frame, long, fields, ranges, metric)
        # 参考区间带从同一处口径取（不能用 ranges.interval：无性别时它返回 None）
        bands = stats_mod.reference_bands(metric, ranges)[1]
        decimals = int(fields.decimals_of(metric))
        charts.append(
            _image_block(
                f"{box['title']}（箱线图）",
                box["caption"],
                render.box_image(
                    long,
                    metric,
                    name_cn=box["title"],
                    unit=box["unit"],
                    bands=bands,
                    decimals=decimals,
                ),
                note="箱体为四分位距，横线为中位数；虚线/点线为男性/女性参考上下限。",
            )
        )
        hist = chart_mod.hist_chart(frame, long, fields, ranges, metric)
        charts.append(
            _image_block(
                f"{hist['title']}（直方图）",
                hist["caption"],
                render.hist_image(
                    long,
                    metric,
                    name_cn=hist["title"],
                    unit=hist["unit"],
                    bands=bands,
                    decimals=decimals,
                ),
                note="横轴为实测值，纵轴为样本数；竖线为参考区间上下限。",
            )
        )

    correlation = (dataset.stats or {}).get("correlation") or {}
    if correlation.get("matrix"):
        try:
            corr_caption = chart_mod.corr_chart(frame, fields, correlation)["caption"]
            charts.append(
                _image_block(
                    "指标间相关性（热力图）",
                    corr_caption,
                    render.corr_image(correlation),
                    note="Spearman 秩相关；|ρ| < 0.3 不解读。MCH、MCHC 等指标与 HGB 存在定义性耦合，"
                    "相关系数接近 1 是恒等式所致，不是新发现。",
                )
            )
        except ValueError:
            pass

    anomalies = []
    if len(summary):
        top = summary.sort_values("severity", ascending=False).head(MAX_ANOMALY_ROWS)
        for row in top.itertuples():
            if not row.n_abnormal:
                continue
            anomalies.append(
                {
                    "sample_index": int(row.sample_index),
                    "gender": {"male": "男", "female": "女"}.get(row.gender, "—"),
                    "age": _age(row.age),
                    "pattern_text": PATTERN_TEXT.get(str(row.pattern), str(row.pattern)),
                    "abnormal_metrics": str(row.abnormal_metrics).replace("|", "、").upper(),
                    "severity": f"{float(row.severity):.1f}%" if row.severity == row.severity else "—",
                }
            )

    clean_report = dataset.clean_report or {}
    quality = dataset.quality or {}
    dq = quality.get("dq") or {}
    dq_rows = [
        {"code": code, "label": DQ_LABELS.get(code, code), "value": _pct(dq.get(code))}
        for code in sorted(dq)
        if dq.get(code) is not None
    ]
    before = clean_report.get("before") or {}
    after = clean_report.get("after") or {}
    stage_rows = [
        {
            "label": label,
            "rows": f"{int(stage.get('rows') or 0):,}",
            "columns": int(stage.get("columns") or 0),
            "missing_rate": _pct(stage.get("missing_rate")),
            "completeness": _pct(stage.get("core_completeness")),
        }
        for label, stage in (("清洗前", before), ("清洗后", after))
        if stage
    ]
    removed_rows = [
        {"label": REMOVED_LABELS.get(reason, reason), "count": f"{count:,}"}
        for reason, count in (clean_report.get("removed_by_reason") or {}).items()
    ]

    # 质量图（FR-13 的报告版）。这一块是"附加信息"：出图失败不能让整份报告生不出来，
    # 但也不能悄悄吞掉——所以失败时只丢这一块，其余章节照常。
    quality_block = None
    if (quality.get("completeness") or dq) and clean_report.get("health"):
        try:
            payload = quality_chart_mod.quality_chart(dataset, fields, settings=settings)
            quality_block = {
                "caption": payload["caption"],
                "image": base64.b64encode(
                    render.quality_image(quality, clean_report, fields)
                ).decode("ascii"),
                "note": (
                    "左：各字段完整率（条越短缺得越多，虚线是 90% 最低可接受线）；"
                    "中：DQ-01~06 得分（留空表示该项未计算，不是 0 分）；"
                    "右：清洗剔除的原因分布——剔除的只是脏数据，偏离参考区间的样本一律保留。"
                ),
            }
        except (ValueError, KeyError, RuntimeError):  # 出图失败只丢这一块
            quality_block = None

    has_gender = "gender" in frame.columns and frame["gender"].isin(["male", "female"]).any()
    if dataset.unified_ranges:
        ri_source_text = "统一区间（用户声明本数据集无性别）"
        unified_note = "本数据集未提供性别，且已由用户声明按统一区间判定；因此男/女共用同一组下限与上限。"
    elif has_gender:
        ri_source_text = "按性别各自区间"
        unified_note = ""
    else:
        ri_source_text = "未按性别判定"
        unified_note = ""

    na_count = int((dataset.anomaly or {}).get("gender_missing_samples") or 0)
    na_note = (
        f"因关键字段缺失未判定：{na_count} 条（性别缺失时 HGB/RBC/HCT 不套用男性区间）"
        if na_count and not dataset.unified_ranges
        else ""
    )

    snapshot = dataset.ranges_snapshot or {}
    resolved_ri_version = dataset.ri_version or ranges.version
    method_rows = [
        {
            "item": "数据来源",
            "detail": (
                f"{dataset.original_filename or dataset.name}（SHA-256 前 12 位 "
                f"{(dataset.sha256 or '')[:12] or '未记录'}；"
                f"许可：{(dataset.quality or {}).get('license') or '见数据集登记表'}）"
            ),
        },
        {
            "item": "处理链路",
            "detail": (
                "S1 读取（编码与分隔符探测）→ S2 字段映射与单位归一 → S3 质量校验 → "
                "S4 清洗（越界置空 / 去重 / 缺失填充）→ S5 派生（年龄段、样本序号）→ "
                "S6 逐指标对比参考区间 → S7 描述统计与检验。每一步的中间产物都落盘，可单独重跑。"
            ),
        },
        {
            "item": "判定口径",
            "detail": (
                f"参考区间 {resolved_ri_version}，{ri_source_text}"
                + (f"，口径指纹 {snapshot.get('digest')}" if snapshot.get("digest") else "")
                + (f"，判定于 {dataset.judged_at.strftime('%Y-%m-%d %H:%M')}" if dataset.judged_at else "")
                + "。区间为闭区间：等于下限或上限都算在区间内。"
            ),
        },
        {
            "item": "缺失与不可判",
            "detail": (
                "核心字段缺失率过高的列不整列剔除；中位数填充只用于保持行完整，"
                "填充值不参与判定与异常统计（BR-21）；性别缺失时 HGB/RBC/HCT 判为未判定，"
                "不默认套用男性区间（BR-17）；未满 18 岁不套用成人区间（BR-22）。"
            ),
        },
        {
            "item": "样本量规则",
            "detail": (
                "组内样本量任一组不足 10 时不进行组间检验，报告中不出现 p 值；"
                "少于 5 个样本不出箱线图与直方图（画出来会被当成结论）。"
            ),
        },
        {
            "item": "相关与检验",
            "detail": (
                "相关性使用 Spearman 秩相关（对偏态与离群值稳健）；|ρ| < 0.3 时不作解读；"
                "指标之间的数学定义关系（MCH=HGB/RBC、MCHC=HGB/HCT、HCT≈RBC×MCV/10）"
                "会在图中标注为数学耦合，不计为独立发现。组间比较使用 Mann-Whitney U 检验。"
            ),
        },
        {
            "item": "措辞约束",
            "detail": (
                "本报告只陈述「哪些指标超出参考区间」，不写「差异有统计学意义」这类判断语，"
                "不出现病名，也不给出任何建议（完整的禁用词表见需求文档 BR-16）。"
            ),
        },
    ]

    template = _environment(settings).get_template("report_template.html.j2")
    return template.render(
        dataset={
            "name": dataset.name,
            "rows": f"{int(dataset.rows or 0):,}",
            "license_note": (dataset.quality or {}).get("license") or "公开数据集，许可见数据集登记表",
        },
        cards=cards,
        charts=charts,
        anomalies=anomalies,
        health=clean_report.get("health") or "",
        stage_rows=stage_rows,
        dq_rows=dq_rows,
        removed_rows=removed_rows,
        quality_block=quality_block,
        method_rows=method_rows,
        na_note=na_note,
        unified_note=unified_note,
        ri_version=dataset.ri_version or ranges.version,
        ri_source_text=ri_source_text,
        generated_at=datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M"),
        app_version=APP_VERSION,
        report_version=REPORT_VERSION,
        color=render.colors(),
    )


def save_report(dataset, *, settings: Settings | None = None) -> Path:
    """生成并落盘到 ``data/reports/{dataset_id}.html``，返回路径。"""
    settings = settings or get_settings()
    html_text = build_report(dataset, settings=settings)
    path = Path(settings.reports_dir) / f"{dataset.id}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")
    return path


def escape(text: str) -> str:
    """模板外拼字符串时的转义入口（保持报告里不出现裸 HTML）。"""
    return html.escape(text, quote=True)


__all__ = [
    "build_report",
    "save_report",
    "escape",
    "APP_VERSION",
    "REPORT_VERSION",
    "PATTERN_TEXT",
    "stats_mod",
    "caption_mod",
]
