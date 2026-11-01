"""价格消费契约：真实单股/批量入口、非法输入拒绝、固定基准与跨语言 MA。"""

import json
from contextlib import nullcontext
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from backend.backtest.engine import BacktestEngine
from backend.backtest.forward import compute_forward_returns
from backend.common.exceptions import DataQualityError
from backend.indicators.engine import IndicatorEngine
from backend.indicators.operators import MA
from backend.price_adjustment import adjust_price_columns, hfq_price_sql
from backend.services.training_service import TrainingService
from backend.storage.repository import MarketRepository


@pytest.fixture
def prices(market):
    market.execute("""INSERT INTO stock_basic(code,list_date) VALUES ('A.SZ','2010-01-01')""")
    market.execute("""INSERT INTO daily_bar
        (code,trade_date,open,high,low,close,pre_close,adj_factor,adj_factor_clean)
        VALUES ('A.SZ','2020-01-01',10,11,9,10,9,2,NULL),
               ('A.SZ','2020-01-02',6,7,5,6,5,9,4)""")
    return market


def test_single_bulk_hfq_and_fixed_anchor_share_price_contract(prices):
    repo = MarketRepository(prices)
    engine = IndicatorEngine.__new__(IndicatorEngine)
    engine.c = prices
    single = repo.get_bars('A.SZ', date(2020, 1, 2))
    bulk = engine._bulk_qfq_bars(['A.SZ'], date(2020, 1, 2), 2)
    for col in ('open', 'high', 'low', 'close', 'pre_close'):
        np.testing.assert_allclose(single[col], bulk[col])
    assert single.close.tolist() == [5, 6]
    hfq = repo.get_bars('A.SZ', date(2020, 1, 2), adjust='hfq')
    assert hfq.close.tolist() == [20, 24]
    fixed = adjust_price_columns(
        repo.get_bars('A.SZ', date(2020, 1, 2), adjust=''), 'qfq', base_factor=2
    )
    assert fixed.close.tolist() == [10, 12]
    # 未参与换算的来源事实不变，收尾因子也不因消费而写回。
    assert prices.query_df('SELECT adj_factor FROM daily_bar ORDER BY trade_date').adj_factor.tolist() == [2, 9]


@pytest.mark.parametrize('bad', [None, 0, -1, float('inf'), float('-inf'), float('nan')])
def test_missing_or_invalid_effective_factor_never_defaults_to_one(prices, monkeypatch, bad):
    prices.execute("UPDATE daily_bar SET adj_factor=?,adj_factor_clean=NULL WHERE trade_date='2020-01-02'", [bad])
    repo = MarketRepository(prices)
    engine = IndicatorEngine.__new__(IndicatorEngine)
    engine.c = prices
    for run in (
        lambda: repo.get_bars('A.SZ', date(2020, 1, 2)),
        lambda: engine._bulk_qfq_bars(['A.SZ'], date(2020, 1, 2), 2),
        lambda: compute_forward_returns(date(2020, 1, 1), date(2020, 1, 2), [1], client=prices),
    ):
        with pytest.raises(DataQualityError, match='复权因子未就绪'):
            run()
    # 回测真实价格预载也拒绝；ST 门禁在本用例由单独链路测试负责。
    monkeypatch.setattr('backend.services.stock_st_status.StockSTStatusService.assert_published', lambda _: None)
    backtest = BacktestEngine.__new__(BacktestEngine)
    backtest.c = prices
    with pytest.raises(DataQualityError):
        backtest._load_prices(date(2020, 1, 1), date(2020, 1, 2), 2)
    # 原始价展示不依赖因子；显式缺数模式不会偷偷改用上一有效末日基准。
    assert repo.get_bars('A.SZ', date(2020, 1, 2), adjust='').close.tolist() == [10, 6]
    shown = repo.get_bars('A.SZ', date(2020, 1, 2), strict_factors=False)
    assert shown.close.isna().all()


def test_invalid_clean_does_not_fallback_to_valid_source_and_sql_nan_matches_bulk(prices):
    engine = IndicatorEngine.__new__(IndicatorEngine)
    engine.c = prices
    for bad in (0, -1, float('inf'), float('nan')):
        prices.execute("UPDATE daily_bar SET adj_factor=4,adj_factor_clean=? WHERE trade_date='2020-01-02'", [bad])
        with pytest.raises(DataQualityError):
            MarketRepository(prices).get_bars('A.SZ', date(2020, 1, 2))
        with pytest.raises(DataQualityError):
            engine._bulk_qfq_bars(['A.SZ'], date(2020, 1, 2), 2)


def test_display_sql_and_vector_agree_on_invalid_factors(prices):
    prices.execute("UPDATE daily_bar SET adj_factor=0,adj_factor_clean=NULL WHERE trade_date='2020-01-02'")
    expression = hfq_price_sql('close', 'COALESCE(adj_factor_clean,adj_factor)')
    sql = prices.query_df(f'SELECT {expression} h FROM daily_bar ORDER BY trade_date').h
    frame = prices.query_df('SELECT * FROM daily_bar ORDER BY trade_date')
    actual = adjust_price_columns(frame, 'hfq', strict=False).close
    np.testing.assert_allclose(sql, actual, equal_nan=True)


def test_grouped_anchors_preserve_missing_last_row_and_non_default_index():
    frame = pd.DataFrame({'code': ['A', 'A', 'B', 'B'], 'close': [10, 6, 4, 5],
                          'adj_factor': [2, np.nan, 3, 3]}, index=[4, 8, 12, 16])
    result = adjust_price_columns(frame, 'qfq', strict=False)
    assert result.loc[[4, 8], 'close'].isna().all()
    assert result.loc[[12, 16], 'close'].tolist() == [4, 5]


