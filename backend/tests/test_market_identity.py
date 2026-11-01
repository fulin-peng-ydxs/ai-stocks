"""更码身份、逐日来源、横截面与跨代码记账的共同边界。"""
from datetime import date, timedelta
from types import SimpleNamespace

import duckdb
import pandas as pd
import pytest

from backend.market_identity import (
    IDENTITY_VERSION,
    STOCK_CODE_CHANGES,
    canonical_stock_code,
    filter_trading_codes,
    source_code_periods,
    trading_code_active_sql,
    trading_code_at,
)


@pytest.mark.parametrize("change", STOCK_CODE_CHANGES)
def test_code_identity_python_sql_and_frame_agree(change):
    before = change.effective_date - timedelta(days=1)
    rows = pd.DataFrame([
        {"code": code, "trade_date": day}
        for code in [change.previous_code, change.current_code, "600000.SH"]
        for day in [before, change.effective_date, change.effective_date + timedelta(days=1)]
    ])
    expected = rows[[trading_code_at(row.code, row.trade_date) == row.code
                     for row in rows.itertuples(index=False)]]
    actual = filter_trading_codes(rows)
    pd.testing.assert_frame_equal(actual, expected)
    with duckdb.connect(":memory:") as c:
        c.register("identity_rows", rows)
        sql = trading_code_active_sql("code", "trade_date")
        assert c.execute(f"SELECT code,trade_date FROM identity_rows WHERE {sql} ORDER BY 1,2").fetchall() == sorted(
            (row.code, pd.Timestamp(row.trade_date).date())
            for row in expected.itertuples(index=False)
        )
    assert canonical_stock_code(change.previous_code) == change.current_code
    assert canonical_stock_code(change.current_code) == change.current_code


@pytest.mark.parametrize("change", STOCK_CODE_CHANGES)
def test_source_code_periods_are_inclusive_disjoint_and_evidenced(change):
    before, after = change.effective_date - timedelta(days=1), change.effective_date + timedelta(days=1)
    for code in [change.previous_code, change.current_code]:
        assert source_code_periods(code, before, after) == [
            (change.previous_code, before, before, change.evidence_url),
            (change.current_code, change.effective_date, after, change.evidence_url),
        ]
    assert source_code_periods(change.current_code, date(2012, 1, 1), date(2012, 12, 31))[0][0] == change.previous_code


def test_identity_registry_is_explicit_and_single_sourced():
    assert len(IDENTITY_VERSION) == 16
    assert len({x.previous_code for x in STOCK_CODE_CHANGES}) == len(STOCK_CODE_CHANGES)
    assert len({x.current_code for x in STOCK_CODE_CHANGES}) == len(STOCK_CODE_CHANGES)
    assert all(x.evidence_url.startswith("https://") for x in STOCK_CODE_CHANGES)
    assert trading_code_at("600000.SH", date(2012, 1, 4)) == "600000.SH"
    assert source_code_periods("600000.SH", date(2012, 1, 4), date(2012, 1, 5)) == [
        ("600000.SH", date(2012, 1, 4), date(2012, 1, 5), None),
    ]


@pytest.mark.parametrize("change", STOCK_CODE_CHANGES)
def test_baostock_st_routes_actual_codes_and_preserves_origin(monkeypatch, change):
    import baostock as bs

    from backend.datasource.baostock_source import BaostockSource, full_to_bs

    source = BaostockSource()
    source._min_interval_sec = 0
    before, after = change.effective_date - timedelta(days=1), change.effective_date + timedelta(days=1)
    calls = []

    def query(code, fields, **params):
        calls.append((code, params["start_date"], params["end_date"]))
        # 两边故意多返一个越界日，必须按真实身份区间裁剪后才能落准确事实。
        return pd.DataFrame([
            {"date": day.isoformat(), "tradestatus": "1", "isST": "0"}
            for day in [before, change.effective_date, after]
        ])

    monkeypatch.setattr(bs, "query_history_k_data_plus", query)
    monkeypatch.setattr(source, "_query_frame", lambda call: call())
    result = source.get_st_status(change.current_code, before, after)
    assert calls == [
        (full_to_bs(change.previous_code), before.isoformat(), before.isoformat()),
        (full_to_bs(change.current_code), change.effective_date.isoformat(), after.isoformat()),
    ]
    assert result.trade_date.tolist() == [before, change.effective_date, after]
    assert result.code.tolist() == [change.current_code] * 3
    assert change.previous_code in result.source_ref.iloc[0]
    assert change.evidence_url in result.source_ref.iloc[0]


