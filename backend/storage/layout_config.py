"""可配置布局系统持久化（agent-works/configurable-layout-system M4）。

后端分别保存视觉预设与受控的页面、用户覆盖层。页面实际结构仍由前端
PageLayout 声明提供，后端负责最终守门：schema 版本、路径白名单、类型和值域，
以及 validate 接口中传入 layout 时的组件存在性、尺寸下限和理想高度关系。视觉预设不参与布局合并。
"""

from __future__ import annotations

import json
import math
import re
import threading
from datetime import datetime
from typing import Any, Literal

from backend.common.logging import get_logger
from backend.storage.duckdb_client import DuckDBClient, get_client
from backend.storage.pg_client import get_pg_client
from backend.auth.context import get_current_owner
from backend.storage.pg_ddl import (
    DEFAULT_OWNER_USER_ID,
    DDL_APP_CONFIG,
    DDL_LAYOUT_FIELD_POLICY,
    DDL_LAYOUT_PAGE_CONFIG,
    DDL_LAYOUT_PRESET,
    DDL_LAYOUT_USER_CONFIG,
)

log = get_logger("storage.layout_config")

# 布局用户层身份键：对齐多租户归属模型，默认=平台管理员（原值 "local"，stage1 起统一）。
# 存量 "local" 偏好由 migrate-rbac 重映射为 admin（见 migrate_rbac._transform）。
DEFAULT_USER_ID = DEFAULT_OWNER_USER_ID  # "admin"
LAYOUT_CONFIG_SCHEMA_VERSION = 1

Density = Literal["compact", "standard", "comfortable"]
ScrollOwnership = Literal["none", "body-y", "body-xy", "region"]
LayoutConfigLayer = Literal["page", "user"]

DENSITIES = {"compact", "standard", "comfortable"}
SCROLL_OWNERSHIPS = {"none", "body-y", "body-xy", "region"}
PAGE_KEY_RE = re.compile(r"^[A-Za-z0-9:_-]{1,80}$")
PRESET_KEY_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
SLOT_ID_RE = re.compile(r"^[A-Za-z0-9:_-]{1,80}$")
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
# 组件配置覆盖路径：slots.<slotId>.config.<field>（与前端 componentConfig.ts 同口径）。
COMPONENT_CONFIG_PATH_RE = re.compile(r"^slots\.([A-Za-z0-9:_-]{1,80})\.config\.([A-Za-z0-9_]{1,40})$")

# 组件特性配置字段规则（后端最终守门：未登记字段、类型错误、越权层级一律拒绝）。
# 与前端 componentConfig.ts 的 COMPONENT_FIELD_DEFS 保持一致：只登记已被页面真实消费的字段，
# 不预设无消费的字段。类型、层级和通用数值边界按字段名维护；组件专属静态值域另按
# (component kind, field) 维护，避免同名字段在不同组件中的语义互相污染。
COMPONENT_CONFIG_FIELD_RULES: dict[str, dict[str, Any]] = {
    "border": {"type": "bool", "layers": {"page"}},
    "pageSize": {"type": "int", "layers": {"page", "user"}, "min": 10, "max": 200},
    "defaultSort": {"type": "str", "layers": {"page", "user"}},
    "hiddenColumns": {"type": "str_list", "layers": {"page", "user"}},
    "minHeight": {"type": "int", "layers": {"page", "user"}, "min": 480, "max": 900},
    "klineRangePreferences": {"type": "object", "layers": {"user"}},
    "stockChart": {"type": "object", "layers": {"page", "user"}},
    "stockAnalysis": {"type": "object", "layers": {"page", "user"}},
    "sectorAnalysis": {"type": "object", "layers": {"page", "user"}},
    "klinePeriod": {
        "type": "enum",
        "layers": {"page", "user"},
        "options": {"day", "week", "month", "year"},
    },
    "returnMeasurementMode": {
        "type": "enum",
        "layers": {"page", "user"},
        "options": {"latest", "range"},
    },
    # 兼容历史配置读取；新页面配置统一写 masterRatio，避免跨屏固定像素导致分栏失衡。
    "masterWidth": {"type": "int", "layers": {"page", "user"}, "min": 360, "max": 1200},
    "masterRatio": {"type": "int", "layers": {"page", "user"}, "min": 30, "max": 70},
    "masterRatioProfiles": {"type": "object", "layers": {"user"}},
    "defaultActive": {"type": "str", "layers": {"page", "user"}},
    "size": {"type": "enum", "layers": {"page", "user"}, "options": {"sm", "md", "lg"}},
    "bodyScroll": {"type": "bool", "layers": {"page"}},
    "collapsibleSections": {"type": "bool", "layers": {"page"}},
    "defaultCollapsed": {"type": "str_list", "layers": {"page", "user"}},
    "showGroupDescription": {"type": "bool", "layers": {"page", "user"}},
    "showSectionDescription": {"type": "bool", "layers": {"page", "user"}},
    "visibleIndicatorFields": {"type": "str_list", "layers": {"page", "user"}},
    "visibleItems": {"type": "str_list", "layers": {"page", "user"}},
    "autoScroll": {"type": "bool", "layers": {"page", "user"}},
}

# 组件种类 -> 允许的配置字段集合（与前端 COMPONENT_FIELD_DEFS 同口径）。
# 仅按字段名校验无法发现"字段挂错组件/挂错 slot"（如 toolbar.config.pageSize、data-table.config.defaultActive），
# 必须结合页面 layout 的 slot->component 映射做归属校验，才是真正的数据边界收口。
COMPONENT_CONFIG_FIELDS_BY_KIND: dict[str, set[str]] = {
    "data-table": {"border", "pageSize", "defaultSort", "hiddenColumns"},
    "wide-table": {"border", "pageSize", "defaultSort", "hiddenColumns"},
    "chart": {
        "minHeight",
        "stockChart",
        "stockAnalysis",
        "sectorAnalysis",
        "klinePeriod",
        "returnMeasurementMode",
        "klineRangePreferences",
    },
    "section": {"visibleIndicatorFields"},
    "kpi-grid": {"visibleItems"},
    "detail": {"autoScroll"},
    "master-detail": {"masterWidth", "masterRatio", "masterRatioProfiles"},
    "tabs": {"defaultActive"},
    "settings-drawer": {"size", "bodyScroll"},
    "config-panel": {"collapsibleSections", "defaultCollapsed", "showGroupDescription", "showSectionDescription"},
}

# 同名字段可能因组件种类拥有不同静态值域；动态页面值域不在此表硬编码。
COMPONENT_CONFIG_OPTIONS_BY_KIND_FIELD: dict[tuple[str, str], set[str]] = {
    ("chart", "klinePeriod"): {"day", "week", "month", "year"},
    ("chart", "returnMeasurementMode"): {"latest", "range"},
    ("settings-drawer", "size"): {"sm", "md", "lg"},
    ("section", "visibleIndicatorFields"): {
        "ma20",
        "ma60",
        "dist_to_high_2y",
        "is_high_2y",
        "is_bull_arrange",
        "ma20_up",
        "is_platform_breakout",
        "is_vol_breakout",
    },
}

# user 层并不等于一律写 layout_user_config。跨页面共享的个人偏好由专用偏好存储承接；
# 此表是布局写接口的反向拦截事实源，按 (kind, field) 判断，避免绑定具体 pageKey/slotId。
COMPONENT_CONFIG_USER_PERSISTENCE_BY_KIND_FIELD: dict[tuple[str, str], str] = {
    ("settings-drawer", "size"): "global-preference",
    ("chart", "klineRangePreferences"): "global-preference",
}

