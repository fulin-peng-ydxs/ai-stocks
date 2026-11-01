"""显式停牌状态才能排除零量占位；复用状态材料，删除/备份/入库在一个事务。"""

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.common.exceptions import DataSourceError, StorageError
from backend.services.ingest import IngestionService, _DailySTMaterial
from backend.storage.repository import MarketRepository

CODE = "002015.SZ"
DAYS = [date(2019, 3, d) for d in [18, 19, 20]]


@pytest.fixture()
def prepared(market, monkeypatch):
    market.execute(
        "INSERT INTO stock_basic(code,list_date,board,price_limit_pct) "
        "VALUES (?,DATE '2004-07-08','主板',0.1)",
        [CODE],
    )
    for day in DAYS:
        market.execute("INSERT INTO trade_calendar VALUES (?,TRUE)", [day])
    frame = pd.DataFrame(
        [
            {
                "code": CODE,
                "trade_date": day,
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "pre_close": 10.0,
                "volume": volume,
                "amount": float(volume * 10),
                "adj_factor": 1.0,
                "turnover_rate": 0.0,
                "_pre_close_factor_event": False,
            }
            for day, volume in zip(DAYS, [100, 0, 100])
        ]
    )
    states = pd.DataFrame(
        [
            {
                "code": CODE,
                "trade_date": day,
                "is_st": False,
                "trade_status": status,
                "source_ref": "query_history_k_data_plus:isST",
            }
            for day, status in zip(DAYS, [1, 0, 1])
        ]
    )
    obj = object.__new__(IngestionService)
    obj.c, obj.repo = market, MarketRepository(market)
    obj.s = SimpleNamespace(datasource=SimpleNamespace(primary="akshare"))
    obj.src = SimpleNamespace(name="akshare")
    fetches = []
    monkeypatch.setattr(
        obj, "_fetch_daily_with_fallback", lambda *a, **kw: (frame.copy(), "akshare")
    )
    monkeypatch.setattr(
        obj,
        "_fetch_st_status_rows",
        lambda *a, **kw: (fetches.append(a) or SimpleNamespace(name="baostock"), states.copy()),
    )
    return obj, frame, states, fetches


def test_verified_zero_row_is_not_reintroduced_and_material_is_reused(prepared, market):
    obj, _, _, fetches = prepared
    count = obj.ingest_one_daily(CODE, DAYS[0], DAYS[-1])
    assert count == 2
    assert len(fetches) == 1
    assert pd.to_datetime(
        market.query_df("SELECT trade_date FROM daily_bar ORDER BY trade_date").trade_date
    ).dt.date.tolist() == [DAYS[0], DAYS[2]]
    row = market.query_df(
        "SELECT source FROM stock_suspension WHERE code=? AND trade_date=?", [CODE, DAYS[1]]
    )
    assert row.source.tolist() == ["baostock:trade_status=0"]
    assert (
        market.query_df("SELECT count(*) FROM stock_st_status_daily WHERE quality='accurate'").iloc[
            0, 0
        ]
        == 3
    )


def test_existing_zero_and_metrics_are_backed_up_and_purged(prepared, market):
    obj, _, _, _ = prepared
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,close,pre_close,volume,amount,adj_factor) "
        "VALUES (?,?,6.93,6.93,0,0,1)",
        [CODE, DAYS[1]],
    )
    market.execute(
        "INSERT INTO daily_metrics(code,trade_date,total_mv) VALUES (?,?,693)", [CODE, DAYS[1]]
    )
    assert obj.ingest_one_daily(CODE, DAYS[0], DAYS[-1]) == 2
    assert market.query_df("SELECT * FROM daily_metrics WHERE trade_date=?", [DAYS[1]]).empty
    backup = market.query_df(
        "SELECT detail FROM data_update_log WHERE source='review:suspension_backup'"
    )
    assert len(backup) == 1 and "6.93" in backup.detail.iloc[0] and "693" in backup.detail.iloc[0]


