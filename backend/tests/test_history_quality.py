"""全历史日线缺口：存续边界、真实停牌、规模扫描与统一复检。"""

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.services.data_report import DataIntegrityReport
from backend.services.data_verify import DataVerifier
from backend.services.history_quality import HistoryQualityService
from backend.services.ingest import IngestionService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


@pytest.fixture
def market():
    with DuckDBClient(":memory:") as c:
        init_db(c)
        c.execute(
            "INSERT INTO trade_calendar(trade_date,is_open) SELECT DATE '2017-01-02'+i::INTEGER,true FROM range(5) t(i)"
        )
        c.execute(
            "INSERT INTO stock_basic(code,list_date,delist_date) VALUES ('A.SH','2017-01-02',NULL),('B.SZ','2017-01-03','2017-01-06'),('C.BJ','2017-01-02',NULL)"
        )
        c.execute(
            "INSERT INTO daily_bar(code,trade_date,close) VALUES ('A.SH','2017-01-04',10),('A.SH','2017-01-06',10),('B.SZ','2017-01-04',10)"
        )
        yield c


def test_missing_includes_leading_and_delisted_but_excludes_confirmed_suspension(market):
    q = HistoryQualityService(market)
    assert q.dates("A.SH") == [date(2017, 1, 2), date(2017, 1, 3), date(2017, 1, 5)]
    assert q.dates("B.SZ") == [date(2017, 1, 3), date(2017, 1, 5)]
    assert q.dates("C.BJ") == []
    market.execute("INSERT INTO stock_suspension(code,trade_date) VALUES ('A.SH','2017-01-03')")
    assert len(q.dates("A.SH")) == 2
    v = DataVerifier(market, quiet=True)
    v.check_history_coverage()
    assert not v.results[-1][1] and "缺 4 " in v.results[-1][2]


def test_ledger_identity_recheck_and_other_stock_preserved(market):
    q = HistoryQualityService(market)
    r = DataIntegrityReport(market)
    r._upsert_scan_issues(q.issues(), ("history_data_gap",))
    iid = market.query_df("SELECT id FROM data_quality_issue WHERE code='A.SH'").iloc[0, 0]
    for day in q.dates("A.SH"):
        market.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES ('A.SH',?,10)", [day])
    assert r.recheck_clean("history_data_gap", "A.SH", None)
    r._upsert_scan_issues(q.issues(), ("history_data_gap",))
    assert (
        market.query_df("SELECT status FROM data_quality_issue WHERE id=?", [int(iid)]).iloc[0, 0]
        == "resolved"
    )
    assert not r.recheck_clean("history_data_gap", "B.SZ", None)


def test_recent_batch_keeps_original_start_suspension_and_delisting_semantics(market):
    report = DataIntegrityReport(market)
    market.execute("UPDATE stock_basic SET delist_date='2017-01-05' WHERE code='B.SZ'")
    market.execute("INSERT INTO stock_suspension(code,trade_date) VALUES ('A.SH','2017-01-05')")
    rows = report.missing_days_many(["A.SH", "B.SZ", "C.BJ", "A.SH"])
    actual = [(row.code, row.trade_date.date()) for row in rows.itertuples()]
    # 近端规则从已有首条行情开始，且原规则并不按退市日期裁剪，不能拿历史规则替代。
    assert actual == [("B.SZ", date(2017, 1, 5)), ("B.SZ", date(2017, 1, 6)),
                      *(('C.BJ', date(2017, 1, day)) for day in range(2, 7))]
    assert HistoryQualityService(market).dates("B.SZ") == [date(2017, 1, 3)]
    assert report.missing_days_for("A.SH") == []
    assert report.missing_days_many([]).empty


