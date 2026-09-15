"""平台技术指标定义维护：跨库引用审计、语义保护与代表性行情试算。"""

from __future__ import annotations

import json
import math
from datetime import date
from typing import Any

import pandas as pd

from backend.indicators.definition import (
    IndicatorDefRepo,
    definition_semantic_signature,
    render_expression,
    validate_definition,
)
from backend.screening.expression import ExprError
from backend.storage.pg_client import get_pg_client


def _loads(raw: Any, fallback: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw) if raw else fallback
    except (TypeError, ValueError):
        return fallback


def _screen_uses(node: Any, key: str) -> bool:
    if not isinstance(node, dict):
        return False
    if node.get("type") == "ind" and node.get("key") == key:
        return True
    if node.get("type") == "col" and node.get("field") == key:
        return True
    return any(_screen_uses(child, key) for child in node.get("children", []))


def _trade_uses(node: Any, key: str) -> bool:
    if not isinstance(node, dict):
        return False
    if node.get("indicator") == key:
        return True
    return any(_trade_uses(child, key) for child in node.get("children", []))


class IndicatorDefinitionService:
    """定义在 DuckDB、用户方案在 PG；所有关联在服务层合并，禁止跨库 JOIN。"""

    def __init__(self, market=None, pg=None):
        self.repo = IndicatorDefRepo(market)
        self.pg = pg or get_pg_client()

    def references(self, key: str) -> dict:
        token = f"%{key}%"
        refs: list[dict] = []
        specs = (
            ("screen", "screen_profile", "expression", False, _screen_uses),
            ("screen", "screen_profile_version", "expression", True, _screen_uses),
            ("score", "score_profile", "items", False,
             lambda payload, target: any(i.get("indicator") == target for i in payload if isinstance(i, dict))),
            ("score", "score_profile_version", "items", True,
             lambda payload, target: any(i.get("indicator") == target for i in payload if isinstance(i, dict))),
        )
        matched_versions: list[tuple[str, str, str, str, int]] = []
        for kind, table, column, historical, matcher in specs:
            df = self.pg.query_df(
                f"SELECT tenant_id,owner_user_id,id,name,version,{column} AS payload "
                f"FROM {table} WHERE {column} LIKE %s", [token]
            )
            for row in df.to_dict("records"):
                payload = _loads(row["payload"], {} if kind == "screen" else [])
                if not matcher(payload, key):
                    continue
                refs.append(self._ref_row(kind, row, historical))
                matched_versions.append((kind, str(row["tenant_id"]), str(row["owner_user_id"]),
                                         str(row["id"]), int(row["version"])))

        for table, historical in (("trade_profile", False), ("trade_profile_version", True)):
            df = self.pg.query_df(
                f"SELECT tenant_id,owner_user_id,id,name,version,buy_tree,sell_tree FROM {table} "
                "WHERE buy_tree LIKE %s OR sell_tree LIKE %s", [token, token]
            )
            for row in df.to_dict("records"):
                if not (_trade_uses(_loads(row["buy_tree"], {}), key)
                        or _trade_uses(_loads(row["sell_tree"], {}), key)):
                    continue
                refs.append(self._ref_row("trade", row, historical))
                matched_versions.append(("trade", str(row["tenant_id"]), str(row["owner_user_id"]),
                                         str(row["id"]), int(row["version"])))

        run_ids: set[str] = set()
        for kind in ("screen", "score", "trade"):
            targets = sorted({item[1:] for item in matched_versions if item[0] == kind})
            if not targets:
                continue
            id_col, version_col = {
                "screen": ("profile_id", "profile_version"),
                "score": ("score_profile_id", "score_profile_version"),
                "trade": ("trade_profile_id", "trade_profile_version"),
            }[kind]
            tuples = ",".join(["(%s,%s,%s,%s)"] * len(targets))
            params = [value for target in targets for value in target]
            df = self.pg.query_df(
                f"SELECT id FROM backtest_run WHERE (tenant_id,owner_user_id,{id_col},{version_col}) "
                f"IN ({tuples})", params,
            )
            run_ids.update(str(value) for value in df.get("id", []))
        # 当前表与版本表会同时保存当前版本；同一方案版本只展示一次，当前态优先于历史态。
        unique: dict[tuple, dict] = {}
        for item in refs:
            identity = (item["kind"], item["_tenant_id"], item["_owner_user_id"],
                        item["id"], item["version"])
            if identity not in unique or not item["historical"]:
                unique[identity] = item
        refs = sorted(
            unique.values(),
            key=lambda item: (item["kind"], item["name"], item["version"], item["historical"]),
        )
        for item in refs:
            item.pop("_tenant_id", None)
            item.pop("_owner_user_id", None)
        return {"key": key, "count": len(refs), "backtest_count": len(run_ids), "items": refs}

    @staticmethod
    def _ref_row(kind: str, row: dict, historical: bool) -> dict:
        return {
            "kind": kind,
            "id": str(row["id"]),
            "name": str(row["name"]),
            "version": int(row["version"]),
            "historical": historical,
            "_tenant_id": str(row["tenant_id"]),
            "_owner_user_id": str(row["owner_user_id"]),
        }

    def save(self, body: dict, *, key: str | None = None) -> dict:
        target_key = key or str(body.get("key") or "")
        existing = self.repo.get(target_key)
        if key is None and existing:
            raise ValueError("指标 key 已存在；请使用编辑接口或更换 key")
        if key is not None and existing is None:
            raise LookupError("指标不存在")
        if existing and existing["is_builtin"]:
            raise ValueError("内置指标不可编辑")
        normalized = validate_definition(str(body.get("expression") or ""), body.get("params"))
        if existing:
            old_semantic = definition_semantic_signature(
                existing["dtype"], existing["expression"], existing["params"]
            )
            new_semantic = definition_semantic_signature(body["dtype"], body["expression"], normalized)
            if old_semantic != new_semantic and self.references(target_key)["count"]:
                raise ValueError("指标已被方案引用，计算类型、表达式和参数结构不可原地修改；请另存为新指标")
        self.repo.save_custom(
            target_key, body["name_cn"], body["dtype"], body["expression"],
            params=normalized, category=body.get("category", "自定义"),
            direction=body.get("direction"), desc=body.get("desc", ""),
            categories=body.get("categories"),
        )
        return self.repo.get(target_key) or {"key": target_key}

    def delete(self, key: str) -> None:
        if self.repo.get(key) is None:
            raise LookupError("指标不存在")
        references = self.references(key)
        if references["count"]:
            raise IndicatorReferenceError(references)
        self.repo.delete(key)

    def preview(self, body: dict) -> dict:
        from backend.indicators.engine import IndicatorEngine

        params = validate_definition(body["expression"], body.get("params"))
        values = body.get("values") or {}
        rendered = render_expression(body["expression"], values, params)
        code = body["code"]
        asof = body.get("trade_date")
        if asof is None:
            raw = self.repo.c.query_df(
                "SELECT max(trade_date) AS d FROM daily_bar WHERE code=?", [code]
            ).iloc[0]["d"]
            if pd.isna(raw):
                raise ValueError("股票没有可用于试算的历史行情")
            asof = pd.Timestamp(raw).date()
        elif isinstance(asof, str):
            asof = date.fromisoformat(asof)
        count = int(self.repo.c.query_df(
            "SELECT count(*) AS n FROM daily_bar WHERE code=? AND trade_date<=?", [code, asof]
        ).iloc[0]["n"])
        if count == 0:
            raise ValueError("该股票在所选日期前没有行情数据")
        effective = {p["name"]: values.get(p["name"], p["default"]) for p in params}
        try:
            result = IndicatorEngine(self.repo.c)._eval_expr_indicator(
                body["expression"], values, params, asof, [code], strict=True
            )
            value = result.get(code)
        except ExprError as exc:
            status = "missing_field" if "未知变量" in str(exc) else "expression_error"
            return self._preview_failure(status, str(exc), code, asof, rendered, effective)
        except Exception as exc:  # noqa: BLE001
            return self._preview_failure(
                "expression_error", f"表达式计算失败: {exc}", code, asof, rendered, effective
            )
        required_history = max([
            2,
            *(
                int(v) + 1 for v in effective.values()
                if isinstance(v, (int, float))
                and not isinstance(v, bool)
                and float(v).is_integer()
            ),
        ])
        if value is None or pd.isna(value):
            return {
                "status": "history_insufficient" if count < required_history else "empty_result",
                "reason": "历史数据不足" if count < required_history else "表达式结果为空",
                "code": code, "trade_date": str(asof), "rendered_expression": rendered,
                "effective_params": effective,
                "value": None,
            }
        if hasattr(value, "item"):
            value = value.item()
        if body["dtype"] == "number" and not math.isfinite(float(value)):
            return self._preview_failure(
                "expression_error", "表达式结果不是有限数值", code, asof, rendered, effective
            )
        return {
            "status": "ok", "reason": "", "code": code, "trade_date": str(asof),
            "rendered_expression": rendered,
            "effective_params": effective,
            "value": bool(value) if body["dtype"] == "bool" else float(value),
        }

    @staticmethod
    def _preview_failure(
        status: str,
        reason: str,
        code: str,
        asof: date,
        rendered: str,
        effective: dict,
    ) -> dict:
        """保持所有试算失败类型使用同一稳定响应结构。"""
        return {
            "status": status,
            "reason": reason,
            "code": code,
            "trade_date": str(asof),
            "rendered_expression": rendered,
            "effective_params": effective,
            "value": None,
        }


class IndicatorReferenceError(ValueError):
    def __init__(self, references: dict):
        super().__init__("指标仍被方案引用，不能删除")
        self.references = references
