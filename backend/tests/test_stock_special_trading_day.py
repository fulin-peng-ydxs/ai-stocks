"""公告事实导入、精确日期消费与天梯发布门禁回归。"""

from datetime import date

import pandas as pd
import pytest

from backend.market_rules import CloseLimitStatus
from backend.services.limit_ladder_calculator import LimitLadderCalculator
from backend.services.limit_ladder_snapshot import LimitLadderSnapshotService
from backend.services.stock_special_trading_day import (
    StockSpecialTradingDayService,
    normalize_special_day_params,
)
from backend.tests.test_limit_ladder_t4 import _bar, _seed_basic, _seed_calendar, _upsert_bars

DAY = date(2026, 9, 30)
CODE = "301139.SZ"


def _params(**overrides):
    return {
        "records": [
            {
                "code": CODE,
                "trade_date": str(DAY),
                "event_type": "delisting_first_day",
                "announcement_date": "2026-09-21",
                "source_ref": "https://disc.static.szse.cn/example.pdf",
                "note": "测试公告事实",
                **overrides,
            }
        ]
    }


def _seed(market):
    days = _seed_calendar(market, DAY)
    _seed_basic(market, [(CODE, "测试公司", "创业板", date(2020, 1, 1), "通信", 0.2)])
    bars = [_bar(CODE, d, close=12) for d in days]
    bars[-1].update(open=0.8, high=1.27, low=0.75, close=0.91, pre_close=None)
    _upsert_bars(market, pd.DataFrame(bars))
    return days


def test_special_day_passes_gate_only_on_exact_date_and_does_not_count_limit_up(market):
    days = _seed(market)
    gate = LimitLadderSnapshotService(market)
    before = gate.check_coverage(DAY)
    assert not before.ready and before.invalid_bar_count == 1
    assert before.diagnostics[0]["code"] == CODE
    service = StockSpecialTradingDayService(market)
    assert service.import_records(_params(), task_id="test")["changed_count"] == 1
    assert service.import_records(_params(), task_id="test")["changed_count"] == 0
    assert gate.check_coverage(DAY).ready
    calculator = LimitLadderCalculator(market)
    facts = calculator._load_daily_facts([CODE], days)
    basic = {"code": CODE, "board": "创业板", "list_date": date(2020, 1, 1), "price_limit_pct": 0.2}
    result, _ = calculator.evaluate_fact(
        code=CODE, basic=basic, fact=facts[CODE, DAY], calendar=days
    )
    assert result.status is CloseLimitStatus.NO_PRICE_LIMIT
    previous, _ = calculator.evaluate_fact(
        code=CODE, basic=basic, fact=facts[CODE, days[-2]], calendar=days
    )
    assert previous.status is CloseLimitStatus.LIMIT_UP
    outcome = gate.materialize(DAY)
    assert outcome.status == "valid"
    assert market.query_df(
        "SELECT * FROM limit_ladder_snapshot_stock WHERE snapshot_id=?", [outcome.snapshot_id]
    ).empty
    assert (
        service.import_records(_params(active=False, note="撤销错误公告"), task_id="revoke")[
            "invalidated_count"
        ]
        == 1
    )
    assert not gate.check_coverage(DAY).ready
    state = market.query_df(
        "SELECT status,current_snapshot_id FROM limit_ladder_snapshot_state"
    ).iloc[0]
    assert state["status"] == "invalid" and state["current_snapshot_id"] == outcome.snapshot_id


def test_no_limit_does_not_bypass_bad_ohlc(market):
    _seed(market)
    StockSpecialTradingDayService(market).import_records(_params(), task_id="test")
    market.execute("UPDATE daily_bar SET high=0 WHERE code=? AND trade_date=?", [CODE, DAY])
    coverage = LimitLadderSnapshotService(market).check_coverage(DAY)
    assert not coverage.ready and coverage.diagnostics[0]["reason"] == "INVALID_OHLC"


@pytest.mark.parametrize(
    "overrides",
    [
        {"announcement_date": "2026-10-01"},
        {"event_type": "guess_from_price"},
        {"source_ref": "https://example.com/notice"},
        {"active": "false"},
        {"note": ""},
    ],
)
def test_unverified_or_future_facts_rejected(overrides):
    with pytest.raises(ValueError):
        normalize_special_day_params(_params(**overrides))


def test_bad_pool_record_rolls_back_entire_batch(market):
    _seed(market)
    params = _params()
    params["records"] += _params(code="600999.SH")["records"]
    with pytest.raises(ValueError):
        StockSpecialTradingDayService(market).import_records(params, task_id="test")
    assert market.query_df("SELECT * FROM stock_special_trading_day").empty


def test_import_retry_finishes_pending_invalidation_even_when_facts_unchanged(market, monkeypatch):
    _seed(market)
    original = LimitLadderSnapshotService.process_pending_invalidations
    calls = 0

    def fail_after_commit(service):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('模拟事实提交后通知处理中断')
        return original(service)

    service = StockSpecialTradingDayService(market)
    monkeypatch.setattr(LimitLadderSnapshotService, 'process_pending_invalidations', fail_after_commit)
    with pytest.raises(RuntimeError, match='通知处理中断'):
        service.import_records(_params(), task_id='first')
    assert len(market.query_df('SELECT * FROM stock_special_trading_day')) == 1
    monkeypatch.setattr(LimitLadderSnapshotService, 'process_pending_invalidations', original)
    assert service.import_records(_params(), task_id='retry')['changed_count'] == 0
    assert market.query_df("SELECT * FROM limit_ladder_invalidation_outbox WHERE status='pending'").empty


def test_special_day_breaks_next_days_consecutive_streak(market):
    from backend.storage.repository import MarketRepository

    _seed(market)
    StockSpecialTradingDayService(market).import_records(_params(), task_id='test')
    next_day = date(2026, 10, 8)
    MarketRepository(market).upsert_trade_calendar(
        pd.DataFrame({'trade_date': [next_day], 'is_open': [True]})
    )
    next_bar = _bar(CODE, next_day, close=1.09)
    next_bar['pre_close'] = .91
    _upsert_bars(market, pd.DataFrame([next_bar]))
    outcome = LimitLadderSnapshotService(market).materialize(next_day)
    assert outcome.status == 'valid'
    stock = market.query_df(
        'SELECT consecutive_days FROM limit_ladder_snapshot_stock WHERE snapshot_id=? AND code=?',
        [outcome.snapshot_id, CODE],
    ).iloc[0]
    assert stock['consecutive_days'] == 1


def test_special_day_task_uses_global_write_mutex(market, monkeypatch):
    from backend.services.async_task import WRITE_TASK_TYPES, AsyncTaskService, ConcurrentTaskError

    _seed(market)
    assert 'stock_special_trading_day' in WRITE_TASK_TYPES
    service = AsyncTaskService(market)
    monkeypatch.setattr(service, '_running_write', lambda: ('running-task', 'stock_ingest'))
    with pytest.raises(ConcurrentTaskError):
        service.create('stock_special_trading_day', _params())
    with pytest.raises(ValueError):
        service.create('stock_special_trading_day', _params(announcement_date='2026-10-01'))
