"""板块自选业务编排：PG 保存选择，DuckDB 提供板块事实与行情。"""

from __future__ import annotations

from datetime import date

from backend.groups.board_watchlist import BoardWatchlistRepo
from backend.services.board_query import SORT_FIELDS, BoardQueryService


class BoardWatchlistService:
    def __init__(self, repo: BoardWatchlistRepo | None = None, market: BoardQueryService | None = None):
        self.repo = repo or BoardWatchlistRepo()
        self.market = market or BoardQueryService()

    def list(self) -> dict:
        rows = self.repo.list()
        return {"list": rows, "total": len(rows)}

    def add(self, board_code: str) -> dict:
        detail = self.market.get_sector(board_code)
        if detail is None:
            raise ValueError("板块不存在或尚未采集")
        added = self.repo.add(board_code, detail["name"], detail["board_type"])
        return {"board_code": board_code, "added": added}

    def remove(self, board_code: str) -> dict:
        return {"board_code": board_code, "removed": self.repo.remove(board_code)}

    def list_markets(
        self,
        *,
        trade_date: date | None = None,
        board_type: str | None = None,
        sort_by: str = "pct_today",
        order: str = "desc",
        keyword: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """返回自选板块的当前行情；已失效板块保留快照并明确标记 unavailable。"""
        entries = self.repo.list()
        codes = {entry["board_code"] for entry in entries}
        current = self.market.list_sectors(
            trade_date=trade_date,
            board_codes=codes,
            page=1,
            size=max(len(codes), 1),
        )
        current_by_code = {row["board_code"]: row for row in current["list"]}
        rows: list[dict] = []
        for entry in entries:
            row = current_by_code.get(entry["board_code"])
            if row is not None:
                rows.append({**row, "available": True, "added_at": entry["added_at"]})
                continue
            rows.append({
                "board_code": entry["board_code"],
                "app_code": None,
                "name": entry["name"],
                "board_type": entry["board_type"],
                "member_count": None,
                "has_members": False,
                "has_bar": False,
                "has_fund_flow": False,
                "pct_today": None,
                "pct_5d": None,
                "pct_10d": None,
                "pct_20d": None,
                "net_inflow": None,
                "leader_stock": None,
                "leader_pct": None,
                "up_count": 0,
                "down_count": 0,
                "available": False,
                "added_at": entry["added_at"],
            })

        if board_type:
            rows = [row for row in rows if row["board_type"] == board_type]
        if keyword:
            needle = keyword.strip().lower()
            rows = [
                row for row in rows
                if needle in row["name"].lower() or needle in row["board_code"].lower()
            ]
        if sort_by in SORT_FIELDS:
            rows.sort(
                key=lambda row: (
                    row.get("available") is False,
                    row.get(sort_by) is None,
                    (
                        -float(row[sort_by])
                        if order == "desc" and row.get(sort_by) is not None
                        else float(row[sort_by]) if row.get(sort_by) is not None else 0
                    ),
                    row["board_code"],
                ),
            )

        total = len(rows)
        start = (page - 1) * size
        return {
            "list": rows[start:start + size],
            "total": total,
            "trade_date": current["trade_date"],
            "fund_flow_date": current["fund_flow_date"],
            "page": page,
            "size": size,
        }
