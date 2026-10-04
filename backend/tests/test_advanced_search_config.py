"""高级搜索配置纯校验：不初始化数据库、不访问真实用户配置。"""

import pytest

from backend.storage.layout_config import (
    LayoutConfigValidationError,
    _normalize_component_value,
    check_component_config_ownership,
)


@pytest.mark.parametrize("value", [[], ["status"], ["status", "status"], ["a", "b", "c"], [1, 2]])
def test_common_fields_requires_two_distinct_string_keys(value):
    with pytest.raises(LayoutConfigValidationError):
        _normalize_component_value("commonFields", value, "user")


@pytest.mark.parametrize("layer", ["page", "user"])
def test_common_fields_roundtrip_and_kind_boundary(layer):
    value = ["status", "keyword"]
    assert _normalize_component_value("commonFields", value, layer) == value
    values = {"slots.filters.config.commonFields": value}
    layout = {"slots": [{"id": "filters", "component": "filter-bar"}]}
    assert check_component_config_ownership(values, layout) == []
    layout["slots"][0]["component"] = "data-table"
    assert check_component_config_ownership(values, layout)
