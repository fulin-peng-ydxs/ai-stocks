"""交易纪律确定性 E2E 夹具的安全、数据覆盖与幂等回归。"""

from __future__ import annotations

import pytest

from backend.common.exceptions import StorageError
from backend.devtools import e2e_trade_discipline as fixture
from backend.services.trade_discipline_service import TradeDisciplineService
from backend.services.trade_ledger_service import TradeLedgerService
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.pg_identity import pg_fingerprint
from backend.storage.trade_discipline_repository import TradeDisciplineRepository
from backend.storage.trade_ledger_repository import TradeLedgerRepository
from backend.tests.conftest import TEST_OWNER, TEST_TENANT

TEST_OWNERS = ((TEST_TENANT, TEST_OWNER),)


class _NoDatabaseAccess:
    def query_df(self, *_args, **_kwargs):
        raise AssertionError("非法指纹不应访问 PostgreSQL")


@pytest.mark.parametrize("value", ["", "abc", "G" * 64, "0" * 63, "0" * 65])
def test_invalid_pg_fingerprint_fails_before_database_access(value) -> None:
    with pytest.raises(RuntimeError, match="64 位 PostgreSQL 指纹"):
        fixture._assert_pg_target(_NoDatabaseAccess(), value)


def _count_pg(pg, table: str, prefix_column: str) -> int:
    return int(
        pg.query_df(
            f"SELECT count(*) AS n FROM {table} WHERE tenant_id=%s AND owner_user_id=%s "
            f"AND {prefix_column} LIKE %s ESCAPE '\\'",
            [TEST_TENANT, TEST_OWNER, "e2e\\_td\\_%"],
        ).iloc[0]["n"]
    )


def _seed(monkeypatch, pg, market):
    monkeypatch.setenv("AI_STOCKS_ENV", "test")
    monkeypatch.setenv("AI_STOCKS_E2E_WRITE", "1")
    return fixture.seed_trade_discipline_data(
        expected_pg_fingerprint=pg_fingerprint(pg),
        pg=pg,
        market=market,
        owners=TEST_OWNERS,
    )


