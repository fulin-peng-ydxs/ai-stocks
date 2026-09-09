"""存储层包：DuckDB（行情只读）+ PostgreSQL（资产读写）+ Redis（短状态）。"""

from backend.storage.duckdb_client import (
    DuckDBClient,
    DuckDBReadClient,
    close_duckdb_clients,
    get_client,
    get_read_client,
    get_write_client,
)
from backend.storage.pg_client import PostgresClient, get_pg_client
from backend.storage.redis_client import RedisClient, get_redis_client

__all__ = [
    "DuckDBClient",
    "DuckDBReadClient",
    "close_duckdb_clients",
    "get_client",
    "get_read_client",
    "get_write_client",
    "PostgresClient",
    "get_pg_client",
    "RedisClient",
    "get_redis_client",
]
