"""真实任务运行态和历史大表中的修复规模回归；仅固定外部估值响应。"""

import json
import os
import resource
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.config.settings import Settings
from backend.datasource.base import check_thread_cancel
from backend.services import async_task, ingest
from backend.services.async_task import AsyncTaskService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.repository import MarketRepository
from backend.storage.task_runtime import PostgresTaskRuntimeClient


def measure_history_repair(root, monkeypatch, *, universe, days, targets=64, http=False,
                           kind="capital_gap"):
    """三张事实表同规模，真实创建任务并等终态；设置两路 SQL 线程限制本机竞争。"""
    from backend.storage import task_runtime
    monkeypatch.setattr(task_runtime, "_backend_cache", "postgres")
    monkeypatch.setenv("AI_STOCKS_TASK_STORAGE_BACKEND", "postgres")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with DuckDBClient(str(root / "scale.duckdb")) as client:
        reuse = (root / "seeded").exists()
        init_db(client)
        client.execute("SET threads=2")
        client.execute("SET memory_limit='3GB'")
        client.execute(
            "CREATE TEMP TABLE scale_dates AS SELECT d::DATE trade_date FROM "
            "generate_series(DATE '2009-01-01',DATE '2026-01-01',INTERVAL 1 DAY) t(d) "
            "WHERE isodow(d)<=5 ORDER BY d LIMIT ?", [days],
        )
        if not reuse:
            client.execute(
                "INSERT INTO stock_basic(code,name,list_date,price_limit_pct) "
                "SELECT (600000+i)::VARCHAR||'.SH','规模测试',DATE '2009-01-01',0.1 "
                "FROM range(?) t(i)", [universe],
            )
            client.execute(
                "INSERT INTO daily_bar(code,trade_date,close,adj_factor,adj_factor_clean) "
                "SELECT code,trade_date,10,1,1 FROM stock_basic CROSS JOIN scale_dates ORDER BY code,trade_date"
            )
            client.execute(
                "INSERT INTO stock_share_capital_daily(code,trade_date,total_share,float_share,"
                "total_source,float_source,total_effective_date,float_effective_date) "
                "SELECT code,trade_date,100,80,'eastmoney_daily','eastmoney_daily',trade_date,trade_date "
                "FROM daily_bar"
            )
            client.execute(
                "INSERT INTO daily_metrics(code,trade_date,total_mv,float_mv,total_mv_source,"
                "float_mv_source,reported_total_mv,reported_float_mv,reported_total_mv_source,"
                "reported_float_mv_source,reported_total_close,reported_float_close) "
                "SELECT code,trade_date,1000,800,'computed:eastmoney_daily','computed:eastmoney_daily',"
                "1000,800,'eastmoney_daily','eastmoney_daily',10,10 FROM daily_bar"
            )
            client.execute("CHECKPOINT")
            (root / "seeded").write_text(f"{universe}:{days}")
        else:
            assert (root / "seeded").read_text() == f"{universe}:{days}"
            client.execute("DELETE FROM data_quality_issue")
            client.execute("DELETE FROM data_update_log")
        dates = client.query_df("SELECT trade_date FROM scale_dates ORDER BY trade_date").trade_date.dt.date
        end = dates.max()
        codes = [f"{600000+i}.SH" for i in range(min(targets, universe))]
        if reuse:
            # 外部前后对照重用相同大表，重置目标事实与投影，避免已修复输入影响比较。
            client.execute(
                "UPDATE daily_metrics SET total_mv=1000,float_mv=800,reported_total_mv=1000,"
                "reported_float_mv=800,total_mv_source='computed:eastmoney_daily',"
                "float_mv_source='computed:eastmoney_daily',reported_total_close=10,"
                "reported_float_close=10 WHERE code IN (SELECT unnest(?::VARCHAR[]))", [codes],
            )
            client.execute(
                "UPDATE stock_basic SET total_share=NULL,float_share=NULL,total_share_date=NULL,"
                "float_share_date=NULL WHERE code IN (SELECT unnest(?::VARCHAR[]))", [codes],
            )
        client.execute("INSERT INTO trade_calendar SELECT trade_date,TRUE FROM scale_dates "
                       "ON CONFLICT DO NOTHING")
        if kind == "history_data_gap":
            client.execute(
                "DELETE FROM daily_bar WHERE trade_date=? AND code IN (SELECT unnest(?::VARCHAR[]))",
                [end, codes],
            )
        client.execute(
            "UPDATE daily_metrics SET total_mv=NULL,float_mv=NULL,reported_total_mv=NULL,"
            "reported_float_mv=NULL WHERE trade_date=? AND code IN (SELECT unnest(?::VARCHAR[]))",
            [end, codes],
        )
        ids = client.query_df(
            "INSERT INTO data_quality_issue(id,code,issue_type,status,detail) "
            "SELECT nextval('seq_quality_issue'),unnest(?::VARCHAR[]),?,'open','{}' "
            "RETURNING id", [codes, kind],
        ).id.tolist()
        client.execute("CHECKPOINT")
        calls, merges = [], []
        lock = threading.Lock()

        class Source:
            name = "akshare"

            def get_valuation(self, code, start, end):
                check_thread_cancel()
                with lock:
                    calls.append(code)
                frame = pd.DataFrame({"code": code, "trade_date": dates,
                                      "total_share": 100., "float_share": 80.,
                                      "total_mv": 1000., "float_mv": 800., "valuation_close": 10.})
                self._last_valuation_prices = code, dict.fromkeys(dates, 10.)
                return frame[frame.trade_date.between(start, end)]

        service = ingest.IngestionService.__new__(ingest.IngestionService)
        service.s, service.c, service.repo = Settings(), client, MarketRepository(client)
        service.s.datasource.update_concurrency = 4
        service.src = Source()
        service._bao = None
        def daily(code, start, end, *_args, **_kwargs):
            frame = pd.DataFrame({"code": code, "trade_date": dates, "open": 10., "high": 10.,
                                  "low": 10., "close": 10., "pre_close": 10., "volume": 100,
                                  "amount": 1000., "adj_factor": 1., "total_share": 100.,
                                  "float_share": 80., "turnover_rate": 1.})
            return frame[frame.trade_date.between(start, end)], "akshare"
        def status(code, start, end, **_kwargs):
            frame = pd.DataFrame({"trade_date": dates, "is_st": False, "trade_status": 1})
            return SimpleNamespace(name="baostock"), frame[frame.trade_date.between(start, end)]
        service._fetch_daily_with_fallback = daily
        service._fetch_st_status_rows = status
        service._source_for = lambda *_: Source()
        local = threading.local()
        def thread_source(*_args):
            if not hasattr(local, "source"):
                local.source = Source()
            return local.source
        service._thread_source = thread_source
        from backend.services.share_capital import ShareCapitalService
        merge = ShareCapitalService.merge
        def merged(self, frame, *args, **kwargs):
            merges.append(frame.code.nunique())
            return merge(self, frame, *args, **kwargs)
        monkeypatch.setattr(ShareCapitalService, "merge", merged)
        monkeypatch.setattr(ingest, "IngestionService", lambda *_: service)
        monkeypatch.setattr(async_task, "get_client", lambda: client)
        runtime = AsyncTaskService(PostgresTaskRuntimeClient(), market_client=client)
        transport, headers = None, {}
        if http:
            from fastapi.testclient import TestClient

            from backend.api import data_tasks
            from backend.auth.jwt_tokens import issue_access
            from backend.main import create_app
            from backend.storage.pg_client import get_pg_client
            monkeypatch.setattr(data_tasks, "AsyncTaskService", lambda: runtime)
            version = int(get_pg_client().query_df(
                "SELECT perm_ver FROM sys_user WHERE id='admin'",
            ).iloc[0, 0])
            headers = {"Authorization": "Bearer " + issue_access("admin", "default", version)}
            transport = TestClient(create_app())  # 不启动其它调度；路由、鉴权和任务本身均为真实实现。
        started = time.monotonic()
        usage = resource.getrusage(resource.RUSAGE_SELF)
        started_cpu = usage.ru_utime + usage.ru_stime
        if transport is None:
            tid = runtime.create("fix", {"issue_ids": ids})
        else:
            response = transport.post("/api/data/tasks", headers=headers,
                                      json={"task_type": "fix", "params": {"issue_ids": ids}})
            assert response.status_code == 200, response.text
            tid = response.json()["data"]["task_id"]
        deadline = started + 1500  # 与单个 CI job 的30分钟上限保持有界。
        while True:
            if transport is None:
                task = runtime.get(tid)
            else:
                response = transport.get(f"/api/data/tasks/{tid}", headers=headers)
                assert response.status_code == 200, response.text
                task = response.json()["data"]
            if task["status"] not in ("pending", "running"):
                break
            if time.monotonic() > deadline:
                runtime.cancel(tid)
                for _ in range(600):
                    if runtime.get(tid)["status"] not in ("pending", "running"):
                        break
                    time.sleep(.05)
                raise AssertionError("规模修复在25分钟内未达到终态")
            time.sleep(.05)
        elapsed = time.monotonic() - started
        assert task["status"] == "done", task
        assert task["result"]["resolved"] == len(codes)
        facts = client.query_df(
            "SELECT count(*) n,sum(total_mv) total_mv,sum(float_mv) float_mv,"
            "sum(reported_total_mv) reported_total_mv,sum(reported_float_mv) reported_float_mv "
            "FROM daily_metrics"
        ).iloc[0].to_dict()
        assert facts == {"n": universe * days, "total_mv": universe * days * 1000.,
                         "float_mv": universe * days * 800.,
                         "reported_total_mv": universe * days * 1000.,
                         "reported_float_mv": universe * days * 800.}
        assert len(calls) == len(codes) and set(calls) == set(codes)
        usage = resource.getrusage(resource.RUSAGE_SELF)
        metrics = task["result"].get("request_runtime", {})
        result = {"repair_kind": kind, "universe": universe, "days": days, "rows_per_fact_table": universe * days,
                  "repair_targets": len(codes), "source_calls": len(calls),
                  "seconds": round(elapsed, 3), "db_queries": metrics.get("db_queries"),
                  "db_execute_seconds": metrics.get("db_execute_seconds"),
                  "merge_calls": len(merges), "largest_merge_stocks": max(merges),
                  "resolved": task["result"]["resolved"], "facts": facts,
                  "cpu_seconds": round(usage.ru_utime + usage.ru_stime - started_cpu, 3),
                  "peak_rss_mb": round(usage.ru_maxrss / (1024**2 if sys.platform == "darwin" else 1024), 1)}
        print("REPAIR_HISTORY_SCALE " + json.dumps(result, ensure_ascii=False))
        return result


@pytest.mark.parametrize("kind", ["capital_gap", "history_data_gap"])
def test_repair_batch_with_background_history(tmp_path, monkeypatch, kind):
    result = measure_history_repair(tmp_path, monkeypatch, universe=40, days=120, targets=16,
                                    http=True, kind=kind)
    assert result["largest_merge_stocks"] > 1
    assert result["merge_calls"] < result["repair_targets"]


@pytest.mark.skipif(not os.getenv("STOCK_INGEST_SCALE_STOCKS"), reason="显式历史大表规模门禁")
@pytest.mark.parametrize("kind", ["capital_gap", "history_data_gap"])
def test_full_history_repair_scale(tmp_path, monkeypatch, kind):
    universe = int(os.environ["STOCK_INGEST_SCALE_STOCKS"])
    result = measure_history_repair(tmp_path, monkeypatch, universe=universe, days=3600, kind=kind)
    assert result["largest_merge_stocks"] > 1
    assert result["merge_calls"] < result["repair_targets"]
    # 查询数量与目标批次数相关，不能回退至每股几十次的完整历史查询。
    assert result["db_queries"] < result["repair_targets"] * 35
