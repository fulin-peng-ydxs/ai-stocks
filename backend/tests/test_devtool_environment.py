from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from backend.api.health import e2e_health
from backend.devtools.environment_guard import (
    require_e2e_write_enabled,
    require_local_test_environment,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("value", [None, "", "prod", "production", "staging", "typo"])
def test_debug_write_guard_fails_closed(monkeypatch, value) -> None:
    monkeypatch.delenv("AI_STOCKS_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    if value is not None:
        monkeypatch.setenv("AI_STOCKS_ENV", value)

    with pytest.raises(RuntimeError, match="拒绝执行调试数据操作"):
        require_local_test_environment()


@pytest.mark.parametrize("value", ["dev", "development", "local", "test", "testing"])
def test_debug_write_guard_accepts_explicit_local_or_test_environment(
    monkeypatch,
    value,
) -> None:
    monkeypatch.setenv("AI_STOCKS_ENV", value)
    assert require_local_test_environment() == value


def test_e2e_write_guard_requires_dedicated_switch(monkeypatch) -> None:
    monkeypatch.setenv("AI_STOCKS_ENV", "test")
    monkeypatch.delenv("AI_STOCKS_E2E_WRITE", raising=False)
    with pytest.raises(RuntimeError, match="AI_STOCKS_E2E_WRITE=1"):
        require_e2e_write_enabled()

    monkeypatch.setenv("AI_STOCKS_E2E_WRITE", "1")
    assert require_e2e_write_enabled() == "test"


def test_e2e_health_only_exposes_fingerprint_in_explicit_write_environment(
    monkeypatch,
) -> None:
    monkeypatch.delenv("AI_STOCKS_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("AI_STOCKS_E2E_WRITE", raising=False)
    assert e2e_health().code == 403

    monkeypatch.setenv("AI_STOCKS_ENV", "dev")
    monkeypatch.setenv("AI_STOCKS_E2E_WRITE", "1")
    monkeypatch.setattr("backend.api.health.pg_fingerprint", lambda: "a" * 64)
    response = e2e_health()
    assert response.code == 0
    assert response.data == {"environment": "dev", "pgFingerprint": "a" * 64}


def test_shared_local_env_loader_applies_pg_overrides(tmp_path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "AI_STOCKS_ENV=test\n"
        "AI_STOCKS_PG_DSN=postgresql://fixture-host/fixture-db\n"
        "AI_STOCKS_PG_PASSWORD=fixture-password\n"
        "export AI_STOCKS_TEST_USER_PASSWORD=ExportFixturePassword123\n",
        encoding="utf-8",
    )
    env = {
        "PATH": os.environ.get("PATH", ""),
        "AI_STOCKS_ENV_FILE": str(env_file),
    }
    result = subprocess.run(
        [
            "bash",
            "-c",
            "source scripts/load-local-env.sh; "
            "load_project_local_env; "
            "printf '%s|%s|%s|%s' "
            "\"$AI_STOCKS_ENV\" \"$AI_STOCKS_PG_DSN\" \"$AI_STOCKS_PG_PASSWORD\" "
            "\"$AI_STOCKS_TEST_USER_PASSWORD\"",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == (
        "test|postgresql://fixture-host/fixture-db|fixture-password|"
        "ExportFixturePassword123"
    )


def test_playwright_npm_entry_reuses_shared_local_env_loader() -> None:
    package = json.loads(
        (PROJECT_ROOT / "frontend/package.json").read_text(encoding="utf-8")
    )
    assert package["scripts"]["test:e2e"] == "../scripts/run-playwright.sh"
    assert package["scripts"]["test:e2e:ui"] == "../scripts/run-playwright.sh --ui"

    launcher = (PROJECT_ROOT / "scripts/run-playwright.sh").read_text(encoding="utf-8")
    assert 'source "$PROJECT_ROOT/scripts/load-local-env.sh"' in launcher
    assert "load_project_local_env" in launcher


@pytest.mark.parametrize("value", [None, "unknown", "production"])
def test_dev_users_list_guard_fails_closed_before_database_access(
    tmp_path,
    value,
) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "" if value is None else f"AI_STOCKS_ENV={value}\n",
        encoding="utf-8",
    )
    env = {
        "PATH": os.environ.get("PATH", ""),
        "AI_STOCKS_ENV_FILE": str(env_file),
    }
    result = subprocess.run(
        ["./start.sh", "dev-users", "--list"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "拒绝执行调试数据操作" in f"{result.stdout}\n{result.stderr}"
