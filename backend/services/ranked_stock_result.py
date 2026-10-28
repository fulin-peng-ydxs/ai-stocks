"""统一评分结果行装配：名称、板块、点时 ST 与稳定字段语义。"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from backend.services.listed_boards import listed_board_labels


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


def ranked_page(
    market,
    run_date: date,
    board: pd.DataFrame,
    *,
    page: int,
    page_size: int,
    listed_boards: list[str] | None = None,
    keyword: str = "",
    related_board_keyword: str = "",
) -> tuple[int, list[dict]]:
    """按股票、走势板块名称和上市板块过滤，保留快照的全市场排名后分页。

    PG 评分快照与 DuckDB 股票基础信息分别读取后在服务层合并，不做跨库 JOIN。
    仅对当前页装配 ST 状态等扩展字段，避免分页后仍对全量股票做二次查询。
    """
    if board is None or board.empty:
        return 0, []

    codes = board["code"].astype(str).tolist()
    placeholders = ",".join("?" * len(codes))
    basic = market.query_df(
        f"SELECT code, name, board FROM stock_basic WHERE code IN ({placeholders})", codes
    )
    basic_by_code = {}
    for _, row in basic.iterrows():
        name = row.get("name")
        listed_board = row.get("board")
        basic_by_code[str(row["code"])] = {
            "name": "" if pd.isna(name) else str(name),
            "board": "" if pd.isna(listed_board) else str(listed_board),
        }
    selected_labels = set(listed_board_labels(listed_boards))
    normalized_keyword = keyword.strip().casefold()
    normalized_related_keyword = related_board_keyword.strip().casefold()
    related_by_code = {}
    if normalized_related_keyword:
        from backend.services.stock_board_correlation import StockBoardCorrelationService

        # 与表格共用按业务日读取及样本不足历史回退口径，不以累计所属板块替代走势冠军。
        # 搜索扫描全榜时只读已有结果，避免一次输入为全市场创建首次计算任务。
        related_by_code = StockBoardCorrelationService(market).get_related_boards(
            codes, run_date, schedule_missing=False,
        )

    matched_indexes: list[int] = []
    for index, row in board.iterrows():
        code = str(row["code"])
        info = basic_by_code.get(code, {"name": "", "board": ""})
        if selected_labels and info["board"] not in selected_labels:
            continue
        if normalized_keyword and not any(
            normalized_keyword in text.casefold() for text in (code, info["name"])
        ):
            continue
        if normalized_related_keyword:
            summary = related_by_code.get(code) or {}
            names = []
            if not summary.get("unavailable_reason"):
                names = [
                    winner.get("name", "")
                    for kind in ("industry", "concept")
                    if (winner := summary.get(kind))
                ]
            if not any(
                normalized_related_keyword in str(text or "").casefold() for text in names
            ):
                continue
        matched_indexes.append(index)

    total = len(matched_indexes)
    start = (page - 1) * page_size
    page_indexes = matched_indexes[start:start + page_size]
    if not page_indexes:
        return total, []
    return total, ranked_rows(market, run_date, board.loc[page_indexes])
