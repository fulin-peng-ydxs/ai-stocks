"""性能改动的成功断点、失败续跑、来源证据及分钟值等价回归。"""

from contextlib import contextmanager

import pandas as pd
import pytest
import requests

from backend.datasource import request_policy as rp
from backend.datasource import request_runtime as rt
from backend.datasource.observability import RequestTracker, observe_work, record_source
from backend.services.async_task import TaskCancelled
from backend.services.intraday_source import IntradaySourceService
from backend.services.share_capital import ShareCapitalService
from backend.services.share_capital_history import ShareCapitalHistoryService
from backend.tests.test_daily_collection_performance import DAY, Context
from backend.tests.test_daily_collection_performance import service as service  # noqa: PLC0414
from backend.tests.test_valuation_batch import seed_latest


class Checkpoints(Context):
    def __init__(self):
        super().__init__()
        self.phases = []

    def set_phase(self, phase, **values):
        self.phases.append((phase, values.copy()))
        super().set_phase(phase, **values)


@pytest.mark.parametrize("concurrency", [1, 4])
def test_complete_snapshot_uses_bounded_blocks_and_few_checkpoints(service, monkeypatch, concurrency):
    codes, calls, _ = seed_latest(service, monkeypatch, count=130, missing={"600129.SH"})
    sizes = []
    original = ShareCapitalService.merge
    def merge(obj, frame, *args, **kwargs):
        if kwargs.get("reported"):
            sizes.append(len(frame))
        return original(obj, frame, *args, **kwargs)
    monkeypatch.setattr(ShareCapitalService, "merge", merge)
    ctx = Checkpoints()
    result = service.ingest_valuation_latest(DAY, codes=codes, concurrency=concurrency, ctx=ctx)
    assert result["ok"] == result["total_mv_rows"] == 130 and result["fail"] == 0
    assert sizes[:3] == [64, 64, 1]
    assert calls["single"] == ["600129.SH"]
    assert len([p for p, _ in ctx.phases if p == "valuation_latest"]) < 10
    assert set(ctx.checkpoint["valuation_latest_done_codes"]) == set(codes)
    final_phase = [v for p, v in ctx.phases if p == "valuation_latest"][-1]
    assert final_phase["phase_done"] == final_phase["phase_total"] == 130
    facts = service.c.query_df("SELECT * FROM daily_metrics")
    assert len(facts) == 130
    assert facts.total_mv.eq(1000).all() and facts.reported_total_mv.eq(1000).all()
    assert facts.reported_total_close.eq(10).all()


def test_cancelled_block_persists_only_finished_block_and_resumes(service, monkeypatch):
    codes, calls, _ = seed_latest(service, monkeypatch, count=130)
    ctx = Context()
    original = ShareCapitalHistoryService.rebuild_many
    def rebuild(obj, selected, *args, **kwargs):
        result = original(obj, selected, *args, **kwargs)
        ctx.cancel = True
        return result
    monkeypatch.setattr(ShareCapitalHistoryService, "rebuild_many", rebuild)
    with pytest.raises(TaskCancelled):
        service.ingest_valuation_latest(DAY, codes=codes, concurrency=4, ctx=ctx)
    assert len(ctx.checkpoint["valuation_latest_done_codes"]) == 64
    assert service.c.query_df("SELECT count(*) FROM daily_metrics").iloc[0, 0] == 64
    first_done = set(ctx.checkpoint["valuation_latest_done_codes"])
    monkeypatch.setattr(ShareCapitalHistoryService, "rebuild_many", original)
    ctx.cancel = False
    result = service.ingest_valuation_latest(DAY, codes=codes, concurrency=4, ctx=ctx)
    assert result["ok"] == 66 and result["fail"] == 0
    assert not first_done & set(calls["batch"][-1][0])
    assert set(ctx.checkpoint["valuation_latest_done_codes"]) == set(codes)
    assert service.c.query_df("SELECT count(*) FROM daily_metrics").iloc[0, 0] == 130


def test_committed_material_without_derived_finish_is_not_skipped_on_resume(service, monkeypatch):
    codes, _, _ = seed_latest(service, monkeypatch, count=65)
    service.c.execute("INSERT INTO stock_share_capital_history(code,trade_date,total_share) "
                      "SELECT code,trade_date,100 FROM daily_bar")
    ctx = Context()
    original = ShareCapitalHistoryService.rebuild_many
    def fail(*args, **kwargs):
        raise RuntimeError("history maintenance failed")
    monkeypatch.setattr(ShareCapitalHistoryService, "rebuild_many", fail)
    with pytest.raises(RuntimeError, match="history maintenance"):
        service.ingest_valuation_latest(DAY, codes=codes, concurrency=4, ctx=ctx)
    assert ctx.checkpoint["valuation_latest_done_codes"] == []
    assert service.c.query_df("SELECT count(*) FROM daily_metrics").iloc[0, 0] == 64
    rebuilt = []
    def rebuild(obj, selected, *args, **kwargs):
        rebuilt.extend(selected)
        return original(obj, selected, *args, **kwargs)
    monkeypatch.setattr(ShareCapitalHistoryService, "rebuild_many", rebuild)
    result = service.ingest_valuation_latest(DAY, codes=codes, concurrency=4, ctx=ctx)
    assert result["ok"] == 65 and set(rebuilt) == set(codes)
    assert service.c.query_df("SELECT * FROM stock_share_capital_history").empty
    assert len(service.c.query_df("SELECT * FROM stock_share_capital_daily")) == 65


