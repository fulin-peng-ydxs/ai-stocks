"""交易纪律 Playwright 的确定性 PostgreSQL + DuckDB 夹具。

夹具只允许在明确的本地/测试环境和 ``AI_STOCKS_E2E_WRITE=1`` 下运行。PG 写入按
``debug_tenant + debug_* owner`` 归属，并使用 ``e2e_td_`` ID / ``E2E纪律-`` 名称前缀；
DuckDB 只写 ``9988*.SZ`` 与 2098 年固定交易日。seed/cleanup 在任何物理写入前都会把
调用方显式传入的后端 PG 指纹与夹具进程直连值做常量时间比较，禁止猜测数据库目标。
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from backend.common.exceptions import StorageError
from backend.devtools.environment_guard import require_e2e_write_enabled
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient, get_client
from backend.storage.pg_client import PostgresClient, get_pg_client
from backend.storage.pg_identity import pg_fingerprint

FIXTURE_TENANT_ID = "debug_tenant"
FIXTURE_ID_PREFIX = "e2e_td_"
FIXTURE_NAME_PREFIX = "E2E纪律-"
FIXTURE_REASON_PREFIX = "E2E原因-"
FIXTURE_OWNER_ACCOUNTS = (
    "debug_normal",
    "debug_trade_discipline_view",
    "debug_trade_discipline_submit",
    "debug_tenant_admin",
)
STOCK_CODES = ("998801.SZ", "998802.SZ", "998803.SZ")
SHANGHAI = ZoneInfo("Asia/Shanghai")
_PG_FINGERPRINT_RE = re.compile(r"^[a-f0-9]{64}$")
_LIKE_ID_PREFIX = "e2e\\_td\\_%"
_LIKE_NAME_PREFIX = f"{FIXTURE_NAME_PREFIX}%"
_LIKE_REASON_PREFIX = f"{FIXTURE_REASON_PREFIX}%"


def fixture_trade_dates() -> tuple[date, ...]:
    """返回 10 个固定工作日；最后 3 日只在日历中，用于展示待生效 v4。"""
    result: list[date] = []
    current = date(2098, 6, 2)
    while len(result) < 10:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return tuple(result)


FIXTURE_TRADE_DATES = fixture_trade_dates()
FIXTURE_CURRENT_TRADE_DATE = FIXTURE_TRADE_DATES[6]
FIXTURE_PENDING_TRADE_DATE = FIXTURE_TRADE_DATES[7]


def _assert_pg_target(pg: PostgresClient, expected_pg_fingerprint: str) -> None:
    """先校验参数格式再连接 PG；非法参数不得触发任何数据库访问。"""
    if not _PG_FINGERPRINT_RE.fullmatch(expected_pg_fingerprint or ""):
        raise RuntimeError("缺少合法的 64 位 PostgreSQL 指纹，拒绝执行 E2E 数据写入")
    actual = pg_fingerprint(pg)
    if not secrets.compare_digest(actual, expected_pg_fingerprint):
        raise RuntimeError("E2E 夹具 PostgreSQL 与被测后端不一致，拒绝执行数据写入")


def _default_owners() -> tuple[tuple[str, str], ...]:
    # 调试账号脚本固定 user id == account；cleanup 不依赖账号仍存在，才能清理中断残留。
    return tuple((FIXTURE_TENANT_ID, account) for account in FIXTURE_OWNER_ACCOUNTS)


def _assert_seed_owners(pg: PostgresClient) -> tuple[tuple[str, str], ...]:
    frame = pg.query_df(
        "SELECT tenant_id,id,account,status FROM sys_user WHERE account=ANY(%s)",
        [list(FIXTURE_OWNER_ACCOUNTS)],
    )
    rows = {str(row["account"]): row for _, row in frame.iterrows()}
    missing = [account for account in FIXTURE_OWNER_ACCOUNTS if account not in rows]
    invalid = [
        account
        for account, row in rows.items()
        if str(row["tenant_id"]) != FIXTURE_TENANT_ID
        or str(row["id"]) != account
        or str(row["status"]) != "active"
    ]
    if missing or invalid:
        detail = ", ".join([*(f"缺失:{item}" for item in missing), *(f"异常:{item}" for item in invalid)])
        raise RuntimeError(f"交易纪律固定调试账号未校准（{detail}），请先执行 ./start.sh dev-users")
    return _default_owners()


def _cleanup_pg(cur, owners: Iterable[tuple[str, str]]) -> dict[str, int]:
    removed: dict[str, int] = {}
    targets = tuple(owners)
    labels = (
        "operation", "violation", "reason", "checkin_revision", "checkin", "activation",
        "draft_action", "draft_stock", "draft", "action_rule", "stock_rule", "rule_version",
        "name_claim", "rule",
    )
    removed.update(dict.fromkeys(labels, 0))
    for tenant_id, owner_user_id in targets:
        cur.execute(
            "SELECT r.id FROM trade_discipline_rule r "
            "WHERE r.tenant_id=%s AND r.owner_user_id=%s AND ("
            "r.id LIKE %s ESCAPE '\\' OR r.name LIKE %s OR EXISTS ("
            "SELECT 1 FROM trade_discipline_rule_draft d "
            "WHERE d.tenant_id=r.tenant_id AND d.owner_user_id=r.owner_user_id "
            "AND d.rule_id=r.id AND d.proposed_name LIKE %s))",
            [tenant_id, owner_user_id, _LIKE_ID_PREFIX, _LIKE_NAME_PREFIX, _LIKE_NAME_PREFIX],
        )
        rule_ids = [str(row[0]) for row in cur.fetchall()]
        cur.execute(
            "SELECT id FROM trade_discipline_reason WHERE tenant_id=%s AND owner_user_id=%s "
            "AND (id LIKE %s ESCAPE '\\' OR name LIKE %s)",
            [tenant_id, owner_user_id, _LIKE_ID_PREFIX, _LIKE_REASON_PREFIX],
        )
        reason_ids = [str(row[0]) for row in cur.fetchall()]
        if not rule_ids and not reason_ids:
            continue
        checkin_ids: list[str] = []
        if rule_ids:
            cur.execute(
                "SELECT id FROM trade_discipline_checkin WHERE tenant_id=%s "
                "AND owner_user_id=%s AND rule_id=ANY(%s)",
                [tenant_id, owner_user_id, rule_ids],
            )
            checkin_ids = [str(row[0]) for row in cur.fetchall()]
            cur.execute(
                "UPDATE trade_discipline_rule SET status='unpublished',latest_version_no=NULL "
                "WHERE tenant_id=%s AND owner_user_id=%s AND id=ANY(%s)",
                [tenant_id, owner_user_id, rule_ids],
            )

        statements: tuple[tuple[str, str, list[object]], ...] = (
            ("operation", "DELETE FROM trade_discipline_operation WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=ANY(%s)", [tenant_id, owner_user_id, rule_ids]),
            ("violation", "DELETE FROM trade_discipline_violation WHERE tenant_id=%s AND owner_user_id=%s AND checkin_id=ANY(%s)", [tenant_id, owner_user_id, checkin_ids]),
            ("checkin_revision", "DELETE FROM trade_discipline_checkin_revision WHERE tenant_id=%s AND owner_user_id=%s AND checkin_id=ANY(%s)", [tenant_id, owner_user_id, checkin_ids]),
            ("checkin", "DELETE FROM trade_discipline_checkin WHERE tenant_id=%s AND owner_user_id=%s AND id=ANY(%s)", [tenant_id, owner_user_id, checkin_ids]),
            ("reason", "DELETE FROM trade_discipline_reason WHERE tenant_id=%s AND owner_user_id=%s AND id=ANY(%s)", [tenant_id, owner_user_id, reason_ids]),
            ("activation", "DELETE FROM trade_discipline_rule_activation WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=ANY(%s)", [tenant_id, owner_user_id, rule_ids]),
            ("draft_action", "DELETE FROM trade_discipline_draft_action_rule WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=ANY(%s)", [tenant_id, owner_user_id, rule_ids]),
            ("draft_stock", "DELETE FROM trade_discipline_draft_stock_rule WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=ANY(%s)", [tenant_id, owner_user_id, rule_ids]),
            ("draft", "DELETE FROM trade_discipline_rule_draft WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=ANY(%s)", [tenant_id, owner_user_id, rule_ids]),
            ("action_rule", "DELETE FROM trade_discipline_action_rule WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=ANY(%s)", [tenant_id, owner_user_id, rule_ids]),
            ("stock_rule", "DELETE FROM trade_discipline_stock_rule WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=ANY(%s)", [tenant_id, owner_user_id, rule_ids]),
            ("rule_version", "DELETE FROM trade_discipline_rule_version WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=ANY(%s)", [tenant_id, owner_user_id, rule_ids]),
            ("name_claim", "DELETE FROM trade_discipline_rule_name_claim WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=ANY(%s)", [tenant_id, owner_user_id, rule_ids]),
            ("rule", "DELETE FROM trade_discipline_rule WHERE tenant_id=%s AND owner_user_id=%s AND id=ANY(%s)", [tenant_id, owner_user_id, rule_ids]),
        )
        for label, sql, params in statements:
            if not params[-1]:
                continue
            cur.execute(sql, params)
            removed[label] += max(cur.rowcount, 0)

    residual: dict[str, int] = {}
    for tenant_id, owner_user_id in targets:
        cur.execute(
            "SELECT count(*) FROM trade_discipline_rule r WHERE r.tenant_id=%s "
            "AND r.owner_user_id=%s AND (r.id LIKE %s ESCAPE '\\' OR r.name LIKE %s OR "
            "EXISTS (SELECT 1 FROM trade_discipline_rule_draft d WHERE d.tenant_id=r.tenant_id "
            "AND d.owner_user_id=r.owner_user_id AND d.rule_id=r.id AND d.proposed_name LIKE %s))",
            [tenant_id, owner_user_id, _LIKE_ID_PREFIX, _LIKE_NAME_PREFIX, _LIKE_NAME_PREFIX],
        )
        rules_left = int(cur.fetchone()[0])
        cur.execute(
            "SELECT count(*) FROM trade_discipline_reason WHERE tenant_id=%s AND owner_user_id=%s "
            "AND (id LIKE %s ESCAPE '\\' OR name LIKE %s)",
            [tenant_id, owner_user_id, _LIKE_ID_PREFIX, _LIKE_REASON_PREFIX],
        )
        reasons_left = int(cur.fetchone()[0])
        if rules_left:
            residual[f"rule:{owner_user_id}"] = rules_left
        if reasons_left:
            residual[f"reason:{owner_user_id}"] = reasons_left
    if residual:
        raise RuntimeError(f"交易纪律 PostgreSQL 夹具清理后仍有残留：{residual}")
    return removed


def _cleanup_duck(market: DuckDBClient) -> dict[str, int]:
    removed: dict[str, int] = {}
    rows = market.execute(
        "DELETE FROM daily_bar WHERE code IN (SELECT unnest(?::VARCHAR[])) RETURNING 1",
        [list(STOCK_CODES)],
    ).fetchall()
    removed["daily_bar"] = len(rows)
    rows = market.execute(
        "DELETE FROM stock_basic WHERE code IN (SELECT unnest(?::VARCHAR[])) RETURNING 1",
        [list(STOCK_CODES)],
    ).fetchall()
    removed["stock_basic"] = len(rows)
    rows = market.execute(
        "DELETE FROM trade_calendar WHERE trade_date BETWEEN ? AND ? RETURNING 1",
        [FIXTURE_TRADE_DATES[0], FIXTURE_TRADE_DATES[-1]],
    ).fetchall()
    removed["trade_calendar"] = len(rows)
    residual = {
        "daily_bar": int(market.query_df(
            "SELECT count(*) AS n FROM daily_bar "
            "WHERE code IN (SELECT unnest(?::VARCHAR[]))",
            [list(STOCK_CODES)],
        ).iloc[0]["n"]),
        "stock_basic": int(market.query_df(
            "SELECT count(*) AS n FROM stock_basic "
            "WHERE code IN (SELECT unnest(?::VARCHAR[]))",
            [list(STOCK_CODES)],
        ).iloc[0]["n"]),
        "trade_calendar": int(market.query_df(
            "SELECT count(*) AS n FROM trade_calendar WHERE trade_date BETWEEN ? AND ?",
            [FIXTURE_TRADE_DATES[0], FIXTURE_TRADE_DATES[-1]],
        ).iloc[0]["n"]),
    }
    remaining = {key: value for key, value in residual.items() if value}
    if remaining:
        raise RuntimeError(f"交易纪律 DuckDB 夹具清理后仍有残留：{remaining}")
    return removed


def _seed_duck(market: DuckDBClient) -> dict[str, int]:
    market.conn.executemany(
        "INSERT INTO trade_calendar (trade_date,is_open) VALUES (?,TRUE)",
        [(current,) for current in FIXTURE_TRADE_DATES],
    )
    market.conn.executemany(
        "INSERT INTO stock_basic "
        "(code,name,exchange,board,list_date,industry,price_limit_pct) "
        "VALUES (?,?,'SZ','主板',DATE '2090-01-01','E2E行业',0.10)",
        [(code, f"E2E股票{index:02d}") for index, code in enumerate(STOCK_CODES, 1)],
    )
    bars = []
    for stock_index, code in enumerate(STOCK_CODES, 1):
        for day_index, current in enumerate(FIXTURE_TRADE_DATES[:7]):
            close = Decimal("10.00") + Decimal(stock_index) + Decimal(day_index) / 10
            bars.append(
                (code, current, close, close + 1, close - 1, close, close - Decimal("0.10"))
            )
    market.conn.executemany(
        "INSERT INTO daily_bar "
        "(code,trade_date,open,high,low,close,pre_close,volume,amount,turnover_rate,"
        "is_st,is_suspended,limit_status,is_one_word) "
        "VALUES (?,?,?,?,?,?,?,100000,1000000,1.5,FALSE,FALSE,0,FALSE)",
        bars,
    )
    return {"trade_calendar": len(FIXTURE_TRADE_DATES), "stock_basic": len(STOCK_CODES), "daily_bar": len(bars)}


def _insert_rule_version(cur, tenant_id: str, owner_user_id: str, rule_id: str, version_no: int) -> None:
    name = f"{FIXTURE_NAME_PREFIX}{owner_user_id}-v{version_no}"
    normalized_name = name.casefold()
    cur.execute(
        "INSERT INTO trade_discipline_rule_version "
        "(rule_id,tenant_id,owner_user_id,version_no,name,normalized_name,capital,published_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        [rule_id, tenant_id, owner_user_id, version_no, name, normalized_name, "100000.00", datetime.combine(FIXTURE_TRADE_DATES[min(version_no - 1, 3)], time(9), SHANGHAI)],
    )
    stock_rows = (
        ("e2e_td_stock_primary", "主趋势候选", "60000.00", "趋势向上且量价配合", 1),
        ("e2e_td_stock_secondary", "回踩候选", "40000.00", "缩量回踩关键均线", 2),
    )
    for detail_id, detail_name, max_capital, content, display_order in stock_rows:
        cur.execute(
            "INSERT INTO trade_discipline_stock_rule "
            "(rule_id,tenant_id,owner_user_id,version_no,detail_id,name,max_capital,content,display_order,enabled) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)",
            [rule_id, tenant_id, owner_user_id, version_no, detail_id, detail_name, max_capital, content, display_order],
        )
    action_rows = (
        ("e2e_td_action_buy", "回踩买入", "buy", "open_position", "确认承接后买入", 1),
        ("e2e_td_action_sell", "破位卖出", "sell", "liquidate", "跌破关键位离场", 1),
    )
    for detail_id, detail_name, action_type, subtype, content, display_order in action_rows:
        cur.execute(
            "INSERT INTO trade_discipline_action_rule "
            "(rule_id,tenant_id,owner_user_id,version_no,detail_id,name,action_type,action_subtype,content,display_order,enabled) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)",
            [rule_id, tenant_id, owner_user_id, version_no, detail_id, detail_name, action_type, subtype, content, display_order],
        )


def _insert_operation(
    cur,
    *,
    tenant_id: str,
    owner_user_id: str,
    rule_id: str,
    checkin_id: str,
    revision_no: int,
    operation_id: str,
    stock_index: int,
    side: str,
    display_order: int,
    operated_at: datetime,
) -> None:
    cur.execute(
        "INSERT INTO trade_discipline_operation "
        "(id,tenant_id,owner_user_id,checkin_id,revision_no,rule_id,version_no,stock_code,"
        "stock_name_snapshot,side,stock_rule_id,action_rule_id,price,quantity,amount,fee,"
        "operated_at,note,display_order) "
        "VALUES (%s,%s,%s,%s,%s,%s,3,%s,%s,%s,'e2e_td_stock_primary',%s,%s,%s,%s,%s,%s,%s,%s)",
        [
            operation_id,
            tenant_id,
            owner_user_id,
            checkin_id,
            revision_no,
            rule_id,
            STOCK_CODES[stock_index],
            f"E2E股票{stock_index + 1:02d}",
            side,
            "e2e_td_action_buy" if side == "buy" else "e2e_td_action_sell",
            "12.3456",
            "1000.0000",
            "12345.60",
            "5.00",
            operated_at,
            "E2E 多笔操作",
            display_order,
        ],
    )


def _insert_owner_fixture(cur, tenant_id: str, owner_user_id: str) -> dict[str, object]:
    slug = owner_user_id.removeprefix("debug_")
    rule_id = f"{FIXTURE_ID_PREFIX}{slug}_rule"
    latest_name = f"{FIXTURE_NAME_PREFIX}{owner_user_id}-v4"
    cur.execute(
        "INSERT INTO trade_discipline_rule "
        "(id,tenant_id,owner_user_id,name,normalized_name,status,latest_version_no,next_activation_seq,created_at,updated_at) "
        "VALUES (%s,%s,%s,%s,%s,'unpublished',NULL,6,%s,%s)",
        [rule_id, tenant_id, owner_user_id, latest_name, latest_name.casefold(), datetime.combine(FIXTURE_TRADE_DATES[0], time(8), SHANGHAI), datetime.combine(FIXTURE_CURRENT_TRADE_DATE, time(16), SHANGHAI)],
    )
    for version_no in range(1, 5):
        _insert_rule_version(cur, tenant_id, owner_user_id, rule_id, version_no)
    cur.execute(
        "UPDATE trade_discipline_rule SET status='active',latest_version_no=4 "
        "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
        [tenant_id, owner_user_id, rule_id],
    )
    cur.execute(
        "INSERT INTO trade_discipline_rule_name_claim "
        "(tenant_id,owner_user_id,normalized_name,rule_id,claimed_name) VALUES (%s,%s,%s,%s,%s)",
        [tenant_id, owner_user_id, latest_name.casefold(), rule_id, latest_name],
    )

    equal_event_at = datetime.combine(FIXTURE_TRADE_DATES[2], time(15, 30), SHANGHAI)
    events = (
        (1, "publish", 1, FIXTURE_TRADE_DATES[0], datetime.combine(FIXTURE_TRADE_DATES[0], time(9), SHANGHAI)),
        (2, "publish", 2, FIXTURE_TRADE_DATES[1], datetime.combine(FIXTURE_TRADE_DATES[1], time(9), SHANGHAI)),
        (3, "archive", 2, FIXTURE_TRADE_DATES[2], equal_event_at),
        (4, "restore", 2, FIXTURE_TRADE_DATES[2], equal_event_at),
        (5, "publish", 3, FIXTURE_TRADE_DATES[3], datetime.combine(FIXTURE_TRADE_DATES[3], time(9), SHANGHAI)),
        (6, "publish", 4, FIXTURE_PENDING_TRADE_DATE, datetime.combine(FIXTURE_CURRENT_TRADE_DATE, time(16), SHANGHAI)),
    )
    for event_seq, event_type, version_no, effective_date, occurred_at in events:
        cur.execute(
            "INSERT INTO trade_discipline_rule_activation "
            "(id,tenant_id,owner_user_id,rule_id,event_seq,event_type,version_no,occurred_at,activated_at,effective_from_trade_date) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [f"{FIXTURE_ID_PREFIX}{slug}_activation_{event_seq}", tenant_id, owner_user_id, rule_id, event_seq, event_type, version_no, occurred_at, occurred_at, effective_date],
        )

    reason_id = f"{FIXTURE_ID_PREFIX}{slug}_reason_custom"
    cur.execute(
        "INSERT INTO trade_discipline_reason "
        "(id,tenant_id,owner_user_id,name,normalized_name,is_active) VALUES (%s,%s,%s,'E2E计划外','e2e计划外',TRUE)",
        [reason_id, tenant_id, owner_user_id],
    )
    combinations = (
        ("complied", True),
        ("complied", False),
        ("breached", True),
        ("breached", False),
    )
    checkin_ids: list[str] = []
    for index, (assessment, no_operation) in enumerate(combinations, 1):
        trade_date = FIXTURE_TRADE_DATES[index + 1]
        checkin_id = f"{FIXTURE_ID_PREFIX}{slug}_checkin_{index}"
        checkin_ids.append(checkin_id)
        current_revision = 2 if index == 4 else 1
        submitted_at = datetime.combine(trade_date, time(15), SHANGHAI)
        amended_at = datetime.combine(trade_date, time(16), SHANGHAI) if current_revision == 2 else None
        cur.execute(
            "INSERT INTO trade_discipline_checkin "
            "(id,tenant_id,owner_user_id,rule_id,trade_date,current_revision_no,status,submitted_at,submission_source,amended_at,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'workbench',%s,%s,%s)",
            [checkin_id, tenant_id, owner_user_id, rule_id, trade_date, current_revision, "amended" if current_revision == 2 else "submitted", submitted_at, amended_at, submitted_at, amended_at or submitted_at],
        )
        if current_revision == 2:
            cur.execute(
                "INSERT INTO trade_discipline_checkin_revision "
                "(checkin_id,tenant_id,owner_user_id,revision_no,rule_id,version_no,revision_kind,assessment,no_operation,violation_detail,review_note,created_at) "
                "VALUES (%s,%s,%s,1,%s,3,'initial','complied',TRUE,NULL,'E2E 修正前快照',%s)",
                [checkin_id, tenant_id, owner_user_id, rule_id, submitted_at],
            )
        cur.execute(
            "INSERT INTO trade_discipline_checkin_revision "
            "(checkin_id,tenant_id,owner_user_id,revision_no,rule_id,version_no,revision_kind,assessment,no_operation,violation_detail,review_note,created_at) "
            "VALUES (%s,%s,%s,%s,%s,3,%s,%s,%s,%s,%s,%s)",
            [checkin_id, tenant_id, owner_user_id, current_revision, rule_id, "amendment" if current_revision == 2 else "initial", assessment, no_operation, "E2E 未按计划执行" if assessment == "breached" else None, "E2E 复盘记录", amended_at or submitted_at],
        )
        if assessment == "breached":
            cur.execute(
                "INSERT INTO trade_discipline_violation "
                "(checkin_id,tenant_id,owner_user_id,revision_no,reason_code,reason_id,reason_name_snapshot) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                [checkin_id, tenant_id, owner_user_id, current_revision, "missed_required_action" if no_operation else None, None if no_operation else reason_id, "未执行计划动作" if no_operation else "E2E计划外"],
            )
        if not no_operation:
            _insert_operation(
                cur,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                rule_id=rule_id,
                checkin_id=checkin_id,
                revision_no=current_revision,
                operation_id=f"{FIXTURE_ID_PREFIX}{slug}_operation_{index}_1",
                stock_index=0,
                side="buy",
                display_order=1,
                operated_at=datetime.combine(trade_date, time(10, 30), SHANGHAI),
            )
            _insert_operation(
                cur,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                rule_id=rule_id,
                checkin_id=checkin_id,
                revision_no=current_revision,
                operation_id=f"{FIXTURE_ID_PREFIX}{slug}_operation_{index}_2",
                stock_index=1,
                side="sell",
                display_order=2,
                operated_at=datetime.combine(trade_date, time(14, 30), SHANGHAI),
            )
    return {"owner": owner_user_id, "ruleId": rule_id, "checkinIds": checkin_ids}


def seed_trade_discipline_data(
    *,
    expected_pg_fingerprint: str,
    pg: PostgresClient | None = None,
    market: DuckDBClient | None = None,
    owners: tuple[tuple[str, str], ...] | None = None,
) -> dict[str, object]:
    """幂等重建全部专属数据；PG 与 DuckDB 写块均失败回滚。"""
    require_e2e_write_enabled()
    pg = pg or get_pg_client()
    _assert_pg_target(pg, expected_pg_fingerprint)
    targets = owners or _assert_seed_owners(pg)
    market = market or get_client()
    init_db(market)
    duck_committed = False
    try:
        with pg.transaction() as conn, conn.cursor() as cur:
            with market.transaction():
                removed_pg = _cleanup_pg(cur, targets)
                removed_duck = _cleanup_duck(market)
                seeded_duck = _seed_duck(market)
                seeded_owners = [_insert_owner_fixture(cur, *owner) for owner in targets]
            duck_committed = True
    except StorageError as seed_error:
        # 极窄窗口：DuckDB 已提交而 PG 最终提交失败时，补偿删除本夹具专属数据。
        if duck_committed:
            try:
                with market.transaction():
                    _cleanup_duck(market)
            except StorageError as cleanup_error:
                raise ExceptionGroup(
                    "交易纪律 seed 失败，且 DuckDB 补偿清理失败",
                    [seed_error, cleanup_error],
                ) from seed_error
        raise
    return {
        "tenantId": FIXTURE_TENANT_ID,
        "currentTradeDate": FIXTURE_CURRENT_TRADE_DATE.isoformat(),
        "pendingTradeDate": FIXTURE_PENDING_TRADE_DATE.isoformat(),
        "stockCodes": list(STOCK_CODES),
        "owners": seeded_owners,
        "seededDuck": seeded_duck,
        "removedBeforeSeed": {"pg": removed_pg, "duck": removed_duck},
    }


def cleanup_trade_discipline_data(
    *,
    expected_pg_fingerprint: str,
    pg: PostgresClient | None = None,
    market: DuckDBClient | None = None,
    owners: tuple[tuple[str, str], ...] | None = None,
) -> dict[str, object]:
    """按归属、ID/代码和固定日期精确清理；重复执行保持幂等。"""
    require_e2e_write_enabled()
    pg = pg or get_pg_client()
    _assert_pg_target(pg, expected_pg_fingerprint)
    targets = owners or _default_owners()
    market = market or get_client()
    init_db(market)
    with pg.transaction() as conn, conn.cursor() as cur:
        removed_pg = _cleanup_pg(cur, targets)
    with market.transaction():
        removed_duck = _cleanup_duck(market)
    return {"removedPg": removed_pg, "removedDuck": removed_duck}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="交易纪律 Playwright 确定性夹具")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("seed", "cleanup"):
        action = sub.add_parser(command)
        action.add_argument("--expected-pg-fingerprint", required=True)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "seed":
        result = seed_trade_discipline_data(expected_pg_fingerprint=args.expected_pg_fingerprint)
    else:
        result = cleanup_trade_discipline_data(expected_pg_fingerprint=args.expected_pg_fingerprint)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
