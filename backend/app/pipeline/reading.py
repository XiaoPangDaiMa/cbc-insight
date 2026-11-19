"""S1 读取原始 CSV（SRS FR-01、9 章 S1）。

编码与分隔符都必须"探测后留痕"，因为静默猜错编码是本类项目最常见的翻车点：
中文列名变成 ``锟斤拷`` 之后，字段映射会把它们全部判为未识别。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from app.core.errors import AppError

# 顺序即优先级：UTF-8 系列在前，GBK 在后。gb18030 兜底（它是 gbk 的超集）。
ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "gbk", "gb18030")
DELIMITERS: tuple[str, ...] = (",", ";", "\t", "|")
SAMPLE_BYTES = 65536


@dataclass
class ReadResult:
    frame: pd.DataFrame
    encoding: str
    delimiter: str
    columns: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def rows(self) -> int:
        return len(self.frame)

    @property
    def n_columns(self) -> int:
        return len(self.frame.columns)


def detect_encoding(raw: bytes) -> str:
    """按 ENCODINGS 顺序试解码；全部失败抛 40001（8.3）。"""
    sample = raw[:SAMPLE_BYTES]
    for encoding in ENCODINGS:
        try:
            sample.decode(encoding)
        except UnicodeDecodeError:
            continue
        return encoding
    raise AppError(40001, detail="已尝试 " + " / ".join(ENCODINGS))


def detect_delimiter(text: str) -> str:
    """在首 5 个非空行上按出现次数投票，平票时按 DELIMITERS 顺序取先者。"""
    lines = [ln for ln in text.splitlines()[:20] if ln.strip()][:5]
    if not lines:
        return ","
    best, best_count = ",", -1
    for delimiter in DELIMITERS:
        counts = [len(next(csv.reader([line], delimiter=delimiter))) for line in lines]
        # 只考虑"每行字段数一致且 > 1"的分隔符
        if len(set(counts)) != 1 or counts[0] <= 1:
            continue
        if counts[0] > best_count:
            best, best_count = delimiter, counts[0]
    return best


def read_csv(path: str | Path, *, nrows: int | None = None) -> ReadResult:
    """读取 CSV，保留字符串原样（``12.3*``、``<0.5`` 这类脏值由 S4 处理）。"""
    p = Path(path)
    if not p.exists():
        raise AppError(40401, detail=f"文件不存在：{p.name}")

    raw = p.read_bytes()[:SAMPLE_BYTES]
    if not raw.strip():
        raise AppError(40003, detail="文件为空")

    encoding = detect_encoding(raw)
    delimiter = detect_delimiter(raw.decode(encoding, errors="ignore"))

    try:
        frame = pd.read_csv(
            p,
            encoding=encoding,
            sep=delimiter,
            dtype=str,
            keep_default_na=False,
            skip_blank_lines=True,
            nrows=nrows,
        )
    except pd.errors.EmptyDataError as exc:  # 只有分隔符没有表头
        raise AppError(40003, detail="缺少表头") from exc
    except pd.errors.ParserError as exc:
        raise AppError(40003, detail=f"解析失败：{exc}") from exc

    frame.columns = [str(c).strip() for c in frame.columns]
    if not list(frame.columns) or any(col == "" for col in frame.columns):
        raise AppError(40003, detail="存在空列名")

    # 空白字符串 → NaN；单元格去首尾空格
    frame = frame.map(lambda v: v.strip() if isinstance(v, str) else v)
    frame = frame.replace(r"^\s*$", pd.NA, regex=True)

    notes: list[str] = []
    if encoding not in {"utf-8", "utf-8-sig"}:
        notes.append(f"编码探测为 {encoding}")
    if delimiter != ",":
        notes.append(f"分隔符探测为 {delimiter!r}")

    return ReadResult(
        frame=frame,
        encoding=encoding,
        delimiter=delimiter,
        columns=list(frame.columns),
        notes=notes,
    )
