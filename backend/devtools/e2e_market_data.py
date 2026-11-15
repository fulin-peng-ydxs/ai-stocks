"""确定性行情夹具共用的准确 ST 材料；调用方负责环境守卫及事务。"""

from collections.abc import Iterable
from datetime import date

from backend.storage.duckdb_client import DuckDBClient


def seed_non_st_daily(
    client: DuckDBClient, code_dates: Iterable[tuple[str, date]], *, source: str,
) -> None:
    """仅供明确声明为非 ST 的固定材料，不从名称或 daily_bar 推断真实状态。"""
    rows = [(code, day, source) for code, day in code_dates]
    if rows:
        client.conn.executemany(
            "INSERT INTO stock_st_status_daily "
            "(code,trade_date,is_st,source,source_ref,quality,captured_at,updated_at) "
            "VALUES (?,?,FALSE,?,'fixture-market','accurate',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            rows,
        )


def cleanup_st_daily(
    client: DuckDBClient, codes: Iterable[str], start: date, end: date, *, source: str,
) -> int:
    """按夹具来源、专属代码及日期求交清理，不删除其它材料。"""
    return len(client.execute(
        "DELETE FROM stock_st_status_daily WHERE source=? "
        "AND code IN (SELECT unnest(?::VARCHAR[])) AND trade_date BETWEEN ? AND ? RETURNING 1",
        [source, list(codes), start, end],
    ).fetchall())
