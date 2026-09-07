from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.devtools.backend_runtime_state import (
    build_restore_environment,
    build_runtime_state,
    restore_runtime_state,
    snapshot_runtime_state,
)


def runtime_state(tmp_path: Path, environment: dict[str, str]) -> dict:
    env_file = tmp_path / ".env.local"
    env_file.write_text("AI_STOCKS_ENV=dev\n", encoding="utf-8")
    return build_runtime_state(
        mode="dev",
        pid=123,
        env_file=str(env_file),
        python_command="python",
        environment=environment,
        fingerprint="a" * 64,
    )


def test_restore_rejects_changed_env_file_or_extra_project_environment(tmp_path: Path) -> None:
    environment = {
        "AI_STOCKS_ENV": "dev",
        "AI_STOCKS_JWT_SECRET": "secret-a",
    }
    state = runtime_state(tmp_path, environment)
    env_file = Path(state["envFile"])
    env_file.write_text("AI_STOCKS_ENV=test\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="环境文件在测试期间发生变化"):
        build_restore_environment(state, current_environment=environment)

    env_file.write_text("AI_STOCKS_ENV=dev\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="额外 AI_STOCKS 环境变量"):
        build_restore_environment(
            state,
            current_environment={**environment, "AI_STOCKS_JWT_SECRET": "secret-b"},
        )


def test_restore_recovers_safe_flags_without_storing_other_plaintext(tmp_path: Path) -> None:
    environment = {
        "AI_STOCKS_ENV": "local",
        "AI_STOCKS_DUCKDB_READ_ONLY": "1",
        "AI_STOCKS_JWT_SECRET": "must-not-be-persisted",
    }
    state = runtime_state(tmp_path, environment)

    assert "must-not-be-persisted" not in json.dumps(state)
    restored = build_restore_environment(
        state,
        current_environment={
            **environment,
            "AI_STOCKS_ENV": "dev",
            "AI_STOCKS_DUCKDB_READ_ONLY": "0",
        },
    )
    assert restored["AI_STOCKS_ENV"] == "local"
    assert restored["AI_STOCKS_DUCKDB_READ_ONLY"] == "1"


def test_snapshot_rejects_stale_pid_before_writing_target(tmp_path: Path) -> None:
    source = tmp_path / "runtime.json"
    target = tmp_path / "snapshot.json"
    source.write_text(json.dumps(runtime_state(tmp_path, {})), encoding="utf-8")

    with pytest.raises(RuntimeError, match="当前进程不匹配"):
        snapshot_runtime_state(source=source, target=target, expected_pid=456)

    assert not target.exists()


def test_restore_force_stops_backend_when_pg_fingerprint_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "snapshot.json"
    runtime_file = tmp_path / "runtime.json"
    start_script = tmp_path / "start.sh"
    state = {"mode": "dev", "pgFingerprint": "a" * 64}
    calls: list[list[str]] = []

    monkeypatch.setattr(
        "backend.devtools.backend_runtime_state.load_runtime_state",
        lambda path: state if path == source else {"pgFingerprint": "b" * 64},
    )
    monkeypatch.setattr(
        "backend.devtools.backend_runtime_state.build_restore_environment",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        "backend.devtools.backend_runtime_state.subprocess.run",
        lambda command, **kwargs: calls.append([str(value) for value in command]),
    )

    with pytest.raises(RuntimeError, match="PostgreSQL 指纹"):
        restore_runtime_state(
            source=source,
            start_script=start_script,
            runtime_file=runtime_file,
        )

    assert calls == [
        [str(start_script), "dev"],
        [str(start_script), "stop", "--force"],
    ]
