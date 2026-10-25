"""指标定义仓库（M2.1b）——统一管理内置 + 自定义技术指标的"定义"。

- 内置指标（registry.REGISTRY）seed 进 indicator_def 表，kind=builtin/expr、is_builtin=True（不可删，仅启停）。
- 自定义指标：用户保存一段带 {参数} 占位的 DSL 表达式，kind=expr、is_builtin=False。
- 表达式在使用时由 IndicatorEngine 渲染参数 → 逐股点时求值（复用 expression DSL 沙箱）。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime
from string import Formatter

from backend.common.logging import get_logger
from backend.indicators.registry import REGISTRY, governance_metadata, preset_categories
from backend.screening.expression import ExprError, validate_expr
from backend.storage.duckdb_client import get_client

log = get_logger("indicators.definition")

_PARAM_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_LEGACY_DEFAULT_DISABLED_DESCRIPTIONS = {
    "total_mv": (
        "口径:总股本×收盘价(元)。是什么:公司总规模。怎么用:市值分层/过滤。"
        "注:总市值数据当前未入库(需 valuation 采集流程),暂禁用;流通市值 float_mv 可正常用。"
    ),
}


def normalize_param_defs(params: list[dict] | None) -> list[dict]:
    """校准自定义参数 schema，并确保占位渲染与下游输入共享同一约束。"""
    normalized: list[dict] = []
    names: set[str] = set()
    for raw in params or []:
        name = str(raw.get("name") or "").strip()
        if not _PARAM_NAME_RE.fullmatch(name):
            raise ValueError("参数名须以英文字母开头，且只含英文、数字或下划线")
        if name in names:
            raise ValueError(f"参数名重复: {name}")
        names.add(name)
        param_type = str(raw.get("type") or "")
        if param_type not in ("int", "float"):
            raise ValueError(f"参数 {name} 类型须为 int 或 float")
        default = raw.get("default")
        if isinstance(default, bool) or not isinstance(default, (int, float)):
            raise ValueError(f"参数 {name} 默认值须为数字")  # noqa: TRY004
        if param_type == "int" and not float(default).is_integer():
            raise ValueError(f"参数 {name} 默认值须为整数")
        minimum, maximum = raw.get("min"), raw.get("max")
        for label, value in (("最小值", minimum), ("最大值", maximum)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
                raise ValueError(f"参数 {name} {label}须为数字")
            if param_type == "int" and value is not None and not float(value).is_integer():
                raise ValueError(f"参数 {name} {label}须为整数")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError(f"参数 {name} 最小值不能大于最大值")
        if minimum is not None and default < minimum or maximum is not None and default > maximum:
            raise ValueError(f"参数 {name} 默认值超出允许范围")
        normalized.append({
            "name": name,
            "label": str(raw.get("label") or name).strip(),
            "type": param_type,
            "default": int(default) if param_type == "int" else float(default),
            "min": minimum,
            "max": maximum,
            "unit": str(raw.get("unit") or "").strip(),
            "description": str(raw.get("description") or "").strip(),
        })
    return normalized


def validate_definition(expression: str, params: list[dict] | None) -> list[dict]:
    """严格校验参数与表达式占位符的一一对应关系，并执行 DSL 白名单验证。"""
    normalized = normalize_param_defs(params)
    try:
        placeholders = {
            field_name for _, field_name, _, _ in Formatter().parse(expression)
            if field_name is not None
        }
    except ValueError as exc:
        raise ValueError(f"表达式占位符格式错误: {exc}") from exc
    names = {item["name"] for item in normalized}
    missing = sorted(placeholders - names)
    unused = sorted(names - placeholders)
    if missing:
        raise ValueError(f"表达式占位符缺少参数定义: {', '.join(missing)}")
    if unused:
        raise ValueError(f"参数未被表达式使用: {', '.join(unused)}")
    render_expression(expression, None, normalized)
    return normalized


def definition_semantic_signature(dtype: str, expression: str, params: list[dict]) -> tuple:
    """只纳入影响计算结果的字段；标签、单位和说明变化不应淘汰数值缓存。"""
    return (
        dtype,
        expression,
        tuple((p.get("name"), p.get("type"), p.get("default"), p.get("min"), p.get("max"))
              for p in params),
    )


def render_expression(template: str, params: dict | None, param_defs: list[dict] | None = None) -> str:
    """把表达式模板的 {param} 占位用参数值渲染为可执行表达式，并做白名单校验。"""
    merged: dict = {}
    definitions = param_defs or []
    known = {item["name"] for item in definitions}
    unknown = sorted(set(params or {}) - known)
    if param_defs is not None and unknown:
        raise ValueError(f"存在未定义的指标参数: {', '.join(unknown)}")
    for pd_ in definitions:
        merged[pd_["name"]] = pd_.get("default")
    for k, v in (params or {}).items():
        merged[k] = v
    for pd_ in definitions:
        name, value = pd_["name"], merged[pd_["name"]]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"参数 {name} 须为数字")  # noqa: TRY004
        if pd_.get("type") == "int" and not float(value).is_integer():
            raise ValueError(f"参数 {name} 须为整数")
        if pd_.get("min") is not None and value < pd_["min"]:
            raise ValueError(f"参数 {name} 不能小于 {pd_['min']}")
        if pd_.get("max") is not None and value > pd_["max"]:
            raise ValueError(f"参数 {name} 不能大于 {pd_['max']}")
    try:
        expr = template.format(**merged)
    except (KeyError, IndexError) as e:
        raise ValueError(f"表达式缺少参数: {e}") from e
    try:
        validate_expr(expr)
    except ExprError as e:
        raise ValueError(f"表达式非法: {e}") from e
    return expr


def _row(d) -> dict:
    """IndicatorDef(dataclass) → 表行 dict。"""
    layer, parent_key, preset_params = governance_metadata(d)
    return {
        "key": d.key, "name_cn": d.name_cn, "category": d.category, "dtype": d.dtype,
        "direction": d.direction, "kind": d.kind, "expression": d.expression,
        "params": json.dumps([asdict(p) for p in d.params], ensure_ascii=False),
        "categories": json.dumps(preset_categories(d.key, d.category), ensure_ascii=False),
        "layer": layer, "parent_key": parent_key,
        "preset_params": json.dumps(preset_params, ensure_ascii=False),
        "enabled": d.enabled, "is_builtin": d.is_builtin, "descr": d.desc,
    }


def _parse(r: dict) -> dict:
    r = dict(r)
    r["params"] = json.loads(r["params"]) if r.get("params") else []
    r["categories"] = json.loads(r["categories"]) if r.get("categories") else []
    r["preset_params"] = json.loads(r["preset_params"]) if r.get("preset_params") else {}
    r["desc"] = r.pop("descr", "")
    for k in ("created_at", "updated_at"):
        if r.get(k) is not None:
            r[k] = str(r[k])
    return r


class IndicatorDefRepo:
    def __init__(self, client=None):
        self.c = client or get_client()
        # 查询链路复用启动时已初始化的指标表，不能通过读门面触发建表或补列。
        if self.c.read_only:
            return
        from backend.storage.ddl import init_db
        init_db(self.c)
        # 兼容旧库：补 categories 列（幂等）
        try:
            self.c.execute("ALTER TABLE indicator_def ADD COLUMN IF NOT EXISTS categories VARCHAR")
        except Exception:  # noqa: BLE001
            pass

    def list(self, include_disabled: bool = True) -> list[dict]:
        sql = ("SELECT key,name_cn,category,dtype,direction,kind,expression,params,"
               "categories,layer,parent_key,preset_params,enabled,is_builtin,descr,created_at,"
               "updated_at FROM indicator_def")
        if not include_disabled:
            sql += " WHERE enabled"
        sql += " ORDER BY is_builtin DESC, category, key"
        return [_parse(r) for r in self.c.query_df(sql).to_dict("records")]

    def get(self, key: str) -> dict | None:
        df = self.c.query_df("SELECT * FROM indicator_def WHERE key=?", [key])
        return _parse(df.iloc[0].to_dict()) if not df.empty else None

    def _upsert(self, row: dict) -> None:
        now = datetime.now()
        created = self.c.query_df("SELECT created_at FROM indicator_def WHERE key=?", [row["key"]])
        created_at = created.iloc[0]["created_at"] if not created.empty else now
        self.c.execute(
            "INSERT INTO indicator_def (key,name_cn,category,dtype,direction,kind,expression,"
            "params,categories,layer,parent_key,preset_params,enabled,is_builtin,descr,created_at,"
            "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (key) DO UPDATE SET "
            "name_cn=EXCLUDED.name_cn, category=EXCLUDED.category, dtype=EXCLUDED.dtype, "
            "direction=EXCLUDED.direction, kind=EXCLUDED.kind, expression=EXCLUDED.expression, "
            "params=EXCLUDED.params, categories=EXCLUDED.categories, enabled=EXCLUDED.enabled, "
            "layer=EXCLUDED.layer, parent_key=EXCLUDED.parent_key, "
            "preset_params=EXCLUDED.preset_params, is_builtin=EXCLUDED.is_builtin, "
            "descr=EXCLUDED.descr, updated_at=EXCLUDED.updated_at",
            [row["key"], row["name_cn"], row["category"], row["dtype"], row["direction"],
             row["kind"], row["expression"], row["params"], row.get("categories", "[]"),
             row.get("layer"), row.get("parent_key"), row.get("preset_params", "{}"),
             row["enabled"], row["is_builtin"], row["descr"], created_at, now],
        )

    def save_custom(self, key: str, name_cn: str, dtype: str, expression: str,
                    params: list[dict] | None = None, category: str = "自定义",
                    direction: str | None = None, desc: str = "",
                    categories: list[str] | None = None) -> None:
        """保存/更新自定义表达式指标（校验表达式合法、key 不与内置冲突）。"""
        if not _PARAM_NAME_RE.fullmatch(key):
            raise ValueError("指标标识 key 须以英文字母开头，且只含英文、数字或下划线")
        name_cn = name_cn.strip()
        if not name_cn:
            raise ValueError("请填写指标中文名称")
        expression = expression.strip()
        if not expression:
            raise ValueError("请填写指标表达式")
        exist = self.get(key)
        if exist and exist["is_builtin"]:
            raise ValueError(f"{key} 为内置指标，不可覆盖")
        if dtype not in ("bool", "number"):
            raise ValueError("dtype 须为 bool 或 number")
        params = validate_definition(expression, params)
        cats = categories if categories is not None else (exist["categories"] if exist else [category])
        old_semantic = None if not exist else definition_semantic_signature(
            exist["dtype"], exist["expression"], exist["params"]
        )
        self._upsert({
            "key": key, "name_cn": name_cn, "category": category, "dtype": dtype,
            "direction": direction, "kind": "expr", "expression": expression,
            "params": json.dumps(params, ensure_ascii=False),
            "categories": json.dumps(cats, ensure_ascii=False),
            "layer": "signal" if dtype == "bool" else "metric",
            "parent_key": None, "preset_params": "{}",
            "enabled": bool(exist["enabled"]) if exist else True,
            "is_builtin": False, "descr": desc,
        })
        if old_semantic != definition_semantic_signature(dtype, expression, params):
            from backend.indicators.engine import clear_indicator_caches
            clear_indicator_caches()

    def set_enabled(self, key: str, enabled: bool) -> None:
        self.c.execute("UPDATE indicator_def SET enabled=?, updated_at=? WHERE key=?",
                       [enabled, datetime.now(), key])

    def set_categories(self, key: str, categories: list[str]) -> None:
        self.c.execute("UPDATE indicator_def SET categories=?, updated_at=? WHERE key=?",
                       [json.dumps(categories or [], ensure_ascii=False), datetime.now(), key])

    def delete(self, key: str) -> None:
        d = self.get(key)
        if d and d["is_builtin"]:
            raise ValueError("内置指标不可删除（可禁用）")
        self.c.execute("DELETE FROM indicator_def WHERE key=?", [key])
        from backend.indicators.engine import clear_indicator_caches
        clear_indicator_caches()

    def seed_builtins(self) -> int:
        """内置指标定义入库（幂等；保留用户改过的 enabled 与 categories）。"""
        existing = {
            r["key"]: r
            for r in self.c.query_df(
                "SELECT key,name_cn,category,dtype,direction,kind,expression,params,categories,"
                "layer,parent_key,preset_params,enabled,is_builtin,descr FROM indicator_def "
                "WHERE is_builtin"
            ).to_dict("records")
        }
        compare_fields = (
            "name_cn", "category", "dtype", "direction", "kind", "expression", "params",
            "categories", "layer", "parent_key", "preset_params", "enabled", "is_builtin", "descr",
        )
        changed = 0
        for d in REGISTRY:
            row = _row(d)
            old = existing.get(d.key)
            if old:  # 不覆盖用户对内置的启停 / 分类自定义
                # NULL 是旧库未初始化，不是管理员明确禁用；应回退到 REGISTRY 默认值。
                # 旧版本因数据尚未接入而默认禁用的定义，在数据能力上线后随旧说明一次性校准；
                # 说明已更新后的管理员启停仍按常规保留。
                migrate_legacy_default = (
                    old.get("descr") == _LEGACY_DEFAULT_DISABLED_DESCRIPTIONS.get(d.key)
                )
                if old.get("enabled") is not None and not migrate_legacy_default:
                    row["enabled"] = bool(old["enabled"])
                # SQL NULL 表示旧库尚未初始化分类，应补预设；"[]" 是管理员明确清空，必须保留。
                if isinstance(old.get("categories"), str):
                    row["categories"] = old["categories"]
                if all(old.get(field) == row[field] for field in compare_fields):
                    continue
            self._upsert(row)
            changed += 1
        log.info("内置指标定义校准完成：总数 %d，变更 %d", len(REGISTRY), changed)
        return len(REGISTRY)
