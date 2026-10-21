"""启动脚本文件日志：真实管道、滚动、恢复及清理，不访问应用数据库。"""

from __future__ import annotations

import gzip
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from scripts import service_logs as logs


def _policy(**overrides) -> logs.LogPolicy:
    return logs.LogPolicy(**{
        "max_bytes": 100,
        "retention_days": 30,
        "archive_bytes": 10_000,
        **overrides,
    })


def _contents(path: Path) -> bytes:
    archives = sorted((path.parent / "archive").glob(f"{path.stem}.*.gz"))
    return b"".join(gzip.decompress(p.read_bytes()) for p in archives) + path.read_bytes()


def _wait_for(predicate, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "日志收集器未在期限内完成操作"
        time.sleep(0.02)


def test_rollover_is_lossless_for_large_output_and_restart(tmp_path: Path) -> None:
    path = tmp_path / "backend.log"
    payload = "中文异常日志\n".encode() * 300
    first = logs.RollingLog(path, _policy(archive_bytes=100_000))
    try:
        first.write(payload)
        assert path.stat().st_size <= 100
    finally:
        first.close()
    second = logs.RollingLog(path, _policy(archive_bytes=100_000))
    try:
        second.write(b"after restart\n")
        assert _contents(path) == payload + b"after restart\n"
    finally:
        second.close()


def test_idle_midnight_rollover_and_existing_file_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = datetime(2026, 10, 20, 23, 59, tzinfo=logs.LOCAL_TZ)
    monkeypatch.setattr(logs, "now_local", lambda: current)
    path = tmp_path / "frontend.log"
    path.write_bytes(b"previous run\n")
    stamp = (current - timedelta(days=1)).timestamp()
    os.utime(path, (stamp, stamp))
    writer = logs.RollingLog(path, _policy())
    try:
        assert list(writer.archive_dir.glob("frontend.2026-10-19.*.log.gz"))
        writer.write(b"before midnight\n")
        current += timedelta(minutes=2)
        writer.tick()
        assert path.read_bytes() == b""
        assert list(writer.archive_dir.glob("frontend.2026-10-20.*.log.gz"))
        writer.write(b"after midnight\n")
        assert _contents(path) == b"previous run\nbefore midnight\nafter midnight\n"
    finally:
        writer.close()


def test_cleanup_limits_age_and_capacity_without_touching_other_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = datetime(2026, 10, 21, tzinfo=logs.LOCAL_TZ)
    monkeypatch.setattr(logs, "now_local", lambda: current)
    directory = tmp_path / "archive"
    directory.mkdir()
    old = directory / "frontend.2026-09-01.000001.log.gz"
    oldest = directory / "frontend.2026-10-19.000001.log.gz"
    newest = directory / "frontend.2026-10-20.000001.log.gz"
    unrelated = directory / "frontend-5181.2026-09-01.000001.log.gz"
    unknown = directory / "frontend.notes.gz"
    for path in (old, oldest, newest, unrelated, unknown):
        path.write_bytes(gzip.compress(b"preserved log"))
    writer = logs.RollingLog(
        tmp_path / "frontend.log", _policy(archive_bytes=newest.stat().st_size),
    )
    try:
        assert not old.exists()
        assert not oldest.exists()
        assert newest.exists()
        assert unrelated.exists() and unknown.exists()
    finally:
        writer.close()


def test_recover_uncompressed_archive_and_replace_partial_gzip(tmp_path: Path) -> None:
    directory = tmp_path / "archive"
    directory.mkdir()
    raw = directory / f"backend.{logs.now_local().date()}.000001.log"
    raw.write_bytes(b"crash interrupted compression\n")
    partial = raw.with_suffix(".log.gz.tmp")
    partial.write_bytes(b"partial gzip")
    writer = logs.RollingLog(tmp_path / "backend.log", _policy())
    try:
        assert not raw.exists() and not partial.exists()
        assert gzip.decompress(raw.with_suffix(".log.gz").read_bytes()) == (
            b"crash interrupted compression\n"
        )
    finally:
        writer.close()


def test_large_existing_log_does_not_require_startup_compression(tmp_path: Path) -> None:
    path = tmp_path / "backend.log"
    path.write_bytes(b"existing log" * 100)
    writer = logs.RollingLog(path, _policy(), defer_compression=True)
    try:
        assert path.read_bytes() == b""
        raw = list(writer.archive_dir.glob("*.log"))
        assert len(raw) == 1 and raw[0].read_bytes() == b"existing log" * 100
        writer.maintain()
        assert _contents(path) == b"existing log" * 100
    finally:
        writer.close()


def test_compression_failure_keeps_raw_log_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = logs.RollingLog(tmp_path / "backend.log", _policy(max_bytes=500))
    compress = writer._compress

    def fail(path):
        raise OSError("simulated compressor failure")

    try:
        writer.write(b"original log\n")
        monkeypatch.setattr(writer, "_compress", fail)
        writer.rotate()
        raw = list(writer.archive_dir.glob("*.log"))
        assert len(raw) == 1 and raw[0].read_bytes() == b"original log\n"
        assert "压缩失败" in writer.path.read_text()
        monkeypatch.setattr(writer, "_compress", compress)
        writer.maintain()
        assert not raw[0].exists()
        assert gzip.decompress(raw[0].with_suffix(".log.gz").read_bytes()) == b"original log\n"
    finally:
        writer.close()


def test_single_writer_lock_is_released_on_close(tmp_path: Path) -> None:
    path = tmp_path / "backend.log"
    writer = logs.RollingLog(path, _policy())
    try:
        with pytest.raises(RuntimeError, match="已有收集器"):
            logs.RollingLog(path, _policy())
    finally:
        writer.close()
    replacement = logs.RollingLog(path, _policy())
    replacement.close()


@pytest.mark.parametrize("bad", [0, -1, True, "50", 1.5])
def test_invalid_policy_is_rejected_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad,
) -> None:
    config = tmp_path / "settings.yaml"
    config.write_text(yaml.safe_dump({"logging": {"backend": {"max_file_mb": bad}}}))
    monkeypatch.setenv("AI_STOCKS_CONFIG", str(config))
    marker = tmp_path / "must-not-start"
    with pytest.raises(RuntimeError, match="必须为正整数"):
        logs.launch_logged_process(
            [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"],
            path=str(tmp_path / "backend.log"), service="backend",
        )
    assert not marker.exists()


def test_real_detached_output_rotation_idle_cleanup_and_group_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "settings.yaml"
    config.write_text(yaml.safe_dump({"logging": {
        "cleanup_interval_sec": 1,
        "backend": {"max_file_mb": 1, "retention_days": 30, "total_size_mb": 5},
    }}))
    monkeypatch.setenv("AI_STOCKS_CONFIG", str(config))
    path = tmp_path / "backend.log"
    payload_size = 2_500_000
    # 子进程模拟 reload worker：共享输出管道，父进程退出后仍可继续写入。
    script = (
        "import os, subprocess, sys, time; "
        f"os.write(1, b'x' * {payload_size}); os.write(2, b'stderr captured\\n'); "
        "subprocess.Popen([sys.executable, '-c', "
        "\"import os, time; time.sleep(.2); os.write(1,b'worker log\\\\n'); time.sleep(30)\"]); "
        "time.sleep(30)"
    )
    process = logs.launch_logged_process(
        [sys.executable, "-c", script], path=str(path), service="backend",
    )
    try:
        assert os.getpgid(process.pid) == process.pid
        _wait_for(lambda: b"worker log" in path.read_bytes())
        assert path.stat().st_size <= 1024 * 1024
        assert _contents(path).startswith(b"x" * payload_size + b"stderr captured\n")
        old = path.parent / "archive" / "backend.2000-01-01.000001.log.gz"
        old.write_bytes(gzip.compress(b"expired while idle"))
        _wait_for(lambda: not old.exists())
    finally:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)

    def released() -> bool:
        try:
            writer = logs.RollingLog(path, logs.load_policy("backend"))
        except RuntimeError:
            return False
        writer.close()
        return True

    _wait_for(released)