@pytest.mark.parametrize("status,expected", [(None, 0), (1, 0), (0, 3)])
def test_empty_source_never_implies_suspension(market, status, expected):
    ing = IngestionService.__new__(IngestionService)
    ing.c = market
    ing.ingest_one_daily = lambda *a, **kw: 0
    ing._bao_source = lambda: SimpleNamespace()
    ing._fetch_st_status_rows = lambda *a, **kw: (
        "baostock",
        pd.DataFrame()
        if status is None
        else pd.DataFrame(
            {"trade_date": HistoryQualityService(market).dates("A.SH"), "trade_status": status}
        ),
    )
    result = ing.reconcile_gaps("A.SH", full_history=True)
    assert result["confirmed"] == expected
    assert len(HistoryQualityService(market).dates("A.SH")) == 3 - expected


def test_scale_240000_expected_dates_aggregate_and_real_repair(market):
    market.execute("DELETE FROM daily_bar")
    market.execute("DELETE FROM stock_basic")
    market.execute("DELETE FROM trade_calendar")
    market.execute(
        "INSERT INTO trade_calendar(trade_date,is_open) SELECT DATE '2017-01-01'+i::INTEGER,true FROM range(2400) t(i)"
    )
    market.execute(
        "INSERT INTO stock_basic(code,list_date) SELECT i::VARCHAR||'.SH',DATE '2017-01-01' FROM range(100) t(i)"
    )
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,close) SELECT code,DATE '2017-01-01'+2399,10 FROM stock_basic"
    )
    q = HistoryQualityService(market)
    assert int(q.aggregate().missing_days.sum()) == 239900
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,close) SELECT '0.SH',trade_date,10 FROM trade_calendar WHERE trade_date<DATE '2017-01-01'+2399"
    )
    assert q.aggregate(["0.SH"]).empty
    assert len(q.aggregate()) == 99


def test_conflicting_status_does_not_confirm_suspension(market):
    ing = IngestionService.__new__(IngestionService)
    ing.c = market
    ing.ingest_one_daily = lambda *a, **kw: 0
    ing._bao_source = lambda: SimpleNamespace()
    ing._fetch_st_status_rows = lambda *a, **kw: (
        "baostock",
        pd.DataFrame({"trade_date": ["2017-01-02", "2017-01-02"], "trade_status": [0, 1]}),
    )
    assert ing.reconcile_gaps("A.SH", full_history=True)["confirmed"] == 0


def test_suspension_confirmed_inside_ingestion_is_counted(market):
    ing = IngestionService.__new__(IngestionService)
    ing.c = market
    def collect(*args, **kwargs):
        DataIntegrityReport(market).confirm_suspension('A.SH', HistoryQualityService(market).dates('A.SH'))
        return 0
    ing.ingest_one_daily = collect
    ing._fetch_st_status_rows = lambda *a, **kw: ('baostock', pd.DataFrame())
    result = ing.reconcile_gaps('A.SH', full_history=True)
    assert result['confirmed'] == 3
    assert IngestionService.reconcile_note(result) == '确认停牌 3 天'


def test_evidence_first_skips_price_requests_and_persists_proof(market):
    ing = IngestionService.__new__(IngestionService)
    ing.c = market
    ing._fetch_st_status_rows = lambda *a, **kw: (
        'baostock', pd.DataFrame({'trade_date': ['2017-01-02','2017-01-03','2017-01-05'], 'trade_status': [0,0,0]}))
    def unexpected(*args, **kwargs):
        pytest.fail('已确认全为停牌，不应重采价格')
    ing.ingest_one_daily = unexpected
    result = ing.reconcile_gaps('A.SH', full_history=True)
    assert result['confirmed'] == 3
    assert result['backfilled'] == []
    proof = market.query_df("SELECT source,row_count,detail FROM data_update_log WHERE table_name='stock_suspension'").iloc[0]
    assert proof['row_count'] == 3 and 'trade_status=0' in proof['source']
    assert '2017-01-05' in proof['detail']


