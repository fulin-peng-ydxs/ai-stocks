"""可重复的数据库门禁，所有 DDL/DML 只进入随机命名的临时 PG 库。

显式 AI_STOCKS_DB_GATE_ADMIN_DSN 仅用于 CREATE/DROP 随机测试库；未设置时启动
独立临时 PostgreSQL 集群，不读取业务 DSN。外部服务不可用或任一测试跳过均失败。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from backend.config import PROJECT_ROOT
from backend.devtools.isolated_environment import clean_environment
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.pg_client import PostgresClient
from backend.storage.schema_contract import (
    CONTRACT_PATH,
    create_declared_schema,
    duck_schema,
    pg_schema,
)

ADMIN_DSN_ENV = "AI_STOCKS_DB_GATE_ADMIN_DSN"


@contextmanager
def temporary_database(admin_dsn: str):
    """仅创建和删除本次生成的数据库；不接受待删除库名，不操作 admin 库中的表。"""
    name = "ai_stocks_gate_" + uuid4().hex
    with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=5) as admin:
        if admin.info.server_version < 140000:
            raise RuntimeError("数据库门禁要求 PostgreSQL >=14")
        admin.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(
                sql.Identifier(name)
            )
        )
        pg = PostgresClient(make_conninfo(admin_dsn, dbname=name), min_size=1, max_size=3)
        try:
            yield pg
        finally:
            pg.close()
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@contextmanager
def gate_server():
    """优先用显式测试管理连接，否则用本机 PG 二进制启动隔离集群。"""
    configured = os.environ.get(ADMIN_DSN_ENV)
    if configured:
        yield configured
        return
    initdb, pg_ctl = shutil.which("initdb"), shutil.which("pg_ctl")
    if not initdb or not pg_ctl:
        raise RuntimeError(f"缺少 initdb/pg_ctl；安装 PG >=14 或设置 {ADMIN_DSN_ENV}")
    # Unix socket 路径有长度上限，集群目录使用系统短临时路径；服务日志在项目 logs。
    with tempfile.TemporaryDirectory(prefix="ai-stocks-db-", dir="/tmp") as directory:
        root = Path(directory)
        cluster = root / "cluster"
        subprocess.run(
            [
                initdb,
                "-D",
                str(cluster),
                "-A",
                "trust",
                "-U",
                "gate",
                "--encoding=UTF8",
                "--no-locale",
            ],
            check=True,
            capture_output=True,
        )
        log = PROJECT_ROOT / "logs" / f"database-gate-{uuid4().hex}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                pg_ctl,
                "-D",
                str(cluster),
                "-l",
                str(log),
                "-w",
                "start",
                "-o",
                f"-h '' -k {root} -p 55439 -F",
            ],
            check=True,
            capture_output=True,
        )
        try:
            yield make_conninfo(host=str(root), port=55439, user="gate", dbname="postgres")
        finally:
            subprocess.run(
                [pg_ctl, "-D", str(cluster), "-m", "fast", "-w", "stop"],
                check=True,
                capture_output=True,
            )


def refresh_schema_contract(admin_dsn: str) -> None:
    """机器基线只能从独立空库的目标声明生成，不能从开发/生产现库导出。"""
    with temporary_database(admin_dsn) as pg, DuckDBClient(":memory:") as duck:
        create_declared_schema(duck, pg)
        payload = {"duckdb": duck_schema(duck), "postgres": pg_schema(pg)}
        # 每表一行，保持生成文件紧凑、差异定位到具体表；禁止人工维护第二套字段定义。
        lines = ["{"]
        for index, database in enumerate(("duckdb", "postgres")):
            lines.append(f'  "{database}": {{')
            lines.append('    "tables": {')
            tables = sorted(payload[database]["tables"].items())
            for position, (name, definition) in enumerate(tables):
                suffix = "," if position < len(tables) - 1 else ""
                lines.append(
                    f'      "{name}": '
                    + json.dumps(definition, ensure_ascii=False, sort_keys=True)
                    + suffix
                )
            lines.append("    },")
            lines.append(
                '    "sequences": ' + json.dumps(payload[database]["sequences"], sort_keys=True)
            )
            lines.append("  }" + ("," if index == 0 else ""))
        lines.append("}")
        # 原子替换，避免其他读取者看到半份 JSON；失败时保留原契约。
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, dir=CONTRACT_PATH.parent, suffix=".tmp"
        ) as output:
            temporary = Path(output.name)
            try:
                output.write("\n".join(lines) + "\n")
                output.flush()
                os.fsync(output.fileno())
                temporary.replace(CONTRACT_PATH)
            finally:
                temporary.unlink(missing_ok=True)


def gate_test_paths(suite: str = "database") -> list[str]:
    """复用唯一套件登记，新增数据库测试文件不能只分流、却遗漏实际执行。"""
    from backend.devtools.ci import registry

    paths = [
        path for path, entry in registry()["special_files"].items()
        if entry["suite"] == suite
    ]
    if not paths:
        raise ValueError("数据库门禁测试集合为空")
    return paths


def run_gate(*, refresh_contract: bool = False, suite: str = "database") -> int:
    """在显式隔离环境运行数据库专项测试；不调用可能访问共享开发库的 pg fixture。"""
    paths = gate_test_paths(suite)
    with gate_server() as admin_dsn:
        if refresh_contract:
            refresh_schema_contract(admin_dsn)
        env = clean_environment()
        # 环境中的 -k/-m/--lf 或插件不能缩小“完整门禁”的执行范围。
        for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_CURRENT_TEST"):
            env.pop(key, None)
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        env[ADMIN_DSN_ENV] = admin_dsn
        env["AI_STOCKS_ENV"] = "test"
        # 避免测试签名值/管理员密码继承到临时集群外；只用于子进程临时数据库。
        env["AI_STOCKS_ADMIN_PASSWORD"] = uuid4().hex
        env["AI_STOCKS_TASK_STORAGE_BACKEND"] = "auto"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                *paths,
                "-p",
                "backend.devtools.database_gate_plugin",
                "-o",
                "addopts=",
                "-q",
                "-x",
                "--tb=short",
                "--junitxml=logs/ci-database.xml",
            ],
            cwd=PROJECT_ROOT,
            env=env,
            check=False,
        )
        return result.returncode