def test_st_conversion_preserves_queried_identity_in_both_paths(market, monkeypatch):
    from backend.services.ingest import IngestionService

    source = SimpleNamespace(name="baostock")
    origin = "query_history_k_data_plus:isST;query_code=000043.SZ;identity=verified"
    rows = pd.DataFrame([{"code": "001914.SZ", "trade_date": date(2012, 9, 10),
                          "is_st": False, "trade_status": 1, "source_ref": origin}])
    service = object.__new__(IngestionService)
    service.c = market
    monkeypatch.setattr(service, "_fetch_st_status_rows", lambda *a, **kw: (source, rows))
    monkeypatch.setattr(service, "_persist_gap_status", lambda *a, **kw: None)
    normal = service._accurate_st_facts("001914.SZ", [date(2012, 9, 10)])
    refresh = service._st_facts_from_rows("001914.SZ", source, rows)
    assert normal[0].status.source_ref == refresh[0].status.source_ref == origin
    assert normal[0].status.is_st is False


def test_rs_cross_section_does_not_double_count_code_aliases():
    from backend.indicators.engine import IndicatorEngine

    rows = pd.DataFrame([
        {"code": code, "trade_date": date(2012, 6, 29), "ret_w": value}
        for code, value in [("000043.SZ", .1), ("001914.SZ", .1), ("600000.SH", .2)]
    ])
    result = IndicatorEngine._cross_sectional_rs([rows]).set_index("code")
    assert set(result.index) == {"000043.SZ", "600000.SH"}
    assert result.loc["000043.SZ", "rs_pct"] == 50
    assert result.loc["600000.SH", "rs_pct"] == 100


def test_identity_sql_at_representative_market_scale():
    expression = trading_code_active_sql("code", "day")
    with duckdb.connect(":memory:") as c:
        count = c.execute(f"SELECT count(*) FROM (SELECT '001914.SZ' code, "
                          "DATE '2019-12-15'+(i%2)::INTEGER AS day FROM range(3000000) t(i)) "
                          f"WHERE {expression}").fetchone()[0]
    assert count == 1_500_000


def test_broker_code_transfer_preserves_value_and_does_not_trade():
    from backend.backtest.broker import Broker
    from backend.config import CostConfig

    costs = CostConfig(commission_rate=0, commission_min=0, stamp_tax_rate=0,
                       transfer_fee_rate=0, slippage=0)
    broker = Broker(cash=10_000, cost=costs, lot_size=1)
    broker.buy("000043.SZ", date(2019, 12, 13), 100, 10_000)
    broker.transfer_code("000043.SZ", "001914.SZ", .4, date(2019, 12, 16))
    assert len(broker.fills) == 1
    assert broker.cash == 0
    assert broker.positions["001914.SZ"].shares == 100
    broker.mark({"001914.SZ": 250})
    assert broker.equity() == 10_000
    fill = broker.sell_all("001914.SZ", date(2019, 12, 17), 275)
    assert fill.price == 110
    assert broker.cash == 11_000


def test_forward_return_spans_code_change_with_one_hfq_basis(market):
    from backend.backtest.forward import compute_forward_returns

    for code, factor in [("000043.SZ", 2.), ("001914.SZ", 20.)]:
        for day, price in [(date(2019, 12, 13), 10.), (date(2019, 12, 16), 11.),
                           (date(2019, 12, 17), 12.)]:
            if code == "000043.SZ" and day >= date(2019, 12, 16):
                continue
            market.execute("INSERT INTO daily_bar(code,trade_date,open,high,close,adj_factor) "
                           "VALUES (?,?,?,?,?,?)", [code, day, price, price, price, factor])
    result = compute_forward_returns(date(2019, 12, 13), date(2019, 12, 13), [2],
                                     codes=["000043.SZ"], client=market)
    assert result.code.tolist() == ["000043.SZ"]
    assert result.eval_2.tolist() == [True]
    assert result.fwd_ret_2.iloc[0] == pytest.approx(12 / 11 - 1)


