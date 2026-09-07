"""Backend start-script task guard and explicit force semantics."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
START_SCRIPT = ROOT / "start.sh"


def _run_main(
    *args: str,
    idle_exit: int = 0,
    running: bool = True,
) -> subprocess.CompletedProcess[str]:
    quoted_args = " ".join(f"'{arg}'" for arg in args)
    running_pid = "echo 12345" if running else ":"
    command = f"""
source '{START_SCRIPT}'
running_pid() {{ {running_pid}; }}
assert_idle() {{ echo assert-idle; return {idle_exit}; }}
terminate_backend() {{ echo terminate-backend; }}
start() {{ echo start-$1; }}
main {quoted_args}
"""
    return subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env={**os.environ, "AI_STOCKS_ENV_FILE": "/dev/null"},
        text=True,
        capture_output=True,
        check=False,
    )


def test_stop_refuses_when_idle_guard_rejects() -> None:
    result = _run_main("stop", idle_exit=23)

    assert result.returncode == 23
    assert result.stdout.splitlines() == ["assert-idle"]
    assert "terminate-backend" not in result.stdout


def test_restart_refuses_when_idle_guard_rejects() -> None:
    result = _run_main("restart", idle_exit=23)

    assert result.returncode == 23
    assert result.stdout.splitlines() == ["assert-idle"]
    assert "terminate-backend" not in result.stdout
    assert "start-dev" not in result.stdout


def test_safe_stop_and_restart_check_idle_before_process_change() -> None:
    stopped = _run_main("stop")
    restarted = _run_main("restart")

    assert stopped.stdout.splitlines() == ["assert-idle", "terminate-backend"]
    assert restarted.stdout.splitlines() == [
        "assert-idle",
        "terminate-backend",
        "start-dev",
    ]


def test_stop_without_running_backend_does_not_require_health_endpoint() -> None:
    result = _run_main("stop", idle_exit=23, running=False)

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["terminate-backend"]
    assert "assert-idle" not in result.stdout


def test_force_stop_and_restart_explicitly_skip_idle_guard() -> None:
    stopped = _run_main("stop", "--force", idle_exit=23)
    restarted = _run_main("restart", "--force", idle_exit=23)

    assert stopped.returncode == 0
    assert stopped.stdout.splitlines() == ["terminate-backend"]
    assert "assert-idle" not in stopped.stdout
    assert "强制停止" in stopped.stderr
    assert restarted.returncode == 0
    assert restarted.stdout.splitlines() == ["terminate-backend", "start-dev"]
    assert "assert-idle" not in restarted.stdout
    assert "强制停止" in restarted.stderr


def test_stop_and_restart_reject_unknown_arguments() -> None:
    for action in ("stop", "restart"):
        result = _run_main(action, "--unsafe")
        assert result.returncode == 2
        assert "仅支持可选参数 --force" in result.stderr
        assert "terminate-backend" not in result.stdout
