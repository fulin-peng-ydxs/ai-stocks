"""日线取数流水线的真实落表、原子边界和有界预取回归。"""

import threading
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.common.exceptions import DataSourceError, StorageError
from backend.config.settings import Settings
from backend.datasource.akshare_source import AKShareSource
from backend.datasource.observability import RequestTracker
from backend.datasource.share_capital import fetch_daily_valuation
from backend.services import ingest
from backend.services.async_task import TaskCancelled
from backend.services.bounded_parallel import run_bounded_parallel
from backend.services.share_capital import ShareCapitalService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.repository import MarketRepository

DAY = date(2026, 10, 26)


class Context:
    def __init__(self):
        self.checkpoint = {}
        self.cancel = False
        self.request_tracker = RequestTracker()

    def check_cancel(self):
        if self.cancel:
            raise TaskCancelled()

    def log(self, *args):
        pass

    def flush(self):
        pass

    def set_checkpoint(self, **values):
        self.checkpoint.update(values)

    def set_phase(self, phase, **values):
        self.checkpoint.update(phase=phase, **values)

    def progress(self, *args):
        pass


@pytest.fixture
def service(tmp_path):
    # 落盘临时库也验证回滚后重新连接；内存库会掩盖连接恢复边界。
    with DuckDBClient(str(tmp_path / "daily.duckdb")) as c:
        init_db(c)
        c.execute("INSERT INTO trade_calendar VALUES (?,true)", [DAY])
        svc = ingest.IngestionService.__new__(ingest.IngestionService)
        svc.s = Settings()
        svc.c = c
        svc.repo = MarketRepository(c)
        svc.src = SimpleNamespace(name="akshare")
        svc._bao = None
        yield svc


def bars(code):
    return pd.DataFrame(
        [
            {
                "code": code,
                "trade_date": DAY,
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "pre_close": 10.0,
                "volume": 100,
                "amount": 1000.0,
                "adj_factor": 1.0,
                "turnover_rate": 1.0,
                "float_share": 80.0,
                "total_share": 100.0,
            }
        ]
    )


def wire_sources(monkeypatch, svc, *, status_error=None):
    main = threading.get_ident()
    calls = []
    monkeypatch.setattr(svc, "_thread_source", lambda *_: svc.src)
    monkeypatch.setattr(svc, "_fetch_daily_with_fallback", lambda code, *_: (bars(code), "akshare"))

    def status(code, start, end):
        assert threading.get_ident() != main
        calls.append(code)
        if status_error:
            raise status_error
        return SimpleNamespace(name="baostock"), pd.DataFrame(
            [{"code": code, "trade_date": DAY, "is_st": False, "trade_status": 1}]
        )

    monkeypatch.setattr(svc, "_fetch_st_status_rows", status)
    return calls


def run_daily(svc, codes, *, ctx=None, complete=None, concurrency=4):
    results = []
    svc._run_daily_parallel(
        codes,
        {code: DAY for code in codes},
        DAY,
        concurrency=concurrency,
        ctx=ctx,
        label="日线回归",
        on_complete=complete
        or (lambda i, code, value, error, pending: results.append((code, value, error))),
    )
    return results


def test_valuation_range_filter_keeps_all_pages_and_rejects_inverse_range(monkeypatch):
    calls = []

    def fetch(url, *, params, timeout):
        calls.append(dict(params))
        page = params["pageNumber"]
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "result": {
                    "pages": 2,
                    "count": 2,
                    "data": [
                        {
                            "TRADE_DATE": f"2026-10-{27 - page}",
                            "TOTAL_SHARES": 100,
                            "FREE_SHARES_A": 80,
                            "TOTAL_MARKET_CAP": 1000,
                            "NOTLIMITED_MARKETCAP_A": 800,
                        }
                    ],
                }
            },
        )

    monkeypatch.setattr("backend.datasource.share_capital.requests.get", fetch)
    result = fetch_daily_valuation("600000.SH", start=date(2026, 10, 23), end=DAY)
    assert len(result) == 2
    assert [x["pageNumber"] for x in calls] == [1, 2]
    assert all(
        x["filter"] == '(SECURITY_CODE="600000")'
        "(TRADE_DATE>='2026-10-23')(TRADE_DATE<='2026-10-26')"
        for x in calls
    )
    with pytest.raises(ValueError, match="起始日期"):
        fetch_daily_valuation("600000.SH", start=DAY, end=date(2026, 10, 23))
    assert len(calls) == 2