@pytest.fixture()
def identity_market(market):
    from backend.tests.test_backtest import _seed_index, _seed_one_stock

    days = [date(2019, 12, d) for d in [11, 12, 13, 16, 17]]
    for code, factor in [("000043.SZ", 2.), ("001914.SZ", 20.)]:
        rows = [(day, price, price, price, price, price)
                for day, price in zip(days, [10, 10, 10, 11, 12])
                if code != "000043.SZ" or day < date(2019, 12, 16)]
        _seed_one_stock(market, code, rows)
        market.execute("UPDATE stock_basic SET list_date=DATE '1994-09-28',delist_date=? WHERE code=?",
                       [date(2019, 12, 16) if code == "000043.SZ" else None, code])
        market.execute("UPDATE daily_bar SET adj_factor=? WHERE code=?", [factor, code])
    _seed_index(market, days)
    return market, days


@pytest.mark.parametrize("mode", ["hold", "buy_on_change", "pending_sell", "missing_anchor", "conflicting_anchor"])
def test_strategy_code_change_closes_execution_and_accounting(identity_market, monkeypatch, mode):
    from backend.backtest import engine as module
    from backend.backtest.broker import Broker
    from backend.config import CostConfig

    market, days = identity_market
    zero = CostConfig(commission_rate=0, commission_min=0, stamp_tax_rate=0,
                      transfer_fee_rate=0, slippage=0)
    monkeypatch.setattr(module, "Broker", lambda cash: Broker(cash, cost=zero, lot_size=1))
    engine = module.BacktestEngine(market)
    selections = {}
    for day in days:
        if mode == "buy_on_change" and day < date(2019, 12, 13):
            continue
        if mode == "pending_sell" and day >= date(2019, 12, 12):
            continue
        selections[pd.Timestamp(day)] = pd.DataFrame([{
            "code": trading_code_at("001914.SZ", day), "total_score": 80., "grade": "A"}])
    monkeypatch.setattr(engine, "_load_scores", lambda *a: selections)
    if mode == "pending_sell":
        # 周四跌至9触发止损，周五跌停不可卖；下周一更码后必须继续执行。
        market.execute("UPDATE daily_bar SET close=9 WHERE trade_date=DATE '2019-12-12'")
        market.execute("UPDATE daily_bar SET open=9,pre_close=10 WHERE code='000043.SZ' "
                       "AND trade_date=DATE '2019-12-13'")
    if mode == "conflicting_anchor":
        market.execute("UPDATE daily_bar SET close=10.05 WHERE code='001914.SZ' "
                       "AND trade_date=DATE '2019-12-13'")
        with pytest.raises(ValueError, match="复权锚点价格或因子不一致"):
            engine.run({"date_start": days[0], "date_end": days[-1], "initial_capital": 10_000,
                        "top_n": 1, "sell_ma_period": 100})
        return
    if mode == "missing_anchor":
        market.execute("DELETE FROM daily_bar WHERE code='001914.SZ' AND trade_date<DATE '2019-12-16'")
        with pytest.raises(ValueError, match="缺切换前共同复权锚点"):
            engine.run({"date_start": days[0], "date_end": days[-1], "initial_capital": 10_000,
                        "top_n": 1, "sell_ma_period": 100})
        return
    result = engine.run({"date_start": days[0], "date_end": days[-1], "initial_capital": 10_000,
                         "top_n": 1, "sell_ma_period": 100,
                         "stop_loss": .05 if mode == "pending_sell" else None})
    assert len(result["trades"]) == 1
    trade = result["trades"][0]
    assert trade["code"] == "001914.SZ"
    assert trade["entry_rank"] == trade["entry_pick_rank"] == trade["entry_pool"] == 1
    if mode == "hold":
        assert trade["entry_date"] == date(2019, 12, 12)
        assert trade["return_pct"] == .2
        assert result["equity"].equity.tolist() == [10_000, 10_000, 10_000, 11_000, 12_000]
        assert "000043.SZ→001914.SZ" in trade["exit_detail"]
    elif mode == "buy_on_change":
        assert trade["entry_date"] == date(2019, 12, 16)
        assert trade["entry_price"] == 220
        assert trade["return_pct"] == pytest.approx(12 / 11 - 1, abs=1e-6)
    else:
        assert trade["exit_date"] == date(2019, 12, 16)
        assert trade["exit_reason"] == "顺延"
        assert trade["return_pct"] == .1


