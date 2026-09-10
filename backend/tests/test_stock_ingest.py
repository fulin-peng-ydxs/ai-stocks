from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.scheduler.scheduler import SCHEDULABLE_TASK_TYPES
from backend.services.async_task import (
    _HANDLERS,
    TASK_CAPABILITIES,
    TASK_TYPES,
    WRITE_TASK_TYPES,
    _h_stock_ingest,
)
from backend.services.stock_ingest import normalize_stock_ingest_params


class _Ctx:
    def __init__(self):
        self.logs = []
        self.progresses = []

    def log(self, message, level="info"):
        self.logs.append((level, message))

    def progress(self, value, message):
        self.progresses.append((value, message))


def test_stock_ingest_task_registered_as_resumable_write_task():
    assert "stock_ingest" in TASK_TYPES
    assert "stock_ingest" in WRITE_TASK_TYPES
    assert _HANDLERS["stock_ingest"] is _h_stock_ingest
    assert TASK_CAPABILITIES["stock_ingest"]["can_resume"] is True
    assert "stock_ingest" in SCHEDULABLE_TASK_TYPES


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"recipe": "daily_update"}, {"recipe": "daily_update"}),
        (
            {"recipe": "daily_update", "force_current_day": True},
            {"recipe": "daily_update", "force_current_day": True},
        ),
        (
            {"recipe": "history_backfill", "codes": ["600000.SH"], "years": 5, "concurrency": 2},
            {"recipe": "history_backfill", "codes": ["600000.SH"], "years": 5, "concurrency": 2},
        ),
        (
            {"recipe": "range_refetch", "date_start": "2026-08-01"},
            {"recipe": "range_refetch", "date_start": "2026-08-01", "date_end": "2026-08-01"},
        ),
        ({"recipe": "valuation_history", "years": "3"}, {"recipe": "valuation_history", "years": 3}),
        ({"recipe": "valuation_gaps", "concurrency": 1}, {"recipe": "valuation_gaps", "concurrency": 1}),
        ({"recipe": "basic_refresh"}, {"recipe": "basic_refresh"}),
        ({"recipe": "delisted_history", "years": 10}, {"recipe": "delisted_history", "years": 10}),
        ({"recipe": "st_status_refresh"}, {"recipe": "st_status_refresh"}),
        (
            {"recipe": "st_status_refresh", "codes": ["600000.SH"], "date_start": "2026-08-01"},
            {"recipe": "st_status_refresh", "codes": ["600000.SH"],
             "date_start": "2026-08-01", "date_end": "2026-08-01"},
        ),
    ],
)
def test_normalize_stock_ingest_params_accepts_seven_safe_recipes(params, expected):
    assert normalize_stock_ingest_params(params) == expected


@pytest.mark.parametrize(
    "params",
    [
        {}, {"recipe": "unknown"}, {"recipe": "daily_update", "codes": []},
        {"recipe": "daily_update", "codes": ["600000"]}, {"recipe": "range_refetch"},
        {"recipe": "range_refetch", "date_start": "2026-08-02", "date_end": "2026-08-01"},
        {"recipe": "basic_refresh", "codes": ["600000.SH"]},
        {"recipe": "basic_refresh", "concurrency": 2},
        {"recipe": "valuation_gaps", "years": 5},
        {"recipe": "daily_update", "concurrency": 17},
        {"recipe": "daily_update", "concurrency": 0},
        {"recipe": "daily_update", "extra": True},
        {"recipe": "daily_update", "force_current_day": "true"},
        {"recipe": "history_backfill", "force_current_day": True},
        {"recipe": "st_status_refresh", "date_end": "2026-08-01"},
        {"recipe": "st_status_refresh", "concurrency": 2},
    ],
)
def test_normalize_stock_ingest_params_rejects_unsafe_combinations(params):
    with pytest.raises(ValueError):
        normalize_stock_ingest_params(params)


