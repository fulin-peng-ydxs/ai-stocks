"""股票/指数共享采集与质量闭环，以及全局起点前移、防丢失回退。"""

import json
from datetime import datetime

import pandas as pd
import pytest

from backend.services import eod_dates
from backend.services.intraday_archive import IntradayArchiveService
from backend.services.intraday_contract import candidate_rank, normalize_intraday_params
from backend.services.intraday_evidence import IntradayEvidence, window_evidence
from backend.services.intraday_source import IntradaySourceService
from backend.tests.test_intraday_archive import CODE, DAY, Windows, window
from backend.tests.test_intraday_archive import db as archive_db
from backend.tests.test_intraday_source import (
    request_settings,  # noqa: F401 -- 注册公共请求策略夹具
)

INDEX = "000001.SH"

# 使用既有内存行情夹具，不复制建库和股票数据准备。
db = archive_db


@pytest.fixture(autouse=True)
def indices(monkeypatch):
    monkeypatch.setattr(
        "backend.services.intraday_archive.configured_benchmark_codes", lambda: [INDEX]
    )


def index_day(db, day=DAY):
    db.execute("INSERT INTO index_bar(index_code,trade_date,close) VALUES (?,?,3800)", [INDEX, day])


def test_default_collects_both_types_and_index_uses_240_minutes(db):
    index_day(db)
    service = IntradayArchiveService(db, quotes=Windows([window(provider="ths")]))
    result = service.collect()
    assert result["ok"] and (result["stocks"], result["indices"]) == (1, 1)
    assert result["inserted"] == 2 and service.issues() == []
    summary = service.summary()
    assert (summary["stocks"], summary["indices"]) == (1, 1)
    assert summary["latest_complete_indices"] == 1
    assert db.query_df("SELECT count(*) n FROM stock_basic WHERE code=?", [INDEX]).iloc[0].n == 0
    # 同样的238点对个股完整，对指数仍缺14:58/14:59，整日候选不能混源拼接。
    missing = window(provider="sina")
    missing["rows"] = [r for r in missing["rows"] if r[0][11:16] not in ("14:58", "14:59")]
    assert candidate_rank(missing["rows"], "sina", CODE)[0]
    assert not candidate_rank(missing["rows"], "sina", INDEX)[0]
    db.execute(
        "DELETE FROM stock_intraday_bar WHERE code=? AND strftime(timestamp,'%H:%M')='14:59'",
        [INDEX],
    )
    issues = service.sync()
    assert issues["intraday_partial"] == issues["intraday_invalid"] == 1
    issue = next(i for i in service.issues() if i["issue_type"] == "intraday_partial")
    assert issue["code"] == INDEX
    assert json.loads(issue["detail"])["coverage"]["required_count"] == 240


def test_index_first_start_aligns_existing_stocks_and_keeps_earlier_source_rows_out(db):
    IntradayArchiveService(db, quotes=Windows([window()])).collect({"asset_type": "stock"})
    index_day(db)
    index_day(db, "2026-09-09")
    db.execute("INSERT INTO trade_calendar VALUES ('2026-09-09',true)")
    source = Windows([window("2026-09-09", "ths"), window(provider="ths")])
    service = IntradayArchiveService(db, quotes=source)
    assert service.collect({"asset_type": "index"})["inserted"] == 1
    assert str(service.global_start()) == DAY
    assert (
        db.query_df("SELECT min(trade_date) d FROM stock_intraday_bar WHERE code=?", [INDEX])
        .iloc[0]
        .d.date()
        .isoformat()
        == DAY
    )


def test_successful_earlier_backfill_expands_every_subject_and_deletion_does_not_retreat(db):
    index_day(db)
    service = IntradayArchiveService(db, quotes=Windows([window(provider="ths")]))
    service.collect()
    db.execute("UPDATE stock_basic SET list_date='2026-09-01'")
    db.execute("INSERT INTO trade_calendar VALUES ('2026-09-09',true)")
    db.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES (?,'2026-09-09',3.6)", [CODE])
    index_day(db, "2026-09-09")
    service.quotes = Windows([window("2026-09-09", "ths")])
    service.collect({"mode": "refetch", "codes": [INDEX], "date_start": "2026-09-09"})
    assert str(service.global_start()) == "2026-09-09"
    # 只补指数也必须立即为未补的股票产生历史整日缺失台账。
    gaps = db.query_df(
        "SELECT code FROM data_quality_issue WHERE issue_type='intraday_gap' AND status='open'"
    )
    assert CODE in gaps.code.tolist()
    db.execute("DELETE FROM stock_intraday_bar WHERE trade_date='2026-09-09'")
    db.execute("DELETE FROM stock_intraday_coverage WHERE trade_date='2026-09-09'")
    fresh = IntradayArchiveService(db)
    assert str(fresh.global_start()) == "2026-09-09"
    assert {r["code"] for r in fresh.issues() if r["issue_type"] == "intraday_gap"} == {CODE, INDEX}