@pytest.mark.parametrize("day,expected", [(date(2019, 12, 13), "000043.SZ"),
                                         (date(2019, 12, 16), "001914.SZ")])
def test_point_in_time_consumers_share_code_eligibility(identity_market, day, expected, monkeypatch):
    from backend.api import stocks
    from backend.services.limit_ladder_calculator import LimitLadderCalculator
    from backend.services.stock_board_correlation import (
        CorrelationInputError,
        StockBoardCorrelationService,
    )
    from backend.storage.repository import MarketRepository

    market, _ = identity_market
    filters = {"exclude_st": False, "min_list_days": 0, "exclude_one_word_limit": False,
               "float_mv_min": None, "float_mv_max": None}
    assert MarketRepository(market).get_universe_asof(day, filters) == [expected]
    assert LimitLadderCalculator(market)._point_in_time_basics(day).code.tolist() == [expected]
    service = StockBoardCorrelationService(market)
    assert service.resolve_target_codes(day)[0] == [expected]
    other = "001914.SZ" if expected == "000043.SZ" else "000043.SZ"
    with pytest.raises(CorrelationInputError, match="未生效或已更码"):
        service.resolve_target_codes(day, [other])
    monkeypatch.setattr(stocks, "get_client", lambda: market)
    monkeypatch.setattr(stocks, "get_current_context", lambda: None)
    # 列表附加走势读取另有独立测试；此处只验证真实列表与 ST 前检的候选范围。
    monkeypatch.setattr(StockBoardCorrelationService, "attach_related_boards", lambda *a, **kw: None)
    result = stocks.list_stocks(trade_date=day, statuses="正常上市,ST")
    assert [r["code"] for r in result.data["list"]] == [expected]


def test_trade_discipline_rejects_inactive_code_at_both_boundaries(identity_market, monkeypatch):
    from backend.api import trade_discipline as api
    from backend.common.exceptions import ValidationError
    from backend.services.trade_discipline_service import TradeDisciplineService

    market, _ = identity_market
    day = date(2019, 12, 13)
    monkeypatch.setattr(api, "get_client", lambda: market)
    result = api.stock_options(q="0", limit=20, trade_date=day)
    assert [r["code"] for r in result.data["list"]] == ["000043.SZ"]
    service = object.__new__(TradeDisciplineService)
    service.market = market
    version = {"stock_rules": [{"detail_id": "s", "enabled": True}],
               "action_rules": [{"detail_id": "a", "enabled": True, "action_type": "buy"}]}
    operation = {"stock_code": "001914.SZ", "side": "buy", "stock_rule_id": "s",
                 "action_rule_id": "a", "price": 10, "quantity": 100, "amount": 1000, "fee": 0}
    with pytest.raises(ValidationError, match="未生效或已更码"):
        service._prepare_operations([operation], trade_date=day, version=version)


def test_identity_changes_invalidate_indicator_input_semantics():
    from backend.indicators.compute import build_params, param_hash

    params = build_params()
    assert params["stock_identity_version"] == IDENTITY_VERSION
    previous = {k: v for k, v in params.items() if k != "stock_identity_version"}
    assert param_hash(params) != param_hash(previous)


