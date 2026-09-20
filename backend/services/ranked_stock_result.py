"""统一评分结果行装配：名称、板块、点时 ST 与稳定字段语义。"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd


def parse_sub_scores(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value) if value else {}
    except (TypeError, ValueError):
        return {}


def ranked_rows(market, run_date: date, board: pd.DataFrame) -> list[dict]:
    """把评分快照行转换为各入口共用的评分结果契约。"""
    if board is None or board.empty:
        return []
    codes = board["code"].astype(str).tolist()
    placeholders = ",".join("?" * len(codes))
    basic = market.query_df(
        f"SELECT code, name, board FROM stock_basic WHERE code IN ({placeholders})", codes
    )
    name_map = dict(zip(basic["code"], basic["name"]))
    board_map = dict(zip(basic["code"], basic["board"]))
    from backend.services.stock_st_status import StockSTStatusService

    status_map = StockSTStatusService(market).status_map(run_date, codes)
    rows = []
    for _, row in board.iterrows():
        code = str(row["code"])
        rows.append({
            "rank": int(row["rank"]),
            "code": code,
            "name": name_map.get(code),
            "board": board_map.get(code),
            "total_score": round(float(row["total_score"]), 2),
            "grade": str(row.get("grade") or ""),
            "sub_scores": parse_sub_scores(row.get("sub_scores")),
            "is_st": bool(status_map[code]),
            "score_status": "ranked",
            "related_boards": [],
            "groups": [],
        })
    return rows
