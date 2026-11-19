"""S1 读取与 S2 映射（T-01 / T-02）。"""

from __future__ import annotations

from pathlib import Path

from app.pipeline.mapping import FieldMapper, normalize
from app.pipeline.reading import detect_delimiter, read_csv


def test_reads_fixture(pipeline, clean_csv):
    result = pipeline(clean_csv)
    assert result.read.encoding == "utf-8-sig"
    assert result.read.delimiter == ","
    assert result.read.columns[0] == "age"


def test_gbk_file_is_decoded(tmp_path: Path):
    path = tmp_path / "gbk.csv"
    path.write_bytes("性别,血红蛋白\n男,140\n女,120\n".encode("gbk"))
    result = read_csv(path)
    assert result.encoding in {"gbk", "gb18030"}
    assert list(result.frame.columns) == ["性别", "血红蛋白"]
    assert result.frame.iloc[0, 0] == "男"


def test_semicolon_delimiter(tmp_path: Path):
    path = tmp_path / "semi.csv"
    path.write_text("age;gender;hgb\n30;male;140\n", encoding="utf-8")
    result = read_csv(path)
    assert result.delimiter == ";"
    assert result.frame.shape == (1, 3)


def test_detect_delimiter_prefers_consistent_separator():
    assert detect_delimiter("a,b\n1,2\n3,4\n") == ","
    assert detect_delimiter("a\tb\n1\t2\n3\t4\n") == "\t"


def test_empty_cells_become_na(tmp_path: Path):
    path = tmp_path / "blank.csv"
    path.write_text("age,gender,hgb\n30,male,\n,,\n", encoding="utf-8")
    result = read_csv(path)
    assert result.frame["hgb"].isna().all()
    assert result.frame["gender"].isna().tolist() == [False, True]


def test_normalize_ignores_case_spaces_and_symbols():
    assert normalize("Hemoglobin") == "hemoglobin"
    assert normalize("  WBC ") == "wbc"
    assert normalize("HGB(g/L)") == "hgbgl"  # 括号被去掉，内部字符保留
    assert normalize("mcv_%") == "mcv%"


def test_mapping_hits_standard_and_alias_names(fields, mapping_config):
    mapper = FieldMapper(fields, mapping_config)
    result = mapper.suggest(["Hemoglobin", "WBC", "PLT", "Age", "Gender"])
    mapping = result.mapping
    assert mapping["Hemoglobin"] == "hgb"
    assert mapping["WBC"] == "wbc"
    assert mapping["PLT"] == "plt"
    assert result.needs_confirmation is False


def test_too_few_metrics_blocks_confirmation(fields, mapping_config):
    mapper = FieldMapper(fields, mapping_config)
    result = mapper.suggest(["hgb", "备注"])
    assert result.needs_confirmation is True
    assert result.missing_required


def test_unrecognised_column_is_ignored(fields, mapping_config):
    mapper = FieldMapper(fields, mapping_config)
    result = mapper.suggest(["hgb", "wbc", "plt", "医嘱内容"])
    assert "医嘱内容" in result.ignored
    assert "医嘱内容" not in result.mapping


def test_payload_is_json_friendly(fields, mapping_config):
    mapper = FieldMapper(fields, mapping_config)
    payload = mapper.suggest(["hgb", "wbc", "plt"]).to_payload()
    assert isinstance(payload["items"], list)
    assert payload["needs_confirmation"] is False