def test_seed_is_deterministic_complete_and_cleanup_is_idempotent(pg, market, monkeypatch) -> None:
    result = _seed(monkeypatch, pg, market)
    assert result["currentTradeDate"] == "2098-06-10"
    assert result["pendingTradeDate"] == "2098-06-11"
    assert result["stockCodes"] == list(fixture.STOCK_CODES)
    st_rows = market.query_df(
        "SELECT code,trade_date,is_st,quality FROM stock_st_status_daily "
        "WHERE source='e2e-trade-discipline'"
    )
    assert len(st_rows) == int(market.query_df("SELECT count(*) n FROM daily_bar").iloc[0]["n"])
    assert not st_rows["is_st"].any()
    assert set(st_rows["quality"]) == {"accurate"}

    expected_counts = {
        ("trade_discipline_rule", "id"): 1,
        ("trade_discipline_rule_version", "rule_id"): 4,
        ("trade_discipline_stock_rule", "rule_id"): 8,
        ("trade_discipline_action_rule", "rule_id"): 8,
        ("trade_discipline_rule_activation", "id"): 6,
        ("trade_discipline_checkin", "id"): 0,
        ("trade_discipline_checkin_revision", "checkin_id"): 0,
        ("trade_discipline_reason", "id"): 0,
        ("trade_discipline_violation", "checkin_id"): 0,
        ("trade_discipline_operation", "id"): 0,
    }
    for (table, prefix_column), expected in expected_counts.items():
        assert _count_pg(pg, table, prefix_column) == expected

    equal_events = pg.query_df(
        "SELECT event_seq,event_type,occurred_at,effective_from_trade_date "
        "FROM trade_discipline_rule_activation WHERE tenant_id=%s AND owner_user_id=%s "
        "AND event_seq IN (3,4) ORDER BY event_seq",
        [TEST_TENANT, TEST_OWNER],
    )
    assert equal_events["event_type"].tolist() == ["archive", "restore"]
    assert equal_events.iloc[0]["occurred_at"] == equal_events.iloc[1]["occurred_at"]
    assert (
        equal_events.iloc[0]["effective_from_trade_date"]
        == equal_events.iloc[1]["effective_from_trade_date"]
    )

    service = TradeDisciplineService(
        TradeDisciplineRepository(pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER),
        market,
    )
    state = service.list_rules_with_state(fixture.FIXTURE_CURRENT_TRADE_DATE)[0]
    assert state["latest_version_no"] == 4
    assert state["effective_event_seq"] == 5
    assert state["effective_version"]["version_no"] == 3
    assert state["has_pending_management_action"] is True

    ledger = TradeLedgerService(TradeLedgerRepository(pg, tenant_id=TEST_TENANT, owner_user_id=TEST_OWNER), market)
    history = ledger.repo.history(sort_order="asc")["list"]
    assert len(history) == 4
    assert [(row["snapshot"]["assessment"], row["snapshot"]["operation_count"] == 0) for row in history] == [
        ("complied", True), ("complied", False), ("breached", True), ("breached", False),
    ]
    assert [row["current_revision_no"] for row in history] == [1, 1, 1, 2]
    assert ledger.revisions(fixture.FIXTURE_TRADE_DATES[2], 1)["snapshot"]["rules"][0]["version_no"] == 2
    original = ledger.revisions(fixture.FIXTURE_TRADE_DATES[5], 1)["snapshot"]
    revised = ledger.revisions(fixture.FIXTURE_TRADE_DATES[5], 2)["snapshot"]
    assert original["events"] == [] and original["review_note"] == "E2E 修正前快照"
    assert len(revised["events"]) == 2 and revised["review_note"] == "E2E 账本复盘记录"
    assert revised["buy_amount"] == revised["sell_amount"] == "1234.56"
    assert revised["fee"] == "10.00"
    assert ledger.context(fixture.FIXTURE_CURRENT_TRADE_DATE)["cash"] == "99980.00"
    assert int(market.query_df(
        "SELECT count(*) AS n FROM stock_basic WHERE code IN (SELECT unnest(?::VARCHAR[]))",
        [list(fixture.STOCK_CODES)],
    ).iloc[0]["n"]) == 3
    assert int(market.query_df(
        "SELECT count(*) AS n FROM daily_bar "
        "WHERE code IN (SELECT unnest(?::VARCHAR[]))",
        [list(fixture.STOCK_CODES)],
    ).iloc[0]["n"]) == 19
    delisted_last_bar = market.query_df(
        "SELECT max(trade_date) AS d FROM daily_bar WHERE code=?",
        [fixture.STOCK_CODES[-1]],
    ).iloc[0]["d"].date()
    assert delisted_last_bar < fixture.FIXTURE_DELIST_DATE
    assert market.query_df(
        "SELECT max(trade_date) AS d FROM daily_bar "
        "WHERE code IN (SELECT unnest(?::VARCHAR[]))",
        [list(fixture.STOCK_CODES)],
    ).iloc[0]["d"].date() == fixture.FIXTURE_CURRENT_TRADE_DATE

    _seed(monkeypatch, pg, market)
    for (table, prefix_column), expected in expected_counts.items():
        assert _count_pg(pg, table, prefix_column) == expected

    # 页面生成的 ID 没有夹具前缀；只能依据已保存的专属草稿名精确回收，不得清理其他匿名草稿。
    pg.execute(
        "INSERT INTO trade_discipline_rule (id,tenant_id,owner_user_id,status) "
        "VALUES ('tdr_e2e_abandoned',%s,%s,'unpublished'),"
        "('tdr_e2e_named',%s,%s,'unpublished')",
        [TEST_TENANT, TEST_OWNER, TEST_TENANT, TEST_OWNER],
    )
    pg.execute(
        "INSERT INTO trade_discipline_rule_draft "
        "(rule_id,tenant_id,owner_user_id,draft_revision,proposed_name,normalized_name) "
        "VALUES ('tdr_e2e_abandoned',%s,%s,1,NULL,NULL),"
        "('tdr_e2e_named',%s,%s,1,'E2E纪律-页面保存','e2e纪律-页面保存')",
        [TEST_TENANT, TEST_OWNER, TEST_TENANT, TEST_OWNER],
    )
    pg.execute(
        "INSERT INTO trade_discipline_reason "
        "(id,tenant_id,owner_user_id,name,normalized_name) "
        "VALUES ('tdreason_e2e_generated',%s,%s,'E2E原因-页面新增','e2e原因-页面新增')",
        [TEST_TENANT, TEST_OWNER],
    )

    with pytest.raises(RuntimeError, match="PostgreSQL 与被测后端不一致"):
        fixture.cleanup_trade_discipline_data(
            expected_pg_fingerprint="0" * 64,
            pg=pg,
            market=market,
            owners=TEST_OWNERS,
        )
    assert _count_pg(pg, "trade_discipline_rule", "id") == 1

    pg.execute(
        "INSERT INTO trade_discipline_account (tenant_id,owner_user_id,id,opening_cash) "
        "VALUES (%s,%s,'other-account',777)", [TEST_TENANT, TEST_OWNER],
    )
    first = fixture.cleanup_trade_discipline_data(
        expected_pg_fingerprint=pg_fingerprint(pg),
        pg=pg,
        market=market,
        owners=TEST_OWNERS,
    )
    second = fixture.cleanup_trade_discipline_data(
        expected_pg_fingerprint=pg_fingerprint(pg),
        pg=pg,
        market=market,
        owners=TEST_OWNERS,
    )
    assert first["removedPg"]["rule"] == 2
    assert first["removedPg"]["reason"] == 1
    assert first["removedPg"]["ledger_revision"] == 5
    assert first["removedPg"]["ledger_day"] == 4
    assert first["removedPg"]["account"] == 1
    assert int(pg.query_df(
        "SELECT opening_cash FROM trade_discipline_account "
        "WHERE tenant_id=%s AND owner_user_id=%s AND id='other-account'", [TEST_TENANT, TEST_OWNER],
    ).iloc[0]["opening_cash"]) == 777
    assert first["removedDuck"]["stock_basic"] == 3
    assert first["removedDuck"]["stock_st_status_daily"] == len(st_rows)
    assert int(pg.query_df(
        "SELECT count(*) AS n FROM trade_discipline_rule WHERE id='tdr_e2e_abandoned'",
    ).iloc[0]["n"]) == 1
    assert all(value == 0 for value in second["removedPg"].values())
    assert all(value == 0 for value in second["removedDuck"].values())


