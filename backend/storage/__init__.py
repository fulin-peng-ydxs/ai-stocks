"""存储层包：DuckDB 连接、DDL、Repository。"""

from backend.storage.duckdb_client import DuckDBClient, get_client

__all__ = ["DuckDBClient", "get_client"]
