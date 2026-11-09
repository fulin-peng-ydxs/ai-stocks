"""数据库结构契约：由独立空库生成基线，目标库校验只读系统目录。

基线是 DDL 的机器产物，禁止手改。门禁同时核对声明式新装、实际初始化及旧库升级，
避免只检查“物理上存在的字段”而漏掉缺列、约束或索引漂移。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from backend.config import PROJECT_ROOT

CONTRACT_PATH = PROJECT_ROOT / "backend/storage/database_contract.json"


def _sql(value: Any) -> str | None:
    """保留数据库系统目录的规范化输出，不自行改写引号、限定名或字面量。"""
    if value is None:
        return None
    return str(value).strip()


def duck_schema(duck) -> dict:
    """读取 main 的列、约束、显式索引和序列定义，不读取行情数据。"""
    tables = {
        str(row["table_name"]): {"columns": {}, "constraints": [], "indexes": {}}
        for row in duck.query_df(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main' AND table_type='BASE TABLE'"
        ).to_dict("records")
    }
    for row in duck.query_df(
        "SELECT table_name,column_name,data_type,is_nullable,column_default "
        "FROM information_schema.columns WHERE table_schema='main'"
    ).to_dict("records"):
        tables[row["table_name"]]["columns"][row["column_name"]] = [
            row["data_type"],
            row["is_nullable"] == "YES",
            _sql(row["column_default"]),
        ]
    for row in duck.query_df(
        "SELECT table_name,constraint_type,constraint_text FROM duckdb_constraints() "
        "WHERE schema_name='main' AND constraint_type<>'NOT NULL'"
    ).to_dict("records"):
        tables[row["table_name"]]["constraints"].append(_sql(row["constraint_text"]))
    for row in duck.query_df(
        "SELECT table_name,index_name,sql FROM duckdb_indexes() WHERE schema_name='main'"
    ).to_dict("records"):
        tables[row["table_name"]]["indexes"][row["index_name"]] = _sql(row["sql"])
    for table in tables.values():
        table["constraints"].sort()
    sequences = {
        row["sequence_name"]: [
            row["increment_by"],
            row["min_value"],
            row["max_value"],
            row["cycle"],
        ]
        for row in duck.query_df(
            "SELECT sequence_name,increment_by,min_value,max_value,cycle "
            "FROM duckdb_sequences() WHERE schema_name='main'"
        ).to_dict("records")
    }
    return {"tables": tables, "sequences": sequences}


def target_fingerprint(pg, duck_path: Path) -> str:
    """计划与写入绑定同一 PG 身份及解析后的 DuckDB 文件，防止只确认半个目标。"""
    from backend.storage.pg_identity import pg_fingerprint

    # Unix socket 的 inet_server_addr/port 都为空；还需绑定真实连接端点，避免不同本机集群碰撞。
    with pg.pool.connection() as connection:
        endpoint = [connection.info.host, connection.info.port]
    payload = json.dumps(
        {"postgres": pg_fingerprint(pg), "endpoint": endpoint, "duckdb": str(duck_path.resolve())},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def pg_schema(pg) -> dict:
    """读取 public 的结构，包含 CHECK/FK 删除策略、延迟属性及索引谓词。"""
    tables = {
        row["table_name"]: {"columns": {}, "constraints": [], "indexes": {}}
        for row in pg.query_df(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE'"
        ).to_dict("records")
    }
    for row in pg.query_df(
        "SELECT c.relname AS table_name,a.attname AS column_name,"
        "format_type(a.atttypid,a.atttypmod) AS data_type,a.attnotnull AS not_null,"
        "a.attidentity,a.attgenerated,"
        "pg_get_expr(d.adbin,d.adrelid) AS column_default "
        "FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum "
        "WHERE n.nspname='public' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped"
    ).to_dict("records"):
        kind = row["data_type"]
        if row["attidentity"] or row["attgenerated"]:
            kind += f" [identity={row['attidentity']},generated={row['attgenerated']}]"
        tables[row["table_name"]]["columns"][row["column_name"]] = [
            kind,
            not row["not_null"],
            _sql(row["column_default"]),
        ]
    for row in pg.query_df(
        "SELECT c.relname AS table_name,pg_get_constraintdef(k.oid,true) AS definition,"
        "k.convalidated FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND k.contype IN ('p','u','f','c','x')"
    ).to_dict("records"):
        definition = _sql(row["definition"])
        if not row["convalidated"]:
            definition += " [unvalidated]"
        tables[row["table_name"]]["constraints"].append(definition)
    for row in pg.query_df(
        "SELECT t.relname AS tablename,i.relname AS indexname,pg_get_indexdef(i.oid) AS indexdef,"
        "x.indisvalid,x.indisready FROM pg_index x JOIN pg_class i ON i.oid=x.indexrelid "
        "JOIN pg_class t ON t.oid=x.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
        "WHERE n.nspname='public'"
    ).to_dict("records"):
        definition = _sql(row["indexdef"])
        if not row["indisvalid"] or not row["indisready"]:
            definition += " [invalid-or-not-ready]"
        tables[row["tablename"]]["indexes"][row["indexname"]] = definition
    for table in tables.values():
        table["constraints"].sort()
    sequences = {
        row["sequencename"]: [row["increment_by"], row["min_value"], row["max_value"], row["cycle"]]
        for row in pg.query_df(
            "SELECT sequencename,increment_by,min_value,max_value,cycle "
            "FROM pg_sequences WHERE schemaname='public'"
        ).to_dict("records")
    }
    return {"tables": tables, "sequences": sequences}


def load_contract(path: Path = CONTRACT_PATH) -> dict:
    """缺少基线直接失败，不能以当前目标库自我生成期望值。"""
    return json.loads(path.read_text(encoding="utf-8"))


def contract_digest(contract: dict | None = None) -> str:
    payload = json.dumps(contract or load_contract(), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def schema_differences(expected: Any, actual: Any, path: str = "") -> list[str]:
    """给出精确对象路径；值可能包含业务默认值，对外只返回差异类型。"""
    if isinstance(expected, dict) and isinstance(actual, dict):
        differences = [f"{path}.{key}: 缺失" for key in sorted(expected.keys() - actual.keys())]
        differences += [f"{path}.{key}: 未登记" for key in sorted(actual.keys() - expected.keys())]
        for key in sorted(expected.keys() & actual.keys()):
            differences += schema_differences(expected[key], actual[key], f"{path}.{key}")
        return differences
    return [] if expected == actual else [f"{path}: 定义不一致"]


def schema_report(duck, pg, *, contract: dict | None = None) -> dict:
    expected = contract or load_contract()
    actual = {"duckdb": duck_schema(duck), "postgres": pg_schema(pg)}
    violations = schema_differences(expected, actual)
    return {
        "ok": not violations,
        "violations": violations,
        "contract_sha256": contract_digest(expected),
    }


def create_declared_schema(duck, pg) -> None:
    """门禁参考库只按目标 DDL 建结构；不执行旧库补列或 seed。

    少量循环外键/跨列约束及索引复用正式 DDL 的公共片段。参考库必须为空，
    不能拿升级完成后的库充当新装定义，否则遗漏的迁移无法被发现。
    """
    from backend.storage import ddl, pg_ddl

    for sql in ddl.DDL_SEQUENCES:
        duck.execute(sql)
    for sql in duck_table_ddl().values():
        duck.execute(sql)
    for sql in ddl._LIMIT_LADDER_INDEXES:
        duck.execute(sql)
    for sql in {**pg_ddl._OTHER_TABLES, **pg_ddl._ASSET_TABLES, **pg_ddl._RBAC_TABLES}.values():
        pg.execute(sql)
    for sql in (
        *pg_ddl._RBAC_INDEXES,
        *pg_ddl._STAGE5_INDEXES,
        *pg_ddl._LIMIT_LADDER_INDEXES,
        *pg_ddl._TASK_RUNTIME_INDEXES,
        *pg_ddl._STAGE6_VISIBILITY_INDEXES,
        *pg_ddl._TRADE_DISCIPLINE_INDEXES,
        *pg_ddl._TRADE_DISCIPLINE_POINTER_CONSTRAINTS,
    ):
        pg.execute(sql)
    pg_ddl._upgrade_identity_uniqueness(pg)
    pg.execute(
        "CREATE INDEX IF NOT EXISTS idx_layout_user_config_owner "
        "ON layout_user_config (tenant_id, owner_user_id)"
    )
    pg.execute(
        "CREATE INDEX IF NOT EXISTS idx_score_profile_visibility "
        "ON score_profile (visibility, tenant_id, owner_user_id)"
    )


def duck_table_ddl() -> dict[str, str]:
    """全量表清单复用既有领域 DDL；新表必须进入正式声明集合。"""
    from backend.storage import ddl

    return {
        **ddl.M1_TABLES,
        **ddl.M2_TABLES,
        **ddl.M3_TABLES,
        **ddl.M4_TABLES,
        **ddl.M5_TABLES,
        **ddl.M6_TABLES,
        **ddl.M28_TABLES,
        **ddl.M_TRAINING_TABLES,
        **ddl.M_BOARD_TABLES,
        **ddl.M_STOCK_BOARD_CORRELATION_TABLES,
        **ddl.M_LIMIT_LADDER_TABLES,
    }
