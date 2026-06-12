"""内置预设筛选方案（SDD §8.4）——趋势龙头/两年新高/平台突破/多头/回踩MA20。

每个方案是一棵条件 AST（col + expr 混合）。回踩 MA20 用表达式 `MA(C,20)` 现算，
示范"固定指标 + 动态表达式"协同。
"""

from __future__ import annotations

PRESET_PROFILES: list[dict] = [
    {
        "id": "preset_trend_leader",
        "name": "趋势龙头",
        "expression": {
            "op": "AND",
            "children": [
                {"type": "col", "field": "is_bull_arrange", "cmp": "==", "value": True},
                {"type": "col", "field": "is_high_2y", "cmp": "==", "value": True},
                {"op": "OR", "children": [
                    {"type": "col", "field": "is_vol_breakout", "cmp": "==", "value": True},
                    {"type": "col", "field": "is_platform_breakout", "cmp": "==", "value": True},
                ]},
                {"type": "col", "field": "rs_pct", "cmp": ">=", "value": 90},
            ],
        },
    },
    {
        "id": "preset_high_2y",
        "name": "两年新高",
        "expression": {"type": "col", "field": "is_high_2y", "cmp": "==", "value": True},
    },
    {
        "id": "preset_platform_breakout",
        "name": "平台突破",
        "expression": {"type": "col", "field": "is_platform_breakout", "cmp": "==", "value": True},
    },
    {
        "id": "preset_bull_arrange",
        "name": "多头排列",
        "expression": {"type": "col", "field": "is_bull_arrange", "cmp": "==", "value": True},
    },
    {
        "id": "preset_pullback_ma20",
        "name": "回踩MA20买点",
        "expression": {
            "op": "AND",
            "children": [
                {"type": "col", "field": "is_bull_arrange", "cmp": "==", "value": True},
                {"type": "col", "field": "ma20_up", "cmp": "==", "value": True},
                # 收盘回踩到 MA20 附近（±3%），表达式现算 MA(C,20)
                {"type": "expr", "expr": "ABS(C - MA(C,20)) / MA(C,20) <= 0.03"},
            ],
        },
    },
]
