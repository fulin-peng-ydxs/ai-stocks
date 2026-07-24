"""PostgreSQL 实例指纹。

只暴露不可逆摘要，用于确认测试夹具与被测后端连接到同一数据库实例和用户。
"""

from __future__ import annotations

import hashlib
import json

from backend.storage.pg_client import PostgresClient, get_pg_client


def pg_fingerprint(pg: PostgresClient | None = None) -> str:
    pg = pg or get_pg_client()
    row = pg.query_df(
        "SELECT current_database() AS database_name, current_user AS user_name, "
        "COALESCE(inet_server_addr()::text, 'local') AS server_address, "
        "COALESCE(inet_server_port(), 0) AS server_port"
    ).iloc[0]
    identity = {
        "database": str(row["database_name"]),
        "user": str(row["user_name"]),
        "serverAddress": str(row["server_address"]),
        "serverPort": int(row["server_port"]),
    }
    payload = json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