def test_history_legacy_ignore_does_not_hide_leading_gap(market):
    market.execute("INSERT INTO data_quality_issue(id,code,issue_type,status,ignore_scope,ignore_active) VALUES (900,'A.SH','data_gap','ignored','object',true)")
    rows = HistoryQualityService(market).aggregate(['A.SH'], respect_legacy_ignores=True)
    # 01-05 内部缺口被旧规则忽略；01-02/03 头部缺口不能随之被隐藏。
    assert rows.iloc[0].missing_days == 2
    assert len(HistoryQualityService(market).dates('A.SH')) == 3


def test_mark_delisted_preserves_pre_delisting_history_gap(market, monkeypatch):
    q = HistoryQualityService(market)
    DataIntegrityReport(market)._upsert_scan_issues(q.issues(), ('history_data_gap',))
    iid = int(market.query_df("SELECT id FROM data_quality_issue WHERE code='A.SH'").iloc[0,0])
    from backend.services.manual_delisting import apply_delisting
    result = apply_delisting(market, {'issue_id': iid, 'delist_date':'2017-01-07', 'reason':'测试正式退市日'}, SimpleNamespace(tid='test'))
    assert result['resolved'] == 0
    assert market.query_df('SELECT status FROM data_quality_issue WHERE id=?',[iid]).iloc[0,0] == 'open'
    assert q.dates('A.SH') == [date(2017,1,2),date(2017,1,3),date(2017,1,5)]


def test_failed_status_provider_not_retried_as_price_fallback(market):
    from backend.common.exceptions import DataSourceError
    ing = IngestionService.__new__(IngestionService)
    ing.c = market
    def unavailable(*args, **kwargs):
        raise DataSourceError('login timeout')
    ing._fetch_st_status_rows = unavailable
    calls = []
    ing.ingest_one_daily = lambda *a,**kw: calls.append(a) or 0
    ing._bao_source = lambda: pytest.fail('已失败的同一状态源不应重复作为行情备用源请求')
    result = ing.reconcile_gaps('A.SH', full_history=True)
    assert len(calls) == 1 and result['stage_errors']['suspension'] == 'login timeout'
    assert market.query_df('SELECT * FROM stock_suspension').empty


def test_explicit_backup_source_does_not_fallback_to_itself():
    from backend.common.exceptions import DataSourceError
    calls = []
    source = SimpleNamespace(name='baostock', get_daily_bar=lambda *a: calls.append(a) or pd.DataFrame())
    ing = IngestionService.__new__(IngestionService)
    ing._bao_source = lambda: source
    with pytest.raises(DataSourceError, match='不重复请求'):
        ing._fetch_daily_with_fallback('A.SH',date(2020,1,1),date(2020,1,2),source)
    assert len(calls) == 1


def test_regular_st_fetch_persists_suspension_without_hiding_incoming_price(market):
    ing = IngestionService.__new__(IngestionService)
    ing.c = market
    ing._fetch_st_status_rows = lambda *a, **kw: (SimpleNamespace(name='baostock'), pd.DataFrame({
        'trade_date': pd.to_datetime(['2017-01-02','2017-01-03','2017-01-04','2017-01-05']),
        'trade_status': [0,0,0,None], 'is_st':[False]*4,
    }))
    ing._accurate_st_facts('A.SH', [date(2017,1,3),date(2017,1,4)])
    # 01-03 是即将写入的行情，01-04 已有行情，01-05 未知；只有 01-02 可归档停牌。
    got = market.query_df("SELECT trade_date FROM stock_suspension WHERE code='A.SH'")
    assert pd.to_datetime(got.trade_date).dt.date.tolist() == [date(2017,1,2)]


def test_baostock_unknown_trade_status_is_not_suspension(monkeypatch):
    from backend.datasource.baostock_source import BaostockSource
    source = BaostockSource.__new__(BaostockSource)
    monkeypatch.setattr(source, '_st_data', lambda *a: pd.DataFrame({
        'date':['2017-01-02','2017-01-03','2017-01-04'], 'isST':['0']*3, 'tradestatus':['','0','wrong'],
    }))
    frame = source.get_st_status('A.SH',date(2017,1,2),date(2017,1,4))
    assert pd.isna(frame.iloc[0].trade_status) and frame.iloc[1].trade_status == 0
    assert pd.isna(frame.iloc[2].trade_status)


