from datetime import date

import pandas as pd

from backend.services.ranked_stock_result import ranked_page


class _Market:
    def __init__(self, basics: list[dict]):
        self.basics = basics

    def query_df(self, _sql: str, params: list[str]) -> pd.DataFrame:
        allowed = set(params)
        return pd.DataFrame([row for row in self.basics if row["code"] in allowed])


def test_ranked_page_filters_before_paging_and_keeps_market_rank(monkeypatch):
    board = pd.DataFrame([
        {"code": "600001.SH", "rank": 1, "total_score": 99, "grade": "A", "sub_scores": "{}"},
        {"code": "300001.SZ", "rank": 2, "total_score": 98, "grade": "A", "sub_scores": "{}"},
        {"code": "688001.SH", "rank": 3, "total_score": 97, "grade": "B", "sub_scores": "{}"},
        {"code": "300002.SZ", "rank": 4, "total_score": 96, "grade": "B", "sub_scores": "{}"},
    ])
    market = _Market([
        {"code": "600001.SH", "name": "主板样例", "board": "主板"},
        {"code": "300001.SZ", "name": "成长一号", "board": "创业板"},
        {"code": "688001.SH", "name": "科创样例", "board": "科创板"},
        {"code": "300002.SZ", "name": "成长二号", "board": "创业板"},
    ])
    monkeypatch.setattr(
        "backend.services.stock_st_status.StockSTStatusService.status_map",
        lambda _self, _run_date, codes: {code: False for code in codes},
    )

    total, rows = ranked_page(
        market,
        date(2026, 9, 25),
        board,
        page=2,
        page_size=1,
        listed_boards=["gem"],
        keyword="成长",
    )

    assert total == 2
    assert [row["code"] for row in rows] == ["300002.SZ"]
    assert rows[0]["rank"] == 4