# registry 统一保留 settings 作为页面设置抽屉 slot。历史折叠字段已改为固定交互，
# 读 effective 时同步屏蔽旧值，避免数据库中的存量覆盖继续泄漏到运行时。
REMOVED_SETTINGS_DRAWER_PATHS = {
    "slots.settings.config.collapsibleSections",
    "slots.settings.config.defaultCollapsed",
}


ALL_COMPONENT_LAYERS = ("page", "user")


def component_field_max_layers(kind: str, field: str) -> set[str] | None:
    """某 (组件种类, 字段) 的代码最大开放集；非该种类受控字段返回 None。

    这是开放策略（layout_field_policy）收放的上界：管理员只能在此集合内收紧 / 放开，
    不能开放代码未声明的层级（安全红线）。
    """
    if field not in COMPONENT_CONFIG_FIELDS_BY_KIND.get(kind, set()):
        return None
    rule = COMPONENT_CONFIG_FIELD_RULES.get(field)
    if not rule:
        return None
    return set(rule["layers"])


def has_component_config_path(values: dict[str, Any]) -> bool:
    return any(COMPONENT_CONFIG_PATH_RE.fullmatch(p) for p in values)


def check_component_config_ownership(values: dict[str, Any], layout: dict[str, Any] | None) -> list[str]:
    """结合 layout 校验组件配置路径归属：slot 必须存在于该页，字段必须属于该 slot 的组件种类。

    无 layout 时无法判定归属，返回空列表（调用方据 has_component_config_path 决定是否因缺 layout 而拒绝）。
    """
    if not isinstance(layout, dict) or not isinstance(layout.get("slots"), list):
        return []
    slot_specs: dict[str, dict[str, Any]] = {
        s["id"]: s
        for s in layout["slots"]
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }
    errors: list[str] = []
    for path in values:
        m = COMPONENT_CONFIG_PATH_RE.fullmatch(path)
        if not m:
            continue
        slot_id, field = m.group(1), m.group(2)
        slot = slot_specs.get(slot_id)
        if slot is None:
            errors.append(f"组件配置 slot 不在该页面布局中: {slot_id}")
            continue
        kind = str(slot.get("component"))
        allowed = COMPONENT_CONFIG_FIELDS_BY_KIND.get(kind)
        if not allowed or field not in allowed:
            errors.append(f"组件 {kind} 不支持配置字段 {field}（slot {slot_id}）")
            continue
        slot_config = slot.get("config") if isinstance(slot.get("config"), dict) else {}
        if field == "pageSize" and slot_config.get("pagination") is not True:
            errors.append(f"组件 {kind} 的当前实例未启用分页，不能配置 pageSize（slot {slot_id}）")
            continue
        if field == "minHeight" and "minHeight" not in slot_config:
            errors.append(f"组件 {kind} 的当前实例使用自适应高度，不能配置 minHeight（slot {slot_id}）")
            continue
        if field == "stockChart" and "stockChart" not in slot_config:
            errors.append(f"组件 {kind} 的当前实例不是股票多图工作区，不能配置 stockChart（slot {slot_id}）")
            continue
        if field == "klineRangePreferences" and "stockChart" not in slot_config:
            errors.append(
                f"组件 {kind} 的当前实例不是 K 线工作区，"
                f"不能配置 klineRangePreferences（slot {slot_id}）"
            )
            continue
        if (
            field == "visibleIndicatorFields"
            and field not in slot_config
        ):
            errors.append(f"组件 {kind} 的当前实例未开放 {field}（slot {slot_id}）")
            continue
        if field == "stockAnalysis" and "stockAnalysis" not in slot_config:
            errors.append(f"组件 {kind} 的当前实例不是联动走势工作台，不能配置 stockAnalysis（slot {slot_id}）")
            continue
        if field == "sectorAnalysis" and "sectorAnalysis" not in slot_config:
            errors.append(f"组件 {kind} 的当前实例不是板块联动走势工作台，不能配置 sectorAnalysis（slot {slot_id}）")
            continue
        if (
            field == "returnMeasurementMode"
            and slot_config.get("returnMeasurement") is not True
        ):
            errors.append(
                f"组件 {kind} 的当前实例未启用涨跌测算，"
                f"不能配置 {field}（slot {slot_id}）"
            )
            continue
        if field == "klinePeriod" and slot_config.get("multiPeriodKline") is not True:
            errors.append(
                f"组件 {kind} 的当前实例未启用多周期 K 线，"
                f"不能配置 {field}（slot {slot_id}）"
            )
            continue
        if field == "defaultSort" and "defaultSort" not in slot_config:
            errors.append(f"组件 {kind} 的当前实例未启用默认排序，不能配置 defaultSort（slot {slot_id}）")
            continue
        options = COMPONENT_CONFIG_OPTIONS_BY_KIND_FIELD.get((kind, field))
        value = values[path]
        if options and (
            (isinstance(value, list) and any(item not in options for item in value))
            or (not isinstance(value, list) and value not in options)
        ):
            errors.append(f"组件 {kind} 配置字段 {field} 包含非法取值（slot {slot_id}）")
    return errors


def _enforce_component_ownership(values: dict[str, Any], layout: dict[str, Any] | None) -> None:
    """保存时强制组件配置归属：含组件配置路径却无 layout，无法校验归属，直接拒绝（数据边界收口）。"""
    if not has_component_config_path(values):
        return
    if layout is None:
        raise LayoutConfigValidationError("保存组件配置需提供页面 layout 以校验字段归属")
    errors = check_component_config_ownership(values, layout)
    if errors:
        raise LayoutConfigValidationError(errors[0])


def _enforce_component_persistence_target(
    values: dict[str, Any], layout: dict[str, Any] | None, layer: str
) -> None:
    """拒绝把有专用持久化目标的 user 值写进页面布局存储。"""
    if layer != "user" or not has_component_config_path(values) or not isinstance(layout, dict):
        return
    slot_kind = {
        slot["id"]: str(slot.get("component"))
        for slot in layout.get("slots", [])
        if isinstance(slot, dict) and isinstance(slot.get("id"), str)
    }
    for path in values:
        match = COMPONENT_CONFIG_PATH_RE.fullmatch(path)
        if not match:
            continue
        slot_id, field = match.group(1), match.group(2)
        kind = slot_kind.get(slot_id)
        target = COMPONENT_CONFIG_USER_PERSISTENCE_BY_KIND_FIELD.get((kind, field))
        if target and target != "layout":
            raise LayoutConfigValidationError(
                f"{kind}.{field} 的 user 层应写入 {target}，不允许写入 layout_user_config"
            )
VISUAL_PRESET_COLOR_FIELDS = {
    "primary", "success", "warning", "danger", "marketUp", "marketDown", "border", "borderStrong"
}
TOKEN_NUMBER_FIELDS = {"cardRadius", "controlRadius"}
TOKEN_TEXT_FIELDS = {"shadow"}

# 后端只需要维护稳定的组件登记和最低尺寸，用于 /validate 的最终拒绝。
# 组件专属 config 能力仍由前端 componentSchemas.ts 负责即时校验。
COMPONENT_MIN_SIZE: dict[str, tuple[int, int]] = {
    "page-shell": (320, 360),
    "section": (280, 120),
    "split-pane": (560, 280),
    "slot-group": (280, 120),
    "filter-bar": (280, 48),
    "search-box": (180, 40),
    "advanced-filter": (320, 96),
    "toolbar": (240, 44),
    "batch-bar": (280, 44),
    "data-table": (360, 300),
    "wide-table": (480, 300),
    "simple-list": (240, 240),
    "description-list": (280, 160),
    "tree-table": (420, 300),
    "pagination": (280, 40),
    "column-settings": (40, 32),
    "sort-control": (120, 32),
    "export-button": (80, 32),
    "form": (360, 300),
    "form-section": (320, 160),
    "config-panel": (320, 120),
    "field-grid": (320, 120),
    "inline-editor": (240, 40),
    "loading-state": (160, 80),
    "empty-state": (160, 120),
    "error-state": (160, 120),
    "skeleton": (160, 80),
    "kpi-grid": (320, 120),
    "metric-card": (160, 96),
    "stat-strip": (280, 64),
    "chart": (320, 260),
    "mini-chart": (160, 80),
    "chart-grid": (320, 260),
    "trend-panel": (320, 220),
    "master-detail": (640, 320),
    "tree-nav": (220, 260),
    "tabs": (280, 120),
    "collapse": (280, 120),
    "steps": (280, 80),
    "kanban": (480, 320),
    "detail-panel": (320, 240),
    "drawer": (320, 360),
    "dialog": (320, 240),
    "settings-drawer": (320, 280),
    "side-panel": (280, 320),
    "detail": (320, 240),
    "timeline": (280, 240),
    "anchor-nav": (160, 200),
    "breadcrumb": (160, 32),
}

