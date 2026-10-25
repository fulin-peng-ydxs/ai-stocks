"""本机一次性交易纪律重置：先备份，全部归属逐一重建 v1，不清理其他业务。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.devtools.environment_guard import require_local_test_environment
from backend.services.trade_ledger import SHANGHAI
from backend.storage.pg_client import PostgresClient, get_pg_client
from backend.storage.pg_ddl import _ASSET_TABLES
from backend.storage.pg_identity import pg_fingerprint
from backend.storage.trade_discipline_repository import TradeDisciplineRepository

MARKER = "trade_discipline.ledger_reset_v1"
TABLES = tuple(name for name in _ASSET_TABLES if name.startswith("trade_discipline_"))
DELETE_ORDER = (
    "trade_discipline_ledger_revision", "trade_discipline_ledger_day", "trade_discipline_account",
    "trade_discipline_operation", "trade_discipline_violation", "trade_discipline_reason",
    "trade_discipline_checkin_revision", "trade_discipline_checkin",
    "trade_discipline_rule_activation", "trade_discipline_action_rule", "trade_discipline_stock_rule",
    "trade_discipline_rule_version", "trade_discipline_action_subtype",
)


def _backup(pg: PostgresClient, destination: Path) -> dict:
    """pg_dump 的连接密码只通过子进程环境传递，备份仅有本用户读取权限。"""
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.exists():
        raise RuntimeError("备份文件已存在，拒绝覆盖")
    options = conninfo_to_dict(pg.conninfo)
    env = dict(os.environ)
    for key, value in options.items():
        if key in {"host", "port", "user", "password", "dbname", "sslmode", "options"}:
            env["PGDATABASE" if key == "dbname" else f"PG{key.upper()}"] = value
    destination.touch(mode=0o600, exist_ok=False)
    result = subprocess.run(
        ["pg_dump", "--format=custom", "--no-owner", "--no-privileges",
         "--table=public.trade_discipline_*", f"--file={destination}"],
        env=env, capture_output=True, text=True, timeout=300, check=False,
    )
    if result.returncode or destination.stat().st_size < 100:
        raise RuntimeError("交易纪律备份失败，未执行删除；请检查 pg_dump 和数据库连接")
    with destination.open("rb") as stream:
        header = stream.read(5)
    if header != b"PGDMP":
        raise RuntimeError("备份格式校验失败，未执行删除")
    listing = subprocess.run(["pg_restore", "--list", str(destination)],
                             capture_output=True, text=True, timeout=30, check=False)
    if listing.returncode or any(f"TABLE DATA public {table} " not in listing.stdout for table in TABLES):
        raise RuntimeError("备份内容校验失败，未执行删除")
    digest = hashlib.sha256()
    with destination.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(destination.resolve()), "bytes": destination.stat().st_size,
            "sha256": digest.hexdigest(), "archive_verified": True}


def _rebuild(conn, pg: PostgresClient, effective_date: date) -> dict:
    """调用方已锁定目标表；公开维护入口负责备份、环境和一次性标识。"""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(" UNION ".join(f"SELECT tenant_id,owner_user_id FROM {table}" for table in TABLES))
        owners = [(r["tenant_id"], r["owner_user_id"]) for r in cur.fetchall()]
        retained = 0
        for tenant, owner in owners:
            repo = TradeDisciplineRepository(pg, tenant_id=tenant, owner_user_id=owner)
            cur.execute("SELECT * FROM trade_discipline_rule WHERE tenant_id=%s AND owner_user_id=%s",
                        [tenant, owner])
            rules = [dict(r) for r in cur.fetchall()]
            versions = {rule["id"]: repo.load_version(rule["id"], rule["latest_version_no"], conn=conn)
                        for rule in rules if rule["latest_version_no"] is not None}
            cur.execute("UPDATE trade_discipline_rule SET status='unpublished',latest_version_no=NULL,"
                        "next_activation_seq=0 WHERE tenant_id=%s AND owner_user_id=%s", [tenant, owner])
            cur.execute("UPDATE trade_discipline_rule_draft SET source_version_no=NULL,"
                        "draft_revision=draft_revision+1 WHERE tenant_id=%s AND owner_user_id=%s",
                        [tenant, owner])
            for table in DELETE_ORDER:
                cur.execute(f"DELETE FROM {table} WHERE tenant_id=%s AND owner_user_id=%s", [tenant, owner])
            for rule in rules:
                version = versions.get(rule["id"])
                if version is None:
                    continue
                repo.insert_version(conn, rule["id"], 1, version)
                repo.update_lifecycle(conn, rule["id"], status=rule["status"], name=version["name"],
                                      normalized_name=version["normalized_name"], latest_version_no=1)
                conn.execute("UPDATE trade_discipline_rule SET next_activation_seq=1 "
                             "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
                             [tenant, owner, rule["id"]])
                conn.execute("UPDATE trade_discipline_rule_draft SET source_version_no=1 "
                             "WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s",
                             [tenant, owner, rule["id"]])
                repo.insert_activation(conn, activation_id=f"tdreset_{uuid4().hex}", rule_id=rule["id"],
                                       event_seq=1, event_type="archive" if rule["status"] == "archived" else "publish",
                                       version_no=1, occurred_at=datetime.now(SHANGHAI), effective_date=effective_date)
                retained += 1
        for table in ("trade_discipline_checkin", "trade_discipline_checkin_revision",
                      "trade_discipline_operation", "trade_discipline_ledger_day"):
            cur.execute(f"SELECT count(*) AS n FROM {table}")
            if cur.fetchone()["n"]:
                raise RuntimeError(f"重置后仍有历史残留：{table}")
        cur.execute("SELECT count(*) AS n FROM trade_discipline_rule_version WHERE version_no<>1")
        if cur.fetchone()["n"]:
            raise RuntimeError("重置后规则仍存在非初始版本")
        return {"owners": len(owners), "retained_rules": retained, "effective_date": effective_date.isoformat()}


def reset_history(*, apply: bool, expected_fingerprint: str, effective_date: date,
                  backup_path: Path | None = None, pg: PostgresClient | None = None) -> dict:
    require_local_test_environment()
    pg = pg or get_pg_client()
    if not re.fullmatch(r"[a-f0-9]{64}", expected_fingerprint or "") or not secrets.compare_digest(
        pg_fingerprint(pg), expected_fingerprint,
    ):
        raise RuntimeError("数据库目标与已核实指纹不一致，拒绝重置")
    with pg.transaction() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(8410010015)")
        existing = conn.execute("SELECT 1 FROM storage_migration WHERE marker=%s", [MARKER]).fetchone()
        if existing:
            return {"already_applied": True, "message": "已执行过本次重置，保留新周期数据"}
        if conn.execute("SELECT current_schema()").fetchone()[0] != "public":
            raise RuntimeError("维护入口只接受已核实的 public 业务模式")
        # SHARE 锁阻止业务写入，但允许独立 pg_dump 连接读取同一稳定数据集。
        conn.execute("SET LOCAL lock_timeout='10s'")
        conn.execute("LOCK TABLE " + ",".join(TABLES) + " IN SHARE MODE")
        counts = {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in TABLES}
        if not apply:
            return {"apply": False, "counts": counts, "effective_date": effective_date.isoformat()}
        if backup_path is None:
            raise RuntimeError("实际重置必须提供备份路径")
        backup = _backup(pg, backup_path)
        conn.execute("LOCK TABLE " + ",".join(TABLES) + " IN ACCESS EXCLUSIVE MODE")
        report = {**_rebuild(conn, pg, effective_date), "before": counts, "backup": backup}
        conn.execute("INSERT INTO storage_migration(marker,state,details) VALUES (%s,'applied',%s)",
                     [MARKER, Jsonb(report)])
        manifest = backup_path.with_suffix(backup_path.suffix + ".json")
        manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        manifest.chmod(0o600)
        return report
