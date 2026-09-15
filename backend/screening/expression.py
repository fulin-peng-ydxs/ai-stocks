"""表达式 DSL 安全沙箱（SDD §8.5）——把用户写的筛选表达式安全地算成布尔 Series。

设计：
- 用 Python `ast` 解析表达式，再**白名单遍历求值**：只允许 变量名 / 白名单函数调用 /
  二元算术 / 比较 / 布尔(and·or·not 与 &·|·~) / 一元 / 常量。
- **禁止**属性访问、下标、推导式、lambda、import、任意函数——杜绝代码注入。
- 变量与函数对 pandas Series 运算，结果通常是布尔 Series（按交易日对齐该股序列）。
- 点时安全：序列由调用方传入（仅含 ≤T）；算子全后向（REF 拒负移）。

变量约定（由调用方在 context 提供）：
  C/O/H/L 前复权 收/开/高/低，V 量，TURN 换手率，以及指标列名(ma20/rs_pct/...)。
函数：MA/HHV/LLV/REF/COUNT/SUM/ABS（复用 indicators.operators）。
"""

from __future__ import annotations

import ast
import operator as pyop
from itertools import pairwise

import pandas as pd

from backend.indicators import operators as ops


class ExprError(Exception):
    """表达式非法（语法不支持 / 未知变量函数 / 含注入风险）。"""