@pytest.mark.parametrize("existing", [False, True])
def test_purge_and_quotes_rollback_together_on_st_write_failure(
    prepared, market, monkeypatch, existing
):
    from backend.services.stock_st_status import StockSTStatusService

    obj, _, _, _ = prepared
    if existing:
        market.execute(
            "INSERT INTO daily_bar(code,trade_date,close,pre_close,volume,amount,adj_factor) "
            "VALUES (?,?,6.93,6.93,0,0,1)",
            [CODE, DAYS[1]],
        )
        market.execute(
            "INSERT INTO daily_metrics(code,trade_date,total_mv) VALUES (?,?,693)", [CODE, DAYS[1]]
        )

    def fail(*a, **kw):
        raise RuntimeError("test ST transaction failure")

    monkeypatch.setattr(StockSTStatusService, "upsert_facts", fail)
    conn = market.conn  # 事务失败会使客户端丢弃连接；内存库通过原连接检查实际回滚结果。
    try:
        with pytest.raises(StorageError, match="transaction failure"):
            obj.ingest_one_daily(CODE, DAYS[0], DAYS[-1])
        assert conn.execute("SELECT close FROM daily_bar").fetchall() == (
            [(6.93,)] if existing else []
        )
        assert conn.execute("SELECT total_mv FROM daily_metrics").fetchall() == (
            [(693.0,)] if existing else []
        )
        assert conn.execute("SELECT count(*) FROM stock_suspension").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM stock_st_status_daily").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT count(*) FROM data_update_log WHERE source='review:suspension_backup'"
            ).fetchone()[0]
            == 0
        )
    finally:
        conn.close()


@pytest.mark.parametrize("status", [1, None])
def test_zero_volume_alone_never_proves_suspension(prepared, market, status):
    obj, frame, states, _ = prepared
    states.loc[1, "trade_status"] = status
    material = _DailySTMaterial(pd.DataFrame(), (SimpleNamespace(name="baostock"), states))
    filtered, proof, _ = obj._filter_verified_suspension_bars(CODE, frame, material)
    assert len(filtered) == 3 and proof is None
    assert market.query_df("SELECT * FROM stock_suspension").empty


def test_prefetched_states_do_not_trigger_another_network_request(prepared, monkeypatch):
    obj, frame, states, _ = prepared
    material = _DailySTMaterial(pd.DataFrame(), (SimpleNamespace(name="baostock"), states))
    monkeypatch.setattr(
        obj, "_fetch_st_status_rows", lambda *a, **kw: pytest.fail("已有材料不得重复取源")
    )
    filtered, proof, actual = obj._filter_verified_suspension_bars(CODE, frame, material)
    assert len(filtered) == 2 and proof is not None and actual is material


def test_positive_existing_trade_conflict_is_preserved(prepared, market):
    obj, _, _, _ = prepared
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,close,volume,amount) VALUES (?,?,6.93,100,693)",
        [CODE, DAYS[1]],
    )
    with pytest.raises(DataSourceError, match="保留原数据"):
        obj.ingest_one_daily(CODE, DAYS[0], DAYS[-1])
    assert market.query_df("SELECT volume FROM daily_bar").volume.tolist() == [100]


@pytest.mark.parametrize("retained", [False, True])
def test_only_suspended_placeholder_still_persists_accurate_facts(
    prepared, market, monkeypatch, retained
):
    obj, frame, _, _ = prepared
    if retained:
        market.execute(
            "INSERT INTO daily_bar(code,trade_date,open,high,low,close,pre_close,volume,amount,adj_factor,adj_factor_clean) "
            "VALUES (?,?,10,10,10,10,10,100,1000,1,1)",
            [CODE, DAYS[0]],
        )
        market.execute(
            "INSERT INTO daily_bar(code,trade_date,close,pre_close,volume,amount,adj_factor,adj_factor_clean) "
            "VALUES (?,?,6.93,6.93,0,0,1,1)",
            [CODE, DAYS[1]],
        )
    monkeypatch.setattr(
        obj, "_fetch_daily_with_fallback", lambda *a, **kw: (frame.iloc[[1]].copy(), "akshare")
    )
    assert obj.ingest_one_daily(CODE, DAYS[0], DAYS[-1]) == 0
    bars = market.query_df("SELECT * FROM daily_bar")
    if retained:
        assert bars.close.tolist() == [10]
        assert bars.adj_factor_clean.isna().all()
        assert obj._dirty_daily_codes([CODE]) == {CODE}
    else:
        assert bars.empty
    assert market.query_df(
        "SELECT trade_date FROM stock_suspension"
    ).trade_date.dt.date.tolist() == [DAYS[1]]
    assert (
        market.query_df(
            "SELECT trade_date FROM stock_st_status_daily WHERE quality='accurate' ORDER BY trade_date"
        ).trade_date.dt.date.tolist()
        == DAYS
    )


