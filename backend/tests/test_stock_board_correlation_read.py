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
        "has_industry_champion,has_concept_champion,industry_empty_reason,"
        "industry_max_sample_20,industry_max_sample_60,concept_empty_reason,"
        "concept_max_sample_20,concept_max_sample_60) VALUES "
        "('600000.SH',?,TIMESTAMP '2026-08-29 10:00:00','stock-board-correlation-v2',"
        "'399001.SZ',false,true,true,NULL,NULL,NULL,NULL,NULL,NULL),"
        "('000001.SZ',?,TIMESTAMP '2026-08-29 10:00:00','stock-board-correlation-v2',"
        "'000001.SH',true,false,false,'insufficient_samples',14,54,'no_candidates',NULL,NULL)",
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


def test_batch_summary_reads_per_day_snapshot(monkeypatch):
    from backend.services.async_task import AsyncTaskService

    monkeypatch.setattr(AsyncTaskService, "_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AsyncTaskService, "_audit_task", staticmethod(lambda **kwargs: None))
    as_of = date(2026, 8, 28)
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_summary(market, as_of=as_of)
        market.execute(
            "INSERT INTO stock_basic (code,name,board,list_date) VALUES "
            "('000001.SZ','平安银行','主板','1991-04-03'),"
            "('300001.SZ','特锐德','创业板','2009-10-30')"
        )
        service = StockBoardCorrelationService(market)

        result = service.get_related_boards(
            ["600000.sh", "000001.SZ", "300001.SZ", "600000.SH"],
            {
                "600000.SH": as_of,
                "000001.SZ": date(2026, 8, 27),
                "300001.SZ": as_of,
            },
        )

        # 同一请求的另一日期任务已占写槽，未创建的范围不能冒充“计算中”。
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
        # 000001.SZ 虽已有 08-28 快照，请求 08-27 缺档仍按日期进入首次计算。
        assert result["000001.SZ"]["unavailable_reason"] == "first_load_pending"
        assert result["000001.SZ"]["as_of_date"] is None


def test_latest_summary_exposes_structured_empty_reason_without_changing_cell_value():
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_summary(market)

        result = StockBoardCorrelationService(market).get_related_boards(["000001.SZ"])

        summary = result["000001.SZ"]
        assert summary["industry"] is None
        assert summary["industry_empty_reason"] == {
            "code": "insufficient_samples",
            "message": "共同有效样本不足：20 日最高 14/15，60 日最高 54/40",
            "max_sample_20": 14,
            "required_sample_20": 15,
            "max_sample_60": 54,
            "required_sample_60": 40,
        }
        assert summary["concept_empty_reason"]["message"] == "该业务日没有可计算的候选板块"


def test_missing_daily_snapshot_enqueues_one_deduplicated_first_load_task(monkeypatch):
    as_of = date(2026, 8, 28)
    from backend.services.async_task import AsyncTaskService

    monkeypatch.setattr(AsyncTaskService, "_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AsyncTaskService, "_audit_task", staticmethod(lambda **kwargs: None))
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        market.execute(
            "INSERT INTO stock_basic (code,name,board,list_date) VALUES "
            "('600000.SH','浦发银行','主板','1999-11-10'),"
            "('000001.SZ','平安银行','主板','1991-04-03')"
        )
        service = StockBoardCorrelationService(market)

        first = service.get_related_boards(["600000.SH", "000001.SZ"], as_of)
        second = service.get_related_boards(["000001.SZ", "600000.SH"], as_of)
        tasks = market.query_df(
            "SELECT id,params,trigger_source,job_name,trigger_event_id FROM async_task"
        ).to_dict("records")

        assert len(tasks) == 1
        assert tasks[0]["trigger_source"] == "system"
        assert tasks[0]["job_name"] == "走势相关自动首次计算"
        assert "stock-board-correlation:first-load:" in tasks[0]["trigger_event_id"]
        assert first["600000.SH"]["unavailable_reason"] == "first_load_pending"
        assert second["000001.SZ"]["unavailable_reason"] == "first_load_pending"


def test_missing_historical_snapshot_enqueues_date_scoped_first_load(monkeypatch):
    """其它日期已有快照也不影响：所选历史日期缺档仍按日期创建首次任务。"""
    from backend.services.async_task import AsyncTaskService

    monkeypatch.setattr(AsyncTaskService, "_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AsyncTaskService, "_audit_task", staticmethod(lambda **kwargs: None))
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_summary(market, as_of=date(2026, 8, 28))
        market.execute(
            "INSERT INTO stock_basic (code,name,board,list_date) "
            "VALUES ('600000.SH','浦发银行','主板','1999-11-10')"
        )

        result = StockBoardCorrelationService(market).get_related_boards(
            ["600000.SH"], date(2026, 8, 27)
        )
        tasks = market.query_df(
            "SELECT params,trigger_event_id FROM async_task"
        ).to_dict("records")

        assert len(tasks) == 1
        assert '"trade_date": "2026-08-27"' in tasks[0]["params"]
        assert ":2026-08-27:" in tasks[0]["trigger_event_id"]
        assert result["600000.SH"]["unavailable_reason"] == "first_load_pending"


def test_old_algorithm_snapshot_is_not_served_and_enqueues_current_version(monkeypatch):
    """同日旧算法结果必须视为缺档，不能继续装饰业务页面。"""
    from backend.services.async_task import AsyncTaskService

    monkeypatch.setattr(AsyncTaskService, "_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AsyncTaskService, "_audit_task", staticmethod(lambda **kwargs: None))
    as_of = date(2026, 8, 28)
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_summary(market, as_of=as_of)
        market.execute(
            "INSERT INTO stock_basic (code,name,board,list_date) "
            "VALUES ('600000.SH','浦发银行','主板','1999-11-10')"
        )
        market.execute(
            "UPDATE stock_board_correlation_state SET algorithm_version='old-version' "
            "WHERE code='600000.SH' AND as_of_date=?",
            [as_of],
        )
        market.execute(
            "UPDATE stock_board_correlation SET algorithm_version='old-version' "
            "WHERE code='600000.SH' AND as_of_date=?",
            [as_of],
        )

        result = StockBoardCorrelationService(market).get_related_boards(["600000.SH"], as_of)
        tasks = market.query_df(
            "SELECT task_type,status FROM async_task WHERE task_type='stock_board_correlation'"
        ).to_dict("records")

        assert result["600000.SH"]["unavailable_reason"] == "first_load_pending"
        assert tasks == [{"task_type": "stock_board_correlation", "status": "pending"}]


def test_failed_first_load_retries_only_after_upstream_data_watermark_changes(monkeypatch):
    """失败任务在相同数据水位保持幂等，上游推进后允许创建一次新尝试。"""
    from backend.services.async_task import AsyncTaskService

    monkeypatch.setattr(AsyncTaskService, "_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AsyncTaskService, "_audit_task", staticmethod(lambda **kwargs: None))
    as_of = date(2026, 8, 28)
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        market.execute(
            "INSERT INTO stock_basic (code,name,board,list_date) "
            "VALUES ('600000.SH','浦发银行','主板','1999-11-10')"
        )
        service = StockBoardCorrelationService(market)

        first = service.get_related_boards(["600000.SH"], as_of)
        first_task = market.query_df("SELECT id FROM async_task").iloc[0]["id"]
        market.execute("UPDATE async_task SET status='failed' WHERE id=?", [first_task])
        unchanged = service.get_related_boards(["600000.SH"], as_of)

        market.execute(
            "INSERT INTO daily_bar (code,trade_date,close,pre_close) "
            "VALUES ('600000.SH',?,10.5,10.0)",
            [as_of],
        )
        retried = service.get_related_boards(["600000.SH"], as_of)
        tasks = market.query_df("SELECT id,status FROM async_task ORDER BY created_at").to_dict(
            "records"
        )
        market.execute("UPDATE async_task SET status='failed' WHERE id=?", [tasks[-1]["id"]])
        repeated = service.get_related_boards(["600000.SH"], as_of)
        final_count = int(market.query_df("SELECT count(*) AS n FROM async_task").iloc[0]["n"])

        assert first["600000.SH"]["unavailable_reason"] == "first_load_pending"
        assert unchanged["600000.SH"]["unavailable_reason"] == "as_of_mismatch"
        assert retried["600000.SH"]["unavailable_reason"] == "first_load_pending"
        assert repeated["600000.SH"]["unavailable_reason"] == "as_of_mismatch"
        assert len(tasks) == 2
        assert final_count == 2


def test_busy_write_slot_does_not_claim_uncreated_first_load_is_calculating(monkeypatch):
    """另一写任务占槽时不冒充走势计算中；释放后再次读取才创建任务。"""
    from backend.services.async_task import AsyncTaskService

    monkeypatch.setattr(AsyncTaskService, "_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AsyncTaskService, "_audit_task", staticmethod(lambda **kwargs: None))
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        market.execute(
            "INSERT INTO stock_basic (code,name,board,list_date) VALUES "
            "('600000.SH','浦发银行','主板','1999-11-10'),"
            "('000001.SZ','平安银行','主板','1991-04-03')"
        )
        service = StockBoardCorrelationService(market)
        first = service.get_related_boards(["600000.SH"], date(2026, 8, 28))
        blocked = service.get_related_boards(["000001.SZ"], date(2026, 8, 28))
        tasks_before_release = market.query_df(
            "SELECT id,status,trigger_event_id FROM async_task ORDER BY created_at"
        ).to_dict("records")

        assert first["600000.SH"]["unavailable_reason"] == "first_load_pending"
        assert blocked["000001.SZ"]["unavailable_reason"] == "as_of_mismatch"
        assert len(tasks_before_release) == 1

        market.execute(
            "UPDATE async_task SET status='done' WHERE id=?",
            [tasks_before_release[0]["id"]],
        )
        retried = service.get_related_boards(["000001.SZ"], date(2026, 8, 28))
        tasks_after_release = market.query_df(
            "SELECT trigger_event_id FROM async_task ORDER BY created_at"
        ).to_dict("records")

        assert retried["000001.SZ"]["unavailable_reason"] == "first_load_pending"
        assert len(tasks_after_release) == 2
        assert len({task["trigger_event_id"] for task in tasks_after_release}) == 2


def test_busy_write_slot_with_missing_upstream_data_does_not_report_calculating(monkeypatch):
    """写槽繁忙但上游数据缺失时直接降级，不能让读取页持续显示计算中。"""
    from backend.services.async_task import AsyncTaskService, ConcurrentTaskError

    def raise_busy(*_args, **_kwargs):
        raise ConcurrentTaskError("stock_ingest", "task-stock-ingest-running")

    monkeypatch.setattr(AsyncTaskService, "create", raise_busy)
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        result = StockBoardCorrelationService(market).get_related_boards(
            ["600000.SH"], date(2026, 8, 28)
        )

    assert result["600000.SH"]["unavailable_reason"] == "as_of_mismatch"


def test_first_load_task_creation_failure_keeps_read_api_available(monkeypatch):
    as_of = date(2026, 8, 28)

    class _BusyTaskService:
        def __init__(self, _client):
            pass

        @staticmethod
        def create(*_args, **_kwargs):
            raise RuntimeError("DuckDB 写任务繁忙")

    monkeypatch.setattr("backend.services.async_task.AsyncTaskService", _BusyTaskService)
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        result = StockBoardCorrelationService(market).get_related_boards(
            ["600000.SH"], as_of
        )

    assert result["600000.SH"]["unavailable_reason"] == "as_of_mismatch"


@pytest.mark.parametrize("count", [50, 200])
def test_batch_summary_query_count_does_not_grow_with_rows(count):
    as_of = date(2026, 8, 28)
    codes = [f"{index:06d}.SZ" for index in range(count)]
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        market.conn.executemany(
            "INSERT INTO stock_board_correlation_state "
            "(code,as_of_date,computed_at,algorithm_version,benchmark_code,"
            "benchmark_fallback,has_industry_champion,has_concept_champion) VALUES "
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
        market.execute(
            "INSERT INTO stock_st_status_daily "
            "(code,trade_date,is_st,source,source_ref,quality,captured_at,updated_at) "
            "VALUES ('600000.SH',?,FALSE,'baostock','query_history_k_data_plus:isST',"
            "'accurate',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            [as_of],
        )
        counting = _CountingClient(market)
        monkeypatch.setattr("backend.api.stocks.get_client", lambda: counting)
        monkeypatch.setattr("backend.api.stocks.get_current_context", lambda: None)

        response = list_stocks(
            q=None,
            boards="主板",
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


def test_screen_results_attach_summary_without_changing_score_order(monkeypatch):
    from backend.scoring.score_profile import ScoreProfileRepo
    from backend.scoring.snapshot import ScoreSnapshotRepo
    from backend.services.stock_st_status import StockSTStatusService

    monkeypatch.setattr(ScoreProfileRepo, "get_visible", lambda *_args, **_kwargs: {
        "id": "profile", "tenant_id": "pytest", "owner_user_id": "pytest_owner",
        "include_st": True,
    })
    monkeypatch.setattr(ScoreSnapshotRepo, "get_board", lambda *_args, **_kwargs: pd.DataFrame([
        {"code": "600000.SH", "rank": 1, "total_score": 88.0, "grade": "A"},
    ]))
    monkeypatch.setattr(StockSTStatusService, "status_map", lambda *_args: {"600000.SH": False})
    as_of = date(2026, 8, 28)
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_summary(market, as_of=as_of)
        market.execute("INSERT INTO stock_basic (code,name) VALUES ('600000.SH','浦发银行')")
        market.execute("INSERT INTO daily_bar (code,trade_date,close) VALUES "
                       "('600000.SH','2026-08-28',10),('600000.SH','2026-08-27',10)")
        service = object.__new__(ScreenScoreService)
        service.c = market
        service.pg = object()  # repo 方法已隔离，禁止测试访问真实资产库。
        service.engine = _ScreenEngine()

        current = service.screen_scored(as_of, "profile", expression={"type": "expr"})["hits"]
        historical = service.screen_scored(date(2026, 8, 27), "profile",
                                            expression={"type": "expr"})["hits"]
        assert current[0]["total_score"] == 88.0
        assert current[0]["related_boards"]["industry"]["name"] == "银行"
        assert historical[0]["related_boards"]["industry"] is None
        assert historical[0]["related_boards"]["unavailable_reason"] == "as_of_mismatch"


def _seed_history(market, day, board_type="industry", *, code="000001.SZ",
                  board_code="881001", version="stock-board-correlation-v2"):
    """仅在用例内存库写入带完整状态的历史冠军。"""
    market.execute(
        "INSERT INTO board_dict (board_code,name,board_type) VALUES (?,?,?) "
        "ON CONFLICT DO NOTHING", [board_code, board_code, board_type],
    )
    market.execute(
        "INSERT INTO stock_board_correlation_state "
        "(code,as_of_date,computed_at,algorithm_version,benchmark_code,"
        "has_industry_champion,has_concept_champion) "
        "VALUES (?,?,current_timestamp,?,'000001.SH',?,?) "
        "ON CONFLICT (code,as_of_date) DO UPDATE SET "
        "has_industry_champion=stock_board_correlation_state.has_industry_champion "
        "OR excluded.has_industry_champion, "
        "has_concept_champion=stock_board_correlation_state.has_concept_champion "
        "OR excluded.has_concept_champion",
        [code, day, version, board_type == "industry", board_type == "concept"],
    )
    market.execute(
        "INSERT INTO stock_board_correlation "
        "(code,board_type,board_code,score,corr_20,corr_60,sample_20,sample_60,confidence,"
        "benchmark_code,benchmark_fallback,as_of_date,computed_at,algorithm_version) "
        "VALUES (?,?,?,0.82,0.86,0.76,20,58,'high','000001.SH',true,?,current_timestamp,?)",
        [code, board_type, board_code, day, version],
    )


def test_sample_shortage_reuses_each_types_nearest_valid_history_and_original_benchmark():
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_summary(market)
        market.execute("UPDATE stock_board_correlation_state SET "
                       "concept_empty_reason='insufficient_samples', "
                       "concept_max_sample_20=20, concept_max_sample_60=32 "
                       "WHERE code='000001.SZ'")
        _seed_history(market, date(2026, 8, 20))
        _seed_history(market, date(2026, 8, 25))
        _seed_history(market, date(2026, 8, 24), "concept", board_code="C_HISTORY")
        _seed_history(market, date(2026, 8, 29), "concept", board_code="C_FUTURE")
        _seed_history(market, date(2026, 8, 27), version="old-version")
        _seed_history(market, date(2026, 8, 26), board_code="I_MISSING")
        market.execute("DELETE FROM board_dict WHERE board_code='I_MISSING'")
        counting = _CountingClient(market)
        service = StockBoardCorrelationService(counting)
        summary = service.get_related_boards(["000001.SZ"], date(2026, 8, 28))["000001.SZ"]

        assert len(counting.queries) == 2
        assert summary["as_of_date"] == "2026-08-28"
        assert summary["industry"]["history"] == {
            "as_of_date": "2026-08-25",
            "benchmark": {"code": "000001.SH", "name": "上证指数", "fallback": True},
        }
        assert summary["concept"]["history"]["as_of_date"] == "2026-08-24"
        assert summary["concept"]["board_code"] == "C_HISTORY"
        assert summary["industry"]["sample_60"] == 58
        assert summary["industry_empty_reason"]["code"] == "insufficient_samples"
        # 沿用只发生在读模型，不改写当日状态或派生结果。
        assert market.query_df("SELECT count(*) n FROM stock_board_correlation "
                               "WHERE code='000001.SZ' AND as_of_date='2026-08-28'").iloc[0]["n"] == 0


@pytest.mark.parametrize("reason", ["no_candidates", "invalid_correlation", None])
def test_non_sample_shortage_never_reuses_history(reason):
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_summary(market)
        _seed_history(market, date(2026, 8, 25))
        market.execute("UPDATE stock_board_correlation_state SET industry_empty_reason=? "
                       "WHERE code='000001.SZ' AND as_of_date='2026-08-28'", [reason])
        summary = StockBoardCorrelationService(market).get_related_boards(
            ["000001.SZ"], date(2026, 8, 28))["000001.SZ"]
        assert summary["industry"] is None


def test_current_result_replaces_history_and_missing_snapshot_still_fails_closed():
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_summary(market)
        _seed_history(market, date(2026, 8, 25))
        _seed_history(market, date(2026, 8, 28))
        market.execute("UPDATE stock_board_correlation_state SET industry_empty_reason=NULL "
                       "WHERE code='000001.SZ' AND as_of_date='2026-08-28'")
        service = StockBoardCorrelationService(market)
        summary = service.get_related_boards(["000001.SZ"], date(2026, 8, 28))["000001.SZ"]
        assert "history" not in summary["industry"]
        missing = service.get_related_boards(["000001.SZ"], date(2026, 8, 27),
                                             schedule_missing=False)["000001.SZ"]
        assert missing["industry"] is None
        assert missing["unavailable_reason"] == "as_of_mismatch"


def test_history_fallback_scales_to_1024_stocks_with_90_snapshots_in_two_queries():
    from backend.devtools.benchmark_stock_board_correlation_read import seed_read_fixture

    with DuckDBClient(db_path=":memory:") as market:
        codes = seed_read_fixture(market, 1024)
        # 184320 历史冠军，走与页面相同的批量读取入口，不能逐股查询。
        market.execute("INSERT INTO stock_board_correlation_state "
                       "SELECT code, as_of_date-CAST(n AS INTEGER), computed_at, "
                       "algorithm_version, benchmark_code, benchmark_fallback, "
                       "has_industry_champion,has_concept_champion, "
                       "industry_empty_reason,industry_max_sample_20,industry_max_sample_60, "
                       "concept_empty_reason,concept_max_sample_20,concept_max_sample_60 "
                       "FROM stock_board_correlation_state CROSS JOIN range(1,91) t(n)")
        market.execute("INSERT INTO stock_board_correlation "
                       "SELECT code,board_type,board_code,score,corr_20,corr_60,sample_20, "
                       "sample_60,confidence,benchmark_code,benchmark_fallback, "
                       "as_of_date-CAST(n AS INTEGER),computed_at,algorithm_version "
                       "FROM stock_board_correlation CROSS JOIN range(1,91) t(n)")
        market.execute("DELETE FROM stock_board_correlation WHERE as_of_date='2026-08-28'")
        market.execute("UPDATE stock_board_correlation_state SET has_industry_champion=false, "
                       "has_concept_champion=false,industry_empty_reason='insufficient_samples', "
                       "concept_empty_reason='insufficient_samples' "
                       "WHERE as_of_date='2026-08-28'")
        counting = _CountingClient(market)
        summaries = StockBoardCorrelationService(counting).get_related_boards(
            codes, date(2026, 8, 28))
        assert len(counting.queries) == 2
        assert len(summaries) == 1024
        for summary in summaries.values():
            for kind in ("industry", "concept"):
                assert summary[kind]["history"]["as_of_date"] == "2026-08-27"