BUILTIN_PRESETS: list[dict[str, Any]] = [
    {
        "key": "balanced",
        "name": "澄空蓝",
        "description": "蓝色强调信号与固定中性明暗表面构成的默认研究空间。",
        "config": {},
    },
]

LEGACY_BUILTIN_PRESET_MAP = {
    "daylight": "balanced",
    "nocturne": "balanced",
    "professional": "balanced",
    "government": "balanced",
    "technology": "balanced",
    "finance": "balanced",
    "high-contrast": "balanced",
}

_SINGLE_BLUE_PRESET_MARKER = "migration.layout_presets_single_blue_v1"
_VISUAL_PRESET_SPLIT_MARKER = "migration.layout_preset_visual_split_v1"
_AUTO_SCALE_CONFIG_PATH = "ui.display.auto_scale_exponent"

# 旧预设编辑器唯一真实写入的组件字段是 data-table.pageSize。迁移目标是当时页面注册表中
# 启用分页的 data-table slot；这是一次性历史快照，不作为后续页面登记或运行时事实源。
_LEGACY_DATA_TABLE_PAGE_SIZE_TARGETS: dict[str, tuple[str, ...]] = {
    "data-quality": ("table",),
    "training": ("history",),
    "trade-discipline": ("history",),
    "user-manage": ("table",),
    "tenant-manage": ("table",),
    "data-dictionary": ("itemTable",),
    "data-ingest": ("taskTable", "logTable"),
    "data-overview": ("stockTable",),
    "sectors-detail": ("memberTable",),
}
_PRESET_SEED_LOCK = threading.Lock()


class LayoutConfigValidationError(ValueError):
    """布局配置校验失败。"""


