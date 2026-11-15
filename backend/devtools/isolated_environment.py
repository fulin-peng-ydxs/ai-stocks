"""隔离测试子进程环境：不继承业务连接、凭据、调试开关和测试筛选。"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PARENT: ContextVar[Path | None] = ContextVar("ci_artifact_parent", default=None)


@contextmanager
def artifact_scope(parent: Path):
    """只重定向本进程执行器的报告；不让派生的门禁自测污染父套件回执。"""
    token = ARTIFACT_PARENT.set(parent)
    try:
        yield
    finally:
        ARTIFACT_PARENT.reset(token)


def create_ci_artifact_dir() -> Path:
    """每次执行独立保存临时诊断，退出后供排错/CI 上传，不混入服务日志。"""
    parent = ARTIFACT_PARENT.get() or ROOT / ".local/tmp/ai-agent"
    parent.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="ci-", dir=parent))
    print(f"CI 临时产物：{directory}", flush=True)
    return directory


def clean_environment() -> dict[str, str]:
    """调用方再注入自身临时连接；普通路径不能回落到本机环境覆盖。"""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("AI_STOCKS_", "PYTEST_")) and key != "ENV"
    }
    env.update(
        {
            "AI_STOCKS_ENV": "test",
            "AI_STOCKS_ENV_FILE": "/dev/null",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "AI_STOCKS_ADMIN_PASSWORD": uuid4().hex,
            "AI_STOCKS_JWT_SECRET": uuid4().hex + uuid4().hex,
            "AI_STOCKS_CONFIG_ENCRYPTION_KEY": "bsKvJrJKsi9lG2hlViiCnZimaUG5tyKh0Rbt5d3ngQU=",
            "AI_STOCKS_TASK_STORAGE_BACKEND": "auto",
            "AI_STOCKS_SMTP_ENABLED": "0",
        }
    )
    # 测试里的 shell 子入口也使用当前解释器，且不能重新加载本机变量文件。
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env["PYTHON"] = sys.executable
    return env


@contextmanager
def temporary_redis(root: Path, artifact_dir: Path):
    """后端和数据库门禁共用自建 Redis；不开放 TCP，不持久化，退出销毁。"""
    import redis

    executable = shutil.which("redis-server")
    if not executable:
        raise RuntimeError("隔离门禁需要 redis-server，不使用业务 Redis")
    socket = root / "redis.sock"
    log = artifact_dir / f"ci-redis-{uuid4().hex}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("wb") as output:
        process = subprocess.Popen(
            [
                executable,
                "--port",
                "0",
                "--unixsocket",
                str(socket),
                "--unixsocketperm",
                "700",
                "--save",
                "",
                "--appendonly",
                "no",
                "--dir",
                str(root),
            ],
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        client = redis.Redis(unix_socket_path=str(socket), socket_timeout=1)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError(f"临时 Redis 启动失败，日志：{log}")
                try:
                    if client.ping():
                        yield "unix://" + str(socket) + "?db=0"
                        return
                except redis.ConnectionError:
                    time.sleep(0.05)
            raise RuntimeError(f"临时 Redis 启动超时，日志：{log}")
        finally:
            client.close()
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@contextmanager
def isolated_storage_environment(admin_dsn: str, artifact_dir: Path | None = None):
    """在导入应用前绑定默认三库；新增测试复用普通客户端也只能进入本次临时资源。

    管理连接由调用方管理，本上下文仅借用它创建/删除随机 PG 库。数据库生命周期用例
    仍可通过同一管理连接另建空库；默认客户端不会因此回落到项目配置中的业务目标。
    """
    import yaml

    # 延迟导入，避免数据库门禁复用此上下文时产生模块初始化循环。
    from backend.devtools.database_gate import ADMIN_DSN_ENV, temporary_database

    artifact_dir = artifact_dir if artifact_dir is not None else create_ci_artifact_dir()
    # Unix socket 使用短系统路径；诊断另存，退出后仍可查看失败原因。
    with tempfile.TemporaryDirectory(prefix="ai-ci-", dir="/tmp") as directory:
        root = Path(directory)
        with temporary_database(admin_dsn) as pg, temporary_redis(root, artifact_dir) as redis_url:
            config = yaml.safe_load((ROOT / "config/settings.yaml").read_text())
            config["paths"] = {
                "duckdb_file": str(root / "market.duckdb"),
                "parquet_dir": str(root / "parquet"),
                "export_dir": str(root / "exports"),
                "log_dir": str(artifact_dir),
            }
            config_path = root / "settings.yaml"
            config_path.write_text(yaml.safe_dump(config, allow_unicode=True))
            env = clean_environment()
            env.update(
                {
                    ADMIN_DSN_ENV: admin_dsn,
                    "AI_STOCKS_CONFIG": str(config_path),
                    "AI_STOCKS_PG_DSN": pg.conninfo,
                    "AI_STOCKS_REDIS_URL": redis_url,
                }
            )
            yield env
