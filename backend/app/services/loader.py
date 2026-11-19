"""配置与资源加载（唯一入口）。

业务代码不直接 ``yaml.safe_load``，也不自己拼 ``resources/`` 路径——所有资源都在这里
带上 mtime 缓存加载一次。好处：改 YAML 不用重启，但同一请求内取到的一定是同一份。
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.pipeline.fielddict import FieldDictionary, MappingConfig
from app.pipeline.reference import ReferenceRanges, load_ranges


@lru_cache(maxsize=1)
def load_fields() -> FieldDictionary:
    return FieldDictionary.load(get_settings().field_dict_path)


@lru_cache(maxsize=1)
def load_mapping_config() -> MappingConfig:
    return MappingConfig.load(get_settings().field_mapping_path)


def load_reference_ranges() -> ReferenceRanges:
    # load_ranges 自己按 mtime 缓存，这里不再套 lru_cache，否则改完 YAML 要重启才生效
    return load_ranges(get_settings().reference_ranges_path)


def reset_caches() -> None:
    """测试用：资源文件被改写后强制重读。"""
    load_fields.cache_clear()
    load_mapping_config.cache_clear()
    load_ranges.cache_clear()