def _SUM(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(int(n), min_periods=int(n)).sum()


# 白名单函数（全部后向、点时安全）
ALLOWED_FUNCS = {
    "MA": ops.MA, "HHV": ops.HHV, "LLV": ops.LLV,
    "REF": ops.REF, "COUNT": ops.COUNT, "SUM": _SUM,
    "ABS": lambda x: x.abs() if hasattr(x, "abs") else abs(x),
}

_BINOPS = {
    ast.Add: pyop.add, ast.Sub: pyop.sub, ast.Mult: pyop.mul,
    ast.Div: pyop.truediv, ast.BitAnd: pyop.and_, ast.BitOr: pyop.or_,
}
_CMP = {
    ast.Gt: pyop.gt, ast.GtE: pyop.ge, ast.Lt: pyop.lt,
    ast.LtE: pyop.le, ast.Eq: pyop.eq, ast.NotEq: pyop.ne,
}


def validate_expr(expr: str) -> None:
    """仅做语法/白名单校验（不需数据），非法抛 ExprError。"""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ExprError(f"表达式语法错误: {e}") from e
    _check(tree.body)


def validate_scale_invariant_expr(expr: str) -> None:
    """校验表达式是否不受价格序列整体缩放影响。

    回测区间批算使用统一 qfq 基准；只有比较两侧价格量纲一致时，结果才与逐日
    rebase 一致。比如 ``C > O``、``C / REF(C, 1) > 1.05`` 合法，``C > 50``
    会因复权基准改变而失真，必须拒绝。
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"表达式语法错误: {exc}") from exc
    _check(tree.body)
    _price_dimension(tree.body)


def _price_dimension(node) -> int:
    """返回价格缩放指数；比较/布尔表达式返回 0，量纲不一致时抛错。"""
    if isinstance(node, ast.Constant):
        return 0
    if isinstance(node, ast.Name):
        return 1 if node.id in {"C", "O", "H", "L"} else 0
    if isinstance(node, ast.UnaryOp):
        return _price_dimension(node.operand)
    if isinstance(node, ast.BoolOp):
        for value in node.values:
            if _price_dimension(value) != 0:
                raise ExprError("布尔运算只能连接条件表达式")
        return 0
    if isinstance(node, ast.Compare):
        dims = [_price_dimension(node.left)]
        dims.extend(_price_dimension(comp) for comp in node.comparators)
        if any(left != right for left, right in pairwise(dims)):
            raise ExprError(
                "回测不支持受复权基准影响的绝对价格比较；"
                "请改用价格比率、同量纲比较或注册表指标"
            )
        return 0
    if isinstance(node, ast.BinOp):
        left = _price_dimension(node.left)
        right = _price_dimension(node.right)
        if isinstance(node.op, (ast.Add, ast.Sub)):
            if left != right:
                raise ExprError("加减运算两侧价格量纲必须一致")
            return left
        if isinstance(node.op, ast.Mult):
            return left + right
        if isinstance(node.op, ast.Div):
            return left - right
        if isinstance(node.op, (ast.BitAnd, ast.BitOr)):
            if left != 0 or right != 0:
                raise ExprError("布尔运算只能连接条件表达式")
            return 0
    if isinstance(node, ast.Call):
        name = node.func.id
        if name == "COUNT":
            return 0
        return _price_dimension(node.args[0]) if node.args else 0
    raise ExprError(f"无法判断表达式价格量纲: {type(node).__name__}")


def _check(node) -> None:
    """白名单遍历校验：遇到不允许的节点立即报错。"""
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float, bool)):
            raise ExprError(f"不允许的常量类型: {type(node.value).__name__}")
    elif isinstance(node, ast.Name):
        return  # 变量合法性在求值时按 context 校验
    elif isinstance(node, ast.BinOp):
        if type(node.op) not in _BINOPS:
            raise ExprError(f"不支持的运算符: {type(node.op).__name__}")
        _check(node.left); _check(node.right)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.USub, ast.Not, ast.Invert)):
            raise ExprError(f"不支持的一元运算: {type(node.op).__name__}")
        _check(node.operand)
    elif isinstance(node, ast.BoolOp):  # and / or
        for v in node.values:
            _check(v)
    elif isinstance(node, ast.Compare):
        for op in node.ops:
            if type(op) not in _CMP:
                raise ExprError(f"不支持的比较: {type(op).__name__}")
        _check(node.left)
        for c in node.comparators:
            _check(c)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCS:
            raise ExprError(f"未知或不允许的函数: {ast.dump(node.func)}")
        if node.keywords:
            raise ExprError("函数不支持关键字参数")
        for a in node.args:
            _check(a)
    else:
        raise ExprError(f"不支持的语法节点: {type(node).__name__}（疑似注入或越权）")


def eval_expr(expr: str, context: dict) -> pd.Series:
    """在 context（变量名→Series/标量）下安全求值，返回 Series。"""
    tree = ast.parse(expr, mode="eval")
    _check(tree.body)
    return _eval(tree.body, context)


def _to_bool_series(x):
    """把布尔结果规整为 pandas boolean Series（NaN→False 由上层处理）。"""
    return x


def _eval(node, ctx):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in ctx:
            raise ExprError(f"未知变量: {node.id}")
        return ctx[node.id]
    if isinstance(node, ast.BinOp):
        return _BINOPS[type(node.op)](_eval(node.left, ctx), _eval(node.right, ctx))
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, ctx)
        if isinstance(node.op, ast.USub):
            return -v
        # Not / Invert → 按元素取反（对布尔 Series 用 ~）
        return ~v if hasattr(v, "__invert__") else (not v)
    if isinstance(node, ast.BoolOp):
        vals = [_eval(v, ctx) for v in node.values]
        combine = pyop.and_ if isinstance(node.op, ast.And) else pyop.or_
        res = vals[0]
        for v in vals[1:]:
            res = combine(res, v)
        return res
    if isinstance(node, ast.Compare):
        left = _eval(node.left, ctx)
        res = None
        for op, comp in zip(node.ops, node.comparators):
            right = _eval(comp, ctx)
            r = _CMP[type(op)](left, right)
            res = r if res is None else (res & r)
            left = right
        return res
    if isinstance(node, ast.Call):
        fn = ALLOWED_FUNCS[node.func.id]
        return fn(*[_eval(a, ctx) for a in node.args])
    raise ExprError(f"不支持的语法节点: {type(node).__name__}")
