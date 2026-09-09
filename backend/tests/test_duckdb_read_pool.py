from __future__ import annotations

import threading

import pandas as pd
import pytest

from backend.common.exceptions import ServiceUnavailableError, StorageError
from backend.storage.duckdb_client import DuckDBClient, DuckDBReadClient, DuckDBReadPool


def _clients(tmp_path, *, size: int = 2, timeout: float = 0.05):
    path = tmp_path / "read-pool.duckdb"
    writer = DuckDBClient(path)
    writer.execute("CREATE TABLE sample (id INTEGER)")
    writer.execute("INSERT INTO sample VALUES (1), (2)")
    pool = DuckDBReadPool(
        path,
        size=size,
        acquire_timeout_sec=timeout,
        read_only=False,
    )
    return writer, pool, DuckDBReadClient(pool, writer)


def test_read_pool_reads_committed_data_and_reports_stats(tmp_path):
    writer, pool, reader = _clients(tmp_path)
    try:
        assert reader.query_df("SELECT sum(id) AS total FROM sample").iloc[0]["total"] == 3
        stats = reader.stats()
        assert stats["size"] == 2
        assert stats["queries"] == 1
        assert stats["active"] == 0
        assert stats["idle"] == 2
    finally:
        pool.close()
        writer.close()


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO sample VALUES (3)",
        "UPDATE sample SET id=3",
        "DELETE FROM sample",
        "CREATE TABLE forbidden(id INTEGER)",
        "SELECT 1; SELECT 2",
    ],
)
def test_read_pool_rejects_writes_and_multiple_statements(tmp_path, sql):
    writer, pool, reader = _clients(tmp_path)
    try:
        with pytest.raises(StorageError):
            reader.query_df(sql)
        assert writer.query_df("SELECT count(*) AS n FROM sample").iloc[0]["n"] == 2
    finally:
        pool.close()
        writer.close()


def test_read_pool_times_out_instead_of_waiting_forever(tmp_path):
    writer, pool, reader = _clients(tmp_path, size=1, timeout=0.02)
    entered = threading.Event()
    release = threading.Event()

    def hold_connection():
        with pool.connection():
            entered.set()
            release.wait(1)

    thread = threading.Thread(target=hold_connection)
    thread.start()
    assert entered.wait(1)
    try:
        with pytest.raises(ServiceUnavailableError, match="查询繁忙"):
            reader.query_df("SELECT * FROM sample")
        assert reader.stats()["timeouts"] == 1
    finally:
        release.set()
        thread.join(timeout=1)
        pool.close()
        writer.close()


def test_disabled_pool_falls_back_to_serial_writer(tmp_path):
    writer, pool, reader = _clients(tmp_path, size=0)
    try:
        assert reader.query_df("SELECT count(*) AS n FROM sample").iloc[0]["n"] == 2
        assert reader.stats()["enabled"] is False
    finally:
        pool.close()
        writer.close()


def test_reader_uses_committed_snapshot_during_writer_transaction(tmp_path):
    writer, pool, reader = _clients(tmp_path, size=1)
    try:
        with writer.transaction():
            writer.execute("UPDATE sample SET id=10 WHERE id=1")
            # 独立连接看见旧的已提交版本，不等待写事务结束，也不读取未提交值。
            assert reader.query_df("SELECT sum(id) AS total FROM sample").iloc[0]["total"] == 3
        assert reader.query_df("SELECT sum(id) AS total FROM sample").iloc[0]["total"] == 12
    finally:
        pool.close()
        writer.close()


def test_reader_temp_view_pins_query_to_borrowed_connection(tmp_path):
    writer, pool, reader = _clients(tmp_path, size=2)
    wanted = pd.DataFrame({"id": [2]})
    try:
        with reader.temp_view(wanted, "wanted") as view:
            result = reader.query_df(
                f"SELECT sample.id FROM sample JOIN {view} USING (id)"
            )
        assert result["id"].tolist() == [2]
        assert reader.stats()["queries"] == 1
        with pytest.raises(StorageError, match="does not exist"):
            reader.query_df(f"SELECT * FROM {view}")
    finally:
        pool.close()
        writer.close()
