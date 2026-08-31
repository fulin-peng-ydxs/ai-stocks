"""T10：个股走势关联板块正式结果表结构体检。"""

from __future__ import annotations

from backend.services.data_verify import DataVerifier
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


def _seed_supported_result(client: DuckDBClient) -> None:
    client.execute(
        "INSERT INTO stock_basic (code,name) VALUES ('600000.SH','E2E体检股票')"
    )
    client.execute(
        "INSERT INTO daily_bar (code,trade_date,close) "
        "VALUES ('600000.SH',DATE '2026-08-28',10)"
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


def test_correlation_checkup_passes_for_supported_consistent_result():
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        _seed_supported_result(client)

        verifier = DataVerifier(client, quiet=True)
        verifier.check_stock_board_correlation()

        assert verifier.fails() == []


def test_correlation_checkup_catches_orphan_mismatch_old_version_and_future_dates():
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
        assert not _result(verifier, "结果算法版本均为 stock-board-correlation-v2")
        assert not _result(verifier, "结果日期不晚于个股行情可用日")
        assert not _result(verifier, "结果日期不晚于基准行情可用日")


def test_structured_checkup_contains_correlation_group():
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        verifier = DataVerifier(client, quiet=True)

        report = verifier.run_structured(cross=False)

        group = next(
            item for item in report["groups"] if item["group"] == "G. 个股走势关联板块"
        )
        assert len(group["checks"]) == 13
        assert all(check["ok"] for check in group["checks"])
