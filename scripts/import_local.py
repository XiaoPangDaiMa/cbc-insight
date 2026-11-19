"""把本地 CSV 走**正式上传链路**登记进系统（B1 真实数据闸门）。

为什么不用 ``pandas.to_sql`` 直接塞库：那样会绕过 S1–S7 的每一步，得到的数据集在
界面上看着正常，但 artifact、清洗日志、判定口径全是空的——正是本项目最想避免的
"看起来对"。

用法：

    backend\\.venv\\Scripts\\python.exe scripts\\import_local.py --user xiaopang
    backend\\.venv\\Scripts\\python.exe scripts\\import_local.py --user xiaopang --preset ds01

预设（对应 backend/data/raw/ 下的两份真实数据）：

    ds01  blood_count_dataset.csv  417 行、有性别、美式单位
    ds02  cbc_dataframe.csv        11.5 万行、无性别 → 需要 --unified 才能判 hgb/rbc/hct

``--unified`` 对应上传页那个显式勾选（FR-16 唯一例外），不传就是 BR-17 的 NA 语义。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.models import Dataset, User  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.services.datasets import save_upload  # noqa: E402

PRESETS = {
    "ds01": ("blood_count_dataset.csv", "DS-01 小样本(有性别)", False),
    "ds02": ("cbc_dataframe.csv", "DS-02 十万级(无性别)", True),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="导入本地 CSV 到 CBC Insight")
    parser.add_argument("--user", required=True, help="归属账号（用户名）")
    parser.add_argument("--preset", choices=sorted(PRESETS), action="append", help="可重复")
    parser.add_argument("--file", action="append", default=[], help="任意 CSV 路径，可重复")
    parser.add_argument("--unified", action="store_true", help="显式声明：本数据集无性别，按统一区间判定")
    args = parser.parse_args()

    settings = get_settings()
    settings.ensure_dirs()
    session_factory = get_session_factory()
    db = session_factory()
    try:
        user = db.scalar(select(User).where(User.username == args.user.strip().lower()))
        if user is None:
            print(f"[错误] 账号不存在：{args.user}（先注册，或检查用户名）")
            return 2

        jobs: list[tuple[Path, str, bool]] = []
        for preset in args.preset or []:
            filename, label, unified = PRESETS[preset]
            jobs.append((settings.raw_dir / filename, label, unified or args.unified))
        for raw in args.file:
            path = Path(raw)
            jobs.append((path, path.stem, args.unified))
        if not jobs:
            print("[错误] 没有指定要导入的文件：用 --preset ds01/ds02 或 --file <path>")
            return 2

        for path, label, unified in jobs:
            if not path.exists():
                print(f"[跳过] 不存在：{path}")
                continue
            data = path.read_bytes()
            started = time.perf_counter()
            print(f"\n=== {label} · {path.name}（{len(data) / 1024 / 1024:.2f} MB, unified={unified}）===")
            try:
                dataset = save_upload(
                    db, user, path.name, data, settings=settings, unified_ranges=unified
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[失败] {type(exc).__name__}: {exc}")
                continue
            elapsed = time.perf_counter() - started
            _report(dataset, elapsed)
    finally:
        db.close()
    return 0


def _report(dataset: Dataset, elapsed: float) -> None:
    clean = dataset.clean_report or {}
    quality = dataset.quality or {}
    anomaly = dataset.anomaly or {}
    mapping = dataset.mapping or {}
    timings = clean.get("timings") or {}

    print(f"  dataset_id   {dataset.id}")
    print(f"  状态         {dataset.status}   ri={dataset.ri_version}  unified={dataset.unified_ranges}")
    print(f"  规模         {dataset.rows} 行 × {dataset.columns} 列（原始行数见清洗报告）")
    print(f"  总耗时       {elapsed:.1f} s")
    if timings:
        detail = "  ".join(f"{k}={v:.1f}s" for k, v in timings.items())
        print(f"  分阶段       {detail}")
    print(f"  映射         {len(mapping.get('mapping', {}))} 列成功，忽略 {len(mapping.get('ignored', []))} 列")
    unresolved = mapping.get("unresolved") or []
    if unresolved:
        print(f"  待确认       {unresolved}")
    dq = quality.get("dq") or {}
    if dq:
        print("  质量         " + "  ".join(f"{k}={v}" for k, v in list(dq.items())[:6]))
    removed = clean.get("removed_by_reason") or {}
    if removed:
        print(f"  清洗剔行     {removed}")
    print(f"  健康度       {clean.get('health', '')}")
    print(
        f"  判定         {anomaly.get('samples', '?')} 样本，异常率 {anomaly.get('anomaly_rate', '?')}"
        f"，NA 样本 {anomaly.get('na_samples', '?')}，ri_source={anomaly.get('ri_source', '?')}"
    )
    patterns = anomaly.get("pattern_counts") or {}
    if patterns:
        top = sorted(patterns.items(), key=lambda kv: kv[1], reverse=True)[:6]
        print(f"  模式分布     {dict(top)}")


if __name__ == "__main__":
    raise SystemExit(main())
