"""Playwright 板块行情确定性 DuckDB 夹具。

夹具只写入 E2E 专属板块/股票代码与 2099 年固定日期，供空库环境稳定验证列表、详情、
成分分页、领涨股、基准指数和 K 线量能。seed/cleanup 均受本地测试环境与
``AI_STOCKS_E2E_WRITE=1`` 双重门控，并按专属主键精确清理，不触碰真实行情。

DuckDB 单文件写锁要求执行 seed/cleanup 时后端已停止；写入完成后再启动被测后端。
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

from backend.devtools.e2e_market_data import cleanup_st_daily, seed_non_st_daily
from backend.devtools.environment_guard import require_e2e_write_enabled
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient, get_client

BOARD_PREFIX = "E2E9"
BOARD_CODES = tuple(f"{BOARD_PREFIX}{i:03d}" for i in range(1, 25))
STOCK_CODES = tuple(f"9999{i:02d}.SZ" for i in range(1, 26))
BENCHMARK_CODES = (
    "000905.SH",
    "000300.SH",
    "000001.SH",
    "000688.SH",
    "399001.SZ",
    "399006.SZ",
)
FIXTURE_START = date(2099, 1, 5)
FIXTURE_POINTS = 140


def _trade_dates() -> list[date]:
    days: list[date] = []
    current = FIXTURE_START
    while len(days) < FIXTURE_POINTS:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _cleanup(client: DuckDBClient) -> dict[str, int]:
    dates = _trade_dates()
    removed: dict[str, int] = {
        "stock_st_status_daily": cleanup_st_daily(
            client, STOCK_CODES, dates[-1], dates[-1], source="e2e-board-data",
        ),
    }
    statements = (
        ("board_fund_flow", "DELETE FROM board_fund_flow WHERE board_code LIKE ?", [f"{BOARD_PREFIX}%"]),
        ("board_member", "DELETE FROM board_member WHERE board_code LIKE ?", [f"{BOARD_PREFIX}%"]),
        ("board_bar", "DELETE FROM board_bar WHERE board_code LIKE ?", [f"{BOARD_PREFIX}%"]),
        ("board_dict", "DELETE FROM board_dict WHERE board_code LIKE ?", [f"{BOARD_PREFIX}%"]),
        (
            "daily_bar",
            "DELETE FROM daily_bar WHERE code IN (SELECT unnest(?::VARCHAR[]))",
            [list(STOCK_CODES)],
        ),
        (
            "stock_basic",
            "DELETE FROM stock_basic WHERE code IN (SELECT unnest(?::VARCHAR[]))",
            [list(STOCK_CODES)],
        ),
        (
            "index_bar",
            (
                "DELETE FROM index_bar WHERE index_code IN (SELECT unnest(?::VARCHAR[])) "
                "AND trade_date BETWEEN ? AND ?"
            ),
            [list(BENCHMARK_CODES), dates[0], dates[-1]],
        ),
        (
            "trade_calendar",
            "DELETE FROM trade_calendar WHERE trade_date BETWEEN ? AND ?",
            [dates[0], dates[-1]],
        ),
    )
    for name, sql, params in statements:
        rows = client.execute(f"{sql} RETURNING 1", params).fetchall()
        removed[name] = len(rows)
    return removed


def seed_board_data(client: DuckDBClient | None = None) -> dict[str, object]:
    """幂等写入固定板块及配套行情；重复 seed 会先清理上一轮专属数据。"""
    require_e2e_write_enabled()
    client = client or get_client()
    init_db(client)
    dates = _trade_dates()
    last_date = dates[-1]
    with client.transaction():
        _cleanup(client)
        client.conn.executemany(
            "INSERT INTO trade_calendar (trade_date, is_open) VALUES (?, true)",
            [(day,) for day in dates],
        )
        client.conn.executemany(
            "INSERT INTO stock_basic (code, name, exchange, board, list_date) "
            "VALUES (?, ?, 'SZ', '主板', DATE '2090-01-01')",
            [(code, f"E2E成分{i:02d}") for i, code in enumerate(STOCK_CODES, 1)],
        )
        # 固定材料明确为非 ST；详情必须消费准确逐日事实，不能从名称/日线推断或绕过守卫。
        seed_non_st_daily(
            client, ((code, last_date) for code in STOCK_CODES), source="e2e-board-data",
        )
        client.conn.executemany(
            "INSERT INTO daily_bar "
            "(code, trade_date, open, high, low, close, pre_close, volume, amount, "
            "turnover_rate, is_suspended) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, false)",
            [
                (
                    code,
                    last_date,
                    10 + i * 0.1,
                    11 + i * 0.1,
                    9 + i * 0.1,
                    10 * (1 + i / 100),
                    10.0,
                    1_000_000 + i * 10_000,
                    10_000_000 + i * 100_000,
                    1 + i / 10,
                )
                for i, code in enumerate(STOCK_CODES, 1)
            ],
        )

        for board_index, board_code in enumerate(BOARD_CODES, 1):
            client.execute(
                "INSERT INTO board_dict "
                "(board_code, app_code, name, board_type, has_members, has_bar, has_fund_flow, "
                "member_count, member_snapshot_at, last_seen_at, updated_at) "
                "VALUES (?, ?, ?, ?, true, true, true, ?, now(), ?, now())",
                [
                    board_code,
                    f"E2EAPP{board_index}",
                    f"E2E板块{board_index}",
                    "concept" if board_index % 2 else "industry",
                    len(STOCK_CODES),
                    last_date,
                ],
            )
            client.conn.executemany(
                "INSERT INTO board_member (board_code, code) VALUES (?, ?)",
                [(board_code, code) for code in STOCK_CODES],
            )
            closes = [100 + point * (0.08 + board_index * 0.03) for point in range(len(dates))]
            client.conn.executemany(
                "INSERT INTO board_bar "
                "(board_code, trade_date, open, high, low, close, volume, amount) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        board_code,
                        day,
                        close - 0.2,
                        close + 0.5,
                        close - 0.5,
                        close,
                        1_000_000 + point * 1_000,
                        100_000_000 + point * 100_000,
                    )
                    for point, (day, close) in enumerate(zip(dates, closes))
                ],
            )
            client.execute(
                "INSERT INTO board_fund_flow "
                "(board_code, snapshot_date, period, inflow, outflow, net_inflow, net_ratio, "
                "leader_stock, leader_pct) VALUES (?, ?, '即时', ?, ?, ?, ?, '源端领涨占位', 99)",
                [board_code, last_date, 20 + board_index, 10.0, 10 + board_index, board_index],
            )

        for benchmark_index, benchmark_code in enumerate(BENCHMARK_CODES, 1):
            client.conn.executemany(
                "INSERT INTO index_bar "
                "(index_code, trade_date, open, high, low, close, volume, amount) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        benchmark_code,
                        day,
                        5000 + point * benchmark_index,
                        5005 + point * benchmark_index,
                        4995 + point * benchmark_index,
                        5000 + point * benchmark_index,
                        10_000_000,
                        1_000_000_000,
                    )
                    for point, day in enumerate(dates)
                ],
            )
    return {
        "boardCodes": list(BOARD_CODES),
        "stockCodes": list(STOCK_CODES),
        "dateStart": dates[0].isoformat(),
        "dateEnd": last_date.isoformat(),
    }


def cleanup_board_data(client: DuckDBClient | None = None) -> dict[str, int]:
    """精确删除本夹具生成的数据。"""
    require_e2e_write_enabled()
    client = client or get_client()
    init_db(client)
    with client.transaction():
        return _cleanup(client)


def main() -> int:
    parser = argparse.ArgumentParser(description="Playwright 板块行情确定性夹具")
    parser.add_argument("command", choices=("seed", "cleanup"))
    args = parser.parse_args()
    result = seed_board_data() if args.command == "seed" else cleanup_board_data()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
