"""T10：关联板块 E2E 夹具的门控、幂等与精确清理。"""

from backend.devtools.e2e_stock_board_correlation import (
    BOARD_CODES,
    STOCK_CODES,
    cleanup_stock_board_correlation,
    seed_stock_board_correlation,
)
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


def test_fixture_seed_is_idempotent_and_cleanup_preserves_unrelated_rows(monkeypatch):
    monkeypatch.setenv("AI_STOCKS_ENV", "test")
    monkeypatch.setenv("AI_STOCKS_E2E_WRITE", "1")
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        client.execute("INSERT INTO stock_basic (code,name) VALUES ('600000.SH','保留股票')")
        client.execute(
            "INSERT INTO board_dict (board_code,name,board_type) "
            "VALUES ('REAL_BOARD','保留板块','industry')"
        )
        client.execute(
            "INSERT INTO scheduled_job (id,name,task_type,params,created_at,updated_at) "
            "VALUES ('job_keep','保留调度','verify','{}',now(),now())"
        )

        first = seed_stock_board_correlation(client, runtime_client=client)
        second = seed_stock_board_correlation(client, runtime_client=client)

        assert first == second
        assert int(client.query_df(
            "SELECT count(*) n FROM stock_basic WHERE code IN (SELECT unnest(?::VARCHAR[]))",
            [list(STOCK_CODES)],
        ).iloc[0]["n"]) == len(STOCK_CODES)
        assert int(client.query_df(
            "SELECT count(*) n FROM board_dict WHERE board_code IN (SELECT unnest(?::VARCHAR[]))",
            [list(BOARD_CODES)],
        ).iloc[0]["n"]) == len(BOARD_CODES)
        assert int(client.query_df(
            "SELECT count(*) n FROM stock_board_correlation"
        ).iloc[0]["n"]) == len(STOCK_CODES) * 2

        result = cleanup_stock_board_correlation(client, runtime_client=client)

        assert result["residual"] == {"stocks": 0, "boards": 0, "tasks": 0}
        assert int(client.query_df(
            "SELECT count(*) n FROM stock_basic WHERE code='600000.SH'"
        ).iloc[0]["n"]) == 1
        assert int(client.query_df(
            "SELECT count(*) n FROM board_dict WHERE board_code='REAL_BOARD'"
        ).iloc[0]["n"]) == 1
        assert int(client.query_df(
            "SELECT count(*) n FROM scheduled_job WHERE id='job_keep'"
        ).iloc[0]["n"]) == 1