def test_failed_command_start_releases_collector(tmp_path: Path) -> None:
    path = tmp_path / "frontend.log"
    with pytest.raises(FileNotFoundError):
        logs.launch_logged_process(
            [str(tmp_path / "nonexistent-command")], path=str(path), service="frontend",
        )
    writer = logs.RollingLog(path, _policy())
    writer.close()


def test_launcher_exit_does_not_keep_terminal_open_or_drop_late_output(tmp_path: Path) -> None:
    path = tmp_path / "frontend.log"
    script = (
        "from scripts.service_logs import launch_logged_process; import sys; "
        "launch_logged_process([sys.executable, '-c', "
        "\"import time; time.sleep(.3); print('after launcher exit')\"], "
        f"path={str(path)!r}, service='frontend')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, timeout=5, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == b"" and result.stderr == b""
    _wait_for(lambda: path.exists() and b"after launcher exit" in path.read_bytes())


def test_collected_service_does_not_create_extra_unmanaged_application_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "settings.yaml"
    config.write_text(yaml.safe_dump({"paths": {"log_dir": str(tmp_path)}}))
    monkeypatch.setenv("AI_STOCKS_CONFIG", str(config))
    monkeypatch.setenv("AI_STOCKS_FILE_LOG", "1")
    path = tmp_path / "backend.log"
    process = logs.launch_logged_process(
        [sys.executable, "-c", ("from backend.common.logging import get_logger; "
                               "get_logger('test').warning('collected application log')")],
        path=str(path), service="backend",
    )
    assert process.wait(timeout=5) == 0
    _wait_for(lambda: b"collected application log" in path.read_bytes())
    assert not (tmp_path / "ai_stocks.log").exists()
