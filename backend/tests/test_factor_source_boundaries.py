"""不同来源因子接缝：真实入库、官方参考价、重算与失败保护。"""

from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.common.exceptions import DataSourceError, StorageError
from backend.services.ingest import IngestionService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.repository import MarketRepository


@pytest.fixture
def ingest(market):
    market.execute(
        "INSERT INTO stock_basic(code,list_date,price_limit_pct) VALUES ('600552.SH','2000-01-01',0.1)"
    )
    svc = IngestionService.__new__(IngestionService)
    svc.c, svc.repo = market, MarketRepository(market)
    svc.s = SimpleNamespace(datasource=SimpleNamespace(primary="akshare"))
    svc.src = SimpleNamespace(name="akshare")
    return svc


def bar(day, close, pre_close, factor):
    return {
        "code": "600552.SH",
        "trade_date": day,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "pre_close": pre_close,
        "adj_factor": factor,
        "volume": 100,
        "amount": 100 * close,
        "turnover_rate": 1.0,
    }


def write(svc, frame):
    svc._fetch_daily_with_fallback = lambda *a, **k: (frame.copy(), "akshare")
    lo, hi = min(frame.trade_date), max(frame.trade_date)
    return svc.ingest_one_daily("600552.SH", lo, hi, is_st=False)


def backup(svc, rows):
    calls = []

    def fetch(code, start, end):
        calls.append((code, start, end))
        return pd.DataFrame(rows)

    svc._bao_source = lambda: SimpleNamespace(name="baostock", get_daily_bar=fetch)
    return calls


@pytest.mark.parametrize("ratio", [1.185629, 1.3, 1.54, 0.8])
def test_incremental_source_switch_survives_full_rebuild_and_next_append(ingest, ratio):
    svc = ingest
    svc.c.execute(
        "INSERT INTO daily_bar(code,trade_date,close,pre_close,adj_factor,adj_factor_clean) VALUES ('600552.SH','2017-01-02',13.54,13.48,6.524843,6.524842)"
    )
    day = date(2017, 1, 3)
    calls = backup(svc, [bar(day, 13.42, 13.54, 6.524843)])
    frame = pd.DataFrame([bar(day, 13.42, 13.54, 6.524843 * ratio)])
    assert write(svc, frame) == 1
    assert len(calls) == 1
    svc._recompute_clean_one("600552.SH", 0.1, full=False)
    first = svc.c.query_df("SELECT * FROM daily_bar ORDER BY trade_date")
    assert first.iloc[-1].pre_close == 13.54
    assert first.iloc[-1].adj_factor_clean == pytest.approx(first.iloc[0].adj_factor_clean)
    assert first.iloc[-1].adj_factor == frame.iloc[0].adj_factor
    svc._recompute_clean_one("600552.SH", 0.1)
    full = svc.c.query_df("SELECT pre_close,adj_factor_clean FROM daily_bar ORDER BY trade_date")
    svc._recompute_clean_one("600552.SH", 0.1)
    pd.testing.assert_frame_equal(
        full, svc.c.query_df("SELECT pre_close,adj_factor_clean FROM daily_bar ORDER BY trade_date")
    )
    assert full.iloc[-1].adj_factor_clean == pytest.approx(full.iloc[0].adj_factor_clean)
    assert (
        write(
            svc, pd.DataFrame([bar(day + timedelta(days=1), 13.5, 13.42, frame.iloc[0].adj_factor)])
        )
        == 1
    )
    svc._recompute_clean_one("600552.SH", 0.1, full=False)
    assert len(calls) == 1  # 同来源后续增量不重复联网校验。
    assert (
        svc.c.query_df("SELECT pre_close FROM daily_bar ORDER BY trade_date DESC LIMIT 1").iloc[
            0, 0
        ]
        == 13.42
    )


def test_source_switch_and_real_split_uses_official_reference(ingest):
    svc = ingest
    svc.c.execute(
        "INSERT INTO daily_bar(code,trade_date,close,adj_factor,adj_factor_clean) VALUES ('600552.SH','2017-01-02',30,1,1)"
    )
    day = date(2017, 1, 3)
    backup(svc, [bar(day, 15.1, 15, 2)])
    write(svc, pd.DataFrame([bar(day, 15.1, 15, 4)]))
    svc._recompute_clean_one("600552.SH", 0.1, full=False)
    row = svc.c.query_df("SELECT * FROM daily_bar ORDER BY trade_date DESC LIMIT 1").iloc[0]
    assert row.pre_close == 15
    assert row.adj_factor_clean == 2
    assert row.adj_factor == 4  # 真实拆股保留，来源原始因子不覆盖。


