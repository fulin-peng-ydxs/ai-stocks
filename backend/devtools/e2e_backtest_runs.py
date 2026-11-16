"""Playwright 公开回测夹具（T6 硬验证项）。

为回测「浏览公开回测」抽屉的 E2E 提供一条**真实**的跨 owner 公开回测记录：
- 用固定调试账号 `debug_normal` 显式归属调用 `BacktestService.run_strategy`，走真实撮合
  （含 DuckDB 计算 + PG 落库 + 结果子表），生成的 run 经 `_decorate_run_row` 产生 opaque
  `run_ref`，再置为 tenant/public，成为他人可浏览、可复用重跑的来源。
- 比手工 INSERT 伪造行更稳：真实 id/params/signature/run_ref/结果子表，不会触发 opaque
  解析或详情缺表的边界。

仅允许本地/测试环境（`AI_STOCKS_ENV=dev|test|local` + `AI_STOCKS_E2E_WRITE=1` 双重授权），
seed/清理都校验被测后端 PG 指纹，只命中本夹具生成的 `e2e_bt_` 前缀记录与其复用审计，
绝不动他人数据。
"""

from __future__ import annotations

import argparse
import json
import secrets
import uuid
from datetime import timedelta

from backend.auth.context import AuthContext, reset_context, set_context
from backend.common.timeutil import shanghai_now_naive
from backend.devtools.e2e_market_data import seed_ci_market as seed_isolated_ci_market
from backend.devtools.environment_guard import require_e2e_write_enabled
from backend.services.backtest_service import BacktestService
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.pg_client import PostgresClient, get_pg_client
from backend.storage.pg_identity import pg_fingerprint

_RUN_ID_PREFIX = "e2e_bt_"


def seed_ci_market(client: DuckDBClient) -> dict[str, int]:
    """只为已初始化的空 CI 库准备行情；公开 run 仍由正式引擎撮合并写 PG。"""
    return seed_isolated_ci_market(
        client, suite="e2e-backtest", end=shanghai_now_naive().date() - timedelta(days=1),
        stock_name_prefix="E2E回测股票",
    )


def _assert_pg_target(pg: PostgresClient, expected_pg_fingerprint: str) -> None:
    if not expected_pg_fingerprint:
        raise RuntimeError("缺少被测后端 PostgreSQL 指纹，拒绝执行 E2E 数据写入")
    actual = pg_fingerprint(pg)
    if not secrets.compare_digest(actual, expected_pg_fingerprint):
        raise RuntimeError("E2E 夹具 PostgreSQL 与被测后端不一致，拒绝执行数据写入")


def _default_window() -> tuple[str, str]:
    """默认短窗口：覆盖近月若干交易日，足以让策略撮合产出完成态 run。"""
    end = shanghai_now_naive().date()
    start = end - timedelta(days=45)
    return start.isoformat(), end.isoformat()


def _owner_identity(pg: PostgresClient, owner_account: str) -> tuple[str, str]:
    owner = pg.query_df(
        "SELECT id, tenant_id FROM sys_user WHERE account=%s AND status='active' LIMIT 1",
        [owner_account],
    )
    if owner.empty:
        raise RuntimeError(f"回测种子归属账号不存在或未激活：{owner_account}")
    return str(owner.iloc[0]["tenant_id"]), str(owner.iloc[0]["id"])