def test_backtest_signature_keeps_original_identity_on_publish_and_restore():
    from backend.services.asset_visibility import (
        ASSET_SCORE_PROFILE,
        backtest_signature,
        make_asset_ref,
        restore_backtest_private_dependencies,
    )

    versions = {"stock_identity_version": IDENTITY_VERSION, "st_data_version": "facts-v1",
                "capital_data_version": 42, "score_profile_version": 1,
                "profile_version": None, "trade_profile_version": None}
    params = {"date_start": "2019-12-11", "date_end": "2019-12-17",
              "score_profile_id": "score", "_data_versions": versions}
    original = backtest_signature("strategy", params, versions)
    profile_versions = {k: v for k, v in versions.items() if k.endswith("profile_version")}
    assert backtest_signature("strategy", params, profile_versions) == original
    ref = make_asset_ref(ASSET_SCORE_PROFILE, "tenant", "owner", "score")
    published = {**params, "score_profile_id": ref}
    restored = restore_backtest_private_dependencies({
        "kind": "strategy", "params": published, "score_profile_id": ref,
        "score_profile_version": 1, "profile_version": None, "trade_profile_version": None})
    assert restored["signature"] == original
    assert backtest_signature("strategy", params, {**versions, "stock_identity_version": "new"}) != original


@pytest.mark.parametrize("change", STOCK_CODE_CHANGES)
def test_daily_quotes_use_actual_code_periods_without_rebasing_source_factors(monkeypatch, change):
    import baostock as bs

    from backend.datasource.baostock_source import BaostockSource, full_to_bs

    source = BaostockSource()
    before = change.effective_date - timedelta(days=1)
    calls = []

    def query(code, fields, **params):
        calls.append((code, params["adjustflag"], params["start_date"], params["end_date"]))
        old = code == full_to_bs(change.previous_code)
        price, factor = (10., 2.) if old else (11., 20.)
        day = before if old else change.effective_date
        value = price * factor if params["adjustflag"] == "1" else price
        return pd.DataFrame([{"date": day.isoformat(), "open": str(value), "high": str(value),
                              "low": str(value), "close": str(value), "preclose": "10",
                              "volume": "100", "amount": str(price * 100), "turn": "1",
                              "tradestatus": "1", "isST": "0"}])

    monkeypatch.setattr(bs, "query_history_k_data_plus", query)
    monkeypatch.setattr(source, "_query_frame", lambda call: call())
    result = source.get_daily_bar(change.current_code, before, change.effective_date)
    assert result.code.tolist() == [change.current_code] * 2
    assert result.close.tolist() == [10, 11]
    assert result.adj_factor.tolist() == [2, 20]
    assert result.reference_pre_close.tolist() == [10, 10]
    assert [(c, a) for c, a, _, _ in calls] == [
        (full_to_bs(change.previous_code), "3"), (full_to_bs(change.current_code), "3"),
        (full_to_bs(change.previous_code), "1"), (full_to_bs(change.current_code), "1")]


def test_clean_factor_bridges_source_basis_reset_without_modifying_raw_factor(market):
    from backend.services.ingest import IngestionService
    from backend.storage.repository import MarketRepository

    for day, price, factor in [(date(2018, 12, 20), 10, 2), (date(2018, 12, 26), 11, 20)]:
        market.execute("INSERT INTO daily_bar(code,trade_date,close,adj_factor,reference_pre_close,"
                       "reference_close,reference_source) VALUES ('001872.SZ',?,?,?,?,?,'baostock')",
                       [day, price, factor, 10, price])
    service = object.__new__(IngestionService)
    service.c = market
    service.repo = MarketRepository(market)
    service._recompute_clean_one("001872.SZ", .1)
    result = market.query_df("SELECT adj_factor,adj_factor_clean,pre_close FROM daily_bar ORDER BY trade_date")
    assert result.adj_factor.tolist() == [2, 20]
    assert result.adj_factor_clean.tolist() == [2, 2]
    assert result.pre_close.tolist() == [10, 10]