@pytest.mark.parametrize("failure", ["missing", "close_conflict", "empty", "timeout"])
def test_boundary_verification_failure_does_not_write(ingest, failure):
    svc = ingest
    svc.c.execute(
        "INSERT INTO daily_bar(code,trade_date,close,adj_factor,adj_factor_clean) VALUES ('600552.SH','2017-01-02',10,1,1)"
    )
    day = date(2017, 1, 3)
    frame = pd.DataFrame([bar(day, 10.1, 10, 1.3)])
    ref = bar(
        day, 99 if failure == "close_conflict" else 10.1, None if failure == "missing" else 10, 1
    )
    backup(svc, [] if failure == "empty" else [ref])
    if failure == "timeout":

        def fail(*args):
            raise TimeoutError("offline")

        svc._bao_source = lambda: SimpleNamespace(name="baostock", get_daily_bar=fail)
    with pytest.raises(DataSourceError):
        write(svc, frame)
    assert svc.c.query_df("SELECT count(*) FROM daily_bar").iloc[0, 0] == 1


def test_partial_refetch_verifies_right_seam_and_preserves_other_rows(ingest):
    svc = ingest
    svc.c.execute(
        "INSERT INTO daily_bar(code,trade_date,close,pre_close,adj_factor,adj_factor_clean) VALUES ('600552.SH','2017-01-02',10,10,1,1),('600552.SH','2017-01-04',10.2,10.1,1,1)"
    )
    day = date(2017, 1, 3)
    calls = backup(svc, [bar(day, 10.1, 10, 1), bar(day + timedelta(days=1), 10.2, 10.1, 1)])
    write(svc, pd.DataFrame([bar(day, 10.1, 10, 1.3)]))
    assert calls == [("600552.SH", day, day + timedelta(days=1))]
    assert (
        svc.c.query_df("SELECT adj_factor_clean FROM daily_bar WHERE trade_date='2017-01-04'")
        .isna()
        .iloc[0, 0]
    )
    svc._recompute_clean_one("600552.SH", 0.1, full=False)
    rows = svc.c.query_df(
        "SELECT close,pre_close,adj_factor,adj_factor_clean,reference_source FROM daily_bar ORDER BY trade_date"
    )
    assert rows.close.tolist() == [10, 10.1, 10.2]
    assert rows.pre_close.tolist() == [10, 10, 10.1]
    assert rows.adj_factor.tolist() == [1, 1.3, 1]
    assert rows.adj_factor_clean.tolist() == pytest.approx([1, 1, 1])


def test_same_basis_real_ex_dividend_does_not_add_network(ingest):
    svc = ingest
    svc.c.execute(
        "INSERT INTO daily_bar(code,trade_date,close,adj_factor,adj_factor_clean) VALUES ('600552.SH','2017-01-02',30,1,1)"
    )
    calls = backup(svc, [])
    write(svc, pd.DataFrame([bar(date(2017, 1, 3), 15.1, 15, 2)]))
    svc._recompute_clean_one("600552.SH", 0.1, full=False)
    assert not calls
    assert (
        svc.c.query_df("SELECT pre_close FROM daily_bar ORDER BY trade_date DESC LIMIT 1").iloc[
            0, 0
        ]
        == 15
    )


def test_source_omission_inside_refetch_also_verifies_internal_seams(ingest):
    svc = ingest
    svc.c.execute(
        "INSERT INTO daily_bar(code,trade_date,close,pre_close,adj_factor,adj_factor_clean) VALUES ('600552.SH','2017-01-02',10,10,1,1),('600552.SH','2017-01-04',10.2,10.1,1,1)"
    )
    days = [date(2017, 1, 3) + timedelta(days=i) for i in range(3)]
    calls = backup(svc, [bar(day, 10.1 + i / 10, 10 + i / 10, 1) for i, day in enumerate(days)])
    write(svc, pd.DataFrame([bar(days[0], 10.1, 10, 1.3), bar(days[2], 10.3, 10.2, 1.3)]))
    assert calls == [("600552.SH", days[0], days[2])]
    svc._recompute_clean_one("600552.SH", 0.1, full=False)
    rows = svc.c.query_df("SELECT pre_close,adj_factor_clean FROM daily_bar ORDER BY trade_date")
    assert rows.pre_close.tolist() == [10, 10, 10.1, 10.2]
    assert rows.adj_factor_clean.tolist() == pytest.approx([1, 1, 1, 1])


