"""个股走势关联板块 Playwright 确定性 DuckDB 夹具。

只写 9977*.SZ、E2ECORR_*、E2E相关-*、e2e_sbc_* 与 2097 年固定日期。
seed/cleanup 均要求本地测试环境和 ``AI_STOCKS_E2E_WRITE=1``，并在事务内按专属
主键交集清理；用于页面 E2E，不得在后端持有 DuckDB 锁时执行。
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

from backend.devtools.environment_guard import require_e2e_write_enabled
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient, get_client

STOCK_CODES = tuple(f"9977{index:02d}.SZ" for index in range(1, 5))
BOARD_CODES = ("E2ECORR_INDUSTRY", "E2ECORR_CONCEPT")
BENCHMARK_CODES = ("000001.SH", "399001.SZ", "399006.SZ", "000688.SH")
TASK_PREFIX = "e2e_sbc_"
FIXTURE_START = date(2097, 1, 2)
FIXTURE_POINTS = 80


def fixture_dates() -> list[date]:
    days: list[date] = []
    current = FIXTURE_START
    while len(days) < FIXTURE_POINTS:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _cleanup(client: DuckDBClient) -> dict[str, int]:
    dates = fixture_dates()
    removed: dict[str, int] = {}
    statements = (
        ("task_log", "DELETE FROM task_log WHERE task_id LIKE ?", [f"{TASK_PREFIX}%"]),
        (
            "async_task",
            "DELETE FROM async_task WHERE id LIKE ? OR job_id LIKE ?",
            [f"{TASK_PREFIX}%", f"{TASK_PREFIX}%"],
        ),
        (
            "scheduled_trigger_event",
            (
                "DELETE FROM scheduled_trigger_event WHERE target_job_id LIKE ? "
                "OR source_task_id LIKE ? OR task_id LIKE ?"
            ),
            [f"{TASK_PREFIX}%", f"{TASK_PREFIX}%", f"{TASK_PREFIX}%"],
        ),
        ("scheduled_job", "DELETE FROM scheduled_job WHERE id LIKE ?", [f"{TASK_PREFIX}%"]),
        (
            "stock_board_correlation",
            "DELETE FROM stock_board_correlation WHERE code IN (SELECT unnest(?::VARCHAR[]))",
            [list(STOCK_CODES)],
        ),
        (
            "stock_board_correlation_state",
            (
                "DELETE FROM stock_board_correlation_state "
                "WHERE code IN (SELECT unnest(?::VARCHAR[]))"
            ),
            [list(STOCK_CODES)],
        ),
        (
            "board_member",
            "DELETE FROM board_member WHERE board_code IN (SELECT unnest(?::VARCHAR[]))",
            [list(BOARD_CODES)],
        ),
        (
            "board_bar",
            "DELETE FROM board_bar WHERE board_code IN (SELECT unnest(?::VARCHAR[]))",
            [list(BOARD_CODES)],
        ),
        (
            "board_dict",
            "DELETE FROM board_dict WHERE board_code IN (SELECT unnest(?::VARCHAR[]))",
            [list(BOARD_CODES)],
        ),
        (
            "daily_metrics",
            "DELETE FROM daily_metrics WHERE code IN (SELECT unnest(?::VARCHAR[]))",
            [list(STOCK_CODES)],
        ),
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
        removed[name] = len(client.execute(f"{sql} RETURNING 1", params).fetchall())
    return removed


def _residual_counts(client: DuckDBClient) -> dict[str, int]:
    code_count = int(
        client.query_df(
            "SELECT count(*) n FROM stock_basic "
            "WHERE code IN (SELECT unnest(?::VARCHAR[]))",
            [list(STOCK_CODES)],
        ).iloc[0]["n"]
    )
    board_count = int(
        client.query_df(
            "SELECT count(*) n FROM board_dict "
            "WHERE board_code IN (SELECT unnest(?::VARCHAR[]))",
            [list(BOARD_CODES)],
        ).iloc[0]["n"]
    )
    task_count = int(
        client.query_df(
            "SELECT (SELECT count(*) FROM scheduled_job WHERE id LIKE ?) + "
            "(SELECT count(*) FROM async_task WHERE id LIKE ? OR job_id LIKE ?) n",
            [f"{TASK_PREFIX}%", f"{TASK_PREFIX}%", f"{TASK_PREFIX}%"],
        ).iloc[0]["n"]
    )
    return {"stocks": code_count, "boards": board_count, "tasks": task_count}


def seed_stock_board_correlation(client: DuckDBClient | None = None) -> dict[str, object]:
    """幂等写入页面、筛选和任务中心所需的固定行情与当前冠军。"""
    require_e2e_write_enabled()
    client = client or get_client()
    init_db(client)
    dates = fixture_dates()
    target_date = dates[-1]
    computed_at = "2097-04-30 18:00:00"
    with client.transaction():
        _cleanup(client)
        client.conn.executemany(
            "INSERT INTO trade_calendar (trade_date,is_open) VALUES (?,true)",
            [(day,) for day in dates],
        )
        client.conn.executemany(
            "INSERT INTO stock_basic "
            "(code,name,exchange,board,list_date,total_share,float_share,industry,concept,"
            "price_limit_pct) VALUES (?,?,'SZ','主板',DATE '2090-01-01',1000000000,"
            "800000000,'E2E相关行业','[\"E2E相关概念\"]',0.10)",
            [(code, f"E2E相关-股票{index}") for index, code in enumerate(STOCK_CODES, 1)],
        )
        daily_rows = []
        metric_rows = []
        for stock_index, code in enumerate(STOCK_CODES, 1):
            previous = 10.0 + stock_index
            for point, day in enumerate(dates):
                close = previous * (1.0 + 0.001 * stock_index + 0.0002 * (point % 5))
                daily_rows.append(
                    (
                        code, day, previous, max(previous, close) + 0.05,
                        min(previous, close) - 0.05, close, previous,
                        1_000_000 + point * 1_000, close * 1_000_000,
                        1.0, 1.0, 1.2 + stock_index * 0.1,
                    )
                )
                metric_rows.append((code, day, close * 800_000_000, close * 1_000_000_000))
                previous = close
        client.conn.executemany(
            "INSERT INTO daily_bar "
            "(code,trade_date,open,high,low,close,pre_close,volume,amount,adj_factor,"
            "adj_factor_clean,turnover_rate,is_st,is_suspended,limit_status,is_one_word) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,false,false,0,false)",
            daily_rows,
        )
        client.conn.executemany(
            "INSERT INTO daily_metrics (code,trade_date,float_mv,total_mv) VALUES (?,?,?,?)",
            metric_rows,
        )

        client.conn.executemany(
            "INSERT INTO board_dict "
            "(board_code,name,board_type,has_members,has_bar,member_count,last_seen_at,updated_at) "
            "VALUES (?,?,?,true,true,?,?,TIMESTAMP '2097-04-30 18:00:00')",
            [
                (BOARD_CODES[0], "E2E相关-行业冠军", "industry", len(STOCK_CODES), target_date),
                (BOARD_CODES[1], "E2E相关-概念冠军", "concept", len(STOCK_CODES), target_date),
            ],
        )
        client.conn.executemany(
            "INSERT INTO board_member (board_code,code) VALUES (?,?)",
            [(board, code) for board in BOARD_CODES for code in STOCK_CODES],
        )
        board_rows = []
        for board_index, board_code in enumerate(BOARD_CODES, 1):
            for point, day in enumerate(dates):
                close = 100 + point * (0.2 + board_index * 0.05)
                board_rows.append(
                    (board_code, day, close - 0.1, close + 0.3, close - 0.3, close, 1_000_000, 100_000_000)
                )
        client.conn.executemany(
            "INSERT INTO board_bar "
            "(board_code,trade_date,open,high,low,close,volume,amount) VALUES (?,?,?,?,?,?,?,?)",
            board_rows,
        )
        client.conn.executemany(
            "INSERT INTO index_bar "
            "(index_code,trade_date,open,high,low,close,volume,amount) VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    benchmark, day, 3000 + point, 3002 + point, 2998 + point,
                    3000 + point, 10_000_000, 1_000_000_000,
                )
                for benchmark in BENCHMARK_CODES
                for point, day in enumerate(dates)
            ],
        )
        client.conn.executemany(
            "INSERT INTO stock_board_correlation_state VALUES "
            "(?,?,?,'stock-board-correlation-v2','000001.SH',false,true,true)",
            [(code, target_date, computed_at) for code in STOCK_CODES],
        )
        champion_rows = []
        for index, code in enumerate(STOCK_CODES, 1):
            champion_rows.extend(
                [
                    (
                        code, "industry", BOARD_CODES[0], 0.8 + index * 0.01,
                        0.82 + index * 0.01, 0.76 + index * 0.01, "high",
                        target_date, computed_at,
                    ),
                    (
                        code, "concept", BOARD_CODES[1], 0.6 + index * 0.01,
                        0.64 + index * 0.01, 0.56 + index * 0.01, "low" if index == 4 else "medium",
                        target_date, computed_at,
                    ),
                ]
            )
        client.conn.executemany(
            "INSERT INTO stock_board_correlation "
            "(code,board_type,board_code,score,corr_20,corr_60,sample_20,sample_60,confidence,"
            "benchmark_code,benchmark_fallback,as_of_date,computed_at,algorithm_version) "
            "VALUES (?,?,?,?,?,?,20,60,?,'000001.SH',false,?,?,'stock-board-correlation-v2')",
            champion_rows,
        )
        client.execute(
            "INSERT INTO scheduled_job "
            "(id,name,task_type,params,freq_type,freq_config,trigger_mode,dependency_delay,"
            "retry_config,trading_day_only,enabled,created_at,updated_at) VALUES "
            "('e2e_sbc_job','E2E相关-盘后计算','stock_board_correlation',"
            "'{\"codes\":[\"997701.SZ\",\"997702.SZ\"],\"force\":false}',"
            "'daily','{\"time\":\"15:30\"}','time','{\"value\":0,\"unit\":\"minute\"}',"
            "'{\"enabled\":false,\"condition\":\"failure\",\"delay\":{\"value\":5,"
            "\"unit\":\"minute\"},\"max_retries\":1}',true,false,?,?)",
            [computed_at, computed_at],
        )
        task_result = json.dumps(
            {
                "target_date": str(target_date),
                "target_stock_count": len(STOCK_CODES),
                "candidate_relation_count": 8,
                "industry_champion_count": 4,
                "concept_champion_count": 4,
                "empty_result_count": 0,
                "fallback_count": 0,
                "skipped_count": 0,
                "failed_count": 0,
                "benchmark_counts": {"000001.SH": 4},
                "calculation_seconds": 0.25,
                "write_seconds": 0.03,
                "switched": True,
            },
            ensure_ascii=False,
        )
        client.execute(
            "INSERT INTO async_task "
            "(id,task_type,params,status,progress,message,result,trigger_source,job_id,job_name,"
            "retry_count,execution_attempt,created_at,updated_at) VALUES "
            "('e2e_sbc_task','stock_board_correlation','{\"force\":false}','done',1,"
            "'E2E 关联计算完成',?,'scheduled','e2e_sbc_job','E2E相关-盘后计算',0,1,?,?)",
            [task_result, computed_at, computed_at],
        )
        client.execute(
            "INSERT INTO task_log (id,task_id,seq,ts,level,message) VALUES "
            "(nextval('seq_task_log'),'e2e_sbc_task',1,?,'info','阶段 5/5：原子切换完成')",
            [computed_at],
        )
    return {
        "stockCodes": list(STOCK_CODES),
        "boardCodes": list(BOARD_CODES),
        "targetDate": target_date.isoformat(),
        "jobId": "e2e_sbc_job",
        "taskId": "e2e_sbc_task",
    }


def cleanup_stock_board_correlation(client: DuckDBClient | None = None) -> dict[str, object]:
    require_e2e_write_enabled()
    client = client or get_client()
    init_db(client)
    with client.transaction():
        removed = _cleanup(client)
        residual = _residual_counts(client)
        if any(residual.values()):
            raise RuntimeError(f"关联板块 E2E 清理后仍有残留：{residual}")
    return {"removed": removed, "residual": residual}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("seed", "cleanup"))
    args = parser.parse_args()
    result = (
        seed_stock_board_correlation()
        if args.command == "seed"
        else cleanup_stock_board_correlation()
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
