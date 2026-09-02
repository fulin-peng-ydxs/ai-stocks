"""T10：个股走势关联板块正式结果表结构体检。"""

from __future__ import annotations

from backend.services.data_verify import DataVerifier
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


def _seed_supported_result(client: DuckDBClient) -> None:
    client.execute("INSERT INTO stock_basic (code,name) VALUES ('600000.SH','E2E体检股票')")
    client.execute(
        "INSERT INTO daily_bar (code,trade_date,close) VALUES ('600000.SH',DATE '2026-08-28',10)"
    )
    client.execute(
        "INSERT INTO board_dict (board_code,name,board_type) "
        "VALUES ('E2ECHECK','E2E体检行业','industry')"
    )
    client.execute(
        "INSERT INTO board_bar (board_code,trade_date,close) "
        "VALUES ('E2ECHECK',DATE '2026-08-28',100)"
    )
    client.execute(
        "INSERT INTO index_bar (index_code,trade_date,close) "
        "VALUES ('000001.SH',DATE '2026-08-28',3000)"
    )
    client.execute(
        "INSERT INTO stock_board_correlation_state VALUES "
        "('600000.SH',DATE '2026-08-28',TIMESTAMP '2026-08-29 10:00:00',"
        "'stock-board-correlation-v2','000001.SH',false,true,false)"
    )
    client.execute(
        "INSERT INTO stock_board_correlation VALUES "
        "('600000.SH','industry','E2ECHECK',0.8,0.9,0.7,20,60,'high',"
        "'000001.SH',false,DATE '2026-08-28',TIMESTAMP '2026-08-29 10:00:00',"
        "'stock-board-correlation-v2')"
    )


def _result(verifier: DataVerifier, name: str) -> bool:
    return next(ok for item_name, ok, _ in verifier.results if item_name == name)


def _status(verifier: DataVerifier, name: str) -> str:
    return next(item["status"] for item in verifier._structured if item["name"] == name)


def test_correlation_checkup_passes_for_supported_consistent_result():
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        _seed_supported_result(client)

        verifier = DataVerifier(client, quiet=True)
        verifier.check_stock_board_correlation()

        assert verifier.fails() == []


def test_correlation_checkup_catches_orphan_and_future_dates():
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        _seed_supported_result(client)
        client.execute("DELETE FROM board_dict WHERE board_code='E2ECHECK'")
        client.execute(
            "UPDATE stock_board_correlation SET algorithm_version='stock-board-correlation-v1'"
        )
        client.execute(
            "UPDATE stock_board_correlation_state SET has_industry_champion=false, "
            "as_of_date=DATE '2026-08-29'"
        )

        verifier = DataVerifier(client, quiet=True)
        verifier.check_stock_board_correlation()

        assert not _result(verifier, "冠军板块均有同类型字典记录")
        # 每日快照下"状态与冠军日期/时间/版本/基准一致"按 (code, as_of_date) 同日比对；
        # 本用例把 state 改为未来 as_of（08-29），属跨日差异而非同日 mismatch，不再触发该项。
        # 最新状态已经推进到 08-29，08-28 的旧算法冠军属于保留的历史快照，不应误报。
        assert _result(verifier, "结果算法版本均为 stock-board-correlation-v2")
        assert _result(verifier, "个股行情覆盖至结果日期")
        assert _status(verifier, "个股行情覆盖至结果日期") == "warn"
        assert not _result(verifier, "基准目标日行情完整")


def test_target_day_stock_and_board_gaps_are_warnings_when_samples_are_sufficient():
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        _seed_supported_result(client)
        client.execute(
            "UPDATE stock_board_correlation_state SET as_of_date=DATE '2026-08-29'"
        )
        client.execute("UPDATE stock_board_correlation SET as_of_date=DATE '2026-08-29'")
        client.execute(
            "INSERT INTO index_bar (index_code,trade_date,close) "
            "VALUES ('000001.SH',DATE '2026-08-29',3001)"
        )

        verifier = DataVerifier(client, quiet=True)
        verifier.check_stock_board_correlation()

        assert verifier.fails() == []
        warnings = [
            item["name"] for item in verifier._structured if item["status"] == "warn"
        ]
        assert warnings == [
            "个股行情覆盖至结果日期",
            "冠军板块行情覆盖至结果日期",
        ]
        assert _status(verifier, "个股行情覆盖至结果日期") == "warn"
        assert _status(verifier, "冠军板块行情覆盖至结果日期") == "warn"
        assert _status(verifier, "基准目标日行情完整") == "pass"


def test_historical_old_champion_is_not_treated_as_latest_when_current_type_is_empty():
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        _seed_supported_result(client)
        client.execute(
            "INSERT INTO stock_board_correlation_state VALUES "
            "('600000.SH',DATE '2026-08-29',TIMESTAMP '2026-08-30 10:00:00',"
            "'stock-board-correlation-v2','000001.SH',false,false,false)"
        )
        client.execute(
            "UPDATE stock_board_correlation SET algorithm_version='stock-board-correlation-v1' "
            "WHERE as_of_date=DATE '2026-08-28'"
        )

        verifier = DataVerifier(client, quiet=True)
        verifier.check_stock_board_correlation()

        assert _result(verifier, "结果算法版本均为 stock-board-correlation-v2")


def test_structured_checkup_contains_correlation_group():
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        verifier = DataVerifier(client, quiet=True)

        report = verifier.run_structured(cross=False)

        group = next(item for item in report["groups"] if item["group"] == "G. 个股走势关联板块")
        assert len(group["checks"]) == 13
        assert all(check["ok"] for check in group["checks"])
        assert all(check["status"] == "pass" for check in group["checks"])


def test_structured_checkup_counts_warning_without_failing(monkeypatch):
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        verifier = DataVerifier(client, quiet=True)
        for method_name in (
            "check_structure",
            "check_prices",
            "check_contract",
            "check_board",
            "check_calendar_readiness",
        ):
            monkeypatch.setattr(verifier, method_name, lambda: None)

        def warn_only() -> None:
            verifier._cur_group = "G. 个股走势关联板块"
            verifier._warn("个股行情覆盖至结果日期", "目标日未覆盖 1 条")

        monkeypatch.setattr(verifier, "check_stock_board_correlation", warn_only)

        report = verifier.run_structured(cross=False)

        assert report["passed"] == 0
        assert report["warning_count"] == 1
        assert report["warnings"] == ["个股行情覆盖至结果日期"]
        assert report["all_ok"]
        assert report["fails"] == []

        verifier.results = []
        verifier._structured = []
        assert verifier.run(cross=False)
