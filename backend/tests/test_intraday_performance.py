"""固定源响应经过真实修复入口，比较数据库开销与处理吞吐，不访问开发行情库。"""

import json
import os
import time
from datetime import date

import pytest

from backend.config.settings import Settings
from backend.datasource.observability import RequestTracker, observe_work, record
from backend.services import async_task, intraday_archive, intraday_source
from backend.services.intraday_archive import IntradayArchiveService
from backend.services.intraday_source import IntradaySourceService
from backend.tests.test_intraday_archive import DAY, Context, Windows, window
from backend.tests.test_intraday_archive import db as db  # noqa: PLC0414
from backend.tests.test_intraday_quotes import _frame, _Redis
from backend.tests.test_intraday_source import request_settings as request_settings  # noqa: PLC0414


@pytest.mark.parametrize("count", [64, pytest.param(
    1000, marks=pytest.mark.skipif(not os.getenv("INTRADAY_SCALE_STOCKS"),
                                 reason="显式千股修复规模门禁"),
)])
def test_fixed_response_repair_cost(db, monkeypatch, count):
    monkeypatch.setattr(intraday_archive, "configured_benchmark_codes", list)
    codes = [f"{601000 + index:06d}.SH" for index in range(count)]
    db.executemany("INSERT INTO stock_basic(code,name,list_date) VALUES (?,?,?)",
                   [(code, code, DAY) for code in codes])
    db.executemany("INSERT INTO daily_bar(code,trade_date,close) VALUES (?,?,3.6)",
                   [(code, DAY) for code in codes])
    IntradayArchiveService(db, quotes=Windows([window(rows=10)])).collect({"codes": codes})
    cfg = Settings()
    cfg.datasource.update_concurrency = 4
    monkeypatch.setattr(intraday_archive, "get_effective_settings", lambda: cfg)
    monkeypatch.setattr(async_task, "get_client", lambda: db)
    monkeypatch.setattr("backend.services.ingest.IngestionService", lambda: None)
    frames = {"sina": _frame(date.fromisoformat(DAY), rows=10), "ths": _frame()}

    class Transport:
        def get_intraday_1m(self, code, provider, **kwargs):
            record(requests=1, network_seconds=0.001)
            return frames[provider].copy()

    cache = _Redis()
    monkeypatch.setattr(intraday_source, "IntradaySourceService", lambda **kwargs:
                        IntradaySourceService(redis_client=cache, source_factory=Transport, **kwargs))
    calls = {"query": 0, "execute": 0}
    for name, key in (("query_df", "query"), ("execute", "execute")):
        original = getattr(db, name)

        def counted(*args, _original=original, _key=key, **kwargs):
            calls[_key] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(db, name, counted)
    ctx = Context()
    ctx.request_tracker = RequestTracker()
    started = time.monotonic()
    with observe_work(ctx.request_tracker, state="coordinator"):
        result = async_task._h_fix({"issue_type": "intraday_partial"}, ctx)
    metrics = ctx.request_tracker.snapshot(ctx.checkpoint)
    print(json.dumps({"stocks": count, "elapsed_sec": round(time.monotonic() - started, 3),
                      **calls, "requests": metrics["requests"],
                      "resolved": result["resolved"]}), flush=True)
    assert result["ok"] and result["resolved"] == count
    assert metrics["requests"] == count * 2
    # 旧逐股多次扫描超过26次读查询；上限留有余量，但应拒绝重新引入同根因重复复检。
    assert calls["query"] <= count * 17 + 64
    assert db.query_df("SELECT count(*) FROM stock_intraday_bar WHERE code IN "
                       "(SELECT unnest(?::VARCHAR[]))", [codes]).iloc[0, 0] == count * 240
