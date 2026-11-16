"""隔离浏览器夹具的共用行情与准确 ST 材料；不采集外部来源。"""

import os
from collections.abc import Iterable
from datetime import date, timedelta

from backend.devtools.environment_guard import require_e2e_write_enabled
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


def seed_ci_market(
    client: DuckDBClient, *, suite: str, end: date,
    benchmark_codes: tuple[str, ...] = ("000905.SH",),
    stock_name_prefix: str = "E2E行情股票",
) -> dict[str, int]:
    """仅给指定隔离专项的空库备齐日线、基准和准确 ST；已有数据先拒写。"""
    require_e2e_write_enabled()
    if suite not in {"e2e-backtest", "e2e-stocks"} or os.environ.get("AI_STOCKS_CI_SUITE") != suite:
        raise RuntimeError("确定性行情仅供隔离 CI 专项")
    for table in ("stock_basic", "daily_bar", "daily_metrics", "stock_st_status_daily",
                  "index_bar", "trade_calendar"):
        if client.query_df(f"SELECT count(*) n FROM {table}").iloc[0]["n"]:
            raise RuntimeError("CI 行情只允许写入空临时库")
    # 两类专项共用暖机材料，合成日线严格止于调用方声明的已收盘日期。
    first = end - timedelta(days=180)
    days = [first + timedelta(days=i) for i in range(181)]
    trading = [day for day in days if day.weekday() < 5]
    codes = ("996601.SZ", "996602.SZ")
    with client.transaction():
        client.conn.executemany(
            "INSERT INTO trade_calendar(trade_date,is_open) VALUES (?,?)",
            [(day, day.weekday() < 5) for day in days],
        )
        client.conn.executemany(
            "INSERT INTO stock_basic(code,name,exchange,board,list_date,industry,price_limit_pct) "
            "VALUES (?,?,'SZ','主板',?,'E2E回测',0.10)",
            [(code, f"{stock_name_prefix}{i}", first - timedelta(days=365)) for i, code in enumerate(codes)],
        )
        bars, metrics, benchmarks = [], [], []
        for i, code in enumerate(codes):
            for point, day in enumerate(trading):
                close = 10 + i * 3 + point * 0.02
                bars.append((code, day, close - 0.01, close + 0.1, close - 0.1,
                             close, close - 0.02, 1_000_000, close * 1_000_000))
                metrics.append((code, day, close * 80_000_000, close * 100_000_000))
        for index_code in benchmark_codes:
            for point, day in enumerate(trading):
                close = 5000 + point
                benchmarks.append((index_code, day, close, close + 1, close - 1, close, 10_000_000, 1e9))
        client.conn.executemany(
            "INSERT INTO daily_bar(code,trade_date,open,high,low,close,pre_close,volume,amount,"
            "adj_factor,adj_factor_clean,turnover_rate,is_suspended,limit_status,is_one_word) "
            "VALUES (?,?,?,?,?,?,?,?,?,1,1,1,FALSE,0,FALSE)", bars,
        )
        client.conn.executemany(
            "INSERT INTO daily_metrics(code,trade_date,float_mv,total_mv) VALUES (?,?,?,?)", metrics,
        )
        client.conn.executemany(
            "INSERT INTO index_bar(index_code,trade_date,open,high,low,close,volume,amount) "
            "VALUES (?,?,?,?,?,?,?,?)", benchmarks,
        )
        seed_non_st_daily(
            client, ((code, day) for code in codes for day in trading), source=suite,
        )
    return {"stocks": len(codes), "trading_days": len(trading), "bars": len(bars)}
