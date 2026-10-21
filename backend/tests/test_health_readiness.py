"""Readiness must inspect persisted data, while idle-task checks remain usable on degradation."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.api import health as health_api
from backend.common.exceptions import StorageError

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("failure", [None, "duckdb", "postgres", "redis", "runtime"])
def test_health_reports_real_dependency_readiness(monkeypatch, failure):
    class Reader:
        db_path = Path("fixture.duckdb")

        def query_df(self, sql, **kwargs):
            # Constant expressions can still succeed on an invalidated database instance.
            if "stock_basic" in sql and failure == "duckdb":
                raise StorageError("database has been invalidated after No space left on device")
            return pd.DataFrame({"v": ["fixture-version"]})

        def stats(self):
            return {"enabled": True}

    def runtime_query(*args):
        if failure == "runtime":
            raise StorageError("runtime unavailable")
        return pd.DataFrame({"n": [0]})

    monkeypatch.setattr(health_api, "get_read_client", Reader)
    monkeypatch.setattr(health_api, "get_pg_client", lambda: SimpleNamespace(
        ping=lambda: failure != "postgres"))
    monkeypatch.setattr(health_api, "get_redis_client", lambda: SimpleNamespace(
        ping=lambda: failure != "redis"))
    monkeypatch.setattr(health_api, "task_runtime_backend", lambda: "postgres")
    monkeypatch.setattr(health_api, "get_task_runtime_client", lambda: SimpleNamespace(
        query_df=runtime_query))
    result = health_api.health()
    assert result.code == 0  # Preserve the diagnostic API envelope and safe-stop access.
    assert result.data["status"] == ("degraded" if failure else "up")
    assert result.data["duckdb_ok"] is (failure != "duckdb")
    if failure == "runtime":
        assert result.data["active_task_count"] is None


def _script(action, body):
    return subprocess.run(
        ["bash", "-c", f'''source start.sh
curl() {{ printf '%s' "$READINESS_FIXTURE"; }}
running_pid() {{ echo 12345; }}
{action}
'''],
        cwd=ROOT, env={**os.environ, "AI_STOCKS_ENV_FILE": "/dev/null",
                       "READINESS_FIXTURE": body},
        text=True, capture_output=True, check=False,
    )


@pytest.mark.parametrize("change", [
    {}, {"status": "degraded"}, {"duckdb_ok": False}, {"pg_ok": False},
    {"redis_ok": False}, {"active_task_count": None}, {"active_task_count": True},
])
def test_start_script_checks_storage_flags_even_with_http_200(change):
    data = {"status": "up", "duckdb_ok": True, "pg_ok": True, "redis_ok": True,
            "active_task_count": 0, **change}
    body = json.dumps({"code": 0, "data": data})
    result = _script("status", body)
    assert (result.returncode == 0) is (not change)
    assert ("运行中" in result.stdout) is (not change)


@pytest.mark.parametrize("body", ["<html>unavailable</html>", "{}", '{"code":5003,"data":null}'])
def test_start_script_rejects_untrusted_health_response(body):
    assert _script("backend_ready", body).returncode != 0


def test_degraded_market_does_not_prevent_safe_stop_with_trusted_idle_runtime():
    body = json.dumps({"code": 0, "data": {
        "status": "degraded", "duckdb_ok": False, "pg_ok": True,
        "redis_ok": True, "active_task_count": 0,
    }})
    assert _script("backend_ready", body).returncode != 0
    assert _script("assert_idle", body).returncode == 0