def test_baostock_login_timeout_does_not_change_global_socket(monkeypatch):
    import socket

    import baostock
    from baostock.common import context
    from baostock.util.socketutil import SocketUtil

    from backend.datasource.baostock_source import BaostockSource

    source = BaostockSource.__new__(BaostockSource)
    source._logged_in = False
    source._login_timeout_sec = 120
    source._socket_timeout_sec = 30
    timeouts = []
    fake_socket = SimpleNamespace(settimeout=lambda value: timeouts.append(value))
    default = socket.getdefaulttimeout()
    connector = SocketUtil()
    original = connector.connect
    def connect(address, *, timeout):
        assert timeout == 120
        return fake_socket
    def login():
        SocketUtil().connect()
        assert context.default_socket is fake_socket
        return SimpleNamespace(error_code="0", error_msg="success")
    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(baostock, "login", login)
    monkeypatch.setattr(baostock, "logout", lambda: None)
    monkeypatch.setattr(context, "default_socket", None, raising=False)
    source._ensure_login()
    assert timeouts == [30]
    assert connector.connect == original
    assert socket.getdefaulttimeout() == default


def test_baostock_login_restores_connector_on_failure(monkeypatch):
    import baostock
    from baostock.util.socketutil import SocketUtil

    from backend.datasource.baostock_source import BaostockSource
    source = BaostockSource.__new__(BaostockSource)
    source._logged_in = False
    source._login_timeout_sec = 120
    connector = SocketUtil()
    original = connector.connect
    def login():
        raise TimeoutError("login timed out")
    monkeypatch.setattr(baostock, "login", login)
    with pytest.raises(TimeoutError):
        source._ensure_login()
    assert connector.connect == original


def test_backfilled_daily_calls_real_capital_signature(market):
    ing = IngestionService.__new__(IngestionService)
    ing.c = market
    expected = HistoryQualityService(market).dates("A.SH")
    ing._fetch_st_status_rows = lambda *a,**kw: ("baostock", pd.DataFrame())
    def collect(*a, **kw):
        for day in expected:
            market.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES ('A.SH',?,10)", [day])
        return len(expected)
    ing.ingest_one_daily = collect
    ing._source_for = lambda capability: "valuation"
    calls = []
    factor_calls = []
    ing._recompute_clean = lambda codes,ctx=None: factor_calls.append(codes) or {"fail": 0}
    # 与真实方法一致，无 ctx 参数；防止 TypeError 被容错块吞掉。
    def capital(code, source, start, end, diagnostics=None, overwrite_dates=None):
        calls.append((code, start, end))
    ing._collect_capital_one = capital
    result = ing.reconcile_gaps("A.SH", full_history=True)
    assert result["backfilled"] == expected
    assert calls == [("A.SH", min(expected), max(expected))]
    assert factor_calls == [["A.SH"]]


def test_adj_repair_recomputes_clean_factor_before_recheck(market):
    from backend.services.async_task import _recover_one
    market.execute("INSERT INTO data_quality_issue(id,code,trade_date,issue_type,status) VALUES (900,'A.SH','2017-01-04','adj_jump','open')")
    calls = []
    ing = SimpleNamespace(
        ingest_one_daily=lambda *a,**kw: calls.append("ingest"),
        _recompute_clean=lambda *a,**kw: calls.append("clean") or {"fail": 0},
    )
    report = SimpleNamespace(recheck_clean=lambda *a,**kw: calls == ["ingest","clean"])
    context = SimpleNamespace(tid="test_adj_repair",log=lambda *a:None)
    clean, _, _ = _recover_one(market, report, ing, context, 900)
    assert clean and calls == ["ingest","clean"]


