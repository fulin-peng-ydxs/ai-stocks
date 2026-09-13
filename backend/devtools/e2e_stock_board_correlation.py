"""个股走势关联板块 Playwright 确定性 DuckDB + PostgreSQL 夹具。

DuckDB 只写 9977*.SZ、E2ECORR_*、E2E相关-* 与 2097 年固定行情；PostgreSQL
写 e2e_sbc_* 任务运行态及固定归属 default/debug_system 的资产。seed/cleanup 均要求本地测试环境、
``AI_STOCKS_E2E_WRITE=1`` 及被测后端 PG 指纹，并在事务内按专属主键清理；用于页面
E2E，不得在后端持有 DuckDB 锁时执行。
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.devtools.environment_guard import require_e2e_write_enabled
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient, get_client
from backend.storage.pg_client import PostgresClient, get_pg_client
from backend.storage.pg_identity import pg_fingerprint
from backend.storage.task_runtime import (
    PostgresTaskRuntimeClient,
    get_task_runtime_client,
    runtime_json_param,
)

STOCK_CODES = tuple(f"9977{index:02d}.SZ" for index in range(1, 5))
BOARD_CODES = ("E2ECORR_INDUSTRY", "E2ECORR_CONCEPT")
BENCHMARK_CODES = ("000001.SH", "399001.SZ", "399006.SZ", "000688.SH")
TASK_PREFIX = "e2e_sbc_"
FIXTURE_TENANT_ID = "default"
FIXTURE_OWNER_USER_ID = "debug_system"
SCORE_PROFILE_ID = "e2e_sbc_score_profile"
SCREEN_PROFILE_ID = "e2e_sbc_screen_profile"
FIXTURE_START = date(2097, 1, 2)
FIXTURE_POINTS = 80
_PG_FINGERPRINT_RE = re.compile(r"^[a-f0-9]{64}$")


def _assert_pg_target(pg: PostgresClient, expected_pg_fingerprint: str) -> None:
    if not _PG_FINGERPRINT_RE.fullmatch(expected_pg_fingerprint or ""):
        raise RuntimeError("缺少合法的 64 位 PostgreSQL 指纹，拒绝执行关联板块 E2E 数据写入")
    if not secrets.compare_digest(pg_fingerprint(pg), expected_pg_fingerprint):
        raise RuntimeError("关联板块 E2E 夹具 PostgreSQL 与被测后端不一致，拒绝执行数据写入")


def _assert_seed_owner(pg: PostgresClient) -> None:
    owner = pg.query_df(
        "SELECT tenant_id,id,status FROM sys_user WHERE account=%s LIMIT 1",
        [FIXTURE_OWNER_USER_ID],
    )
    if (
        owner.empty
        or str(owner.iloc[0]["tenant_id"]) != FIXTURE_TENANT_ID
        or str(owner.iloc[0]["id"]) != FIXTURE_OWNER_USER_ID
        or str(owner.iloc[0]["status"]) != "active"
    ):
        raise RuntimeError("关联板块固定调试账号未校准，请先执行 ./start.sh dev-users")


def _cleanup_pg(pg: PostgresClient) -> dict[str, int]:
    removed: dict[str, int] = {}
    with pg.transaction() as conn, conn.cursor() as cur:
        statements = (
            (
                "score_snapshot",
                (
                    "DELETE FROM score_snapshot WHERE tenant_id=%s AND owner_user_id=%s "
                    "AND profile_id=%s"
                ),
                [FIXTURE_TENANT_ID, FIXTURE_OWNER_USER_ID, SCORE_PROFILE_ID],
            ),
            (
                "score_snapshot_meta",
                (
                    "DELETE FROM score_snapshot_meta WHERE tenant_id=%s AND owner_user_id=%s "
                    "AND profile_id=%s"
                ),
                [FIXTURE_TENANT_ID, FIXTURE_OWNER_USER_ID, SCORE_PROFILE_ID],
            ),
            (
                "score_profile_version",
                (
                    "DELETE FROM score_profile_version WHERE tenant_id=%s AND owner_user_id=%s "
                    "AND id=%s"
                ),
                [FIXTURE_TENANT_ID, FIXTURE_OWNER_USER_ID, SCORE_PROFILE_ID],
            ),
            (
                "score_profile",
                "DELETE FROM score_profile WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
                [FIXTURE_TENANT_ID, FIXTURE_OWNER_USER_ID, SCORE_PROFILE_ID],
            ),
            (
                "screen_profile_version",
                (
                    "DELETE FROM screen_profile_version WHERE tenant_id=%s AND owner_user_id=%s "
                    "AND id=%s"
                ),
                [FIXTURE_TENANT_ID, FIXTURE_OWNER_USER_ID, SCREEN_PROFILE_ID],
            ),
            (
                "screen_profile",
                "DELETE FROM screen_profile WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
                [FIXTURE_TENANT_ID, FIXTURE_OWNER_USER_ID, SCREEN_PROFILE_ID],
            ),
        )
        for name, sql, params in statements:
            cur.execute(sql, params)
            removed[name] = max(cur.rowcount, 0)
    return removed


def _seed_pg(pg: PostgresClient, target_date: date) -> None:
    from backend.scoring.snapshot import _current_param_hash

    now = datetime(2097, 4, 30, 18, 0, 0, tzinfo=UTC)
    score_items = json.dumps(
        [{
            "indicator": "total_mv",
            "params": {},
            "weight": 1,
            "scoring": {"type": "linear", "min": 0, "max": 20_000_000_000},
        }],
        ensure_ascii=False,
    )
    grade_thresholds = json.dumps({"watch": 0, "leader": 101, "core": 102})
    screen_expression = json.dumps(
        {"type": "col", "field": "total_mv", "cmp": ">", "value": 0},
        ensure_ascii=False,
    )
    with pg.transaction() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO score_profile "
            "(id,tenant_id,owner_user_id,name,version,items,grade_thresholds,is_preset,"
            "visibility,created_at,updated_at) VALUES (%s,%s,%s,%s,1,%s,%s,false,'private',%s,%s)",
            [SCORE_PROFILE_ID, FIXTURE_TENANT_ID, FIXTURE_OWNER_USER_ID,
             "E2E 关联展示评分方案", score_items, grade_thresholds, now, now],
        )
        cur.execute(
            "INSERT INTO score_profile_version "
            "(id,tenant_id,owner_user_id,version,name,items,grade_thresholds,saved_at) "
            "VALUES (%s,%s,%s,1,%s,%s,%s,%s)",
            [SCORE_PROFILE_ID, FIXTURE_TENANT_ID, FIXTURE_OWNER_USER_ID,
             "E2E 关联展示评分方案", score_items, grade_thresholds, now],
        )
        for rank, code in enumerate(STOCK_CODES, 1):
            cur.execute(
                "INSERT INTO score_snapshot "
                "(trade_date,tenant_id,owner_user_id,profile_id,profile_version,code,"
                "total_score,grade,rank,sub_scores) VALUES (%s,%s,%s,%s,1,%s,%s,%s,%s,%s)",
                [target_date, FIXTURE_TENANT_ID, FIXTURE_OWNER_USER_ID, SCORE_PROFILE_ID,
                 code, 90 - rank, "观察", rank, json.dumps({"total_mv": 90 - rank})],
            )
        cur.execute(
            "INSERT INTO score_snapshot_meta "
            "(trade_date,tenant_id,owner_user_id,profile_id,profile_version,computed_at,"
            "stale,n_codes,param_hash) VALUES (%s,%s,%s,%s,1,%s,false,%s,%s)",
            [target_date, FIXTURE_TENANT_ID, FIXTURE_OWNER_USER_ID, SCORE_PROFILE_ID,
             now, len(STOCK_CODES), _current_param_hash()],
        )
        cur.execute(
            "INSERT INTO screen_profile "
            "(id,tenant_id,owner_user_id,name,version,expression,params,is_preset,visibility,"
            "created_at,updated_at) VALUES (%s,%s,%s,%s,1,%s,'{}',false,'private',%s,%s)",
            [SCREEN_PROFILE_ID, FIXTURE_TENANT_ID, FIXTURE_OWNER_USER_ID,
             "E2E 关联展示筛选方案", screen_expression, now, now],
        )
        cur.execute(
            "INSERT INTO screen_profile_version "
            "(id,tenant_id,owner_user_id,version,name,expression,saved_at) "
            "VALUES (%s,%s,%s,1,%s,%s,%s)",
            [SCREEN_PROFILE_ID, FIXTURE_TENANT_ID, FIXTURE_OWNER_USER_ID,
             "E2E 关联展示筛选方案", screen_expression, now],
        )


def _pg_residual_counts(pg: PostgresClient) -> dict[str, int]:
    frame = pg.query_df(
        "SELECT "
        "(SELECT count(*) FROM score_profile WHERE tenant_id=%s AND owner_user_id=%s AND id=%s) "
        "+ (SELECT count(*) FROM score_profile_version WHERE tenant_id=%s AND owner_user_id=%s "
        "AND id=%s) "
        "+ (SELECT count(*) FROM score_snapshot WHERE tenant_id=%s AND owner_user_id=%s "
        "AND profile_id=%s) "
        "+ (SELECT count(*) FROM score_snapshot_meta WHERE tenant_id=%s AND owner_user_id=%s "
        "AND profile_id=%s) AS score_rows, "
        "(SELECT count(*) FROM screen_profile WHERE tenant_id=%s AND owner_user_id=%s AND id=%s) "
        "+ (SELECT count(*) FROM screen_profile_version WHERE tenant_id=%s AND owner_user_id=%s "
        "AND id=%s) "
        "AS screen_rows",
        [FIXTURE_TENANT_ID, FIXTURE_OWNER_USER_ID, SCORE_PROFILE_ID,
         FIXTURE_TENANT_ID, FIXTURE_OWNER_USER_ID, SCORE_PROFILE_ID,
         FIXTURE_TENANT_ID, FIXTURE_OWNER_USER_ID, SCORE_PROFILE_ID,
         FIXTURE_TENANT_ID, FIXTURE_OWNER_USER_ID, SCORE_PROFILE_ID,
         FIXTURE_TENANT_ID, FIXTURE_OWNER_USER_ID, SCREEN_PROFILE_ID,
         FIXTURE_TENANT_ID, FIXTURE_OWNER_USER_ID, SCREEN_PROFILE_ID],
    )
    return {
        "score_rows": int(frame.iloc[0]["score_rows"]),
        "screen_rows": int(frame.iloc[0]["screen_rows"]),
    }


def fixture_dates() -> list[date]:
    days: list[date] = []
    current = FIXTURE_START
    while len(days) < FIXTURE_POINTS:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _cleanup_runtime(runtime: Any) -> dict[str, int]:
    removed: dict[str, int] = {}
    statements = (
        (
            "scheduled_trigger_event",
            (
                "target_job_id LIKE ? OR source_task_id LIKE ? OR task_id LIKE ?"
            ),
            [f"{TASK_PREFIX}%", f"{TASK_PREFIX}%", f"{TASK_PREFIX}%"],
        ),
        ("task_log", "task_id LIKE ?", [f"{TASK_PREFIX}%"]),
        (
            "async_task",
            "id LIKE ? OR job_id LIKE ?",
            [f"{TASK_PREFIX}%", f"{TASK_PREFIX}%"],
        ),
        ("scheduled_job", "id LIKE ?", [f"{TASK_PREFIX}%"]),
    )
    with runtime.transaction():
        for table, where, params in statements:
            frame = runtime.query_df(f"SELECT count(*) AS n FROM {table} WHERE {where}", params)
            removed[table] = int(frame.iloc[0]["n"])
            runtime.execute(f"DELETE FROM {table} WHERE {where}", params)
    return removed


def _runtime_residual_count(runtime: Any) -> int:
    frame = runtime.query_df(
        "SELECT "
        "(SELECT count(*) FROM scheduled_trigger_event WHERE target_job_id LIKE ? "
        "OR source_task_id LIKE ? OR task_id LIKE ?) + "
        "(SELECT count(*) FROM task_log WHERE task_id LIKE ?) + "
        "(SELECT count(*) FROM async_task WHERE id LIKE ? OR job_id LIKE ?) + "
        "(SELECT count(*) FROM scheduled_job WHERE id LIKE ?) AS n",
        [f"{TASK_PREFIX}%"] * 7,
    )
    return int(frame.iloc[0]["n"])


def _seed_runtime(runtime: Any, target_date: date) -> None:
    now = datetime(2097, 4, 30, 18, 0, 0, tzinfo=UTC)
    task_result = {
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
    }
    with runtime.transaction():
        runtime.execute(
            "INSERT INTO scheduled_job "
            "(id,name,task_type,params,freq_type,freq_config,trigger_mode,dependency_delay,"
            "retry_config,trading_day_only,enabled,created_at,updated_at) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                "e2e_sbc_job",
                "E2E相关-盘后计算",
                "stock_board_correlation",
                runtime_json_param(runtime, {"codes": list(STOCK_CODES[:2]), "force": False}),
                "daily",
                runtime_json_param(runtime, {"time": "15:30"}),
                "time",
                runtime_json_param(runtime, {"value": 0, "unit": "minute"}),
                runtime_json_param(
                    runtime,
                    {
                        "enabled": False,
                        "condition": "failure",
                        "delay": {"value": 5, "unit": "minute"},
                        "max_retries": 1,
                    },
                ),
                True,
                False,
                now,
                now,
            ],
        )
        runtime.execute(
            "INSERT INTO async_task "
            "(id,task_type,params,status,progress,message,result,trigger_source,job_id,job_name,"
            "retry_count,execution_attempt,created_at,updated_at) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                "e2e_sbc_task",
                "stock_board_correlation",
                runtime_json_param(runtime, {"force": False}),
                "done",
                1,
                "E2E 关联计算完成",
                runtime_json_param(runtime, task_result),
                "scheduled",
                "e2e_sbc_job",
                "E2E相关-盘后计算",
                0,
                1,
                now,
                now,
            ],
        )
        runtime.execute(
            "INSERT INTO task_log (task_id,seq,ts,level,message) VALUES (?,?,?,?,?)",
            ["e2e_sbc_task", 1, now, "info", "阶段 5/5：原子切换完成"],
        )


def _cleanup(client: DuckDBClient) -> dict[str, int]:
    dates = fixture_dates()
    removed: dict[str, int] = {}
    statements = (
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


def _residual_counts(client: DuckDBClient, runtime: Any) -> dict[str, int]:
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
    return {
        "stocks": code_count,
        "boards": board_count,
        "tasks": _runtime_residual_count(runtime),
    }


def seed_stock_board_correlation(
    client: DuckDBClient | None = None,
    *,
    pg: PostgresClient | None = None,
    runtime_client: Any | None = None,
    expected_pg_fingerprint: str | None = None,
) -> dict[str, object]:
    """幂等写入页面、筛选和任务中心所需的固定行情与当前冠军。"""
    require_e2e_write_enabled()
    client = client or get_client()
    init_db(client)
    if expected_pg_fingerprint is not None:
        pg = pg or get_pg_client()
        _assert_pg_target(pg, expected_pg_fingerprint)
    if pg is not None:
        _assert_seed_owner(pg)
        _cleanup_pg(pg)
    runtime = runtime_client or (
        PostgresTaskRuntimeClient(pg) if pg is not None else get_task_runtime_client()
    )
    _cleanup_runtime(runtime)
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
                    (
                        board_code,
                        day,
                        close - 0.1,
                        close + 0.3,
                        close - 0.3,
                        close,
                        1_000_000,
                        100_000_000,
                    )
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
            "INSERT INTO stock_board_correlation_state "
            "(code,as_of_date,computed_at,algorithm_version,benchmark_code,"
            "benchmark_fallback,has_industry_champion,has_concept_champion) VALUES "
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
    if pg is not None:
        _seed_pg(pg, target_date)
    _seed_runtime(runtime, target_date)
    return {
        "stockCodes": list(STOCK_CODES),
        "boardCodes": list(BOARD_CODES),
        "targetDate": target_date.isoformat(),
        "jobId": "e2e_sbc_job",
        "taskId": "e2e_sbc_task",
        "scoreProfileId": SCORE_PROFILE_ID,
        "screenProfileId": SCREEN_PROFILE_ID,
    }


def cleanup_stock_board_correlation(
    client: DuckDBClient | None = None,
    *,
    pg: PostgresClient | None = None,
    runtime_client: Any | None = None,
    expected_pg_fingerprint: str | None = None,
) -> dict[str, object]:
    require_e2e_write_enabled()
    client = client or get_client()
    init_db(client)
    pg_removed: dict[str, int] = {}
    pg_residual: dict[str, int] = {}
    if expected_pg_fingerprint is not None:
        pg = pg or get_pg_client()
        _assert_pg_target(pg, expected_pg_fingerprint)
    if pg is not None:
        pg_removed = _cleanup_pg(pg)
        pg_residual = _pg_residual_counts(pg)
        if any(pg_residual.values()):
            raise RuntimeError(f"关联板块 E2E PostgreSQL 清理后仍有残留：{pg_residual}")
    runtime = runtime_client or (
        PostgresTaskRuntimeClient(pg) if pg is not None else get_task_runtime_client()
    )
    runtime_removed = _cleanup_runtime(runtime)
    with client.transaction():
        removed = _cleanup(client)
        residual = _residual_counts(client, runtime)
        if any(residual.values()):
            raise RuntimeError(f"关联板块 E2E 清理后仍有残留：{residual}")
    return {"removed": {**removed, **runtime_removed}, "residual": residual,
            "pgRemoved": pg_removed, "pgResidual": pg_residual}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("seed", "cleanup"))
    parser.add_argument("--expected-pg-fingerprint", required=True)
    args = parser.parse_args()
    result = (
        seed_stock_board_correlation(expected_pg_fingerprint=args.expected_pg_fingerprint)
        if args.command == "seed"
        else cleanup_stock_board_correlation(expected_pg_fingerprint=args.expected_pg_fingerprint)
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
