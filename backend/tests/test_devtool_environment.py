from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from backend.api.health import e2e_health
from backend.devtools.environment_guard import (
    e2e_login_rate_bypass_enabled,
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


def test_e2e_login_rate_bypass_requires_triple_gate(monkeypatch) -> None:
    """E2E 登录限流豁免的三重门控：环境白名单 + E2E_WRITE + E2E_LOGIN_BYPASS，缺一即关。"""
    for var in ("AI_STOCKS_ENV", "ENV", "AI_STOCKS_E2E_WRITE", "AI_STOCKS_E2E_LOGIN_BYPASS"):
        monkeypatch.delenv(var, raising=False)
    # 全不设置：关
    assert e2e_login_rate_bypass_enabled() is False
    # 仅环境：关
    monkeypatch.setenv("AI_STOCKS_ENV", "dev")
    assert e2e_login_rate_bypass_enabled() is False
    # 环境 + WRITE，无 BYPASS：关
    monkeypatch.setenv("AI_STOCKS_E2E_WRITE", "1")
    assert e2e_login_rate_bypass_enabled() is False
    # 三重全开：开
    monkeypatch.setenv("AI_STOCKS_E2E_LOGIN_BYPASS", "1")
    assert e2e_login_rate_bypass_enabled() is True
    # 生产环境即使三旗标都在：环境白名单拦截，关
    monkeypatch.setenv("AI_STOCKS_ENV", "production")
    assert e2e_login_rate_bypass_enabled() is False
    # BYPASS 非精确 "1"：关
    monkeypatch.setenv("AI_STOCKS_ENV", "test")
    monkeypatch.setenv("AI_STOCKS_E2E_LOGIN_BYPASS", "true")
    assert e2e_login_rate_bypass_enabled() is False


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
            (
                "source scripts/load-local-env.sh; "
                "load_project_local_env; "
                "printf '%s|%s|%s|%s' "
                "\"$AI_STOCKS_ENV\" \"$AI_STOCKS_PG_DSN\" \"$AI_STOCKS_PG_PASSWORD\" "
                "\"$AI_STOCKS_TEST_USER_PASSWORD\""
            ),
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
    assert (
        package["scripts"]["test:e2e:trade-discipline"]
        == "../scripts/run-trade-discipline-e2e.sh"
    )

    launcher = (PROJECT_ROOT / "scripts/run-playwright.sh").read_text(encoding="utf-8")
    assert 'source "$PROJECT_ROOT/scripts/load-local-env.sh"' in launcher
    assert "load_project_local_env" in launcher


def test_trade_discipline_e2e_entry_fails_closed_without_write_gate(tmp_path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text("AI_STOCKS_ENV=test\n", encoding="utf-8")
    result = subprocess.run(
        ["./scripts/run-trade-discipline-e2e.sh"],
        cwd=PROJECT_ROOT,
        env={"PATH": os.environ.get("PATH", ""), "AI_STOCKS_ENV_FILE": str(env_file)},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "AI_STOCKS_E2E_WRITE=1" in f"{result.stdout}\n{result.stderr}"


@pytest.mark.parametrize("fingerprint", [None, "bad-fingerprint"])
def test_trade_discipline_fixture_cli_requires_valid_fingerprint(tmp_path, fingerprint) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text("AI_STOCKS_ENV=test\nAI_STOCKS_E2E_WRITE=1\n", encoding="utf-8")
    command = ["./start.sh", "e2e-trade-discipline", "cleanup"]
    if fingerprint is not None:
        command.extend(["--expected-pg-fingerprint", fingerprint])
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env={"PATH": os.environ.get("PATH", ""), "AI_STOCKS_ENV_FILE": str(env_file)},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    output = f"{result.stdout}\n{result.stderr}"
    expected = "required" if fingerprint is None else "64 位 PostgreSQL 指纹"
    assert expected in output


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