def test_reference_price_restores_dividend_before_factor_reset():
    from backend.datasource.akshare_source import compute_pre_close, dejitter_adj_factor
    raw = pd.Series([1.0, 1.0, 4.18, 4.18])
    close = pd.Series([24.14, 21.33, 21.4, 21.5])
    reference = pd.Series([24.0, 21.71, 21.33, 21.4])
    clean = dejitter_adj_factor(raw, close, reference)
    assert clean.iloc[1] == pytest.approx(24.14 / 21.71)
    assert clean.iloc[2] == pytest.approx(clean.iloc[1])
    assert compute_pre_close(close, clean).iloc[1:].tolist() == reference.iloc[1:].tolist()
    assert raw.tolist() == [1.0, 1.0, 4.18, 4.18]


def test_reference_factor_rebuild_is_persistent_and_idempotent(market):
    from backend.storage.repository import MarketRepository
    market.execute("DELETE FROM daily_bar WHERE code='A.SH'")
    market.execute("""INSERT INTO daily_bar(code,trade_date,close,pre_close,adj_factor)
        VALUES ('A.SH','2017-01-02',24.14,24,1),
               ('A.SH','2017-01-03',21.33,21.71,1),
               ('A.SH','2017-01-04',21.4,21.33,4.18)""")
    ing = IngestionService.__new__(IngestionService)
    ing.c = market
    ing.repo = MarketRepository(market)
    market.execute("UPDATE daily_bar SET reference_pre_close=pre_close,reference_close=close,reference_source='baostock' WHERE code='A.SH'")
    ing._recompute_clean_one('A.SH', 0.1)
    first = market.query_df("SELECT adj_factor,adj_factor_clean,pre_close FROM daily_bar WHERE code='A.SH' ORDER BY trade_date")
    ing._recompute_clean_one('A.SH', 0.1)
    second = market.query_df("SELECT adj_factor,adj_factor_clean,pre_close FROM daily_bar WHERE code='A.SH' ORDER BY trade_date")
    pd.testing.assert_frame_equal(first, second)
    assert first.adj_factor.tolist() == [1, 1, 4.18]
    assert first.pre_close.tolist() == [24, 21.71, 21.33]


def test_factor_reset_calibrates_reference_before_reset_too():
    ing = IngestionService.__new__(IngestionService)
    dates = [date(2017,1,2), date(2017,1,3), date(2017,1,4)]
    frame = pd.DataFrame({"trade_date": dates,"close": [24.14,21.33,21.4],
                              "pre_close": [24,24.14,5.1],"adj_factor": [1,1,4.18],
                              "_pre_close_factor_event": [False,False,True]})
    seen = []
    def reference(code,start,end):
        seen.append((start,end))
        return pd.DataFrame({"trade_date": dates,"pre_close": [24,21.71,21.33],"close": [24.14,21.33,21.4]})
    ing._bao_source = lambda: SimpleNamespace(name="baostock",get_daily_bar=reference)
    calibrated, _ = ing._calibrate_corporate_action_pre_close(frame,"001872.SZ",0.1,"akshare")
    assert seen == [(dates[0], dates[-1])]
    assert calibrated.pre_close.tolist() == [24,21.71,21.33]


@pytest.mark.parametrize('source,reference_close,expected', [(None,15,2),('baostock',16,2),('baostock',15,1)])
def test_old_derived_reference_never_overrides_correct_split(market,source,reference_close,expected):
    from backend.storage.repository import MarketRepository
    market.execute("DELETE FROM daily_bar WHERE code='A.SH'")
    market.execute("INSERT INTO daily_bar(code,trade_date,close,pre_close,adj_factor) VALUES ('A.SH','2017-01-02',30,30,1),('A.SH','2017-01-03',15,30,2)")
    market.execute("UPDATE daily_bar SET reference_pre_close=30,reference_close=?,reference_source=? WHERE code='A.SH' AND trade_date='2017-01-03'",[reference_close,source])
    ing = IngestionService.__new__(IngestionService)
    ing.c,ing.repo = market,MarketRepository(market)
    ing._recompute_clean_one('A.SH',.1)
    assert market.query_df("SELECT adj_factor_clean FROM daily_bar WHERE code='A.SH' ORDER BY trade_date").iloc[-1,0] == expected