def test_valuation_adapter_passes_window_and_preserves_local_bound(monkeypatch):
    calls = []

    def fetch(code, **kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            [
                {
                    "数据日期": day,
                    "总股本": 100,
                    "流通股本": 80,
                    "总市值": 1000,
                    "流通市值": 800,
                    "CLOSE_PRICE": 10,
                }
                for day in ["2026-10-23", "2026-10-26", "2026-10-27"]
            ]
        )

    monkeypatch.setattr("backend.datasource.share_capital.fetch_daily_valuation", fetch)
    result = AKShareSource().get_valuation("600000.SH", DAY, DAY)
    assert calls[0]["start"] == calls[0]["end"] == DAY
    assert result.trade_date.tolist() == [DAY]
    assert result.valuation_close.tolist() == [10]


def test_daily_batch_writes_only_on_main_thread_and_checkpoints_after_commit(service, monkeypatch):
    codes = [f"600{i:03d}.SH" for i in range(16)]
    calls = wire_sources(monkeypatch, service)
    sizes = []
    original = ShareCapitalService.merge
    main = threading.get_ident()

    def merge(self, frame, source, **kwargs):
        assert threading.get_ident() == main
        sizes.append(len(frame))
        return original(self, frame, source, **kwargs)

    monkeypatch.setattr(ShareCapitalService, "merge", merge)

    def complete(index, code, value, error, pending):
        assert error is None and value == 1
        assert (
            service.c.query_df("SELECT total_mv FROM daily_metrics WHERE code=?", [code]).iloc[0, 0]
            == 1000
        )

    run_daily(service, codes, complete=complete)
    assert sorted(calls) == codes
    assert sum(sizes) == 16 and max(sizes) <= 4 and len(sizes) < 16
    assert (
        service.c.query_df(
            "SELECT count(*) FROM stock_st_status_daily WHERE quality='accurate'"
        ).iloc[0, 0]
        == 16
    )


def test_st_fetch_failure_is_not_retried_on_main_or_marked_complete(service, monkeypatch):
    calls = wire_sources(monkeypatch, service, status_error=DataSourceError("状态源失败"))
    results = run_daily(service, ["600000.SH"])
    assert calls == ["600000.SH"]
    assert isinstance(results[0][2], DataSourceError)
    assert service.c.query_df("SELECT count(*) FROM daily_bar").iloc[0, 0] == 0


def test_existing_accurate_st_is_reused_without_network(service, monkeypatch):
    wire_sources(monkeypatch, service, status_error=AssertionError("已有准确状态不得再取源"))
    service.c.execute(
        "INSERT INTO stock_st_status_daily(code,trade_date,is_st,source,quality,captured_at,updated_at) VALUES (?,?,true,'baostock','accurate',now(),now())",
        ["600000.SH", DAY],
    )
    assert run_daily(service, ["600000.SH"])[0][2] is None
    assert bool(service.c.query_df("SELECT is_st FROM daily_bar").iloc[0, 0])


