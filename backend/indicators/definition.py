"""指标定义仓库（M2.1b）——统一管理内置 + 自定义技术指标的"定义"。

- 内置指标（registry.REGISTRY）seed 进 indicator_def 表，kind=builtin/expr、is_builtin=True（不可删，仅启停）。
- 自定义指标：用户保存一段带 {参数} 占位的 DSL 表达式，kind=expr、is_builtin=False。
- 表达式在使用时由 IndicatorEngine 渲染参数 → 逐股点时求值（复用 expression DSL 沙箱）。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime

from backend.common.logging import get_logger
from backend.indicators.registry import REGISTRY, preset_categories
from backend.screening.expression import ExprError, validate_expr
from backend.storage.duckdb_client import get_client

log = get_logger("indicators.definition")


def render_expression(template: str, params: dict | None, param_defs: list[dict] | None = None) -> str:
    """把表达式模板的 {param} 占位用参数值渲染为可执行表达式，并做白名单校验。"""
    merged: dict = {}
    for pd_ in (param_defs or []):
        merged[pd_["name"]] = pd_.get("default")
    for k, v in (params or {}).items():
        merged[k] = v
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
    return {
        "key": d.key, "name_cn": d.name_cn, "category": d.category, "dtype": d.dtype,
        "direction": d.direction, "kind": d.kind, "expression": d.expression,
        "params": json.dumps([asdict(p) for p in d.params], ensure_ascii=False),
        "categories": json.dumps(preset_categories(d.key, d.category), ensure_ascii=False),
        "enabled": d.enabled, "is_builtin": d.is_builtin, "descr": d.desc,
    }


def _parse(r: dict) -> dict:
    r = dict(r)
    r["params"] = json.loads(r["params"]) if r.get("params") else []
    r["categories"] = json.loads(r["categories"]) if r.get("categories") else []
    r["desc"] = r.pop("descr", "")
    for k in ("created_at", "updated_at"):
        if r.get(k) is not None:
            r[k] = str(r[k])
    return r


class IndicatorDefRepo:
    def __init__(self, client=None):
        self.c = client or get_client()
        from backend.storage.ddl import init_db
        init_db(self.c)
        # 兼容旧库：补 categories 列（幂等）
        try:
            self.c.execute("ALTER TABLE indicator_def ADD COLUMN IF NOT EXISTS categories VARCHAR")
        except Exception:  # noqa: BLE001
            pass

    def list(self, include_disabled: bool = True) -> list[dict]:
        sql = ("SELECT key,name_cn,category,dtype,direction,kind,expression,params,"
               "categories,enabled,is_builtin,descr,created_at,updated_at FROM indicator_def")
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
            "params,categories,enabled,is_builtin,descr,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (key) DO UPDATE SET "
            "name_cn=EXCLUDED.name_cn, category=EXCLUDED.category, dtype=EXCLUDED.dtype, "
            "direction=EXCLUDED.direction, kind=EXCLUDED.kind, expression=EXCLUDED.expression, "
            "params=EXCLUDED.params, categories=EXCLUDED.categories, enabled=EXCLUDED.enabled, "
            "is_builtin=EXCLUDED.is_builtin, descr=EXCLUDED.descr, updated_at=EXCLUDED.updated_at",
            [row["key"], row["name_cn"], row["category"], row["dtype"], row["direction"],
             row["kind"], row["expression"], row["params"], row.get("categories", "[]"),
             row["enabled"], row["is_builtin"], row["descr"], created_at, now],
        )

    def save_custom(self, key: str, name_cn: str, dtype: str, expression: str,
                    params: list[dict] | None = None, category: str = "自定义",
                    direction: str | None = None, desc: str = "",
                    categories: list[str] | None = None) -> None:
        """保存/更新自定义表达式指标（校验表达式合法、key 不与内置冲突）。"""
        if not key or not key.replace("_", "").isalnum():
            raise ValueError("指标标识 key 须为英文/数字/下划线")
        exist = self.get(key)
        if exist and exist["is_builtin"]:
            raise ValueError(f"{key} 为内置指标，不可覆盖")
        if dtype not in ("bool", "number"):
            raise ValueError("dtype 须为 bool 或 number")
        params = params or []
        render_expression(expression, None, params)  # 用默认参数试渲染 + 白名单校验
        cats = categories if categories is not None else (exist["categories"] if exist else [category])
        self._upsert({
            "key": key, "name_cn": name_cn, "category": category, "dtype": dtype,
            "direction": direction, "kind": "expr", "expression": expression,
            "params": json.dumps(params, ensure_ascii=False),
            "categories": json.dumps(cats, ensure_ascii=False),
            "enabled": True, "is_builtin": False, "descr": desc,
        })

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

    def seed_builtins(self) -> int:
        """内置指标定义入库（幂等；保留用户改过的 enabled 与 categories）。"""
        existing = {r["key"]: r for r in self.list()}
        for d in REGISTRY:
            row = _row(d)
            old = existing.get(d.key)
            if old:  # 不覆盖用户对内置的启停 / 分类自定义
                row["enabled"] = old["enabled"]
                if old.get("categories"):
                    row["categories"] = json.dumps(old["categories"], ensure_ascii=False)
            self._upsert(row)
        log.info("内置指标定义入库 %d 个", len(REGISTRY))
        return len(REGISTRY)
