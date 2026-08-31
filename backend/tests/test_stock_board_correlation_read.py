"""个股走势关联板块 T6：批量摘要、日期保护和后端消费点。"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backend.api.stocks import list_stocks
from backend.services.screen_score import ScreenScoreService
from backend.services.stock_board_correlation import StockBoardCorrelationService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


class _CountingClient:
    def __init__(self, delegate: DuckDBClient):
        self.delegate = delegate
        self.queries: list[str] = []

    def query_df(self, sql, params=None):
        self.queries.append(sql)
        return self.delegate.query_df(sql, params)

    def temp_view(self, frame, name):
        return self.delegate.temp_view(frame, name)


def _seed_summary(client: DuckDBClient, *, as_of: date = date(2026, 8, 28)) -> None:
    client.execute(
        "INSERT INTO board_dict (board_code,name,board_type) VALUES ('881001','银行','industry')"
    )
    client.execute(
        "INSERT INTO stock_board_correlation_state "
        "(code,as_of_date,computed_at,algorithm_version,benchmark_code,benchmark_fallback,"
        "has_industry_champion,has_concept_champion) VALUES "
        "('600000.SH',?,TIMESTAMP '2026-08-29 10:00:00','stock-board-correlation-v2',"
        "'399001.SZ',false,true,true),"
        "('000001.SZ',?,TIMESTAMP '2026-08-29 10:00:00','stock-board-correlation-v2',"
        "'000001.SH',true,false,false)",
        [as_of, as_of],
    )
    client.execute(
        "INSERT INTO stock_board_correlation "
        "(code,board_type,board_code,score,corr_20,corr_60,sample_20,sample_60,confidence,"
        "benchmark_code,benchmark_fallback,as_of_date,computed_at,algorithm_version) VALUES "
        "('600000.SH','industry','881001',0.82,0.86,0.76,20,58,'high',"
        "'399001.SZ',false,?,TIMESTAMP '2026-08-29 10:00:00','stock-board-correlation-v2'),"
        "('600000.SH','concept','missing-board',0.51,0.55,0.45,18,50,'medium',"
        "'399001.SZ',false,?,TIMESTAMP '2026-08-29 10:00:00','stock-board-correlation-v2')",
        [as_of, as_of],
    )


def test_batch_summary_reads_per_day_snapshot():
    as_of = date(2026, 8, 28)
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_summary(market, as_of=as_of)
        service = StockBoardCorrelationService(market)

        result = service.get_related_boards(
            ["600000.sh", "000001.SZ", "300001.SZ", "600000.SH"],
            {
                "600000.SH": as_of,
                "000001.SZ": date(2026, 8, 27),
                "300001.SZ": as_of,
            },
        )

        assert result["300001.SZ"]["unavailable_reason"] == "as_of_mismatch"
        assert result["600000.SH"] == {
            "as_of_date": "2026-08-28",
            "benchmark": {"code": "399001.SZ", "name": "深证成指", "fallback": False},
            "industry": {
                "board_code": "881001",
                "name": "银行",
                "score": 0.82,
                "corr_20": 0.86,
                "corr_60": 0.76,
                "sample_20": 20,
                "sample_60": 58,
                "confidence": "high",
            },
            "concept": None,
        }
        # 000001.SZ 请求 08-27 无对应日快照 → as_of_mismatch（该历史日期无快照）。
        assert result["000001.SZ"]["unavailable_reason"] == "as_of_mismatch"
        assert result["000001.SZ"]["as_of_date"] is None


@pytest.mark.parametrize("count", [50, 200])
def test_batch_summary_query_count_does_not_grow_with_rows(count):
    as_of = date(2026, 8, 28)
    codes = [f"{index:06d}.SZ" for index in range(count)]
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        market.conn.executemany(
            "INSERT INTO stock_board_correlation_state VALUES "
            "(?, ?, TIMESTAMP '2026-08-29 10:00:00', 'stock-board-correlation-v2', "
            "'000001.SH', false, false, false)",
            [(code, as_of) for code in codes],
        )
        counting = _CountingClient(market)

        result = StockBoardCorrelationService(counting).get_related_boards(  # type: ignore[arg-type]
            codes,
            as_of,
        )

        assert len(result) == count
        assert len(counting.queries) == 1


def test_empty_batch_and_nonstandard_rows():
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        counting = _CountingClient(market)
        service = StockBoardCorrelationService(counting)  # type: ignore[arg-type]

        assert service.get_related_boards([], date(2026, 8, 28)) == {}
        assert counting.queries == []
        rows = service.attach_related_boards(
            [{"code": "LEGACY"}, {"code": "600000.SH"}],
            {"LEGACY": "2026-08-27", "600000.SH": "2026-08-28"},
        )

        # 非标准 legacy 代码安全降级为 null；标准代码请求了具体业务日但该日无快照 → as_of_mismatch。
        assert rows[0] == {"code": "LEGACY", "related_boards": None}
        assert rows[1]["code"] == "600000.SH"
        rb = rows[1]["related_boards"]
        assert rb["unavailable_reason"] == "as_of_mismatch"
        assert rb["as_of_date"] is None


def test_all_none_date_mapping_fails_closed_without_returning_latest_snapshot():
    as_of = date(2026, 8, 28)
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_summary(market, as_of=as_of)

        result = StockBoardCorrelationService(market).get_related_boards(
            ["600000.SH", "000001.SZ"],
            {"600000.SH": None, "000001.SZ": None},
        )

        assert result["600000.SH"]["unavailable_reason"] == "as_of_mismatch"
        assert result["000001.SZ"]["unavailable_reason"] == "as_of_mismatch"
        assert result["600000.SH"]["industry"] is None


def test_stock_list_attaches_one_batch_for_returned_page(monkeypatch):
    as_of = date(2026, 8, 28)
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_summary(market, as_of=as_of)
        market.execute(
            "INSERT INTO stock_basic (code,name,board,industry,list_date) VALUES "
            "('600000.SH','浦发银行','主板','银行业','1999-11-10')"
        )
        market.execute(
            "INSERT INTO daily_bar (code,trade_date,close,pre_close) VALUES "
            "('600000.SH',?,10.5,10.0)",
            [as_of],
        )
        counting = _CountingClient(market)
        monkeypatch.setattr("backend.api.stocks.get_client", lambda: counting)
        monkeypatch.setattr("backend.api.stocks.get_current_context", lambda: None)

        response = list_stocks(
            q=None,
            board=None,
            exclude_st=False,
            trade_date=as_of,
            sort_by="code",
            sort_order="asc",
            page=1,
            size=50,
        )

        row = response.data["list"][0]
        assert row["related_boards"]["industry"]["name"] == "银行"
        assert sum("FROM stock_board_correlation_state" in sql for sql in counting.queries) == 1


class _ScreenEngine:
    def run_ast(self, _expression, _run_date):
        return pd.DataFrame([{"code": "600000.SH", "hit": True}])

    def _snapshot(self, _run_date, _hits):
        return pd.DataFrame({"close": [10.0]}, index=["600000.SH"])


class _ScoreModel:
    def score(self, _snapshot):
        return pd.DataFrame(
            {"total_score": [88.0], "grade": ["A"]},
            index=["600000.SH"],
        )


def test_screen_results_attach_summary_without_changing_score_order():
    as_of = date(2026, 8, 28)
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_summary(market, as_of=as_of)
        market.execute("INSERT INTO stock_basic (code,name) VALUES ('600000.SH','浦发银行')")
        service = object.__new__(ScreenScoreService)
        service.c = market
        service.engine = _ScreenEngine()
        service.model = _ScoreModel()
        service._st_codes = lambda: set()

        current = service.screen_scored(as_of, expression={"type": "expr"})
        historical = service.screen_scored(date(2026, 8, 27), expression={"type": "expr"})

        assert current[0]["total_score"] == 88.0
        assert current[0]["related_boards"]["industry"]["name"] == "银行"
        assert historical[0]["related_boards"]["industry"] is None
        assert historical[0]["related_boards"]["unavailable_reason"] == "as_of_mismatch"