@pytest.mark.parametrize(
    ("params", "called"),
    [
        ({"recipe": "daily_update"}, "update"),
        ({"recipe": "history_backfill"}, "backfill"),
        ({"recipe": "range_refetch", "date_start": "2026-08-01"}, "ingest_date"),
        ({"recipe": "valuation_history"}, "ingest_valuation"),
        ({"recipe": "valuation_gaps"}, "ingest_valuation_gaps"),
        ({"recipe": "basic_refresh"}, "enrich_basic_dates"),
        ({"recipe": "delisted_history"}, "ingest_delisted"),
        ({"recipe": "st_status_refresh"}, "refresh_st_status"),
    ],
)
def test_stock_ingest_handler_dispatches_recipe(monkeypatch, params, called):
    calls = []

    class FakeIngestion:
        def update(self, **kwargs): calls.append(("update", kwargs)); return {"ok": 1, "fail": 0}
        def backfill(self, **kwargs): calls.append(("backfill", kwargs)); return {"ok": 1, "fail": 0}
        def ingest_date(self, *args, **kwargs): calls.append(("ingest_date", (args, kwargs))); return {"ok": 1, "fail": 0}
        def ingest_valuation(self, **kwargs): calls.append(("ingest_valuation", kwargs)); return {"ok": 1, "fail": 0}
        def ingest_valuation_gaps(self, **kwargs): calls.append(("ingest_valuation_gaps", kwargs)); return {"ok": 1, "fail": 0}
        def enrich_basic_dates(self, **kwargs): calls.append(("enrich_basic_dates", kwargs)); return 3
        def ingest_delisted(self, **kwargs): calls.append(("ingest_delisted", kwargs)); return {"ok": 1, "fail": 0}
        def refresh_st_status(self, **kwargs): calls.append(("refresh_st_status", kwargs)); return {"ok": 1, "fail": 0}

    import backend.services.ingest as ingest_module

    monkeypatch.setattr(ingest_module, "IngestionService", FakeIngestion)
    result = _h_stock_ingest(params, _Ctx())
    assert result.get("ok") is not False
    assert called in [name for name, _ in calls]
    if params["recipe"] == "delisted_history":
        assert [name for name, _ in calls][:2] == ["enrich_basic_dates", "ingest_delisted"]


def test_stock_ingest_handler_marks_partial_failure_resumable(monkeypatch):
    import backend.services.ingest as ingest_module

    monkeypatch.setattr(
        ingest_module,
        "IngestionService",
        lambda: SimpleNamespace(update=lambda **kwargs: {"ok": 2, "fail": 1}),
    )
    result = _h_stock_ingest({"recipe": "daily_update"}, _Ctx())
    assert result["ok"] is False
    assert "可重试未完成项" in result["message"]


def test_stock_ingest_handler_forwards_recipe_parameters(monkeypatch):
    calls = []

    class FakeIngestion:
        def backfill(self, **kwargs):
            calls.append(kwargs)
            return {"ok": 1, "fail": 0}

    import backend.services.ingest as ingest_module

    monkeypatch.setattr(ingest_module, "IngestionService", FakeIngestion)
    ctx = _Ctx()
    _h_stock_ingest(
        {
            "recipe": "history_backfill",
            "codes": ["600000.SH"],
            "years": 8,
            "concurrency": 3,
        },
        ctx,
    )
    assert calls == [{
        "codes": ["600000.SH"], "years": 8, "concurrency": 3, "ctx": ctx,
    }]


def test_stock_ingest_handler_forwards_force_current_day(monkeypatch):
    calls = []

    class FakeIngestion:
        def update(self, **kwargs):
            calls.append(kwargs)
            return {"ok": 1, "fail": 0}

    import backend.services.ingest as ingest_module

    monkeypatch.setattr(ingest_module, "IngestionService", FakeIngestion)
    ctx = _Ctx()
    _h_stock_ingest({"recipe": "daily_update", "force_current_day": True}, ctx)

    assert calls == [{
        "codes": None,
        "concurrency": None,
        "force_current_day": True,
        "ctx": ctx,
    }]