def test_serial_network_cancellation_is_not_counted_as_success_or_failure(service, monkeypatch):
    codes, _, _ = seed_latest(service, monkeypatch, count=3)
    def cancel(*args, **kwargs):
        raise TaskCancelled()
    monkeypatch.setattr(service, "_collect_capital_one", cancel)
    ctx = Context()
    with pytest.raises(TaskCancelled):
        service.ingest_valuation_latest(DAY, codes=codes, concurrency=1, ctx=ctx)
    assert ctx.checkpoint["valuation_latest_done_codes"] == []


def test_minute_vector_conversion_preserves_values_order_null_and_diagnostics():
    raw = pd.DataFrame([
        ["2026-10-28 09:32:00", 1, 2, 1, 1.5, 0.25, 37.5],
        ["2026-10-28 09:31:00", 0, 2, 1, 1.25, 0, 0],
        ["2026-10-28 12:00:00", 1, 2, 1, 1.5, 1, 150],
        ["2026-10-28 09:33:00", 1, 2, 1, 1.5, -1, 150],
        ["2026-10-28 09:32:00", 1, 2, 1, 1.75, 0.5, 87.5],
    ], columns=["timestamp", "open", "high", "low", "close", "volume", "amount"])
    raw.attrs["request_years"] = [2026]
    result = IntradaySourceService._frame_to_window(raw, "ths")
    assert result["rows"] == [
        ["2026-10-28 09:31:00", None, 2.0, 1.0, 1.25, 0.0, 0.0],
        ["2026-10-28 09:32:00", 1.0, 2.0, 1.0, 1.75, 0.5, 87.5],
    ]
    assert result["request_years"] == [2026]
    assert result["raw_count"] == 5
    assert result["diagnostics"] == {"invalid_rows": 1, "off_session_rows": 1, "duplicate_rows": 1}
    assert result["day_diagnostics"]["2026-10-28"] == result["diagnostics"]


def test_decode_reuse_is_exact_material_scoped_and_returns_independent_results(monkeypatch):
    import py_mini_racer

    from backend.config.settings import Settings

    calls = []
    class Decoder:
        def call(self, name, *args, **kwargs):
            calls.append((name, args))
            return [{"date": "2026-10-28", "close": 10}]
    monkeypatch.setattr(py_mini_racer, "MiniRacer", Decoder)
    monkeypatch.setattr(rp, "get_effective_settings", Settings)
    @contextmanager
    def slot(*args, **kwargs):
        yield {}
    monkeypatch.setattr(rt, "request_slot", slot)
    def send(adapter, request, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response._content = b'var KLC_K2_sh600000="payload";'
        response._content_consumed = True
        return response
    monkeypatch.setattr(rp, "_HTTP_SEND", send)
    url = "https://finance.sina.com.cn/realstock/company/sh600000/hisdata_klc2/klc_kl.js"
    tracker = RequestTracker()
    with observe_work(tracker), rp.daily_materials("sh600000"):
        requests.get(url)
        first = Decoder().call("d", "payload")
        first[0]["close"] = 99
        assert Decoder().call("d", "payload")[0]["close"] == 10
        Decoder().call("d", "different")
        Decoder().call("other", "payload")
    assert len(calls) == 3
    assert tracker.snapshot()["sina_decode_cache_hits"] == 1
    with rp.daily_materials("sh600000"):
        requests.get(url)
        Decoder().call("d", "payload")
    Decoder().call("d", "payload")
    assert len(calls) == 5


def test_source_counters_are_separate_bounded_and_do_not_change_total():
    tracker = RequestTracker()
    with observe_work(tracker):
        record_source("sina", requests=2, network_seconds=0.12345)
        record_source("baostock", requests=1, session_wait_seconds=1)
        for i in range(100):
            record_source(f"unknown-{i}", requests=1)
    result = tracker.snapshot()
    assert result["requests"] == 0
    assert result["sources"]["sina"] == {"requests": 2, "network_seconds": 0.123}
    assert result["sources"]["baostock"]["session_wait_seconds"] == 1
    assert result["sources"]["other"]["requests"] == 100
    assert len(result["sources"]) == 3


def test_decode_reuse_is_thread_local_and_unknown_nested_values_are_copied(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    import py_mini_racer

    calls = []
    class Decoder:
        def call(self, name, *args, **kwargs):
            calls.append(args)
            return [{"nested": {"close": 10}}]
    monkeypatch.setattr(py_mini_racer, "MiniRacer", Decoder)
    # 只模拟已通过HTTP标的校验的作用域；每个工作单元都必须独立首次解码。
    def one(_):
        with rp.daily_materials("sh600000"):
            rp._REUSE_SCOPE.get()["encoded_daily"] = "same-payload"
            first = Decoder().call("d", "same-payload")
            first[0]["nested"]["close"] = 99
            return Decoder().call("d", "same-payload")[0]["nested"]["close"]
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(one, range(8))) == [10] * 8
    assert len(calls) == 8