def test_index_today_partial_stays_open_and_later_whole_day_replaces_it(db, monkeypatch):
    index_day(db)
    partial = window(provider="ths")
    partial["rows"] = partial["rows"][:-1]
    source = Windows([partial])
    service = IntradayArchiveService(db, quotes=source)
    assert service.collect({"asset_type": "index"})["partial"] == 1
    assert not service.clean("intraday_partial", INDEX, DAY)
    source.windows = [window(provider="ths")]
    service.collect({"asset_type": "index"})
    assert service.clean("intraday_partial", INDEX, DAY)
    # 15:30之前即使源端已有当天全量，也不能写入当天。
    monkeypatch.setattr(
        eod_dates, "shanghai_now", lambda: datetime(2026, 9, 10, 15, tzinfo=eod_dates.SHANGHAI)
    )
    with pytest.raises(ValueError, match="尚未收盘"):
        service.write_day(INDEX, DAY, [window(provider="ths")])


def test_index_evidence_and_source_selection_use_index_rules(db, monkeypatch):
    index_day(db)
    f = window(provider="ths")
    f["code"] = INDEX
    f["rows"] = [r for r in f["rows"] if r[0][11:16] != "14:59"]
    assert window_evidence(f)["missing_by_day"][DAY] == ["14:59"]
    decision = IntradayEvidence(db).assess(INDEX, DAY, ["14:59"], {}, allow_fallback=False)
    assert decision["providers"] == ["ths"]
    calls = []
    svc = IntradaySourceService(redis_client=object(), source_factory=lambda: object())
    monkeypatch.setattr(
        svc,
        "_fetch_ths_years",
        lambda source, code, dates: (
            calls.append(code)
            or pd.DataFrame(
                [[r[0], *r[1:]] for r in window(provider="ths")["rows"]],
                columns=["timestamp", "open", "high", "low", "close", "volume", "amount"],
            ),
            [],
        ),
    )
    assert svc.fetch_window(INDEX, [DAY])["source"] == "ths"
    assert calls == [INDEX]


def test_selected_scope_validates_type_without_silent_expansion(db):
    index_day(db)
    with pytest.raises(ValueError, match="采集对象"):
        IntradayArchiveService(db)._scope(
            normalize_intraday_params({"asset_type": "stock", "codes": [INDEX]}), None
        )
    assert normalize_intraday_params({"asset_type": "index"})["asset_type"] == "index"


def test_quality_list_and_batch_share_index_filter(db, monkeypatch):
    from backend.api.data_admin import _quality_asset_clause, _quality_open_issue_ids, quality

    index_day(db)
    monkeypatch.setattr("backend.api.data_admin.get_client", lambda: db)
    monkeypatch.setattr(
        "backend.services.market_benchmark.configured_benchmark_codes", lambda: [INDEX]
    )
    IntradayArchiveService(db, quotes=Windows([])).collect()
    response = quality(asset_type="index")
    assert response.data["list"] and all(r["code"] == INDEX for r in response.data["list"])
    assert response.data["list"][0]["name"] == "上证指数"
    ids, _ = _quality_open_issue_ids(db, {"asset_type": "index"})
    assert set(ids) == {r["id"] for r in response.data["list"]}
    assert _quality_asset_clause("stock")[1] == []


def test_index_repair_uses_existing_fix_task_and_closes_ledger(db, monkeypatch):
    from backend.services import async_task, intraday_source
    from backend.tests.test_intraday_archive import Context

    index_day(db)
    service = IntradayArchiveService(db, quotes=Windows([window(provider="ths", rows=10)]))
    service.collect({"asset_type": "index"})
    issue_id = int(
        db.query_df(
            "SELECT id FROM data_quality_issue WHERE code=? AND issue_type='intraday_partial'",
            [INDEX],
        ).iloc[0, 0]
    )
    monkeypatch.setattr(async_task, "get_client", lambda: db)
    monkeypatch.setattr("backend.services.ingest.IngestionService", lambda: None)
    source = Windows([window(provider="ths")])
    monkeypatch.setattr(intraday_source, "IntradaySourceService", lambda **kwargs: source)
    context = Context()
    result = async_task._h_fix({"issue_id": issue_id}, context)
    assert result["ok"] and result["resolved"] == 1
    assert source.calls[0][0] == INDEX
    assert source.calls[0][2]["providers"][0] == "ths"
    assert (
        db.query_df("SELECT status FROM data_quality_issue WHERE id=?", [issue_id]).iloc[0, 0]
        == "resolved"
    )
