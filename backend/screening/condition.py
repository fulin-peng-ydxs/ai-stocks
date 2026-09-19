"""筛选条件 AST（SDD §8.2）——解析/校验 + 通用求值框架。

AST（嵌套 JSON dict）：
- 逻辑节点：{"op": "AND"|"OR"|"NOT", "children": [...]}
- 注册表指标叶子(ind)：{"type":"ind","key":"near_ma","params":{"n":5,"tol":1},"cmp":">=","value":1[, "ignore":false]}
  （v2.0 §8：内置→快照列向量化；表达式型/自定义→渲染参数后逐股点时求值。统一从指标注册表取指标。）
- 固定指标叶子(col)：{"type":"col","field":"rs_pct","cmp":">=","value":95[, "ignore":false]}（旧格式，仍兼容）
- 动态表达式叶子(expr)：{"type":"expr","expr":"COUNT(C>REF(C,1),5)==5"[, "ignore":false]}

本模块只管"结构与语义校验"和"按回调求值的合并逻辑"，不接触数据；
具体"col/expr 叶子如何在某交易日对全市场求值"由 ScreenEngine 提供回调（§8.3）。
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from backend.screening.expression import ExprError, validate_expr

_LOGIC = {"AND", "OR", "NOT"}
_CMP = {"==", "!=", ">", ">=", "<", "<=", "between"}


class ConditionError(Exception):
    """AST 结构/语义非法。"""


def is_node_enabled(node: dict) -> bool:
    """历史节点缺省启用；兼容旧 ``ignore=true`` 语义。"""
    return node.get("enabled", not bool(node.get("ignore", False))) is not False


def prune_disabled_ast(node: dict) -> dict | None:
    """裁剪停用叶子及其空分组，避免 AND/OR/NOT 中用常量替代造成语义偏差。"""
    if not isinstance(node, dict):
        return None
    if "op" not in node:
        return dict(node) if is_node_enabled(node) else None
    children = [
        active for child in node.get("children", [])
        if (active := prune_disabled_ast(child)) is not None
    ]
    if not children:
        return None
    op = str(node.get("op", "")).upper()
    if op in {"AND", "OR"} and len(children) == 1:
        return children[0]
    out = dict(node)
    out["children"] = children
    return out


def validate_ast(node: dict, *, require_active: bool = False) -> None:
    """递归校验 AST 合法性，非法抛 ConditionError。"""
    if not isinstance(node, dict):
        raise ConditionError(f"节点必须是对象: {node!r}")
    if "enabled" in node and not isinstance(node["enabled"], bool):
        raise ConditionError("enabled 须为布尔值")
    if "op" in node:
        op = str(node["op"]).upper()
        if op not in _LOGIC:
            raise ConditionError(f"未知逻辑运算: {node['op']}")
        children = node.get("children")
        if not isinstance(children, list) or not children:
            raise ConditionError(f"{op} 缺少 children")
        if op == "NOT" and len(children) != 1:
            raise ConditionError("NOT 只能有一个子节点")
        for c in children:
            validate_ast(c)
        if require_active and prune_disabled_ast(node) is None:
            raise ConditionError("至少需要一个已启用的筛选条件")
        return
    t = node.get("type")
    if t == "ind":
        if not node.get("key"):
            raise ConditionError("ind 叶子缺少 key")
        if node.get("cmp") not in _CMP:
            raise ConditionError(f"ind 叶子 cmp 非法: {node.get('cmp')}")
        if node.get("cmp") == "between":
            v = node.get("value")
            if not (isinstance(v, (list, tuple)) and len(v) == 2):
                raise ConditionError("between 的 value 须为 [下限, 上限]")
    elif t == "col":
        if not node.get("field"):
            raise ConditionError("col 叶子缺少 field")
        if node.get("cmp") not in _CMP:
            raise ConditionError(f"col 叶子 cmp 非法: {node.get('cmp')}")
        if node.get("cmp") == "between":
            v = node.get("value")
            if not (isinstance(v, (list, tuple)) and len(v) == 2):
                raise ConditionError("between 的 value 须为 [下限, 上限]")
    elif t == "expr":
        if not node.get("expr"):
            raise ConditionError("expr 叶子缺少 expr")
        validate_expr(node["expr"])  # 表达式白名单校验（防注入）
    else:
        raise ConditionError(f"叶子缺少合法 type(col/expr): {node!r}")
    if require_active and not is_node_enabled(node):
        raise ConditionError("至少需要一个已启用的筛选条件")


def collect_leaves(node: dict) -> tuple[list[dict], list[dict]]:
    """收集所有 col 叶子与 expr 叶子（供引擎预取列/预编译表达式）。"""
    cols, exprs = [], []

    def walk(n):
        if "op" in n:
            for c in n["children"]:
                walk(c)
        elif n.get("type") == "col":
            cols.append(n)
        elif n.get("type") == "expr":
            exprs.append(n)

    walk(node)
    return cols, exprs


def collect_indicator_leaves(node: dict) -> list[dict]:
    """收集注册表指标叶子，供执行器统一批量补齐表达式指标。"""
    indicators: list[dict] = []

    def walk(n: dict) -> None:
        if "op" in n:
            for child in n.get("children", []):
                walk(child)
        elif n.get("type") == "ind":
            indicators.append({"indicator": n["key"], "params": n.get("params")})

    walk(node)
    return indicators


def eval_ast(node: dict, eval_leaf: Callable[[dict], pd.Series]) -> pd.Series:
    """按 AST 合并各叶子结果（布尔 Series，索引=code）。

    eval_leaf(leaf) → 该叶子对当前票池的布尔 Series（引擎实现，已处理 NULL→False 与 ignore）。
    """
    if "op" in node:
        op = str(node["op"]).upper()
        if op == "NOT":
            return ~eval_ast(node["children"][0], eval_leaf).fillna(False)
        results = [eval_ast(c, eval_leaf).fillna(False) for c in node["children"]]
        res = results[0]
        for r in results[1:]:
            res = (res & r) if op == "AND" else (res | r)
        return res
    return eval_leaf(node).fillna(False)


__all__ = [
    "ConditionError",
    "ExprError",
    "collect_indicator_leaves",
    "collect_leaves",
    "eval_ast",
    "is_node_enabled",
    "prune_disabled_ast",
    "validate_ast",
]