def test_batch_failure_rolls_back_daily_st_capital_and_does_not_advance(service, monkeypatch):
    wire_sources(monkeypatch, service)
    completed = []
    original = ShareCapitalService.merge

    def fail_after_merge(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError("合并后故障")

    monkeypatch.setattr(ShareCapitalService, "merge", fail_after_merge)
    with pytest.raises(StorageError, match="合并后故障"):
        run_daily(
            service, ["600000.SH", "600001.SH"], complete=lambda *args: completed.append(args)
        )
    assert not completed
    for table in [
        "daily_bar",
        "daily_metrics",
        "stock_share_capital_daily",
        "stock_st_status_daily",
        "data_update_log",
    ]:
        assert service.c.query_df(f"SELECT count(*) FROM {table}").iloc[0, 0] == 0
    # 已落表后失败也能重试；不能被最新行情水位误判为已完成。
    monkeypatch.setattr(ShareCapitalService, "merge", original)
    assert all(error is None for _, _, error in run_daily(service, ["600000.SH", "600001.SH"]))


def test_cancel_before_commit_drains_prefetch_without_writes(service, monkeypatch):
    wire_sources(monkeypatch, service)
    ctx = Context()
    original = service._fetch_daily_with_fallback

    def fetch(*args):
        result = original(*args)
        ctx.cancel = True
        return result

    monkeypatch.setattr(service, "_fetch_daily_with_fallback", fetch)
    with pytest.raises(TaskCancelled):
        run_daily(service, ["600000.SH", "600001.SH"], ctx=ctx)
    assert service.c.query_df("SELECT count(*) FROM daily_bar").iloc[0, 0] == 0
    assert ctx.request_tracker.states == {}


def test_next_batch_fetch_overlaps_commit_and_stays_bounded():
    main = threading.get_ident()
    next_started = threading.Event()
    completed = []
    prepared = []

    def prepare(item):
        assert threading.get_ident() == main
        prepared.append(item)
        assert len(prepared) - len(completed) <= 8
        return item

    def worker(item):
        if item >= 4:
            next_started.set()
        return item

    def commit(entries):
        assert len(entries) <= 4
        if entries[0][1] == 0:
            assert next_started.wait(2), "落库时下一窗口必须已开始取数"
        return entries

    run_bounded_parallel(
        list(range(32)),
        worker,
        concurrency=4,
        ctx=None,
        wait_label="重叠回归",
        on_complete=lambda i, item, *_: completed.append(item),
        prepare=prepare,
        transform_batch=commit,
        batch_size=4,
        prefetch_next_batch=True,
    )
    assert sorted(completed) == list(range(32))


def isolate_update_tail(monkeypatch, svc):
    """规模夹具只隔离未涉及的指数/因子算法和外层质检，保留日线及股本真实落表。"""
    from backend.services.capital_quality import CapitalQualityService
    from backend.services.collection_quality import CollectionQualityBatch
    from backend.services.data_report import DataIntegrityReport

    monkeypatch.setattr(DataIntegrityReport, "gapped_codes", lambda *_: [])
    monkeypatch.setattr(CollectionQualityBatch, "finish", lambda *args, **kwargs: {})
    monkeypatch.setattr(CapitalQualityService, "sync", lambda *args, **kwargs: {})
    monkeypatch.setattr(svc, "ingest_valuation_latest", lambda **kwargs: {})
    monkeypatch.setattr(svc, "ingest_valuation", lambda **kwargs: {})
    monkeypatch.setattr(svc, "review_capital_history", lambda **kwargs: {})
    monkeypatch.setattr(svc, "_refresh_clean_factors", lambda *args, **kwargs: {})


def test_update_service_128_stocks_ten_years_batches_real_daily_st_capital(service, monkeypatch):
    main = threading.get_ident()
    codes = [f"600{i:03d}.SH" for i in range(128)]
    dates = pd.bdate_range(end="2026-10-23", periods=2400).date
    with service.c.temp_view(pd.DataFrame({"code": codes}), "scale_codes") as stocks:
        service.c.execute(
            f"INSERT INTO stock_basic(code,list_date) SELECT code,DATE '2010-01-01' FROM {stocks}"
        )
        with service.c.temp_view(pd.DataFrame({"trade_date": dates}), "scale_dates") as days:
            service.c.execute(
                f"INSERT INTO daily_bar(code,trade_date,close,adj_factor) SELECT code,trade_date,10,1 FROM {stocks} CROSS JOIN {days}"
            )
    wire_sources(monkeypatch, service)
    isolate_update_tail(monkeypatch, service)
    sizes = []
    merge = ShareCapitalService.merge

    def capture(self, frame, source, **kwargs):
        assert threading.get_ident() == main
        sizes.append(len(frame))
        return merge(self, frame, source, **kwargs)

    monkeypatch.setattr(ShareCapitalService, "merge", capture)
    ctx = Context()
    ctx.checkpoint["target_end"] = DAY.isoformat()
    result = service.update(codes=codes, concurrency=8, ctx=ctx)
    assert result["ok"] == result["rows"] == result["target"] == 128
    assert result["fail"] == 0
    assert max(sizes) <= 8 and len(sizes) <= 24
    assert set(ctx.checkpoint["done_codes"]) == set(codes)
    assert service.c.query_df("SELECT count(*) FROM daily_bar").iloc[0, 0] == 128 * 2401
    assert (
        service.c.query_df(
            "SELECT count(*) FROM daily_metrics WHERE total_mv=1000 AND float_mv=800"
        ).iloc[0, 0]
        == 128
    )
    assert (
        service.c.query_df(
            "SELECT count(*) FROM stock_st_status_daily WHERE quality='accurate'"
        ).iloc[0, 0]
        == 128
    )


def test_cancel_after_commit_resume_skips_fetch_but_finishes_dirty_factors(service, monkeypatch):
    codes = ["600000.SH", "600001.SH"]
    service.c.executemany(
        "INSERT INTO stock_basic(code,list_date) VALUES (?,DATE '2010-01-01')",
        [(c,) for c in codes],
    )
    calls = wire_sources(monkeypatch, service)
    isolate_update_tail(monkeypatch, service)
    ctx = Context()
    ctx.checkpoint["target_end"] = DAY.isoformat()
    write = service._write_daily_batch

    def cancel_after_write(*args, **kwargs):
        write(*args, **kwargs)
        ctx.cancel = True

    monkeypatch.setattr(service, "_write_daily_batch", cancel_after_write)
    with pytest.raises(TaskCancelled):
        service.update(codes=codes, concurrency=2, ctx=ctx)
    assert not ctx.checkpoint["done_codes"]
    assert service.c.query_df("SELECT count(*) FROM daily_bar").iloc[0, 0] == 2
    monkeypatch.setattr(service, "_write_daily_batch", write)
    refreshed = []
    monkeypatch.setattr(
        service, "_refresh_clean_factors", lambda codes, **kwargs: refreshed.extend(codes)
    )
    calls.clear()
    ctx.cancel = False
    result = service.update(codes=codes, concurrency=2, ctx=ctx)
    assert result["fail"] == result["rows"] == 0
    assert calls == []
    assert sorted(refreshed) == codes
    assert sorted(ctx.checkpoint["done_codes"]) == codes


@pytest.mark.parametrize("entry", ["backfill", "range"])
def test_history_and_range_share_batch_entry_and_keep_date_scope(service, monkeypatch, entry):
    codes = ["600000.SH", "600001.SH"]
    service.c.executemany(
        "INSERT INTO stock_basic(code,list_date,price_limit_pct) VALUES (?,DATE '2010-01-01',0.1)",
        [(code,) for code in codes],
    )
    calls = wire_sources(monkeypatch, service)
    isolate_update_tail(monkeypatch, service)
    monkeypatch.setattr(
        service,
        "_refresh_clean_factors",
        lambda *args, **kwargs: {"target": 2, "ok": 2, "fail": 0, "rows": 2},
    )
    ctx = Context()
    ctx.checkpoint.update(
        prep_done=True, history_start=DAY.isoformat(), history_end=DAY.isoformat()
    )
    result = (
        service.backfill(codes=codes, concurrency=2, ctx=ctx)
        if entry == "backfill"
        else service.ingest_date(DAY, DAY, codes=codes, concurrency=2, ctx=ctx)
    )
    assert result["ok"] == result["rows"] == 2 and result["fail"] == 0
    assert sorted(calls) == codes
    assert set(
        service.c.query_df("SELECT DISTINCT trade_date FROM daily_bar").trade_date.dt.date
    ) == {DAY}


def test_incomplete_prefetched_st_fails_only_affected_stock(service, monkeypatch):
    wire_sources(monkeypatch, service)

    def status(code, *args):
        return SimpleNamespace(name="baostock"), pd.DataFrame(
            [
                {
                    "code": code,
                    "trade_date": date(2026, 10, 23) if code == "600000.SH" else DAY,
                    "is_st": False,
                    "trade_status": 1,
                }
            ]
        )

    monkeypatch.setattr(service, "_fetch_st_status_rows", status)
    results = {
        code: (rows, error) for code, rows, error in run_daily(service, ["600000.SH", "600001.SH"])
    }
    assert isinstance(results["600000.SH"][1], DataSourceError)
    assert results["600001.SH"] == (1, None)
    assert service.c.query_df("SELECT code FROM daily_bar").code.tolist() == ["600001.SH"]


def test_mixed_primary_fallback_batch_keeps_capital_and_revokes_only_traded_suspensions(
    service, monkeypatch
):
    codes = ["600000.SH", "600001.SH"]
    wire_sources(monkeypatch, service)
    service.c.execute(
        "INSERT INTO daily_bar(code,trade_date,close) VALUES (?,?,9)", [codes[1], DAY]
    )
    ShareCapitalService(service.c).merge(bars(codes[1]), "eastmoney_daily")
    service.c.executemany(
        "INSERT INTO stock_suspension(code,trade_date,source) VALUES (?,?,'baostock')",
        [(code, DAY) for code in codes],
    )

    def fetch(code, *args):
        frame = bars(code)
        if code == codes[1]:
            frame = frame.drop(columns=["total_share", "float_share"])
        return frame, "baostock" if code == codes[1] else "akshare"

    monkeypatch.setattr(service, "_fetch_daily_with_fallback", fetch)
    assert all(error is None for _, _, error in run_daily(service, codes))
    assert service.c.query_df("SELECT count(*) FROM stock_suspension").iloc[0, 0] == 0
    assert service.c.query_df("SELECT code,source FROM data_source_provenance").to_dict(
        "records"
    ) == [{"code": codes[1], "source": "baostock"}]
    values = service.c.query_df(
        "SELECT total_mv,float_mv FROM daily_metrics WHERE code=?", [codes[1]]
    ).iloc[0]
    assert values.tolist() == [1000, 800]
    detail = service.c.query_df(
        "SELECT detail FROM data_update_log WHERE table_name='stock_suspension'"
    )
    assert len(detail) == 2 and detail.detail.str.contains("revoke_by_traded_bar").all()
