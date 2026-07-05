"""可配置布局系统持久化（agent-works/configurable-layout-system M4）。

后端只保存受控覆盖层：预设层、页面层、用户层。页面实际结构仍由前端
PageLayout 声明提供，后端负责最终守门：schema 版本、路径白名单、类型和值域、
以及 validate 接口中传入 layout 时的组件存在性和尺寸下限。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal

from backend.common.logging import get_logger
from backend.storage.duckdb_client import DuckDBClient, get_client
from backend.storage.pg_client import get_pg_client
from backend.auth.context import get_current_owner
from backend.storage.pg_ddl import DEFAULT_OWNER_USER_ID

log = get_logger("storage.layout_config")

# 布局用户层身份键：对齐多租户归属模型，默认=平台管理员（原值 "local"，stage1 起统一）。
# 存量 "local" 偏好由 migrate-rbac 重映射为 admin（见 migrate_rbac._transform）。
DEFAULT_USER_ID = DEFAULT_OWNER_USER_ID  # "admin"
LAYOUT_CONFIG_SCHEMA_VERSION = 1

Density = Literal["compact", "standard", "comfortable"]
ScrollOwnership = Literal["none", "body-y", "body-xy", "region"]
LayoutConfigLayer = Literal["preset", "page", "user"]

DENSITIES = {"compact", "standard", "comfortable"}
SCROLL_OWNERSHIPS = {"none", "body-y", "body-xy", "region"}
PAGE_KEY_RE = re.compile(r"^[A-Za-z0-9:_-]{1,80}$")
PRESET_KEY_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
SLOT_ID_RE = re.compile(r"^[A-Za-z0-9:_-]{1,80}$")
# 组件配置覆盖路径：slots.<slotId>.config.<field>（与前端 componentConfig.ts 同口径）。
COMPONENT_CONFIG_PATH_RE = re.compile(r"^slots\.([A-Za-z0-9:_-]{1,80})\.config\.([A-Za-z0-9_]{1,40})$")

# 组件特性配置字段规则（后端最终守门：未登记字段、类型错误、越权层级一律拒绝）。
# 与前端 componentConfig.ts 的 COMPONENT_FIELD_DEFS 保持一致：只登记已被页面真实消费的字段，
# 不预设无消费的字段。首批字段均限 page/user 层（preset 层覆盖会被判越权）。按字段名建表（首批无冲突）。
COMPONENT_CONFIG_FIELD_RULES: dict[str, dict[str, Any]] = {
    # pageSize 放开 preset 层：预设可设某组件种类的默认分页大小（预设×组件默认，P11/D4）。
    "pageSize": {"type": "int", "layers": {"preset", "page", "user"}, "min": 10, "max": 500},
    "defaultSort": {"type": "str", "layers": {"page", "user"}},
    "hiddenColumns": {"type": "str_list", "layers": {"page", "user"}},
    "defaultActive": {"type": "str", "layers": {"page", "user"}},
    "size": {"type": "enum", "layers": {"preset", "page", "user"}, "options": {"sm", "md", "lg"}},
    "bodyScroll": {"type": "bool", "layers": {"preset", "page", "user"}},
    "collapsibleSections": {"type": "bool", "layers": {"preset", "page"}},
    "defaultCollapsed": {"type": "str_list", "layers": {"preset", "page", "user"}},
}

# 组件种类 -> 允许的配置字段集合（与前端 COMPONENT_FIELD_DEFS 同口径）。
# 仅按字段名校验无法发现"字段挂错组件/挂错 slot"（如 toolbar.config.pageSize、data-table.config.defaultActive），
# 必须结合页面 layout 的 slot->component 映射做归属校验，才是真正的数据边界收口。
COMPONENT_CONFIG_FIELDS_BY_KIND: dict[str, set[str]] = {
    "data-table": {"pageSize", "defaultSort", "hiddenColumns"},
    "wide-table": {"pageSize", "hiddenColumns"},
    "tabs": {"defaultActive"},
    "settings-drawer": {"size", "bodyScroll", "collapsibleSections", "defaultCollapsed"},
}


ALL_COMPONENT_LAYERS = ("preset", "page", "user")


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
    slot_kind: dict[str, str] = {
        s["id"]: str(s.get("component"))
        for s in layout["slots"]
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }
    errors: list[str] = []
    for path in values:
        m = COMPONENT_CONFIG_PATH_RE.fullmatch(path)
        if not m:
            continue
        slot_id, field = m.group(1), m.group(2)
        kind = slot_kind.get(slot_id)
        if kind is None:
            errors.append(f"组件配置 slot 不在该页面布局中: {slot_id}")
            continue
        allowed = COMPONENT_CONFIG_FIELDS_BY_KIND.get(kind)
        if not allowed or field not in allowed:
            errors.append(f"组件 {kind} 不支持配置字段 {field}（slot {slot_id}）")
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
TOKEN_COLOR_FIELDS = {
    "primary",
    "success",
    "warning",
    "danger",
    "pageBg",
    "surfaceBg",
    "surfaceHover",
    "border",
    "borderStrong",
    "text",
    "textStrong",
    "textMuted",
    "activeBg",
    "submenuBg",
}
TOKEN_NUMBER_FIELDS = {"cardRadius", "controlRadius", "pageGap", "cardPadding", "tableCellPaddingY"}
TOKEN_TEXT_FIELDS = {"shadow"}
PRESET_DENSITY_FIELDS = {"density", "componentDefaults.density", "componentDefaults.tableSize"}

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
        "key": "professional",
        "name": "专业后台",
        "description": "均衡密度，适合日常管理和分析页面。",
        "config": {"density": "standard"},
    },
    {
        "key": "government",
        "name": "政务稳重",
        "description": "更克制的页面间距和稳重配色预设。",
        "config": {"density": "standard"},
    },
    {
        "key": "technology",
        "name": "科技分析",
        "description": "偏分析场景的紧凑布局预设。",
        "config": {"density": "compact"},
    },
    {
        "key": "finance",
        "name": "金融数据",
        "description": "高信息密度的行情和表格预设。",
        "config": {"density": "compact"},
    },
    {
        "key": "high-contrast",
        "name": "高对比",
        "description": "提高文本和边界对比度的可读性预设。",
        "config": {"density": "standard"},
    },
]


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
        if field == "defaultCollapsed":
            allowed = {"layout", "components", "business"}
            bad = [v for v in value if v not in allowed]
            if bad:
                raise LayoutConfigValidationError(f"组件配置 {field} 仅允许 layout/components/business")
        return value
    if t == "object":
        if not isinstance(value, dict):
            raise LayoutConfigValidationError(f"组件配置 {field} 需为对象")
        return value
    raise LayoutConfigValidationError(f"组件配置 {field} 类型未知")


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


# 预设响应式默认（受控枚举，不开放任意断点 —— §6.4 红线）。
PRESET_REFLOW_BREAKPOINTS = {1024, 1100, 1280}


def _normalize_preset_token(path: str, value: Any) -> str | int | float:
    """预设 token 路径：`tokens.<light|dark>.<颜色/阴影键>` 或 `tokens.shared.<形态/密度键>`。

    颜色/阴影按白天/夜间分两套（M9 模型）；形态/密度（圆角/间距/行高）明暗共用。
    """
    parts = path.split(".")
    if len(parts) == 3:
        scope, token = parts[1], parts[2]
        if scope in ("light", "dark") and token in TOKEN_COLOR_FIELDS | TOKEN_TEXT_FIELDS:
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


def _normalize_preset_component_default(path: str, value: Any) -> Any:
    """预设×组件默认：`componentFieldDefaults.<kind>.<field>`，字段须在该组件种类且允许 preset 层。"""
    parts = path.split(".")
    if len(parts) == 3:
        kind, field = parts[1], parts[2]
        maxl = component_field_max_layers(kind, field)
        if maxl is None or "preset" not in maxl:
            raise LayoutConfigValidationError(f"{kind}.{field} 不支持预设层默认")
        return _normalize_component_value(field, value, "preset")
    raise LayoutConfigValidationError(f"不支持的预设组件默认路径: {path}")


def _normalize_preset_responsive(path: str, value: Any) -> int | float:
    """预设响应式默认：`responsiveDefaults.<key>`，断点为受控枚举（不开放任意断点）。"""
    parts = path.split(".")
    if len(parts) == 2:
        key = parts[1]
        if key == "reflowBreakpoint":
            try:
                num = int(value)
            except (TypeError, ValueError):
                raise LayoutConfigValidationError(f"{path} 需为整数")
            if num not in PRESET_REFLOW_BREAKPOINTS:
                raise LayoutConfigValidationError(f"{path} 仅允许 {sorted(PRESET_REFLOW_BREAKPOINTS)}")
            return num
        if key == "pageGap":
            if isinstance(value, bool):
                raise LayoutConfigValidationError(f"{path} 需为数值")
            try:
                num = float(value)
            except (TypeError, ValueError):
                raise LayoutConfigValidationError(f"{path} 需为数值")
            if num < 0:
                raise LayoutConfigValidationError(f"{path} 不能小于 0")
            return int(num) if num.is_integer() else num
    raise LayoutConfigValidationError(f"不支持的预设响应式路径: {path}")


def normalize_preset_override(raw: dict[str, Any] | None, schema_version: int | None = None) -> dict[str, Any]:
    """预设层允许布局覆盖 + 受控 token/组件默认策略。"""
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
        if path in PRESET_DENSITY_FIELDS:
            if value not in DENSITIES:
                raise LayoutConfigValidationError(f"{path} 需为 compact/standard/comfortable")
            normalized[path] = str(value)
            continue
        if path == "componentDefaults.filterDefaultExpanded":
            if not isinstance(value, bool):
                raise LayoutConfigValidationError(f"{path} 需为布尔值")
            normalized[path] = value
            continue
        if path == "componentDefaults.drawerSize":
            if value not in {"sm", "md", "lg"}:
                raise LayoutConfigValidationError(f"{path} 需为 sm/md/lg")
            normalized[path] = str(value)
            continue
        if path.startswith("tokens."):
            normalized[path] = _normalize_preset_token(path, value)
            continue
        if path.startswith("componentFieldDefaults."):
            normalized[path] = _normalize_preset_component_default(path, value)
            continue
        if path.startswith("responsiveDefaults."):
            normalized[path] = _normalize_preset_responsive(path, value)
            continue
        normalized[path] = _normalize_path_value(path, value, "preset")
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
    return errors


def _row_to_preset(row: Any) -> dict[str, Any]:
    return {
        "key": row["key"],
        "name": row["name"],
        "description": row["description"] or "",
        "config": {
            "schemaVersion": int(row["schema_version"] or LAYOUT_CONFIG_SCHEMA_VERSION),
            "values": _json_load(row["config"], {}),
        },
        "enabled": bool(row["enabled"]),
        "is_builtin": bool(row["is_builtin"]),
        "schemaVersion": int(row["schema_version"] or LAYOUT_CONFIG_SCHEMA_VERSION),
        "created_at": str(row["created_at"]) if row["created_at"] is not None else None,
        "updated_at": str(row["updated_at"]) if row["updated_at"] is not None else None,
    }


class LayoutConfigRepo:
    """可配置布局持久化（混合持久层 stage1·T2）。

    预设层/页面层/字段策略属平台配置，留 DuckDB（self.c）；用户层 layout_user_config
    属用户资产，落 PG（self.pg），按 user_id 隔离（user_id 即归属，owner_user_id 同步写入）。
    """

    def __init__(self, client: DuckDBClient | None = None, *, tenant_id: str | None = None):
        self.c = client or get_client()
        from backend.storage.ddl import init_db

        init_db(self.c)
        self.pg = get_pg_client()
        self.tenant_id = tenant_id or get_current_owner()[0]
        self.seed_builtin_presets()

    def seed_builtin_presets(self) -> int:
        before = int(self.c.query_df("SELECT count(*) AS n FROM layout_preset").iloc[0]["n"])
        now = datetime.now()
        for preset in BUILTIN_PRESETS:
            cfg = normalize_preset_override(preset["config"])
            self.c.execute(
                "INSERT INTO layout_preset "
                "(key, name, description, config, enabled, is_builtin, schema_version, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT (key) DO NOTHING",
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
        after = int(self.c.query_df("SELECT count(*) AS n FROM layout_preset").iloc[0]["n"])
        return after - before

    def list_presets(self, include_disabled: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM layout_preset"
        params: list[Any] = []
        if not include_disabled:
            sql += " WHERE enabled=true"
        sql += " ORDER BY is_builtin DESC, key"
        df = self.c.query_df(sql, params)
        return [self._with_references(_row_to_preset(r)) for _, r in df.iterrows()]

    def get_preset(self, key: str) -> dict[str, Any] | None:
        _validate_key("preset_key", key)
        df = self.c.query_df("SELECT * FROM layout_preset WHERE key=?", [key])
        if df.empty:
            return None
        return self._with_references(_row_to_preset(df.iloc[0]))

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
        _validate_key("preset_key", key)
        if not name:
            raise LayoutConfigValidationError("预设名称不能为空")
        cfg = normalize_preset_override(config, schema_version)
        existing = self.get_preset(key)
        if existing and existing["is_builtin"] and not is_builtin:
            is_builtin = True
        if existing and existing["enabled"] and not enabled and self._preset_ref_count(key) > 0:
            raise LayoutConfigValidationError(f"预设已被页面引用，不能停用: {key}")
        now = datetime.now()
        created_at = now
        if existing and existing.get("created_at"):
            created_at = datetime.fromisoformat(str(existing["created_at"]))
        self.c.execute(
            "INSERT INTO layout_preset "
            "(key, name, description, config, enabled, is_builtin, schema_version, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT (key) DO UPDATE SET "
            "name=EXCLUDED.name, description=EXCLUDED.description, config=EXCLUDED.config, "
            "enabled=EXCLUDED.enabled, is_builtin=EXCLUDED.is_builtin, "
            "schema_version=EXCLUDED.schema_version, updated_at=EXCLUDED.updated_at",
            [key, name, description, _json_dump(cfg["values"]), enabled, is_builtin, cfg["schemaVersion"], created_at, now],
        )
        log.info("布局预设已保存: %s", key)
        return self.get_preset(key) or {}

    def delete_preset(self, key: str) -> None:
        _validate_key("preset_key", key)
        preset = self.get_preset(key)
        if not preset:
            return
        if preset["is_builtin"]:
            raise LayoutConfigValidationError(f"内置预设不能删除: {key}")
        if self._preset_ref_count(key) > 0:
            raise LayoutConfigValidationError(f"预设已被页面引用，不能删除: {key}")
        self.c.execute("DELETE FROM layout_preset WHERE key=?", [key])

    def _preset_ref_count(self, key: str) -> int:
        return int(
            self.c.query_df(
                "SELECT count(*) AS n FROM layout_page_config WHERE preset_key=?", [key]
            ).iloc[0]["n"]
        )

    def _preset_ref_pages(self, key: str) -> list[str]:
        df = self.c.query_df(
            "SELECT page_key FROM layout_page_config WHERE preset_key=? ORDER BY page_key", [key]
        )
        return df["page_key"].tolist()

    def _with_references(self, preset: dict[str, Any]) -> dict[str, Any]:
        pages = self._preset_ref_pages(preset["key"])
        preset["referencedPages"] = pages
        preset["referenceCount"] = len(pages)
        return preset

    def get_page_config(self, page_key: str) -> dict[str, Any]:
        _validate_key("page_key", page_key)
        df = self.c.query_df("SELECT * FROM layout_page_config WHERE page_key=?", [page_key])
        if df.empty:
            return {
                "pageKey": page_key,
                "presetKey": None,
                "config": {"schemaVersion": LAYOUT_CONFIG_SCHEMA_VERSION, "values": {}},
            }
        r = df.iloc[0]
        return {
            "pageKey": page_key,
            "presetKey": r["preset_key"] or None,
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
        _validate_key("page_key", page_key)
        if preset_key:
            _validate_key("preset_key", preset_key)
            preset = self.get_preset(preset_key)
            if not preset or not preset["enabled"]:
                raise LayoutConfigValidationError(f"预设不存在或已停用: {preset_key}")
        cfg = normalize_override(config, schema_version, layer="page")
        _enforce_component_ownership(cfg["values"], layout)
        self._enforce_field_policy(cfg["values"], layout, "page")
        self.c.execute(
            "INSERT INTO layout_page_config (page_key, preset_key, config, schema_version, updated_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT (page_key) DO UPDATE SET "
            "preset_key=EXCLUDED.preset_key, config=EXCLUDED.config, "
            "schema_version=EXCLUDED.schema_version, updated_at=EXCLUDED.updated_at",
            [page_key, preset_key, _json_dump(cfg["values"]), cfg["schemaVersion"], datetime.now()],
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
        df = self.c.query_df("SELECT component_kind, field, allowed_layers FROM layout_field_policy")
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
        self.c.execute(
            "INSERT INTO layout_field_policy (component_kind, field, allowed_layers, updated_at) "
            "VALUES (?,?,?,?) "
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
        self.c.execute(
            "DELETE FROM layout_field_policy WHERE component_kind=? AND field=?",
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
        preset_key = page.get("presetKey")
        preset = self.get_preset(preset_key) if preset_key else None
        user = self.get_user_config(page_key, user_id)
        values: dict[str, Any] = {}
        source: dict[str, str] = {}
        layers: list[dict[str, Any]] = []
        for layer_name, cfg in (
            ("preset", preset["config"] if preset else None),
            ("page", page["config"]),
            ("user", user["config"]),
        ):
            if not cfg:
                continue
            layer_values = cfg.get("values", {})
            layers.append({"layer": layer_name, "config": cfg})
            for path, value in layer_values.items():
                values[path] = value
                source[path] = layer_name
        return {
            "pageKey": page_key,
            "userId": user_id,
            "presetKey": preset_key,
            "schemaVersion": LAYOUT_CONFIG_SCHEMA_VERSION,
            "values": values,
            "source": source,
            "layers": layers,
        }

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
            cfg = self.get_page_config(page_key)
            preset_key = cfg.get("presetKey")
            values = dict(cfg["config"]["values"])
            if path:
                values.pop(path, None)
                return self.set_page_config(page_key, {"values": values}, preset_key)
            self.c.execute("DELETE FROM layout_page_config WHERE page_key=?", [page_key])
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