def test_prefix_does_not_normalize_with_future_factor(prices):
    one = MarketRepository(prices).get_bars('A.SZ', date(2020, 1, 1))
    assert one.close.tolist() == [10]
    for base in (0, -1, float('nan'), float('inf')):
        with pytest.raises(DataQualityError):
            adjust_price_columns(pd.DataFrame({'close': [10], 'adj_factor': [2]}), 'qfq', base_factor=base)


def test_bars_api_preserves_calculation_precision_and_exposes_missing_factor(prices, monkeypatch):
    from backend.api import stocks
    monkeypatch.setattr(stocks, 'get_client', lambda: prices)
    prices.execute("UPDATE daily_bar SET close=10.123456 WHERE trade_date='2020-01-01'")
    result = stocks.stock_bars('A.SZ', end=date(2020, 1, 2))
    assert result.data['bars'][0]['close'] == 5.061728
    prices.execute("UPDATE daily_bar SET adj_factor=NULL,adj_factor_clean=NULL WHERE trade_date='2020-01-02'")
    with pytest.raises(DataQualityError, match='复权因子未就绪'):
        stocks.stock_bars('A.SZ', end=date(2020, 1, 2))


def test_bulk_price_loading_keeps_one_query_at_representative_scale(market):
    market.execute("""INSERT INTO daily_bar
        (code,trade_date,open,high,low,close,adj_factor,adj_factor_clean)
        SELECT 'P'||i::VARCHAR, DATE '2020-01-01'+d::INTEGER,
               10.+d*.001,11.+d*.001,9.+d*.001,10.+d*.001,
               9.,2.+floor(d/200.)*.1 FROM range(256) t(i) CROSS JOIN range(600) u(d)""")
    calls = []
    def query(sql, params):
        calls.append(sql)
        return market.query_df(sql, params)
    engine = IndicatorEngine.__new__(IndicatorEngine)
    engine.c = SimpleNamespace(query_df=query)
    frame = engine._bulk_qfq_bars(None, date(2022, 1, 1), 520)
    assert len(frame) == 256 * 520
    assert len(calls) == 1
    assert frame.groupby('code').tail(1).close.eq(10.599).all()


def test_training_missing_factor_fails_before_pending_order_write(prices):
    service = TrainingService.__new__(TrainingService)
    service.c = prices
    writes = []
    service.pg = SimpleNamespace(execute=lambda *a: writes.append(a))
    service.tenant_id = 'test'
    service.owner_user_id = 'test'
    session = {'id': 'not-persisted', 'fee_enabled': False}
    rnd = {'seq': 0, 'code': 'A.SZ', 'base_factor': 2,
           'pending': {'side': 'sell', 'hands': 1}}
    prices.execute("UPDATE daily_bar SET adj_factor=NULL,adj_factor_clean=NULL WHERE trade_date='2020-01-02'")
    with pytest.raises(DataQualityError):
        service._settle_pending(session, rnd, date(2020, 1, 2))
    assert not writes


def test_price_consumption_signature_preserves_original_asset_version():
    """纯签名计算，无存储访问；新语义区分旧运行，旧资产原签名仍可重建。"""
    from backend.price_adjustment import PRICE_CONSUMPTION_VERSION
    from backend.services.asset_visibility import backtest_signature
    legacy = {'price_consumption_version': 'previous-consumption'}
    stored = {'_data_versions': legacy}
    original = backtest_signature('strategy', {}, legacy)
    assert backtest_signature('strategy', stored, {}) == original
    assert backtest_signature('strategy', {}, {
        'price_consumption_version': PRICE_CONSUMPTION_VERSION,
    }) != original


def test_ladder_price_batch_keeps_suspension_without_factor_and_rejects_priced_gap():
    """只注入读取结果，不初始化 DuckDB；校验真实批量消费者的停牌及缺数边界。"""
    from backend.services.limit_ladder_calculator import LimitLadderCalculator
    rows = pd.DataFrame({
        'code': ['A', 'B'], 'trade_date': pd.to_datetime(['2020-01-01'] * 2),
        'close': [10., np.nan], 'adj_factor': [2., np.nan],
        'confirmed_suspension': [False, True],
    })
    calculator = LimitLadderCalculator.__new__(LimitLadderCalculator)
    calculator._batch_query_count = 0
    calculator.c = SimpleNamespace(
        temp_view=lambda _, name: nullcontext(name),
        query_df=lambda *_: rows.copy(),
    )
    facts = calculator._load_daily_facts(['A', 'B'], [date(2020, 1, 1)])
    assert facts[('A', date(2020, 1, 1))]['close_hfq'] == 20
    assert facts[('B', date(2020, 1, 1))]['confirmed_suspension']
    assert pd.isna(facts[('B', date(2020, 1, 1))]['close_hfq'])
    rows.loc[0, 'adj_factor'] = np.nan
    with pytest.raises(DataQualityError):
        calculator._load_daily_facts(['A', 'B'], [date(2020, 1, 1)])


def test_ma_matches_shared_cross_language_cases():
    cases = json.loads((Path(__file__).parent / 'fixtures/price_series_contract.json').read_text())
    for case in cases:
        actual = MA(pd.Series(case['values'], dtype=float), case['period'])
        np.testing.assert_allclose(actual, pd.Series(case['expected'], dtype=float), atol=1e-12)
