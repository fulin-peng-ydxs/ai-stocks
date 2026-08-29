"""E2E runner 后端生命周期：初始运行/停止、失败与中断契约。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "scripts" / "e2e-backend-lifecycle.sh"
CORRELATION_RUNNER = ROOT / "scripts" / "run-stock-board-correlation-e2e.sh"


def _run_helper(tmp_path: Path, *, running: bool, stop_exit: int = 0) -> subprocess.CompletedProcess[str]:
    state = tmp_path / "state"
    calls = tmp_path / "calls"
    state.write_text("running" if running else "stopped", encoding="utf-8")
    start = tmp_path / "start.sh"
    start.write_text(
        "#!/usr/bin/env bash\n"
        "set -u\n"
        "case \"$1\" in\n"
        f"  status) [[ \"$(cat '{state}')\" == running ]] && echo '后端运行中' || echo '后端未运行' ;;\n"
        f"  stop-if-idle) echo stop-if-idle >> '{calls}'; exit {stop_exit} ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    start.chmod(0o755)
    env = {**os.environ, "PROJECT_ROOT": str(tmp_path)}
    return subprocess.run(
        ["bash", "-c", f"source '{LIFECYCLE}'; stop_backend_if_running"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_initially_stopped_backend_is_not_asked_for_idle_state(tmp_path: Path) -> None:
    result = _run_helper(tmp_path, running=False)
    assert result.returncode == 0
    assert not (tmp_path / "calls").exists()


def test_initially_running_backend_is_stopped_through_idle_guard(tmp_path: Path) -> None:
    result = _run_helper(tmp_path, running=True)
    assert result.returncode == 0
    assert (tmp_path / "calls").read_text(encoding="utf-8").splitlines() == ["stop-if-idle"]


def test_idle_guard_failure_is_not_swallowed(tmp_path: Path) -> None:
    result = _run_helper(tmp_path, running=True, stop_exit=23)
    assert result.returncode == 23


def test_correlation_runner_preserves_test_failure_and_signal_cleanup_contract() -> None:
    script = CORRELATION_RUNNER.read_text(encoding="utf-8")
    assert 'local original_exit="$?"' in script
    assert 'if [[ "$original_exit" != "0" ]]; then' in script
    assert 'if [[ "$cleanup_exit" != "0" || "$restore_exit" != "0" ]]; then' in script
    assert "trap 'exit 130' INT" in script
    assert "trap 'exit 143' TERM" in script
    assert '--expected-pg-fingerprint "$pg_fingerprint"' in script