def test_manual_delisting_protects_from_source_and_can_revoke(market):
    from backend.services.manual_delisting import apply_delisting, validate_delisting
    from backend.storage.repository import MarketRepository
    HistoryQualityService(market).sync(['A.SH'])
    iid = int(market.query_df("SELECT id FROM data_quality_issue WHERE code='A.SH'").iloc[0,0])
    ctx = SimpleNamespace(tid='manual-test')
    for day in ('2017-01-01','2017-01-05','2099-01-01'):
        with pytest.raises(ValueError):
            validate_delisting(market,iid,day,'日期校验')
    params = {'issue_id':iid,'delist_date':'2017-01-07','reason':'已核对正式退市日期'}
    apply_delisting(market,params,ctx)
    MarketRepository(market).upsert_stock_basic(pd.DataFrame([{'code':'A.SH','delist_date':None}]))
    assert str(market.query_df("SELECT delist_date FROM stock_basic WHERE code='A.SH'").iloc[0,0])[:10]=='2017-01-07'
    apply_delisting(market,{**params,'delist_date':None,'reason':'纠正人工日期'},ctx)
    assert pd.isna(market.query_df("SELECT delist_date FROM stock_basic WHERE code='A.SH'").iloc[0,0])
    assert market.query_df("SELECT count(*) FROM data_update_log WHERE source='manual:delist_date'").iloc[0,0] == 2


def test_suspension_review_requires_status_and_retracts_wrong_fact(market):
    from backend.storage.repository import MarketRepository
    market.execute("INSERT INTO stock_suspension(code,trade_date) VALUES ('A.SH','2017-01-02'),('A.SH','2017-01-03'),('A.SH','2017-01-05')")
    ing = IngestionService.__new__(IngestionService)
    ing.c,ing.repo = market,MarketRepository(market)
    ing._fetch_st_status_rows=lambda *a,**kw: ('baostock',pd.DataFrame({'trade_date':['2017-01-02','2017-01-03'], 'trade_status':[0,1]}))
    ing.reconcile_gaps=lambda *a,**kw: {}
    result=ing.review_suspensions()
    assert result['confirmed']==1 and result['revoked']==1 and result['unverified']==1
    assert market.query_df("SELECT * FROM stock_suspension WHERE trade_date='2017-01-03'").empty
    assert market.query_df("SELECT source FROM stock_suspension WHERE trade_date='2017-01-02'").iloc[0,0]=='baostock:trade_status=0'


def test_capital_failure_does_not_undo_bars_and_immediately_uses_existing_ledger(market):
    from backend.storage.repository import MarketRepository
    ing=IngestionService.__new__(IngestionService)
    ing.c,ing.repo=market,MarketRepository(market)
    ing._fetch_st_status_rows=lambda *a,**kw: ('baostock',pd.DataFrame())
    ing._recompute_clean=lambda *a,**kw: {'fail':0}
    ing._source_for=lambda *a: None
    def collect(*a,**kw): raise RuntimeError('provider unavailable')
    ing._collect_capital_one=collect
    def bars(*a,**kw):
        market.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES ('A.SH','2017-01-02',10),('A.SH','2017-01-03',10),('A.SH','2017-01-05',10)")
        return 3
    ing.ingest_one_daily=bars
    result=ing.reconcile_gaps('A.SH',full_history=True)
    assert len(result['backfilled'])==3 and result['stage_errors']['capital']=='provider unavailable'
    assert not market.query_df("SELECT * FROM data_quality_issue WHERE code='A.SH' AND issue_type='capital_gap' AND status='open'").empty


def test_normal_status_retracts_previously_confirmed_suspension(market):
    market.execute("INSERT INTO stock_suspension(code,trade_date,source) VALUES ('A.SH','2017-01-02','baostock:trade_status=0')")
    ing=IngestionService.__new__(IngestionService)
    ing.c=market
    ing._persist_gap_status('A.SH','baostock',pd.DataFrame({'trade_date':['2017-01-02'],'trade_status':[1]}),[date(2017,1,2)],DataIntegrityReport(market))
    assert market.query_df('SELECT * FROM stock_suspension').empty
    assert not market.query_df("SELECT * FROM data_update_log WHERE source='baostock:trade_status=1'").empty


