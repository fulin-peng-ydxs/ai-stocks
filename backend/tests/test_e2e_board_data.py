from __future__ import annotations

from backend.devtools.e2e_board_data import (
    BOARD_CODES,
    STOCK_CODES,
    cleanup_board_data,
    seed_board_data,
)
from backend.services.board_query import BoardQueryService
from backend.storage.duckdb_client import DuckDBClient


def test_seed_and_cleanup_board_data(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_STOCKS_ENV", "test")
    monkeypatch.setenv("AI_STOCKS_E2E_WRITE", "1")
    client = DuckDBClient(tmp_path / "board-e2e.duckdb")
    try:
        result = seed_board_data(client)
        assert result["boardCodes"] == list(BOARD_CODES)
        assert client.query_df(
            "SELECT count(*) AS n FROM board_dict WHERE board_code LIKE 'E2E9%'"
        ).iloc[0]["n"] == len(BOARD_CODES)
        assert client.query_df(
            "SELECT count(*) AS n FROM board_member WHERE board_code LIKE 'E2E9%'"
        ).iloc[0]["n"] == len(BOARD_CODES) * len(STOCK_CODES)
        assert client.query_df(
            "SELECT count(*) AS n FROM board_bar WHERE board_code LIKE 'E2E9%'"
        ).iloc[0]["n"] == len(BOARD_CODES) * 140
        members = BoardQueryService(client).get_members(BOARD_CODES[0])
        assert members["total"] == len(STOCK_CODES)
        assert len(members["list"]) == 20
        assert all(row["is_st"] is False for row in members["list"])
        assert all(row["st_as_of_date"] == result["dateEnd"] for row in members["list"])

        # 重复 seed 幂等，不能累加关系或行情。
        seed_board_data(client)
        assert client.query_df(
            "SELECT count(*) AS n FROM board_member WHERE board_code LIKE 'E2E9%'"
        ).iloc[0]["n"] == len(BOARD_CODES) * len(STOCK_CODES)
        assert client.query_df(
            "SELECT count(*) AS n FROM stock_st_status_daily WHERE source='e2e-board-data' "
            "AND quality='accurate' AND is_st=FALSE"
        ).iloc[0]["n"] == len(STOCK_CODES)

        removed = cleanup_board_data(client)
        assert removed["board_dict"] == len(BOARD_CODES)
        assert removed["board_member"] == len(BOARD_CODES) * len(STOCK_CODES)
        assert removed["board_bar"] == len(BOARD_CODES) * 140
        assert removed["stock_st_status_daily"] == len(STOCK_CODES)
        assert client.query_df(
            "SELECT count(*) AS n FROM stock_st_status_daily WHERE source='e2e-board-data'"
        ).iloc[0]["n"] == 0
        assert client.query_df(
            "SELECT count(*) AS n FROM board_dict WHERE board_code LIKE 'E2E9%'"
        ).iloc[0]["n"] == 0
        assert client.query_df(
            "SELECT count(*) AS n FROM stock_basic WHERE code LIKE '9999%.SZ'"
        ).iloc[0]["n"] == 0
    finally:
        client.close()