def test_boundary_skips_verified_zero_before_selecting_valid_neighbor(
    prepared, market, monkeypatch
):
    obj, frame, _, _ = prepared
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,open,high,low,close,pre_close,volume,amount,adj_factor) "
        "VALUES (?,?,10,10,10,10,10,100,1000,1)",
        [CODE, DAYS[0]],
    )
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,close,pre_close,volume,amount,adj_factor) "
        "VALUES (?,?,6.93,6.93,0,0,1)",
        [CODE, DAYS[1]],
    )
    monkeypatch.setattr(
        obj, "_fetch_daily_with_fallback", lambda *a, **kw: (frame.iloc[1:].copy(), "akshare")
    )
    assert obj.ingest_one_daily(CODE, DAYS[1], DAYS[2]) == 1
    assert market.query_df("SELECT close FROM daily_bar ORDER BY trade_date").close.tolist() == [
        10,
        10,
    ]


@pytest.mark.parametrize("factor_fail", [0, 1])
def test_formal_review_reuses_backup_and_reports_factor_failure(
    prepared, market, monkeypatch, factor_fail
):
    obj, _, _, _ = prepared
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,close,pre_close,volume,amount,adj_factor) "
        "VALUES (?,?,6.93,6.93,0,0,1)",
        [CODE, DAYS[1]],
    )
    calls = []
    monkeypatch.setattr(
        obj, "_recompute_clean", lambda codes, **kw: calls.append(codes) or {"fail": factor_fail}
    )
    result = obj.review_suspensions(codes=[CODE], purge_candidates=True)
    assert result["purged"] == result["confirmed"] == 1
    assert calls == [[CODE]]
    assert result["ok"] is (not factor_fail)
    if factor_fail:
        assert "重算失败" in result["errors"][CODE]
    assert market.query_df("SELECT * FROM daily_bar").empty
    assert (
        len(
            market.query_df("SELECT * FROM data_update_log WHERE source='review:suspension_backup'")
        )
        == 1
    )


@pytest.mark.parametrize(
    "case", ["reuse", "changed_close", "new_direct_evidence", "stale_reference"]
)
def test_reingest_preserves_only_matching_verified_reference(prepared, market, monkeypatch, case):
    obj, frame, states, _ = prepared
    frame["volume"], frame["amount"] = 100, 1000
    states["trade_status"] = 1
    frame.loc[1, "adj_factor"] = 1.1
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,close,reference_pre_close,reference_close,reference_source) "
        "VALUES (?,?,10,9.5,?,'baostock')",
        [CODE, DAYS[1], 9.8 if case == "stale_reference" else 10],
    )
    if case == "changed_close":
        frame.loc[1, ["open", "high", "low", "close"]] = 11.0
    if case == "new_direct_evidence":
        frame["reference_source"] = None
        frame.loc[1, "reference_source"] = "new_direct"
        frame.loc[1, "reference_pre_close"] = 9.8
        frame.loc[1, "reference_close"] = 10.0
        frame.loc[1, "pre_close"] = 9.8
    assert obj.ingest_one_daily(CODE, DAYS[0], DAYS[-1]) == 3
    row = market.query_df(
        "SELECT pre_close,reference_pre_close,reference_source,adj_factor "
        "FROM daily_bar WHERE code=? AND trade_date=?",
        [CODE, DAYS[1]],
    ).iloc[0]
    assert row.adj_factor == 1.1
    if case == "reuse":
        assert row.pre_close == row.reference_pre_close == 9.5
        assert row.reference_source == "baostock"
    elif case == "new_direct_evidence":
        assert row.pre_close == row.reference_pre_close == 9.8
        assert row.reference_source == "new_direct"
    else:
        assert row.pre_close == 10.0
        assert row.reference_source is None
