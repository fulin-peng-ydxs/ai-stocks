"""启动脚本共用的 stdout/stderr 收集器；独立于服务进程组和开发热重载。

每个日志文件只有一个写入者，按北京时间日期/大小归档，gzip 压缩后按期限及容量清理。
仅管理当前文件名对应的归档，前端不同端口互不影响；不访问应用或数据库。
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import os
import re
import selectors
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
READ_SIZE = 64 * 1024


@dataclass(frozen=True)
class LogPolicy:
    """单个输出文件的策略；容量限制只统计归档，当前文件另受 max_bytes 限制。"""

    max_bytes: int
    retention_days: int
    archive_bytes: int
    cleanup_interval_sec: int = 300


def load_policy(service: str) -> LogPolicy:
    """只消费 YAML 基线，遵循 AI_STOCKS_CONFIG；不连接 PG 覆盖层。"""
    path = Path(os.environ.get("AI_STOCKS_CONFIG", ROOT / "config/settings.yaml"))
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or not isinstance(raw.get("logging", {}), dict):
        raise TypeError("logging 配置必须为映射")
    config = raw.get("logging", {})
    defaults = {"backend": (50, 30, 1024), "frontend": (20, 7, 200)}
    size, days, cap = defaults[service]
    values = config.get(service, {})
    if not isinstance(values, dict):
        raise TypeError(f"logging.{service} 配置必须为映射")
    settings = {
        "max_file_mb": values.get("max_file_mb", size),
        "retention_days": values.get("retention_days", days),
        "total_size_mb": values.get("total_size_mb", cap),
        "cleanup_interval_sec": config.get("cleanup_interval_sec", 300),
    }
    for key, value in settings.items():
        if type(value) is not int or value <= 0:
            raise ValueError(f"logging.{service}.{key} 必须为正整数")
    if settings["total_size_mb"] < settings["max_file_mb"]:
        raise ValueError(f"logging.{service}.total_size_mb 不得小于 max_file_mb")
    return LogPolicy(
        max_bytes=settings["max_file_mb"] * 1024 * 1024,
        retention_days=settings["retention_days"],
        archive_bytes=settings["total_size_mb"] * 1024 * 1024,
        cleanup_interval_sec=settings["cleanup_interval_sec"],
    )


def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


class RollingLog:
    """有界字节流写入器；原始归档保留到压缩原子替换成功，支持异常退出后恢复。"""

    def __init__(self, path: Path, policy: LogPolicy, *, defer_compression: bool = False):
        self.path = path.resolve()
        self.policy = policy
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.archive_dir = self.path.parent / "archive"
        self.archive_dir.mkdir(exist_ok=True)
        self.pattern = re.compile(
            rf"^{re.escape(self.path.stem)}\.(\d{{4}}-\d{{2}}-\d{{2}})"
            rf"\.(\d{{6,}}){re.escape(self.path.suffix)}(?:\.gz)?$"
        )
        # 锁文件不删除，避免旧/新收集器锁住不同 inode 后同时写同一路径。
        self.lock = self.path.with_suffix(self.path.suffix + ".lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise RuntimeError(f"日志已有收集器写入: {self.path}") from None
        self.stream = None
        try:
            self.day = (
                datetime.fromtimestamp(self.path.stat().st_mtime, LOCAL_TZ).date()
                if self.path.exists() and self.path.stat().st_size else now_local().date()
            )
            self.stream = self.path.open("ab", buffering=0)
            self.size = self.path.stat().st_size
            # 历史大文件也按原日期整体归档，启动不覆盖存量日志。
            if self.size and (self.day != now_local().date() or self.size >= policy.max_bytes):
                self.rotate(maintain=False)
            self.maintain(compress=not defer_compression)
        except BaseException:
            self.close()
            raise

    def _archives(self) -> list[Path]:
        paths = [p for p in self.archive_dir.iterdir()
                 if self.pattern.fullmatch(p.name) and p.is_file() and not p.is_symlink()]
        return sorted(paths, key=lambda p: (
            self.pattern.fullmatch(p.name)[1], int(self.pattern.fullmatch(p.name)[2]), p.suffix,
        ))

    def _compress(self, raw: Path) -> None:
        target = raw.with_suffix(raw.suffix + ".gz")
        temporary = target.with_suffix(target.suffix + ".tmp")
        try:
            with raw.open("rb") as source, gzip.open(temporary, "wb", compresslevel=1) as output:
                shutil.copyfileobj(source, output, length=READ_SIZE)
            os.replace(temporary, target)
            raw.unlink()
        finally:
            temporary.unlink(missing_ok=True)

    def rotate(self, *, maintain: bool = True) -> None:
        if not self.size:
            self.day = now_local().date()
            return
        prefix = f"{self.path.stem}.{self.day.isoformat()}."
        sequence = max(
            (int(self.pattern.fullmatch(p.name)[2]) for p in self._archives()
             if p.name.startswith(prefix)), default=0,
        ) + 1
        raw = self.archive_dir / f"{prefix}{sequence:06d}{self.path.suffix}"
        self.stream.close()
        os.replace(self.path, raw)
        self.stream = self.path.open("ab", buffering=0)
        self.day = now_local().date()
        self.size = 0
        if maintain:
            self.maintain()

    def maintain(self, *, compress: bool = True) -> None:
        """无日志输出时也定时执行；压缩失败保留原文并参与容量限制，下轮重试。"""
        for path in self._archives():
            if compress and path.suffix != ".gz":
                try:
                    self._compress(path)
                except OSError as error:
                    # 收集器不继承启动终端的文件描述符，诊断也写入受大小限制的当前文件。
                    warning = f"日志归档压缩失败，保留原文: {path.name}: {error}\n".encode()
                    warning = warning[:max(0, self.policy.max_bytes - self.size)]
                    self.stream.write(warning)
                    self.size += len(warning)
        cutoff = now_local().date() - timedelta(days=self.policy.retention_days)
        retained = []
        for path in self._archives():
            if self.pattern.fullmatch(path.name)[1] < cutoff.isoformat():
                path.unlink()
            else:
                retained.append(path)
        total = sum(p.stat().st_size for p in retained)
        for path in retained:
            if total <= self.policy.archive_bytes:
                break
            size = path.stat().st_size
            path.unlink()
            total -= size

    def tick(self) -> None:
        if self.size and self.day != now_local().date():
            self.rotate()
        else:
            self.maintain()

    def write(self, data: bytes) -> None:
        if self.day != now_local().date():
            self.rotate()
        # 输出不必含换行，且单次读取可能超过文件限制，按有界块写入避免长行绕过上限。
        remaining = memoryview(data)
        while remaining:
            if self.size >= self.policy.max_bytes:
                self.rotate()
            count = min(len(remaining), self.policy.max_bytes - self.size)
            self.stream.write(remaining[:count])
            self.size += count
            remaining = remaining[count:]

    def close(self) -> None:
        if self.stream is not None:
            self.stream.close()
        self.lock.close()


def collect(path: Path, service: str) -> None:
    """stdin 管道跟随服务及其子进程生命周期；EOF 后退出，不遗留轮询守护进程。"""
    try:
        # 首次旧日志可能远大于新上限。先移动并按期限/原文容量清理，压缩留给运行期，
        # 避免初始化耗时超过启动握手或服务健康检查期限。
        writer = RollingLog(path, load_policy(service), defer_compression=True)
    except (OSError, RuntimeError, TypeError, ValueError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", flush=True)
        raise SystemExit(1) from None
    try:
        # 父启动器收到 READY 才启动业务进程，配置/文件锁失败不会留下无日志服务。
        print("READY", flush=True)
        with selectors.DefaultSelector() as selector:
            selector.register(sys.stdin.buffer, selectors.EVENT_READ)
            next_cleanup = time.monotonic() + writer.policy.cleanup_interval_sec
            while True:
                timeout = max(0, next_cleanup - time.monotonic())
                for key, _ in selector.select(timeout):
                    data = os.read(key.fd, READ_SIZE)
                    if not data:
                        return
                    writer.write(data)
                if time.monotonic() >= next_cleanup:
                    writer.tick()
                    next_cleanup = time.monotonic() + writer.policy.cleanup_interval_sec
    finally:
        writer.close()


def launch_logged_process(command: list[str], *, path: str, service: str) -> subprocess.Popen:
    """收集器与业务各自独立 session，保持现有后端 PID/进程组停服契约。"""
    collector = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--path", path, "--service", service],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(collector.stdout, selectors.EVENT_READ)
            if not selector.select(10):
                raise RuntimeError("日志收集器启动超时")
            response = collector.stdout.readline()
            if response != b"READY\n":
                raise RuntimeError(f"日志收集器启动失败: {response.decode().strip()}")
        collector.stdout.close()
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=collector.stdin,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "AI_STOCKS_LOG_COLLECTED": "1"},
        )
        # 只有服务持有写端；启动脚本退出不会关闭服务输出，服务组退出则收集器收到 EOF。
        collector.stdin.close()
        return process
    except BaseException:
        collector.stdin.close()
        collector.stdout.close()
        collector.terminate()
        collector.wait(timeout=5)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--service", choices=("backend", "frontend"), required=True)
    args = parser.parse_args()
    collect(args.path, args.service)