def test_ten_year_source_switch_real_ingest_rebuild_and_untouched_evidence(ingest):
    svc = ingest
    svc.c.execute(
        "INSERT INTO daily_bar(code,trade_date,open,high,low,close,pre_close,volume,amount,adj_factor,adj_factor_clean) SELECT '600552.SH',DATE '2010-01-01'+i::INTEGER,10,10,10,10,10,100,1000,1,1 FROM range(2400) t(i)"
    )
    first_new = date(2010, 1, 1) + timedelta(days=2400)
    rows = [bar(first_new + timedelta(days=i), 10, 10, 1.3) for i in range(200)]
    calls = backup(svc, [bar(first_new, 10, 10, 1)])
    before = svc.c.query_df("SELECT trade_date,adj_factor FROM daily_bar ORDER BY trade_date")
    assert write(svc, pd.DataFrame(rows)) == 200
    assert svc._recompute_clean_one("600552.SH", 0.1, full=False) == 200
    assert svc._recompute_clean_one("600552.SH", 0.1) == 2600
    full = svc.c.query_df("SELECT adj_factor_clean,pre_close FROM daily_bar ORDER BY trade_date")
    assert full.adj_factor_clean.tolist() == pytest.approx([1] * 2600)
    assert full.pre_close.tolist() == [10] * 2600
    pd.testing.assert_frame_equal(
        before,
        svc.c.query_df(
            "SELECT trade_date,adj_factor FROM daily_bar ORDER BY trade_date LIMIT 2400"
        ),
    )
    assert len(calls) == 1 and calls[0][1:] == (first_new, first_new)


def test_rebuild_updates_cache_revision_atomically(ingest, monkeypatch, tmp_path):
    svc = ingest
    with DuckDBClient(str(tmp_path / "rollback.duckdb")) as client:
        init_db(client)
        svc.c, svc.repo = client, MarketRepository(client)
        svc.c.execute(
            "INSERT INTO daily_bar(code,trade_date,close,pre_close,adj_factor,adj_factor_clean) VALUES ('600552.SH','2017-01-02',10,10,1,1),('600552.SH','2017-01-03',10.1,7,1.3,1.3)"
        )
        svc.c.execute(
            "UPDATE daily_bar SET reference_pre_close=10,reference_close=close,reference_source='baostock' WHERE trade_date='2017-01-03'"
        )
        svc._recompute_clean_one("600552.SH", 0.1)
        version = svc.c.query_df(
            "SELECT max(id) FROM data_update_log WHERE source='derived:price_factors'"
        ).iloc[0, 0]
        assert version > 0
        svc.c.execute("UPDATE daily_bar SET pre_close=7 WHERE trade_date='2017-01-03'")
        before = svc.c.query_df("SELECT * FROM daily_bar ORDER BY trade_date")

        def failed_log(*args, **kwargs):
            raise RuntimeError("revision write failed")

        monkeypatch.setattr(svc.repo, "log_update", failed_log)
        with pytest.raises(StorageError, match="revision write failed"):
            svc._recompute_clean_one("600552.SH", 0.1)
        pd.testing.assert_frame_equal(
            before, svc.c.query_df("SELECT * FROM daily_bar ORDER BY trade_date")
        )
        assert (
            svc.c.query_df(
                "SELECT max(id) FROM data_update_log WHERE source='derived:price_factors'"
            ).iloc[0, 0]
            == version
        )


@pytest.mark.parametrize("stage", ["source", "after_response"])
def test_cancel_during_reference_check_never_writes(ingest, monkeypatch, stage):
    from backend.services.async_task import TaskCancelled

    svc = ingest
    svc.c.execute(
        "INSERT INTO daily_bar(code,trade_date,close,adj_factor,adj_factor_clean) VALUES ('600552.SH','2017-01-02',10,1,1)"
    )
    cancelled = []
    day = date(2017, 1, 3)

    def fetch(*args):
        if stage == "source":
            raise TaskCancelled()
        cancelled.append(True)
        return pd.DataFrame([bar(day, 10.1, 10, 1)])

    def check():
        if cancelled:
            raise TaskCancelled()

    svc._bao_source = lambda: SimpleNamespace(name="baostock", get_daily_bar=fetch)
    monkeypatch.setattr("backend.services.ingest.check_thread_cancel", check)
    with pytest.raises(TaskCancelled):
        write(svc, pd.DataFrame([bar(day, 10.1, 10, 1.3)]))
    assert svc.c.query_df("SELECT count(*) FROM daily_bar").iloc[0, 0] == 1