def seed_public_run(
    *,
    owner_account: str,
    visibility: str,
    expected_pg_fingerprint: str,
    date_start: str | None = None,
    date_end: str | None = None,
    pg: PostgresClient | None = None,
) -> dict[str, str]:
    """以 owner_account 显式归属真实跑一次策略回测并置为 tenant/public。"""
    require_e2e_write_enabled()
    if visibility not in {"tenant", "public"}:
        raise ValueError(f"不支持的公开可见性：{visibility}")
    pg = pg or get_pg_client()
    _assert_pg_target(pg, expected_pg_fingerprint)
    tenant_id, owner_user_id = _owner_identity(pg, owner_account)

    ds, de = _default_window()
    date_start = date_start or ds
    date_end = date_end or de
    # 方案 ref 缺省：引擎按内置默认评分/买卖口径跑（与页面「不使用选股方案」一致）。
    params = {
        "date_start": date_start,
        "date_end": date_end,
        "profile_id": None,
        "score_profile_id": None,
        "trade_profile_id": None,
        "top_n": 5,
        "initial_capital": 1000000,
        "max_hold_days": 10,
        "rebalance_days": 3,
        "benchmark": "000905.SH",
        "horizons": [5, 10],
        "thresholds": [60, 80],
    }

    # 覆盖 id 前缀以便清理精确命中（真实 _new_id 的秒级时间戳+UUID 后缀仍保唯一）。
    run_id = _RUN_ID_PREFIX + uuid.uuid4().hex[:16]
    # 只读 DuckDB：行情数据只读、回测结果落 PG，夹具进程不持有写锁，可与运行中的后端并存。
    # 只读客户端跳过 init_db 的 CREATE SEQUENCE/DDL（只读模式本就无法执行）。
    duck = DuckDBClient(read_only=True)
    svc = BacktestService(client=duck, tenant_id=tenant_id, owner_user_id=owner_user_id)
    svc._new_id = lambda kind: run_id

    # 显式归属：run 与审计都落在调试账号名下（资产归属取上下文，禁止信任前端）。
    token = set_context(AuthContext(
        user_id=owner_user_id, tenant_id=tenant_id, roles=("normal",), is_system=False))
    try:
        result = svc.run_strategy(params)
        if "error" in result:
            raise RuntimeError(f"公开回测夹具撮合失败：{result['error']}")
        svc.set_run_visibility(run_id, visibility)
        detail = svc.get_run(run_id)
    finally:
        reset_context(token)
        duck.close()

    run_row = (detail or {}).get("run") or {}
    return {
        "runId": run_id,
        "runRef": str(run_row.get("run_ref") or ""),
        "ownerAccount": owner_account,
        "tenantId": tenant_id,
        "visibility": visibility,
        "dateStart": date_start,
        "dateEnd": date_end,
    }


def cleanup_runs(
    *,
    expected_pg_fingerprint: str,
    pg: PostgresClient | None = None,
) -> dict[str, int]:
    """删除本夹具生成的公开回测：结果子表 + run + 以其为来源的复用审计，按 id 前缀精确命中。"""
    require_e2e_write_enabled()
    pg = pg or get_pg_client()
    _assert_pg_target(pg, expected_pg_fingerprint)
    like = f"{_RUN_ID_PREFIX}%"
    removed: dict[str, int] = {}
    with pg.transaction() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, tenant_id, owner_user_id FROM backtest_run WHERE id LIKE %s", [like])
        seed_rows = cur.fetchall()
        for table in ("backtest_trade", "backtest_equity", "backtest_metrics"):
            cur.execute(
                f"DELETE FROM {table} WHERE run_id IN "
                f"(SELECT id FROM backtest_run WHERE id LIKE %s)",
                [like],
            )
            removed[table] = max(cur.rowcount, 0)
        # 复用审计：context.source_run_ref 指向种子 run 的 opaque ref（解码含种子 id）。
        cur.execute("DELETE FROM backtest_run WHERE id LIKE %s", [like])
        removed["run"] = max(cur.rowcount, 0)
        for _run_id, tenant_id, owner_user_id in seed_rows:
            cur.execute(
                "DELETE FROM audit_log WHERE tenant_id=%s AND actor_user_id=%s "
                "AND action='backtest_run_reuse'",
                [tenant_id, owner_user_id],
            )
            removed["audit"] = removed.get("audit", 0) + max(cur.rowcount, 0)
    return removed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Playwright 公开回测夹具")
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed")
    seed.add_argument("--owner-account", default="debug_normal")
    seed.add_argument("--visibility", default="public", choices=["tenant", "public"])
    seed.add_argument("--expected-pg-fingerprint", required=True)
    seed.add_argument("--date-start")
    seed.add_argument("--date-end")
    clean = sub.add_parser("cleanup")
    clean.add_argument("--expected-pg-fingerprint", required=True)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "seed":
        result = seed_public_run(
            owner_account=args.owner_account,
            visibility=args.visibility,
            expected_pg_fingerprint=args.expected_pg_fingerprint,
            date_start=args.date_start,
            date_end=args.date_end,
        )
    else:
        result = cleanup_runs(expected_pg_fingerprint=args.expected_pg_fingerprint)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