def _json_load(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _validate_key(kind: str, key: str) -> str:
    pattern = PAGE_KEY_RE if kind == "page_key" else PRESET_KEY_RE
    if not isinstance(key, str) or not pattern.fullmatch(key):
        raise LayoutConfigValidationError(f"{kind} 格式非法: {key}")
    return key


def _validate_schema_version(schema_version: int | None) -> int:
    version = LAYOUT_CONFIG_SCHEMA_VERSION if schema_version is None else schema_version
    if version != LAYOUT_CONFIG_SCHEMA_VERSION:
        raise LayoutConfigValidationError(
            f"schemaVersion 不兼容: {version}，当前为 {LAYOUT_CONFIG_SCHEMA_VERSION}"
        )
    return version


def _normalize_values(values: dict[str, Any], layer: str | None = None) -> dict[str, Any]:
    if not isinstance(values, dict):
        raise LayoutConfigValidationError("config.values 必须是对象")
    normalized: dict[str, Any] = {}
    for path, value in values.items():
        normalized[path] = _normalize_path_value(path, value, layer)
    return normalized


def _normalize_component_value(field: str, value: Any, layer: str | None) -> Any:
    """校验单个组件配置字段：未登记字段 / 类型错误 / 越权层级一律拒绝。"""
    rule = COMPONENT_CONFIG_FIELD_RULES.get(field)
    if not rule:
        raise LayoutConfigValidationError(f"未登记的组件配置项: {field}")
    if layer is not None and layer not in rule["layers"]:
        raise LayoutConfigValidationError(f"组件配置 {field} 不允许在 {layer} 层覆盖")
    t = rule["type"]
    if t == "bool":
        if not isinstance(value, bool):
            raise LayoutConfigValidationError(f"组件配置 {field} 需为布尔值")
        return value
    if t == "int":
        if isinstance(value, bool):
            raise LayoutConfigValidationError(f"组件配置 {field} 需为整数")
        try:
            num = int(value)
        except (TypeError, ValueError):
            raise LayoutConfigValidationError(f"组件配置 {field} 需为整数")
        if "min" in rule and num < rule["min"]:
            raise LayoutConfigValidationError(f"组件配置 {field} 不能小于 {rule['min']}")
        if "max" in rule and num > rule["max"]:
            raise LayoutConfigValidationError(f"组件配置 {field} 不能大于 {rule['max']}")
        return num
    if t == "enum":
        if value not in rule["options"]:
            raise LayoutConfigValidationError(f"组件配置 {field} 取值非法")
        return str(value)
    if t == "str":
        if not isinstance(value, str):
            raise LayoutConfigValidationError(f"组件配置 {field} 需为字符串")
        return value
    if t == "str_list":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise LayoutConfigValidationError(f"组件配置 {field} 需为字符串数组")
        return value
    if t == "object":
        if not isinstance(value, dict):
            raise LayoutConfigValidationError(f"组件配置 {field} 需为对象")
        if field == "stockChart":
            return _normalize_stock_chart(value)
        if field == "masterRatioProfiles":
            return _normalize_master_ratio_profiles(value)
        return value
    raise LayoutConfigValidationError(f"组件配置 {field} 类型未知")


def _normalize_master_ratio_profiles(value: dict[str, Any]) -> dict[str, Any]:
    """尺寸比例档案只接受有限、可排序的工作区宽度与比例，避免任意对象进入用户配置。"""
    profiles = value.get("profiles")
    if not isinstance(profiles, list):
        raise LayoutConfigValidationError("组件配置 masterRatioProfiles.profiles 需为数组")
    if len(profiles) > 50:
        raise LayoutConfigValidationError("组件配置 masterRatioProfiles 最多保存 50 项")
    normalized: list[dict[str, int]] = []
    seen: set[int] = set()
    for item in profiles:
        if not isinstance(item, dict) or set(item) != {"width", "ratio"}:
            raise LayoutConfigValidationError("尺寸比例档案只允许 width 与 ratio")
        width = item.get("width")
        ratio = item.get("ratio")
        if isinstance(width, bool) or not isinstance(width, int) or not 1 <= width <= 100_000:
            raise LayoutConfigValidationError("尺寸比例档案 width 需为 1～100000 的整数")
        if isinstance(ratio, bool) or not isinstance(ratio, int) or not 30 <= ratio <= 70:
            raise LayoutConfigValidationError("尺寸比例档案 ratio 需为 30～70 的整数")
        if width in seen:
            raise LayoutConfigValidationError("尺寸比例档案 width 不能重复")
        seen.add(width)
        normalized.append({"width": width, "ratio": ratio})
    return {"profiles": sorted(normalized, key=lambda item: item["width"])}


def _normalize_stock_chart(value: dict[str, Any]) -> dict[str, Any]:
    """股票多图组件配置是稳定契约；拒绝缺字段、重复图层或失真的比例。"""
    auxiliary = {"volume", "macd", "hidden"}
    slot2 = value.get("slot2")
    slot3 = value.get("slot3")
    if slot2 not in auxiliary or slot3 not in auxiliary:
        raise LayoutConfigValidationError("组件配置 stockChart 的辅助图类型非法")
    if slot2 != "hidden" and slot2 == slot3:
        raise LayoutConfigValidationError("组件配置 stockChart 的辅助图不能重复")
    expected_lengths = {
        "kline": 1,
        "kline|volume": 2,
        "kline|macd": 2,
        "kline|volume|macd": 3,
        "kline|macd|volume": 3,
    }
    ratios = value.get("heightRatios")
    if not isinstance(ratios, dict) or set(ratios) != set(expected_lengths):
        raise LayoutConfigValidationError("组件配置 stockChart 的高度比例组合不完整")
    normalized_ratios: dict[str, list[float]] = {}
    for key, length in expected_lengths.items():
        items = ratios.get(key)
        if (
            not isinstance(items, list)
            or len(items) != length
            or any(isinstance(item, bool) or not isinstance(item, (int, float)) or item <= 0 for item in items)
        ):
            raise LayoutConfigValidationError(f"组件配置 stockChart 的 {key} 高度比例非法")
        total = float(sum(items))
        if abs(total - 1.0) > 1e-6:
            raise LayoutConfigValidationError(f"组件配置 stockChart 的 {key} 高度比例之和必须为 1")
        normalized_ratios[key] = [float(item) / total for item in items]
    normalized = {"slot2": slot2, "slot3": slot3, "heightRatios": normalized_ratios}
    # 旧配置没有尺寸档案字段，继续原样兼容；新配置按图表组合分别保存工作区宽高与比例。
    raw_profiles = value.get("heightRatioProfiles")
    if raw_profiles is None:
        return normalized
    if not isinstance(raw_profiles, dict) or set(raw_profiles) != set(expected_lengths):
        raise LayoutConfigValidationError("组件配置 stockChart 的尺寸比例档案组合不完整")
    normalized_profiles: dict[str, list[dict[str, Any]]] = {}
    for key, length in expected_lengths.items():
        profiles = raw_profiles.get(key)
        if not isinstance(profiles, list) or len(profiles) > 50:
            raise LayoutConfigValidationError(f"组件配置 stockChart 的 {key} 尺寸比例档案非法")
        seen: set[tuple[int, int]] = set()
        normalized_items: list[dict[str, Any]] = []
        for profile in profiles:
            if not isinstance(profile, dict) or set(profile) != {"width", "height", "ratios"}:
                raise LayoutConfigValidationError("图表尺寸比例档案只允许 width、height 与 ratios")
            width = profile.get("width")
            height = profile.get("height")
            profile_ratios = profile.get("ratios")
            if (
                isinstance(width, bool)
                or not isinstance(width, int)
                or not 1 <= width <= 100_000
                or isinstance(height, bool)
                or not isinstance(height, int)
                or not 1 <= height <= 100_000
            ):
                raise LayoutConfigValidationError("图表尺寸比例档案宽高需为 1～100000 的整数")
            if (
                not isinstance(profile_ratios, list)
                or len(profile_ratios) != length
                or any(
                    isinstance(item, bool)
                    or not isinstance(item, (int, float))
                    or not math.isfinite(item)
                    or item <= 0
                    for item in profile_ratios
                )
            ):
                raise LayoutConfigValidationError(f"图表尺寸比例档案 {key} 的高度比例非法")
            total = float(sum(profile_ratios))
            if not math.isfinite(total) or abs(total - 1.0) > 1e-6:
                raise LayoutConfigValidationError(f"图表尺寸比例档案 {key} 的高度比例之和必须为 1")
            size = (width, height)
            if size in seen:
                raise LayoutConfigValidationError("图表尺寸比例档案的宽高组合不能重复")
            seen.add(size)
            normalized_items.append({
                "width": width,
                "height": height,
                "ratios": [float(item) / total for item in profile_ratios],
            })
        normalized_profiles[key] = sorted(
            normalized_items,
            key=lambda item: (item["width"], item["height"]),
        )
    normalized["heightRatioProfiles"] = normalized_profiles
    return normalized


def _normalize_path_value(path: str, value: Any, layer: str | None = None) -> Any:
    if path == "density":
        if value not in DENSITIES:
            raise LayoutConfigValidationError("density 需为 compact/standard/comfortable")
        return str(value)

    config_match = COMPONENT_CONFIG_PATH_RE.fullmatch(path)
    if config_match:
        return _normalize_component_value(config_match.group(2), value, layer)

    parts = path.split(".")
    if len(parts) != 3 or parts[0] != "slots" or not SLOT_ID_RE.fullmatch(parts[1]):
        raise LayoutConfigValidationError(f"不允许覆盖的布局路径: {path}")
    field = parts[2]
    if field in {"minW", "minH", "idealW", "idealH", "order"}:
        if isinstance(value, bool):
            raise LayoutConfigValidationError(f"{path} 需为数值")
        try:
            num = int(value)
        except (TypeError, ValueError):
            raise LayoutConfigValidationError(f"{path} 需为整数")
        min_value = 0 if field == "order" else 1
        if num < min_value:
            raise LayoutConfigValidationError(f"{path} 不能小于 {min_value}")
        return num
    if field == "scroll":
        if value not in SCROLL_OWNERSHIPS:
            raise LayoutConfigValidationError(f"{path} 滚动归属非法")
        return str(value)
    if field in {"growMain", "reflowable", "visible"}:
        if not isinstance(value, bool):
            raise LayoutConfigValidationError(f"{path} 需为布尔值")
        return value
    raise LayoutConfigValidationError(f"不允许覆盖的布局路径: {path}")


def normalize_override(
    raw: dict[str, Any] | None, schema_version: int | None = None, layer: str | None = None
) -> dict[str, Any]:
    """规范化覆盖层输入，兼容直接传 values 或 {schemaVersion, values}。

    layer 指定本次覆盖归属层（page/user），用于组件配置字段的越权校验；
    None 表示不强制层级（如 validate 接口的通用校验）。
    """
    raw = raw or {}
    if not isinstance(raw, dict):
        raise LayoutConfigValidationError("config 必须是对象")
    version = _validate_schema_version(raw.get("schemaVersion", schema_version))
    values = raw.get("values", raw)
    if "values" not in raw and "schemaVersion" in raw:
        values = {}
    return {"schemaVersion": version, "values": _normalize_values(values, layer)}


def _normalize_preset_token(path: str, value: Any) -> str | int | float:
    """预设 token 路径：明暗颜色/阴影与明暗共用的圆角。"""
    parts = path.split(".")
    if len(parts) == 3:
        scope, token = parts[1], parts[2]
        if scope in ("light", "dark") and token in VISUAL_PRESET_COLOR_FIELDS:
            if not isinstance(value, str) or not value.strip():
                raise LayoutConfigValidationError(f"{path} 不能为空")
            normalized = value.strip()
            if not HEX_COLOR_RE.fullmatch(normalized):
                raise LayoutConfigValidationError(f"{path} 需为 #RRGGBB 颜色")
            return normalized
        if scope in ("light", "dark") and token in TOKEN_TEXT_FIELDS:
            if not isinstance(value, str) or not value.strip():
                raise LayoutConfigValidationError(f"{path} 不能为空")
            return value.strip()
        if scope == "shared" and token in TOKEN_NUMBER_FIELDS:
            if isinstance(value, bool):
                raise LayoutConfigValidationError(f"{path} 需为数值")
            try:
                num = float(value)
            except (TypeError, ValueError):
                raise LayoutConfigValidationError(f"{path} 需为数值")
            if num < 0:
                raise LayoutConfigValidationError(f"{path} 不能小于 0")
            return int(num) if num.is_integer() else num
    raise LayoutConfigValidationError(f"不支持的预设 token 路径: {path}")


def normalize_preset_override(raw: dict[str, Any] | None, schema_version: int | None = None) -> dict[str, Any]:
    """视觉预设只接受颜色、圆角和阴影 token。"""
    raw = raw or {}
    if not isinstance(raw, dict):
        raise LayoutConfigValidationError("config 必须是对象")
    version = _validate_schema_version(raw.get("schemaVersion", schema_version))
    values = raw.get("values", raw)
    if "values" not in raw and "schemaVersion" in raw:
        values = {}
    if not isinstance(values, dict):
        raise LayoutConfigValidationError("config.values 必须是对象")
    normalized: dict[str, str | int | float | bool] = {}
    for path, value in values.items():
        if path.startswith("tokens."):
            normalized[path] = _normalize_preset_token(path, value)
            continue
        raise LayoutConfigValidationError(f"视觉预设不支持配置字段: {path}")
    return {"schemaVersion": version, "values": normalized}


def validate_layout_payload(layout: dict[str, Any]) -> list[str]:
    """校验前端传入的 PageLayout 结构中与后端规则相关的不变量。"""
    errors: list[str] = []
    if not isinstance(layout, dict):
        return ["layout 必须是对象"]
    slots = layout.get("slots")
    if not isinstance(slots, list):
        return ["layout.slots 必须是数组"]
    seen: set[str] = set()
    for idx, slot in enumerate(slots):
        if not isinstance(slot, dict):
            errors.append(f"slots[{idx}] 必须是对象")
            continue
        slot_id = slot.get("id")
        component = slot.get("component")
        if not isinstance(slot_id, str) or not SLOT_ID_RE.fullmatch(slot_id):
            errors.append(f"slots[{idx}].id 格式非法")
        elif slot_id in seen:
            errors.append(f"slot id 重复: {slot_id}")
        else:
            seen.add(slot_id)
        if component not in COMPONENT_MIN_SIZE:
            errors.append(f"组件未登记: {component}")
            continue
        min_w, min_h = COMPONENT_MIN_SIZE[str(component)]
        if "minW" in slot and isinstance(slot.get("minW"), (int, float)) and slot["minW"] < min_w:
            errors.append(f"slots.{slot_id}.minW 不能低于组件下限 {min_w}")
        if "minH" in slot and isinstance(slot.get("minH"), (int, float)) and slot["minH"] < min_h:
            errors.append(f"slots.{slot_id}.minH 不能低于组件下限 {min_h}")
        ideal_h = slot.get("idealH")
        if ideal_h is not None:
            if isinstance(ideal_h, bool) or not isinstance(ideal_h, int) or ideal_h <= 0:
                errors.append(f"slots.{slot_id}.idealH 必须为正整数")
            else:
                configured_min_h = slot.get("minH")
                effective_min_h = (
                    configured_min_h
                    if isinstance(configured_min_h, (int, float))
                    and not isinstance(configured_min_h, bool)
                    else min_h
                )
                if ideal_h < effective_min_h:
                    errors.append(
                        f"slots.{slot_id}.idealH 不能低于有效最低高 {effective_min_h}"
                    )
            if slot.get("growMain") is True:
                errors.append(f"slots.{slot_id} 已是成长主区，不应再声明 idealH")
    return errors


def _visual_preset_values(raw_values: dict[str, Any]) -> dict[str, Any]:
    """只保留且规范化视觉预设字段；历史脏值不再下发。"""
    visual: dict[str, Any] = {}
    for path, value in raw_values.items():
        if not (
            re.fullmatch(
                r"tokens\.(?:light|dark)\.(?:primary|success|warning|danger|marketUp|marketDown|border|borderStrong|shadow)",
                path,
            )
            or re.fullmatch(r"tokens\.shared\.(?:cardRadius|controlRadius)", path)
        ):
            continue
        try:
            visual[path] = _normalize_preset_token(path, value)
        except LayoutConfigValidationError:
            log.warning("已丢弃非法的历史视觉预设字段: %s", path)
    return visual


def _row_to_preset(row: Any) -> dict[str, Any]:
    values = _visual_preset_values(_json_load(row["config"], {}))
    return {
        "key": row["key"],
        "name": row["name"],
        "description": row["description"] or "",
        "config": {
            "schemaVersion": int(row["schema_version"] or LAYOUT_CONFIG_SCHEMA_VERSION),
            "values": values,
        },
        "enabled": bool(row["enabled"]),
        "is_builtin": bool(row["is_builtin"]),
        "schemaVersion": int(row["schema_version"] or LAYOUT_CONFIG_SCHEMA_VERSION),
        "created_at": str(row["created_at"]) if row["created_at"] is not None else None,
        "updated_at": str(row["updated_at"]) if row["updated_at"] is not None else None,
    }


class LayoutConfigRepo:
    """可配置布局持久化。

    视觉预设、页面层和字段策略属平台配置，运行期落 PG；DuckDB 只作为配置迁移前的旧数据
    只读回退源。用户层 layout_user_config 仍落 PG，按 user_id 隔离。
    """

    def __init__(self, client: DuckDBClient | None = None, *, tenant_id: str | None = None):
        self.c = client or get_client()
        from backend.storage.ddl import init_db

        init_db(self.c)
        self.pg = get_pg_client()
        self._init_pg_layout_tables()
        # 平台预设、页面模板和字段策略是全局配置，公开登录页也需要在未认证请求中读取。
        # 租户只在访问用户层配置时解析，避免仓库构造阶段把平台读取误绑到认证上下文。
        self._tenant_id = tenant_id or None
        self.seed_builtin_presets()

    @property
    def tenant_id(self) -> str:
        """用户层配置所属租户；请求内缺少认证上下文时继续 fail-closed。"""
        if self._tenant_id is not None:
            return self._tenant_id
        return get_current_owner()[0]

    def _init_pg_layout_tables(self) -> None:
        """只初始化布局系统需要的 PG 表，避免仓库构造触发全量 RBAC/menu seed。"""
        for ddl in (
            DDL_APP_CONFIG,
            DDL_LAYOUT_PRESET,
            DDL_LAYOUT_PAGE_CONFIG,
            DDL_LAYOUT_FIELD_POLICY,
            DDL_LAYOUT_USER_CONFIG,
        ):
            self.pg.execute(ddl)

    def _pg_layout_count(self, table: str, where: str = "", params: list[Any] | None = None) -> int:
        sql = f"SELECT count(*) AS n FROM {table}"
        if where:
            sql += f" WHERE {where}"
        return int(self.pg.query_df(sql, params or []).iloc[0]["n"])

    def _duck_layout_count(self, table: str, where: str = "", params: list[Any] | None = None) -> int:
        sql = f"SELECT count(*) AS n FROM {table}"
        if where:
            sql += f" WHERE {where}"
        return int(self.c.query_df(sql, params or []).iloc[0]["n"])

    def _config_storage_migrated(self) -> bool:
        from backend.services.migrate_config_storage import config_storage_backend

        return config_storage_backend(self.pg) == "postgres"

    def _should_read_duckdb_layout(self, table: str) -> bool:
        """迁移 marker 缺失且 DuckDB 有旧平台配置时，优先只读回退 DuckDB。

        不再以 PG 表是否为空作为前置条件：迁移前一旦误写 PG，仍应继续展示 DuckDB
        存量，避免管理员误判存量平台配置丢失。
        """
        if self._config_storage_migrated():
            return False
        try:
            has_old_rows = self._duck_layout_count(table) > 0
        except Exception as e:  # noqa: BLE001
            log.warning("DuckDB 布局旧表回退检查失败: table=%s err=%s", table, e)
            return False
        if has_old_rows:
            pg_count = self._pg_layout_count(table)
            if pg_count > 0:
                log.warning(
                    "PG %s 已有 %s 条记录但配置迁移 marker 缺失，继续只读回退 DuckDB 旧配置表",
                    table,
                    pg_count,
                )
            else:
                log.warning("PG %s 为空且迁移 marker 缺失，临时只读回退 DuckDB 旧配置表", table)
        return has_old_rows

    def _has_pending_duckdb_platform_layout(self) -> bool:
        """判断是否仍存在未完成迁移的 DuckDB 平台布局配置。"""
        for table in ("layout_preset", "layout_page_config", "layout_field_policy"):
            try:
                if self._duck_layout_count(table) > 0:
                    return True
            except Exception as e:  # noqa: BLE001
                log.warning("DuckDB 布局旧表写入保护检查失败: table=%s err=%s", table, e)
        return False

    def _ensure_platform_layout_write_ready(self) -> None:
        """迁移完成前禁止平台层写入，避免单次 PG 写入击穿 DuckDB 只读回退。

        用户层 layout_user_config 不受此限制；只拦截 preset/page/field-policy 这类平台配置。
        """
        if self._config_storage_migrated():
            return
        if self._has_pending_duckdb_platform_layout():
            raise LayoutConfigValidationError(
                "配置存储迁移未完成，暂不允许保存平台布局配置；"
                "请先执行 migrate-config-storage 完成 DuckDB 到 PG 的配置迁移"
            )

    def seed_builtin_presets(self) -> int:
        with _PRESET_SEED_LOCK:
            marker = self.pg.query_df(
                "SELECT 1 FROM app_config WHERE key=%s",
                [_SINGLE_BLUE_PRESET_MARKER],
            )
            if not marker.empty:
                self._migrate_visual_preset_split()
                return 0
            pending_duckdb_layout = (
                not self._config_storage_migrated() and self._has_pending_duckdb_platform_layout()
            )
            if pending_duckdb_layout:
                # DuckDB 已有平台布局配置而 PG 还未完成配置迁移时，不写任何 PG preset。
                # 读接口临时只读回退 DuckDB，正式数据只能由 migrate-config-storage 搬入 PG。
                if self._pg_layout_count("layout_preset") == 0:
                    self.pg.execute(
                        "INSERT INTO app_config (key, value, updated_at) VALUES (%s, %s, %s) "
                        "ON CONFLICT (key) DO NOTHING",
                        [_SINGLE_BLUE_PRESET_MARKER, '{"applied":true,"source":"duckdb"}', datetime.now()],
                    )
                return 0
            inserted = self._apply_builtin_preset_migration()
            self.pg.execute(
                "INSERT INTO app_config (key, value, updated_at) VALUES (%s, %s, %s) "
                "ON CONFLICT (key) DO NOTHING",
                [_SINGLE_BLUE_PRESET_MARKER, '{"applied":true}', datetime.now()],
            )
            self._migrate_visual_preset_split()
            return inserted

    def _migrate_visual_preset_split(self) -> None:
        """幂等拆分视觉预设，保留页面显式值并迁移已有组件默认。"""
        marker = self.pg.query_df(
            "SELECT 1 FROM app_config WHERE key=%s",
            [_VISUAL_PRESET_SPLIT_MARKER],
        )
        if not marker.empty or not self._config_storage_migrated():
            return
        rows = self.pg.query_df("SELECT key, config, enabled, is_builtin FROM layout_preset")
        auto_scale = 0.10
        for _, row in rows.iterrows():
            raw = _json_load(row["config"], {})
            if bool(row["enabled"]) and bool(row["is_builtin"]):
                candidate = raw.get("responsiveDefaults.autoScaleResponsiveExponent")
                if isinstance(candidate, (int, float)) and not isinstance(candidate, bool) and 0 <= candidate <= 1:
                    auto_scale = float(candidate)
            legacy_page_size = raw.get("componentFieldDefaults.data-table.pageSize")
            if (
                isinstance(legacy_page_size, int)
                and not isinstance(legacy_page_size, bool)
                and 10 <= legacy_page_size <= 200
            ):
                page_rows = self.pg.query_df(
                    "SELECT page_key, config FROM layout_page_config WHERE preset_key=%s",
                    [row["key"]],
                )
                for _, page_row in page_rows.iterrows():
                    page_key = str(page_row["page_key"])
                    values = _json_load(page_row["config"], {})
                    changed = False
                    for slot_id in _LEGACY_DATA_TABLE_PAGE_SIZE_TARGETS.get(page_key, ()):
                        path = f"slots.{slot_id}.config.pageSize"
                        if path not in values:
                            values[path] = legacy_page_size
                            changed = True
                    if changed:
                        self.pg.execute(
                            "UPDATE layout_page_config SET config=%s, updated_at=%s WHERE page_key=%s",
                            [_json_dump(values), datetime.now(), page_key],
                        )
            visual = _visual_preset_values(raw)
            if visual != raw:
                self.pg.execute(
                    "UPDATE layout_preset SET config=%s, updated_at=%s WHERE key=%s",
                    [_json_dump(visual), datetime.now(), row["key"]],
                )
        # 预设已不再是页面布局层；解除历史页面引用，避免产生无消费的假关联。
        self.pg.execute(
            "UPDATE layout_page_config SET preset_key=NULL, updated_at=%s WHERE preset_key IS NOT NULL",
            [datetime.now()],
        )
        self.pg.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (%s,%s,%s) "
            "ON CONFLICT (key) DO NOTHING",
            [_AUTO_SCALE_CONFIG_PATH, _json_dump(auto_scale), datetime.now()],
        )
        self.pg.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (%s,%s,%s) "
            "ON CONFLICT (key) DO NOTHING",
            [_VISUAL_PRESET_SPLIT_MARKER, '{"applied":true}', datetime.now()],
        )

    def _apply_builtin_preset_migration(self) -> int:
        """一次性收敛为单一内置蓝色预设；自定义预设继续保留并可扩展。"""
        before = self._pg_layout_count("layout_preset")
        now = datetime.now()
        for preset in BUILTIN_PRESETS:
            cfg = normalize_preset_override(preset["config"])
            self.pg.execute(
                "INSERT INTO layout_preset "
                "(key, name, description, config, enabled, is_builtin, schema_version, created_at, updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (key) DO UPDATE SET "
                "name=EXCLUDED.name, description=EXCLUDED.description, enabled=TRUE, is_builtin=TRUE, "
                "schema_version=EXCLUDED.schema_version, updated_at=EXCLUDED.updated_at",
                [
                    preset["key"],
                    preset["name"],
                    preset["description"],
                    _json_dump(cfg["values"]),
                    True,
                    True,
                    cfg["schemaVersion"],
                    now,
                    now,
                ],
            )
        # 历史内置预设收敛为 balanced；页面引用先迁移，再删除旧内置行。
        # 只清理 is_builtin=true，避免误删用户恰好使用旧 key 创建的自定义数据。
        for legacy_key, target_key in LEGACY_BUILTIN_PRESET_MAP.items():
            legacy = self.pg.query_df(
                "SELECT is_builtin FROM layout_preset WHERE key=%s",
                [legacy_key],
            )
            if legacy.empty or not bool(legacy.iloc[0]["is_builtin"]):
                continue
            self.pg.execute(
                "UPDATE layout_page_config SET preset_key=%s WHERE preset_key=%s",
                [target_key, legacy_key],
            )
            self.pg.execute(
                "DELETE FROM layout_preset WHERE key=%s AND is_builtin=true",
                [legacy_key],
            )
        after = self._pg_layout_count("layout_preset")
        return max(0, after - before)

    def list_presets(self, include_disabled: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM layout_preset"
        params: list[Any] = []
        if not include_disabled:
            sql += " WHERE enabled=true"
        sql += " ORDER BY is_builtin DESC, key"
        if self._should_read_duckdb_layout("layout_preset"):
            df = self.c.query_df(sql, params)
        else:
            df = self.pg.query_df(sql, params)
        return [_row_to_preset(r) for _, r in df.iterrows()]

    def get_preset(self, key: str) -> dict[str, Any] | None:
        _validate_key("preset_key", key)
        if self._should_read_duckdb_layout("layout_preset"):
            df = self.c.query_df("SELECT * FROM layout_preset WHERE key=?", [key])
        else:
            df = self.pg.query_df("SELECT * FROM layout_preset WHERE key=%s", [key])
        if df.empty:
            return None
        return _row_to_preset(df.iloc[0])

    def upsert_preset(
        self,
        key: str,
        name: str,
        description: str = "",
        config: dict[str, Any] | None = None,
        enabled: bool = True,
        is_builtin: bool = False,
        schema_version: int | None = None,
    ) -> dict[str, Any]:
        self._ensure_platform_layout_write_ready()
        _validate_key("preset_key", key)
        if not name:
            raise LayoutConfigValidationError("预设名称不能为空")
        cfg = normalize_preset_override(config, schema_version)
        existing = self.get_preset(key)
        if existing and existing["is_builtin"] and not is_builtin:
            is_builtin = True
        now = datetime.now()
        created_at = now
        if existing and existing.get("created_at"):
            created_at = datetime.fromisoformat(str(existing["created_at"]))
        self.pg.execute(
            "INSERT INTO layout_preset "
            "(key, name, description, config, enabled, is_builtin, schema_version, created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (key) DO UPDATE SET "
            "name=EXCLUDED.name, description=EXCLUDED.description, config=EXCLUDED.config, "
            "enabled=EXCLUDED.enabled, is_builtin=EXCLUDED.is_builtin, "
            "schema_version=EXCLUDED.schema_version, updated_at=EXCLUDED.updated_at",
            [key, name, description, _json_dump(cfg["values"]), enabled, is_builtin, cfg["schemaVersion"], created_at, now],
        )
        log.info("视觉预设已保存: %s", key)
        return self.get_preset(key) or {}

    def delete_preset(self, key: str) -> None:
        self._ensure_platform_layout_write_ready()
        _validate_key("preset_key", key)
        preset = self.get_preset(key)
        if not preset:
            return
        if preset["is_builtin"]:
            raise LayoutConfigValidationError(f"内置预设不能删除: {key}")
        self.pg.execute("DELETE FROM layout_preset WHERE key=%s", [key])

    def get_page_config(self, page_key: str) -> dict[str, Any]:
        _validate_key("page_key", page_key)
        if self._should_read_duckdb_layout("layout_page_config"):
            df = self.c.query_df("SELECT * FROM layout_page_config WHERE page_key=?", [page_key])
        else:
            df = self.pg.query_df("SELECT * FROM layout_page_config WHERE page_key=%s", [page_key])
        if df.empty:
            return {
                "pageKey": page_key,
                "presetKey": None,
                "config": {"schemaVersion": LAYOUT_CONFIG_SCHEMA_VERSION, "values": {}},
            }
        r = df.iloc[0]
        return {
            "pageKey": page_key,
            # 字段为旧客户端保留；视觉预设不再作为页面布局层。
            "presetKey": None,
            "config": {
                "schemaVersion": int(r["schema_version"] or LAYOUT_CONFIG_SCHEMA_VERSION),
                "values": _json_load(r["config"], {}),
            },
            "updated_at": str(r["updated_at"]) if r["updated_at"] is not None else None,
        }

    def set_page_config(
        self,
        page_key: str,
        config: dict[str, Any] | None,
        preset_key: str | None = None,
        schema_version: int | None = None,
        layout: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._ensure_platform_layout_write_ready()
        _validate_key("page_key", page_key)
        if preset_key:
            raise LayoutConfigValidationError("视觉预设不再支持绑定页面，请在系统外观中切换")
        cfg = normalize_override(config, schema_version, layer="page")
        _enforce_component_ownership(cfg["values"], layout)
        self._enforce_field_policy(cfg["values"], layout, "page")
        self.pg.execute(
            "INSERT INTO layout_page_config (page_key, preset_key, config, schema_version, updated_at) "
            "VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (page_key) DO UPDATE SET "
            "preset_key=EXCLUDED.preset_key, config=EXCLUDED.config, "
            "schema_version=EXCLUDED.schema_version, updated_at=EXCLUDED.updated_at",
            [page_key, None, _json_dump(cfg["values"]), cfg["schemaVersion"], datetime.now()],
        )
        return self.get_page_config(page_key)

    def get_user_config(self, page_key: str, user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
        _validate_key("page_key", page_key)
        if not user_id:
            raise LayoutConfigValidationError("user_id 不能为空")
        df = self.pg.query_df(
            "SELECT * FROM layout_user_config WHERE user_id=%s AND page_key=%s", [user_id, page_key]
        )
        if df.empty:
            return {
                "userId": user_id,
                "pageKey": page_key,
                "config": {"schemaVersion": LAYOUT_CONFIG_SCHEMA_VERSION, "values": {}},
            }
        r = df.iloc[0]
        return {
            "userId": user_id,
            "pageKey": page_key,
            "config": {
                "schemaVersion": int(r["schema_version"] or LAYOUT_CONFIG_SCHEMA_VERSION),
                "values": _json_load(r["config"], {}),
            },
            "updated_at": str(r["updated_at"]) if r["updated_at"] is not None else None,
        }

    def set_user_config(
        self,
        page_key: str,
        config: dict[str, Any] | None,
        user_id: str = DEFAULT_USER_ID,
        schema_version: int | None = None,
        layout: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _validate_key("page_key", page_key)
        if not user_id:
            raise LayoutConfigValidationError("user_id 不能为空")
        cfg = normalize_override(config, schema_version, layer="user")
        _enforce_component_ownership(cfg["values"], layout)
        _enforce_component_persistence_target(cfg["values"], layout, "user")
        self._enforce_field_policy(cfg["values"], layout, "user")
        # user_id 即归属键；owner_user_id 同步写入以对齐隔离模型，tenant_id 取仓库租户
        self.pg.execute(
            "INSERT INTO layout_user_config "
            "(user_id, tenant_id, owner_user_id, page_key, config, schema_version, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (user_id, page_key) DO UPDATE SET "
            "config=EXCLUDED.config, schema_version=EXCLUDED.schema_version, updated_at=EXCLUDED.updated_at",
            [user_id, self.tenant_id, user_id, page_key, _json_dump(cfg["values"]),
             cfg["schemaVersion"], datetime.now()],
        )
        return self.get_user_config(page_key, user_id)

    # ── 字段开放策略（P10：元配置，不参与运行时值合并）────────────────────
    def get_field_policy_map(self) -> dict[tuple[str, str], set[str]]:
        """读取所有开放策略覆盖：{(kind, field): {允许层级}}。缺行的字段不在表中（回落代码最大集）。"""
        if self._should_read_duckdb_layout("layout_field_policy"):
            df = self.c.query_df("SELECT component_kind, field, allowed_layers FROM layout_field_policy")
        else:
            df = self.pg.query_df("SELECT component_kind, field, allowed_layers FROM layout_field_policy")
        out: dict[tuple[str, str], set[str]] = {}
        for _, r in df.iterrows():
            layers = _json_load(r["allowed_layers"], [])
            if isinstance(layers, list):
                out[(str(r["component_kind"]), str(r["field"]))] = {str(x) for x in layers}
        return out

    def effective_field_layers(self, kind: str, field: str) -> set[str] | None:
        """某 (kind, field) 的当前生效开放集：策略覆盖优先，否则回落代码最大集。"""
        maxl = component_field_max_layers(kind, field)
        if maxl is None:
            return None
        override = self.get_field_policy_map().get((kind, field))
        return (override & maxl) if override is not None else maxl

    def list_field_policies(self) -> list[dict[str, Any]]:
        """列出全部受控 (kind, field) 的开放策略：最大集 + 当前生效集 + 是否被管理员覆盖。"""
        overrides = self.get_field_policy_map()
        out: list[dict[str, Any]] = []
        for kind, fields in COMPONENT_CONFIG_FIELDS_BY_KIND.items():
            for field in sorted(fields):
                maxl = component_field_max_layers(kind, field)
                if maxl is None:
                    continue
                override = overrides.get((kind, field))
                effective = (override & maxl) if override is not None else maxl
                out.append(
                    {
                        "componentKind": kind,
                        "field": field,
                        "maxLayers": [x for x in ALL_COMPONENT_LAYERS if x in maxl],
                        "allowedLayers": [x for x in ALL_COMPONENT_LAYERS if x in effective],
                        "overridden": override is not None,
                    }
                )
        return out

    def set_field_policy(self, component_kind: str, field: str, layers: list[str]) -> dict[str, Any]:
        """设置某 (kind, field) 的开放层级；只能在代码最大集内收放，越界 / 空集拒绝。"""
        self._ensure_platform_layout_write_ready()
        maxl = component_field_max_layers(component_kind, field)
        if maxl is None:
            raise LayoutConfigValidationError(f"组件 {component_kind} 无受控字段 {field}")
        if not isinstance(layers, list) or not layers:
            raise LayoutConfigValidationError("开放层级不能为空")
        chosen: list[str] = []
        for layer in layers:
            if layer not in ALL_COMPONENT_LAYERS:
                raise LayoutConfigValidationError(f"非法层级: {layer}")
            if layer not in maxl:
                raise LayoutConfigValidationError(
                    f"{component_kind}.{field} 不能开放到 {layer} 层（超出代码最大集 {sorted(maxl)}）"
                )
            if layer not in chosen:
                chosen.append(layer)
        ordered = [x for x in ALL_COMPONENT_LAYERS if x in chosen]
        self.pg.execute(
            "INSERT INTO layout_field_policy (component_kind, field, allowed_layers, updated_at) "
            "VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (component_kind, field) DO UPDATE SET "
            "allowed_layers=EXCLUDED.allowed_layers, updated_at=EXCLUDED.updated_at",
            [component_kind, field, _json_dump(ordered), datetime.now()],
        )
        log.info("组件字段开放策略已保存: %s.%s -> %s", component_kind, field, ordered)
        return {
            "componentKind": component_kind,
            "field": field,
            "maxLayers": [x for x in ALL_COMPONENT_LAYERS if x in maxl],
            "allowedLayers": ordered,
            "overridden": True,
        }

    def reset_field_policy(self, component_kind: str, field: str) -> dict[str, Any]:
        """删除某 (kind, field) 的策略覆盖，回落代码最大集。"""
        self._ensure_platform_layout_write_ready()
        self.pg.execute(
            "DELETE FROM layout_field_policy WHERE component_kind=%s AND field=%s",
            [component_kind, field],
        )
        maxl = component_field_max_layers(component_kind, field) or set()
        ordered = [x for x in ALL_COMPONENT_LAYERS if x in maxl]
        return {
            "componentKind": component_kind,
            "field": field,
            "maxLayers": ordered,
            "allowedLayers": ordered,
            "overridden": False,
        }

    def _enforce_field_policy(self, values: dict[str, Any], layout: dict[str, Any] | None, layer: str) -> None:
        """保存时按当前生效开放策略拒绝越权层：管理员收紧后，被禁层的覆盖一律拒绝。

        归属（slot 存在 + 字段属该种类）由 _enforce_component_ownership 先行保证，这里只查层级。
        """
        if not has_component_config_path(values) or not isinstance(layout, dict):
            return
        slot_kind: dict[str, str] = {
            s["id"]: str(s.get("component"))
            for s in layout.get("slots", [])
            if isinstance(s, dict) and isinstance(s.get("id"), str)
        }
        policy = self.get_field_policy_map()
        for path in values:
            m = COMPONENT_CONFIG_PATH_RE.fullmatch(path)
            if not m:
                continue
            slot_id, field = m.group(1), m.group(2)
            kind = slot_kind.get(slot_id)
            if kind is None:
                continue
            maxl = component_field_max_layers(kind, field)
            if maxl is None:
                continue
            effective = (policy.get((kind, field)) & maxl) if (kind, field) in policy else maxl
            if layer not in effective:
                raise LayoutConfigValidationError(
                    f"{kind}.{field} 当前开放策略不允许在 {layer} 层覆盖（允许 {sorted(effective)}）"
                )

    def effective_config(self, page_key: str, user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
        page = self.get_page_config(page_key)
        user = self.get_user_config(page_key, user_id)
        values: dict[str, Any] = {}
        source: dict[str, str] = {}
        layers: list[dict[str, Any]] = []
        for layer_name, cfg in (("page", page["config"]), ("user", user["config"])):
            if not cfg:
                continue
            layer_values = self._filter_effective_layer_values(cfg.get("values", {}), layer_name)
            layers.append({
                "layer": layer_name,
                "config": {**cfg, "values": layer_values},
            })
            for path, value in layer_values.items():
                values[path] = value
                source[path] = layer_name
        return {
            "pageKey": page_key,
            "userId": user_id,
            "presetKey": None,
            "schemaVersion": LAYOUT_CONFIG_SCHEMA_VERSION,
            "values": values,
            "source": source,
            "layers": layers,
            # 普通页面运行时需要同一份生效策略来过滤页面/用户两层与抽屉字段；这里只返回
            # 代码允许的组件字段及层级，不包含平台敏感配置。
            "componentFieldPolicies": self.list_field_policies(),
        }

    @staticmethod
    def _filter_effective_layer_values(values: dict[str, Any], layer: str) -> dict[str, Any]:
        """读时按当前代码层级过滤组件配置，防止历史越权值继续进入 effective_config。"""
        filtered: dict[str, Any] = {}
        for path, value in values.items():
            if path in REMOVED_SETTINGS_DRAWER_PATHS:
                continue
            m = COMPONENT_CONFIG_PATH_RE.fullmatch(path)
            if not m:
                filtered[path] = value
                continue
            rule = COMPONENT_CONFIG_FIELD_RULES.get(m.group(2))
            if rule and layer in rule["layers"]:
                filtered[path] = value
        return filtered

    def reset(
        self,
        scope: Literal["page", "user"],
        page_key: str,
        user_id: str = DEFAULT_USER_ID,
        path: str | None = None,
    ) -> dict[str, Any]:
        _validate_key("page_key", page_key)
        if path is not None:
            _normalize_path_value(path, True if path.endswith(".visible") else self._sample_value_for_path(path))
        if scope == "page":
            self._ensure_platform_layout_write_ready()
            cfg = self.get_page_config(page_key)
            values = dict(cfg["config"]["values"])
            if path:
                values.pop(path, None)
                return self.set_page_config(page_key, {"values": values})
            self.pg.execute("DELETE FROM layout_page_config WHERE page_key=%s", [page_key])
            return self.get_page_config(page_key)
        if scope == "user":
            if not user_id:
                raise LayoutConfigValidationError("user_id 不能为空")
            if path:
                cfg = self.get_user_config(page_key, user_id)
                values = dict(cfg["config"]["values"])
                values.pop(path, None)
                return self.set_user_config(page_key, {"values": values}, user_id)
            self.pg.execute("DELETE FROM layout_user_config WHERE user_id=%s AND page_key=%s", [user_id, page_key])
            return self.get_user_config(page_key, user_id)
        raise LayoutConfigValidationError(f"reset scope 非法: {scope}")

    def _sample_value_for_path(self, path: str) -> Any:
        if path == "density":
            return "standard"
        field = path.split(".")[-1]
        if field == "scroll":
            return "none"
        if field in {"growMain", "reflowable", "visible"}:
            return True
        return 1