def test_seed_failure_rolls_back_both_databases(pg, tmp_path, monkeypatch) -> None:
    # DuckDBClient 会在事务异常后丢弃连接；使用磁盘测试库才能真实验证重连后的回滚事实。
    market = DuckDBClient(tmp_path / "trade-discipline-e2e.duckdb")
    try:
        _seed(monkeypatch, pg, market)
        before_pg = _count_pg(pg, "trade_discipline_rule", "id")
        before_duck = int(market.query_df(
            "SELECT count(*) AS n FROM stock_basic WHERE code IN (SELECT unnest(?::VARCHAR[]))",
            [list(fixture.STOCK_CODES)],
        ).iloc[0]["n"])

        def fail_owner(*_args, **_kwargs):
            raise RuntimeError("注入 seed 失败")

        monkeypatch.setattr(fixture, "_insert_owner_fixture", fail_owner)
        with pytest.raises(StorageError, match="注入 seed 失败"):
            fixture.seed_trade_discipline_data(
                expected_pg_fingerprint=pg_fingerprint(pg),
                pg=pg,
                market=market,
                owners=TEST_OWNERS,
            )

        assert _count_pg(pg, "trade_discipline_rule", "id") == before_pg
        assert int(market.query_df(
            "SELECT count(*) AS n FROM stock_basic WHERE code IN (SELECT unnest(?::VARCHAR[]))",
            [list(fixture.STOCK_CODES)],
        ).iloc[0]["n"]) == before_duck
    finally:
        market.close()


def test_non_fixture_default_account_is_never_replaced_or_deleted(pg, market, monkeypatch):
    pg.execute(
        "INSERT INTO trade_discipline_account (tenant_id,owner_user_id,id,opening_cash) "
        "VALUES (%s,%s,'default',12345.67)", [TEST_TENANT, TEST_OWNER],
    )
    monkeypatch.setenv("AI_STOCKS_ENV", "test")
    monkeypatch.setenv("AI_STOCKS_E2E_WRITE", "1")
    for action in (fixture.seed_trade_discipline_data, fixture.cleanup_trade_discipline_data):
        with pytest.raises(StorageError, match="默认账户不属于确定性夹具"):
            action(expected_pg_fingerprint=pg_fingerprint(pg), pg=pg, market=market, owners=TEST_OWNERS)
        row = pg.query_df(
            "SELECT opening_cash,initialized_on FROM trade_discipline_account "
            "WHERE tenant_id=%s AND owner_user_id=%s AND id='default'", [TEST_TENANT, TEST_OWNER],
        ).iloc[0]
        assert str(row["opening_cash"]) == "12345.67"
    assert market.query_df("SELECT count(*) n FROM stock_basic").iloc[0]["n"] == 0


def test_ledger_failure_rolls_back_previously_written_revision_and_market(pg, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_STOCKS_ENV", "test")
    monkeypatch.setenv("AI_STOCKS_E2E_WRITE", "1")
    original = TradeLedgerService.submit
    calls = 0
    def fail_after_first(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("日结中途失败")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(TradeLedgerService, "submit", fail_after_first)
    with DuckDBClient(tmp_path / "ledger-failure.duckdb") as market:
        with pytest.raises(StorageError, match="日结中途失败"):
            fixture.seed_trade_discipline_data(
                expected_pg_fingerprint=pg_fingerprint(pg), pg=pg, market=market, owners=TEST_OWNERS,
            )
        assert calls == 2
        for table in ("trade_discipline_account", "trade_discipline_ledger_day", "trade_discipline_ledger_revision"):
            assert pg.query_df(f"SELECT count(*) n FROM {table} WHERE tenant_id=%s AND owner_user_id=%s",
                               [TEST_TENANT, TEST_OWNER]).iloc[0]["n"] == 0
        assert market.query_df("SELECT count(*) n FROM stock_basic").iloc[0]["n"] == 0
