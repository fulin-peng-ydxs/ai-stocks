"""E2E runner 后端生命周期：初始运行/停止、失败与中断契约。"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "scripts" / "e2e-backend-lifecycle.sh"
CORRELATION_RUNNER = ROOT / "scripts" / "run-stock-board-correlation-e2e.sh"
SECTOR_RUNNER = ROOT / "scripts" / "run-sector-e2e.sh"


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


@pytest.mark.parametrize(
    ("running", "playwright_exit", "cleanup_exit", "restore_exit", "stop_exit", "snapshot_exit", "expected"),
    [
        (True, 0, 0, 0, 0, 0, 0),
        (False, 0, 0, 0, 0, 0, 0),
        (True, 17, 0, 0, 0, 0, 17),
        (True, 0, 19, 0, 0, 0, 1),
        (True, 0, 0, 23, 0, 0, 1),
        (True, 17, 19, 23, 0, 0, 17),
        (True, 143, 0, 0, 0, 0, 143),
        (True, 0, 0, 0, 41, 0, 1),
        (True, 0, 0, 0, 0, 29, 1),
    ],
)
def test_sector_runner_restores_runtime_and_preserves_failures(
    tmp_path: Path,
    running: bool,
    playwright_exit: int,
    cleanup_exit: int,
    restore_exit: int,
    stop_exit: int,
    snapshot_exit: int,
    expected: int,
) -> None:
    """在独立脚本仓库执行真实 runner；不连接项目服务或数据库。"""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (tmp_path / "frontend").mkdir()
    for source in [SECTOR_RUNNER, LIFECYCLE]:
        shutil.copyfile(source, scripts / source.name)
    (scripts / "load-local-env.sh").write_text(
        "load_project_local_env() { :; }\n", encoding="utf-8"
    )
    (tmp_path / "state").write_text("running" if running else "stopped", encoding="utf-8")
    start = tmp_path / "start.sh"
    start.write_text(
        '''#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
echo "${*:-start}" >> calls
case "${1:-start}" in
  status) [[ "$(cat state)" == running ]] && echo '后端运行中' || echo '后端未运行' ;;
  assert-idle) ;;
  snapshot-runtime)
    [[ "$SNAPSHOT_EXIT" == 0 ]] || exit "$SNAPSHOT_EXIT"
    echo 'prod:original-env:read-only' > "$2" ;;
  stop-if-idle)
    [[ "$(cat state)" == running ]] || exit 31
    echo stopped > state ;;
  stop)
    [[ "$STOP_EXIT" == 0 ]] || exit "$STOP_EXIT"
    echo stopped > state ;;
  e2e-board-data)
    [[ "$AI_STOCKS_ENV_FILE" == /dev/null && "$AI_STOCKS_DUCKDB_READ_ONLY" == 0 ]]
    [[ "$(cat state)" == stopped ]] || exit 32
    if [[ "$2" == seed ]]; then touch seeded; fi
    if [[ "$2" == cleanup && -f seeded ]]; then
      rm seeded
      exit "$CLEANUP_EXIT"
    fi ;;
  restore-runtime)
    [[ "$(cat "$2")" == 'prod:original-env:read-only' ]] || exit 33
    [[ "$RESTORE_EXIT" == 0 ]] || exit "$RESTORE_EXIT"
    echo original-runtime > restored
    echo running > state ;;
  start)
    [[ "$AI_STOCKS_ENV_FILE" == /dev/null && "$AI_STOCKS_DUCKDB_READ_ONLY" == 0 ]]
    echo running > state ;;
  *) exit 34 ;;
esac
''',
        encoding="utf-8",
    )
    start.chmod(0o755)
    playwright = scripts / "run-playwright.sh"
    playwright.write_text(
        '#!/usr/bin/env bash\necho playwright >> "$PROJECT_TEST_ROOT/calls"\n'
        'if [[ "$PLAYWRIGHT_EXIT" == 143 ]]; then kill -TERM "$PPID"; exit 0; fi\n'
        'exit "$PLAYWRIGHT_EXIT"\n', encoding="utf-8"
    )
    playwright.chmod(0o755)
    env = {
        **os.environ, "AI_STOCKS_ENV": "test", "AI_STOCKS_E2E_WRITE": "1",
        "TMPDIR": str(tmp_path), "PROJECT_TEST_ROOT": str(tmp_path),
        "PLAYWRIGHT_EXIT": str(playwright_exit), "CLEANUP_EXIT": str(cleanup_exit),
        "RESTORE_EXIT": str(restore_exit), "SNAPSHOT_EXIT": str(snapshot_exit),
        "STOP_EXIT": str(stop_exit),
    }
    result = subprocess.run(
        ["bash", str(scripts / SECTOR_RUNNER.name), "--grep", "probe"],
        cwd=tmp_path, env=env, text=True, capture_output=True, check=False, timeout=10,
    )
    assert result.returncode == expected, result.stderr
    calls = (tmp_path / "calls").read_text(encoding="utf-8").splitlines()
    snapshots = list(tmp_path.glob("ai-stocks-sector-runtime.*"))
    if running and (restore_exit or stop_exit):
        assert len(snapshots) == 1
        assert snapshots[0].read_text().strip() == "prod:original-env:read-only"
    else:
        assert not snapshots
    if snapshot_exit:
        assert not any(call.startswith(("stop", "e2e-board-data")) for call in calls)
    elif stop_exit:
        assert "playwright" in calls
        assert calls.count("e2e-board-data cleanup") == 1
        assert (tmp_path / "seeded").exists()
        assert not any(call.startswith("restore-runtime ") for call in calls)
        assert (tmp_path / "state").read_text().strip() == "running"
    else:
        assert "playwright" in calls
        assert calls.count("e2e-board-data cleanup") == 2
        assert not (tmp_path / "seeded").exists()
        assert (tmp_path / "restored").exists() is (running and not restore_exit)
        assert any(call.startswith("restore-runtime ") for call in calls) is running
        if not running:
            assert "stop-if-idle" not in calls
            assert (tmp_path / "state").read_text().strip() == "stopped"