def test_reference_refresh_rejects_other_price_and_does_not_fabricate_missing_rows(market):
    from backend.storage.repository import MarketRepository
    ing=IngestionService.__new__(IngestionService)
    ing.c,ing.repo=market,MarketRepository(market)
    ing._bao_source=lambda: SimpleNamespace(name='baostock',get_daily_bar=lambda *a: pd.DataFrame({'trade_date':['2017-01-04','2017-01-06'],'pre_close':[9,9],'close':[10,12]}))
    result=ing.refresh_price_references(['A.SH'])
    assert result['updated']==1 and result['unmatched']==1
    rows=market.query_df("SELECT reference_pre_close FROM daily_bar WHERE code='A.SH' ORDER BY trade_date")
    assert rows.iloc[0,0]==9 and pd.isna(rows.iloc[1,0])


def test_rebuild_scale_and_incremental_matches_full(market):
    from backend.storage.repository import MarketRepository
    market.execute("DELETE FROM daily_bar")
    # 十年逐日规模，覆盖一段正常拆股与旧派生参考价，不仅测试两行算法。
    market.execute("INSERT INTO daily_bar(code,trade_date,close,pre_close,adj_factor) SELECT 'A.SH',DATE '2016-01-01'+i::INTEGER,CASE WHEN i<1200 THEN 30 ELSE 15 END,30,CASE WHEN i<1200 THEN 1 ELSE 2 END FROM range(2400) t(i)")
    ing=IngestionService.__new__(IngestionService)
    ing.c,ing.repo=market,MarketRepository(market)
    assert ing._recompute_clean_one('A.SH',.1)==2400
    full=market.query_df('SELECT trade_date,adj_factor_clean,pre_close FROM daily_bar ORDER BY trade_date')
    market.execute("UPDATE daily_bar SET adj_factor_clean=NULL WHERE trade_date>=DATE '2016-01-01'+1199")
    ing._recompute_clean_one('A.SH',.1,full=False)
    pd.testing.assert_frame_equal(full,market.query_df('SELECT trade_date,adj_factor_clean,pre_close FROM daily_bar ORDER BY trade_date'))
    assert full.iloc[-1].adj_factor_clean==2


def test_suspension_review_removes_post_delisting_records_without_network(market):
    from backend.storage.repository import MarketRepository
    market.execute("INSERT INTO stock_suspension(code,trade_date) VALUES ('B.SZ','2017-01-06')")
    ing=IngestionService.__new__(IngestionService)
    ing.c,ing.repo=market,MarketRepository(market)
    ing._fetch_st_status_rows=lambda *a,**kw: pytest.fail('退市后的无效停牌应按边界撤销，无需再请求接口')
    result=ing.review_suspensions()
    assert result['ok'] and result['revoked']==1
    assert market.query_df('SELECT * FROM stock_suspension').empty
    assert not market.query_df("SELECT * FROM data_update_log WHERE source='review:outside_lifetime'").empty


def test_suspension_review_stops_after_repeated_provider_failure(market):
    from backend.common.exceptions import DataSourceError
    from backend.storage.repository import MarketRepository
    market.execute("INSERT INTO stock_suspension(code,trade_date) SELECT i::VARCHAR||'.SZ',DATE '2017-01-03' FROM range(5) t(i)")
    ing=IngestionService.__new__(IngestionService)
    ing.c,ing.repo=market,MarketRepository(market)
    calls=[]
    def fail(*args,**kwargs):
        calls.append(args)
        raise DataSourceError('offline')
    ing._fetch_st_status_rows=fail
    result=ing.review_suspensions()
    assert len(calls)==3 and result['unverified']==5 and len(result['deferred_codes'])==2
