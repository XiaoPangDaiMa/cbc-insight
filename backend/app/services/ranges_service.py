"""三层参考区间：默认 / 我的 / 临时（SRS 3.5.1、FR-24、FR-36、FR-37、BR-18/19/20）。

这一层要守住的四条语义（3.5.1 明文写的，改代码前先读）：

1. **优先级** ``临时 > 我的 > 默认``。临时层只活在一次请求的内存里，**不落库、不进缓存、
   不进任何持久产物**——一旦泄漏，"我看到的 37% 异常"和"报告里的 41%"就对不上（RK-26）。
2. **默认层只读**。缺指标必须报错，绝不回退到 0 / ∞：那会把"没配"伪装成"判定过了"。
3. **我的区间整份保存 15 项**，版本号自增，``note`` 必填（3.5.1 第三条）。
4. **判定即快照**：S6 跑完把当时生效的整份区间写进 ``artifacts/ranges.snapshot.json``，
   包括口径标识与 digest，之后谁改了区间都不影响这份数据集的历史结论。

``digest`` 是整份区间的 sha256 前 12 位，用于回答"这两次判定是不是同一个标准"。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.models import User, UserRanges
from app.pipeline.reference import Interval, ReferenceRanges
from app.services.loader import load_reference_ranges

#: 参与三层模型的指标（= 默认区间的全部项；新增指标时这里和 YAML 要一起改，RK-29）
RANGE_METRICS: tuple[str, ...] = (
    "wbc",
    "rbc",
    "hgb",
    "hct",
    "mcv",
    "mch",
    "mchc",
    "rdw",
    "plt",
    "mpv",
    "neut_pct",
    "lymph_pct",
    "mono_pct",
    "eo_pct",
    "baso_pct",
)

KIND_DEFAULT = "default"
KIND_USER = "user"
KIND_TEMP = "temp"


@dataclass(frozen=True)
class EffectiveRanges:
    """某一刻真正参与判定的一份区间，附带它从哪来。"""

    ranges: ReferenceRanges
    kind: str  # default / user / temp
    source: str  # default@2026.11.1 / user#v5 / temp#ab12cd34ef56
    version: str
    digest: str
    note: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source": self.source,
            "version": self.version,
            "digest": self.digest,
            "note": self.note,
            "items": items_of(self.ranges),
        }


# --------------------------------------------------------------------------- 基本工具


def items_of(ranges: ReferenceRanges) -> dict[str, dict[str, Any]]:
    """把区间摊平成前端直接可吃的整份指标项（含女性覆盖）。"""
    items: dict[str, dict[str, Any]] = {}
    for metric in RANGE_METRICS:
        base = ranges.default.get(metric)
        if base is None:
            continue
        female = ranges.female_overrides.get(metric)
        items[metric] = {
            "metric": metric,
            "name_cn": base.name_cn,
            "unit": base.unit,
            "low": base.low,
            "high": base.high,
            "female_low": female.low if female else None,
            "female_high": female.high if female else None,
            "gender_dependent": female is not None,
        }
    return items


def _project(items: dict[str, Any]) -> dict[str, dict[str, float | None]]:
    """只保留四个数值键，供指纹使用。

    这一步是必需的：``items_of()`` 的输出带 ``name_cn``/``unit``/``gender_dependent`` 等
    展示字段，而用户保存进库的是"精简版"。若直接对两种形状做哈希，"刚存的"和"当前生效的"
    会算出两个不同 digest，界面就会一直显示"陈旧"——BUG 比不显示更糟，因为它会训练用户
    忽略这条提示（RK-28）。
    """
    return {
        metric: {
            key: (None if spec.get(key) is None else round(float(spec[key]), 6))
            for key in ("low", "high", "female_low", "female_high")
        }
        for metric, spec in items.items()
    }


def digest_of(items: dict[str, Any]) -> str:
    """整份区间的指纹。键序固定、只取数值键，否则同一份区间会算出两个 digest。"""
    canonical = json.dumps(
        dict(sorted(_project(items).items())),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _from_items(base: ReferenceRanges, items: dict[str, Any], *, source: str) -> ReferenceRanges:
    """用摊平的指标项重建一个 :class:`ReferenceRanges`（单位与中文名沿用默认表）。"""
    default: dict[str, Interval] = {}
    female: dict[str, Interval] = {}
    for metric, base_interval in base.default.items():
        spec = items.get(metric)
        if spec is None:
            continue
        default[metric] = Interval(
            metric=metric,
            low=float(spec["low"]),
            high=float(spec["high"]),
            unit=base_interval.unit,
            name_cn=base_interval.name_cn,
            gender=None,
        )
        female_low = spec.get("female_low")
        female_high = spec.get("female_high")
        if female_low is not None and female_high is not None:
            female[metric] = Interval(
                metric=metric,
                low=float(female_low),
                high=float(female_high),
                unit=base_interval.unit,
                name_cn=base_interval.name_cn,
                gender="female",
            )
        elif metric in base.female_overrides:
            # 没给女性值时沿用默认表里的女性口径：只改一半会造成"男性改了、女性没改"的错觉
            female[metric] = base.female_overrides[metric]
    return ReferenceRanges(
        version=base.version,
        source=source,
        applies_to=base.applies_to,
        default=default,
        female_overrides=female,
    )


# --------------------------------------------------------------------------- 三层解析


def default_effective() -> EffectiveRanges:
    ranges = load_reference_ranges()
    items = items_of(ranges)
    return EffectiveRanges(
        ranges=ranges,
        kind=KIND_DEFAULT,
        source=f"default@{ranges.version}",
        version=ranges.version,
        digest=digest_of(items),
    )


def latest_user_row(db: Session, user: User) -> UserRanges | None:
    return db.scalar(
        select(UserRanges)
        .where(UserRanges.user_id == user.id)
        .order_by(UserRanges.version.desc())
        .limit(1)
    )


def user_effective(db: Session, user: User) -> EffectiveRanges | None:
    row = latest_user_row(db, user)
    if row is None or not row.ranges:
        return None
    base = load_reference_ranges()
    items = {m: row.ranges[m] for m in RANGE_METRICS if m in row.ranges}
    if not items:
        return None
    ranges = _from_items(base, items, source=f"user#v{row.version}")
    return EffectiveRanges(
        ranges=ranges,
        kind=KIND_USER,
        source=f"user#v{row.version}",
        version=base.version,
        digest=row.digest or digest_of(items_of(ranges)),
        note=row.note,
    )


def effective(db: Session, user: User, *, temp: dict[str, Any] | None = None) -> EffectiveRanges:
    """``临时 > 我的 > 默认``。临时层不落库，这里只是把它包一层。"""
    if temp:
        return build_temp(db, user, temp)
    return user_effective(db, user) or default_effective()


def build_temp(db: Session, user: User, temp: dict[str, Any]) -> EffectiveRanges:
    """把请求里的临时区间叠加到"我的（或默认）"之上，**只在内存里**。

    ``temp`` 允许只给要试的少数几项，其余沿用下层——用户拖的是 HGB 的两条线，
    没道理顺手把 PLT 也改成默认值。
    """
    base_eff = user_effective(db, user) or default_effective()
    merged = items_of(base_eff.ranges)
    touched = 0
    for metric, spec in temp.items():
        if metric not in merged:
            continue
        try:
            low = float(spec["low"])
            high = float(spec["high"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AppError(42201, detail=f"临时区间 {metric} 必须给出 low / high") from exc
        if not (low < high):
            raise AppError(42201, detail=f"临时区间 {metric} 的下限必须小于上限")
        merged[metric] = {**merged[metric], "low": low, "high": high}
        female_low = spec.get("female_low")
        female_high = spec.get("female_high")
        if female_low is not None and female_high is not None:
            if not (float(female_low) < float(female_high)):
                raise AppError(42201, detail=f"临时区间 {metric} 的女性下限必须小于上限")
            merged[metric] = {
                **merged[metric],
                "female_low": float(female_low),
                "female_high": float(female_high),
            }
        touched += 1
    if not touched:
        raise AppError(42201, detail="临时区间里没有可识别的指标")
    digest = digest_of(merged)
    ranges = _from_items(base_eff.ranges, merged, source=f"temp#{digest}")
    return EffectiveRanges(
        ranges=ranges,
        kind=KIND_TEMP,
        source=f"temp#{digest}",
        version=ranges.version,
        digest=digest,
        note="临时试算，未保存",
    )


# --------------------------------------------------------------------------- 保存 / 重置 / 历史


def _validate_items(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict) or not raw:
        raise AppError(42201, detail="ranges 必须是非空对象")
    cleaned: dict[str, dict[str, Any]] = {}
    for metric, spec in raw.items():
        if metric not in RANGE_METRICS:
            raise AppError(42201, detail=f"未知指标 {metric}")
        try:
            low = float(spec["low"])
            high = float(spec["high"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AppError(42201, detail=f"{metric} 必须给出 low / high") from exc
        if not (low < high):
            raise AppError(42201, detail=f"{metric} 的下限必须小于上限（当前 {low} ≥ {high}）")
        entry = {"low": low, "high": high}
        female_low = spec.get("female_low")
        female_high = spec.get("female_high")
        if female_low is not None and female_high is not None:
            if not (float(female_low) < float(female_high)):
                raise AppError(42201, detail=f"{metric} 的女性下限必须小于上限")
            entry["female_low"] = float(female_low)
            entry["female_high"] = float(female_high)
        cleaned[metric] = entry
    missing = [m for m in RANGE_METRICS if m not in cleaned]
    if missing:
        # 整份保存：少一项就拒绝，而不是"没给的部分保留旧值"——后者会让版本号失去意义
        raise AppError(42201, detail=f"缺少指标：{', '.join(missing)}")
    return cleaned


def save(db: Session, user: User, raw: dict[str, Any], note: str) -> UserRanges:
    items = _validate_items(raw)
    note = (note or "").strip()
    if not note:
        raise AppError(42201, detail="请填写本次修改参考区间的理由（3.5.1 要求）")
    if len(note) > 200:
        raise AppError(42201, detail="理由请控制在 200 字以内")
    last = latest_user_row(db, user)
    version = (last.version + 1) if last else 1
    row = UserRanges(
        user_id=user.id,
        version=version,
        ranges=items,
        digest=digest_of(items),
        note=note,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def reset(db: Session, user: User) -> None:
    """回到默认区间：删掉用户自己的全部版本。

    刻意不写一行"等于默认值"的新版本：那会让历史里凭空多出一次"用户主动改过"的记录，
    而实际上他只是放弃了自定义（3.5.1）。
    """
    for row in db.scalars(select(UserRanges).where(UserRanges.user_id == user.id)):
        db.delete(row)
    db.commit()


def versions(db: Session, user: User) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(UserRanges).where(UserRanges.user_id == user.id).order_by(UserRanges.version.desc())
    ).all()
    return [
        {
            "version": row.version,
            "digest": row.digest,
            "note": row.note,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


# --------------------------------------------------------------------------- 判定快照


def snapshot_path(dataset_id: str, settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return settings.processed_dir / dataset_id / "ranges.snapshot.json"


def write_snapshot(
    dataset_id: str,
    eff: EffectiveRanges,
    *,
    unified: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """判定即快照（3.5.1）。返回写下的那份 dict，调用方直接存进数据库。"""
    path = snapshot_path(dataset_id, settings)
    payload = {
        "source": f"unified@{eff.version}" if unified else eff.source,
        "kind": KIND_DEFAULT if unified else eff.kind,
        "version": eff.version,
        "digest": eff.digest,
        "note": eff.note,
        "unified": unified,
        "saved_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "items": items_of(eff.ranges),
    }
    archive_previous(path, settings=settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def archive_previous(path: Path, *, settings: Settings | None = None) -> None:
    """重判前把旧快照归档：历史结论要能对上"当时用的是哪份表"（BR-20）。"""
    if not path.exists():
        return
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    slug = str(previous.get("source", "unknown")).replace("@", "_").replace("#", "_").replace("/", "_")
    history = path.parent / "history"
    history.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, history / f"ranges.snapshot.{slug}.{stamp}.json")


def read_snapshot(dataset_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    path = snapshot_path(dataset_id, settings)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def wrap(
    ranges: ReferenceRanges,
    *,
    source: str,
    kind: str,
    note: str = "",
) -> EffectiveRanges:
    """把一份裸区间包成 :class:`EffectiveRanges`（供管线内部与测试使用）。"""
    items = items_of(ranges)
    return EffectiveRanges(
        ranges=ranges,
        kind=kind,
        source=source,
        version=ranges.version,
        digest=digest_of(items),
        note=note,
    )


def snapshot_for(
    dataset_id: str,
    ranges: ReferenceRanges,
    *,
    source: str,
    kind: str = KIND_DEFAULT,
    unified: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """判定时调用：把生效区间整份落成 ``ranges.snapshot.json``（3.5.1）。"""
    eff = wrap(ranges, source=source, kind=kind)
    return write_snapshot(dataset_id, eff, unified=unified, settings=settings)
