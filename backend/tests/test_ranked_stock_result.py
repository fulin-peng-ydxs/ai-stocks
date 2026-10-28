from datetime import date

import pandas as pd
import pytest

from backend.services.ranked_stock_result import ranked_page


class _Market:
    def __init__(self, basics: list[dict]):
        self.basics = basics

    def query_df(self, _sql: str, params: list[str]) -> pd.DataFrame:
        allowed = set(params)
        return pd.DataFrame([row for row in self.basics if row["code"] in allowed])


def test_ranked_page_filters_before_paging_and_keeps_market_rank(monkeypatch):
    monkeypatch.setattr(
        "backend.services.stock_board_correlation.StockBoardCorrelationService.get_related_boards",
        lambda *_args, **_kwargs: {},
    )
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


@pytest.mark.parametrize("keyword, related_keyword, expected", [
    ("", " 银行 ", ["600001.SH"]),
    ("", "人工智能", ["300001.SZ"]),
    ("NAME", "", ["688001.SH"]),
    ("300001.sz", "", ["300001.SZ"]),
    ("银行", "", []),
    ("", "NAME", []),
    ("样例", "人工智能", ["300001.SZ"]),
    ("300001", "银行", []),
    ("", "不存在", []),
])
def test_ranked_page_stock_and_related_keywords_are_independent_and_intersect(
    monkeypatch, keyword, related_keyword, expected,
):
    codes = ["600001.SH", "300001.SZ", "688001.SH"]
    board = pd.DataFrame([
        {"code": code, "rank": i + 1, "total_score": 90 - i}
        for i, code in enumerate(codes)
    ])
    market = _Market([
        {"code": code, "name": "NAME" if i == 2 else "样例", "board": "主板"}
        for i, code in enumerate(codes)
    ])
    summaries = {
        codes[0]: {"industry": {"name": "银行"}, "concept": None},
        codes[1]: {"industry": None, "concept": {"name": "人工智能"}},
        codes[2]: {"industry": {"name": "银行"}, "unavailable_reason": "as_of_mismatch"},
    }

    reads = []

    def read(_self, wanted, business_date, *, schedule_missing):
        reads.append(wanted)
        assert wanted == codes
        assert business_date == date(2026, 9, 25)
        assert schedule_missing is False
        return summaries

    monkeypatch.setattr(
        "backend.services.stock_board_correlation.StockBoardCorrelationService.get_related_boards",
        read,
    )
    monkeypatch.setattr(
        "backend.services.stock_st_status.StockSTStatusService.status_map",
        lambda _self, _day, wanted: {code: False for code in wanted},
    )
    total, rows = ranked_page(
        market, date(2026, 9, 25), board, page=1, page_size=50, keyword=keyword,
        related_board_keyword=related_keyword,
    )
    assert total == len(expected)
    assert [row["code"] for row in rows] == expected
    assert bool(reads) is bool(related_keyword.strip())


def test_ranked_search_full_market_paging_and_export_use_batch_reads(monkeypatch, market):
    from backend.devtools.benchmark_stock_board_correlation_read import (
        AS_OF_DATE,
        seed_read_fixture,
    )

    codes = seed_read_fixture(market, 5000)
    market.execute("UPDATE stock_basic SET board=CASE WHEN code<'972500.SZ' "
                   "THEN '主板' ELSE '创业板' END")
    board = pd.DataFrame([
        {"code": code, "rank": i + 1, "total_score": 90}
        for i, code in enumerate(codes)
    ])
    monkeypatch.setattr(
        "backend.services.stock_st_status.StockSTStatusService.status_map",
        lambda _self, _day, wanted: {code: False for code in wanted},
    )
    calls = []
    original_query = market.query_df

    def query(sql, params=None):
        calls.append(sql)
        return original_query(sql, params)

    monkeypatch.setattr(market, "query_df", query)
    total, rows = ranked_page(
        market, AS_OF_DATE, board, page=2, page_size=50,
        listed_boards=["gem"], related_board_keyword="基准概念",
    )
    assert total == 2500
    assert [row["rank"] for row in rows] == list(range(2551, 2601))
    assert len(calls) == 4  # 全量基础信息、冠军、去重行情、当页基础信息，无逐股读取。
    calls.clear()
    exported_total, exported = ranked_page(
        market, AS_OF_DATE, board, page=1, page_size=len(board),
        listed_boards=["gem"], related_board_keyword="基准概念",
    )
    assert exported_total == total
    assert len(exported) == 2500
    assert exported[0]["rank"] == 2501
    assert exported[-1]["rank"] == 5000
    assert len(calls) == 4
