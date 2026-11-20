"""把 SRS 3.2 登记的两份数据集下载到 backend/data/raw/，并校验哈希。

为什么要有这个脚本：README 让评审"按命令能跑"，而"去 Kaggle 网站点两次下载"是不可复现的——
不同时间、不同账号下到的文件可能不同（数据集更新过）。这里把下载与校验钉在一起。

用法：
    python scripts/download_datasets.py            # 下载 + 校验
    python scripts/download_datasets.py --check    # 只校验本地已有文件
    python scripts/download_datasets.py --list     # 列出登记表

前提：装了 kaggle 官方 CLI 并配好凭据（`%USERPROFILE%\\.kaggle\\kaggle.json`，
或环境变量 `KAGGLE_API_TOKEN`）。没装也能用：手工下载后放到 `backend/data/raw/`，
再用 `--check` 校验。

注意：本脚本只负责"取数"，不负责"清洗"。CSV 原样放着，脏数据交给 S3/S4——
如果这里顺手清一遍，BR-06（脏数据与异常分离）就变成了"在脚本里悄悄做掉的事"，
正文再也演示不出来。
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "backend" / "data" / "raw"


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    ref: str
    filename: str
    license: str
    size_hint: str
    note: str
    sha256: str


#: 与 SRS 3.2 的数据集登记表一一对应。哈希是 2026-11 实测值：
#: Kaggle 上的数据集会更新，哈希对不上时脚本只**警告**不阻断——因为绝大多数情况是
#: 上游更新了，而不是你下错了；但报告里必须写清用的是哪一版。
DATASETS: tuple[DatasetSpec, ...] = (
    DatasetSpec(
        key="ds01",
        ref="vizeno/complete-blood-count-cbc-dataset",
        filename="blood_count_dataset.csv",
        license="MIT",
        size_hint="16 KB / 约 400 行",
        note="有年龄与性别，缺 HCT/RDW；答辩现场演示用",
        sha256="dafb7f942e2f5ea2e1b0d60240dc64c3a76c578b16e947b147bcd64167ff1ecc",
    ),
    DatasetSpec(
        key="ds02",
        ref="muhammedsamir/cbc-analysis-dataset",
        filename="cbc_dataframe.csv",
        license="CC BY-SA 4.0",
        size_hint="10.4 MB / 11.5 万行",
        note="无年龄与性别，20 个字段；大样本分布用，需勾选『统一区间』",
        sha256="1df3c2b839bd7458c304c43b335c8ed2e6962e3c169b2ff1ec0b60ceb4a25864",
    ),
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(spec: DatasetSpec, *, force: bool) -> Path:
    target = RAW_DIR / spec.filename
    if target.exists() and not force:
        print(f"[跳过] {target.name} 已存在（{target.stat().st_size:,} B）")
        return target

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "kaggle",
        "datasets",
        "download",
        "-d",
        spec.ref,
        "-p",
        str(RAW_DIR),
        "--unzip",
    ]
    print(f"[下载] {spec.ref} → {RAW_DIR}")
    try:
        subprocess.run(command, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(
            "下载失败。要么装好 kaggle CLI 并配置凭据（pip install kaggle），"
            f"要么手工下载 {spec.ref} 里的 {spec.filename} 放到 {RAW_DIR}。\n原因：{exc}"
        ) from exc

    if not target.exists():
        raise SystemExit(f"下载完成但没找到 {target}；数据集包里的文件名可能变了，请手工确认。")
    return target


def report(spec: DatasetSpec, path: Path) -> None:
    actual = sha256_of(path)
    print(f"  {spec.key}  {path.name}")
    print(f"    许可：{spec.license}（论文/报告里要注明）")
    print(f"    规模：约 {spec.size_hint}，实际 {path.stat().st_size:,} B")
    print(f"    sha256={actual}")
    if actual != spec.sha256:
        print("    [警告] 与登记哈希不一致：上游可能更新过这份数据。结论要注明版本。")
    print(f"    说明：{spec.note}")


def main() -> int:
    parser = argparse.ArgumentParser(description="下载并校验 SRS 3.2 登记的两份 CBC 数据集")
    parser.add_argument("--check", action="store_true", help="不下载，只校验本地文件是否存在")
    parser.add_argument("--list", action="store_true", help="只打印登记表")
    parser.add_argument("--force", action="store_true", help="已存在也重新下载")
    args = parser.parse_args()

    if args.list:
        for spec in DATASETS:
            print(f"{spec.key:5s} {spec.ref:45s} {spec.license:12s} {spec.note}")
        return 0

    missing: list[str] = []
    for spec in DATASETS:
        path = RAW_DIR / spec.filename if args.check else download(spec, force=args.force)
        if not path.exists():
            missing.append(spec.filename)
            print(f"[缺失] {spec.key} {spec.filename}（期望在 {RAW_DIR}）")
            continue
        report(spec, path)

    if missing:
        print("\n缺少文件：" + "、".join(missing))
        return 1

    print("\n下一步：在界面里上传这两个 CSV，或用 scripts/import_local.py 走正式接口登记进库。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
