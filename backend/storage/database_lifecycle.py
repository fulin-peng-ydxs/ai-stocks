"""双库初始化/升级的统一编排、基础数据契约及只读验收。

PG 初始化在同一事务与 advisory lock 内提交。DuckDB 与 PG 无分布式事务：
DuckDB 可重跑，只有所有结构和 seed 校验通过才提交 PG 完成标记。
"""

from __future__ import annotations

import json
import os
import re

from psycopg.types.json import Jsonb

from backend.common.exceptions import StorageError
from backend.storage.client_scope import storage_client_scope
from backend.storage.schema_contract import (
    contract_digest,
    duck_table_ddl,
    load_contract,
    schema_report,
)

LIFECYCLE_MARKER = "database.lifecycle.v1"
INIT_LOCK = "ai-stocks-database-init-v1"


def _completion_details(marker: list[dict]) -> tuple[dict, list[str]]:
    """损坏的完成元数据不能被当成普通旧库，尤其不能把新装来源默认改成 False。"""
    if not marker:
        return {}, []
    details = marker[0]["details"]
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except ValueError:
            details = None
    if (
        marker[0]["state"] != "applied"
        or not isinstance(details, dict)
        or type(details.get("fresh_install")) is not bool
        or not isinstance(details.get("mode"), str)
        or details.get("mode") not in {"init", "upgrade"}
        or not isinstance(details.get("contract_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", details["contract_sha256"]) is None
    ):
        return {}, ["数据库完成标记损坏，拒绝猜测安装来源或覆盖标记"]
    return details, []


def _tables(client, schema: str) -> set[str]:
    placeholder = "?" if schema == "main" else "%s"
    return set(
        client.query_df(
            "SELECT table_name FROM information_schema.tables "
            f"WHERE table_schema={placeholder} AND table_type='BASE TABLE'",
            [schema],
        )["table_name"]
    )


def inspect_instance(pg) -> dict:
    """检查目标 schema 与最低 PG 版本；不输出连接串和凭据。"""
    row = pg.query_df(
        "SELECT current_database() AS database,current_schema() AS schema,"
        "current_setting('server_version_num')::int AS version,"
        "current_setting('server_encoding') AS encoding"
    ).iloc[0]
    violations = []

    if row["schema"] != "public":
        violations.append("PostgreSQL current_schema 必须为 public；请核对 search_path")
    if int(row["version"]) < 140000:
        violations.append("PostgreSQL 要求 >=14")
    if row["encoding"] != "UTF8":
        violations.append("PostgreSQL server_encoding 必须为 UTF8")
    return {
        "ok": not violations,
        "violations": violations,
        "database": str(row["database"]),
        "schema": row["schema"],
        "server_version_num": int(row["version"]),
    }


def _fresh_duck(duck) -> bool:
    """允许首次失败留下的空结构/内置指标，拒绝把已有业务库当作新装。

    用 EXISTS 而不是全表计数。仅两张初始化数据表可非空，指标必须全部为内置。
    """
    tables = _tables(duck, "main")
    if tables - duck_table_ddl().keys():
        return False
    for table in sorted(tables - {"data_dimension_registry", "indicator_def"}):
        if not duck.query_df(f'SELECT 1 FROM "{table}" LIMIT 1').empty:
            return False
    return (
        "indicator_def" not in tables
        or duck.query_df("SELECT 1 FROM indicator_def WHERE is_builtin IS NOT TRUE LIMIT 1").empty
    )


def lifecycle_plan(duck, pg, *, mode: str = "auto") -> dict:
    """只读识别新装/升级；未知旧库不自动迁移资产或改写存储路由。"""
    if mode not in {"auto", "init", "upgrade"}:
        raise ValueError("初始化模式仅支持 auto/init/upgrade")
    instance = inspect_instance(pg)
    pg_tables = _tables(pg, "public")
    fresh = not pg_tables and _fresh_duck(duck)
    marker = []
    if "storage_migration" in pg_tables:
        marker = pg.query_df(
            "SELECT state,details FROM storage_migration WHERE marker=%s",
            [LIFECYCLE_MARKER],
        ).to_dict("records")
    selected = ("init" if fresh else "upgrade") if mode == "auto" else mode
    prior_details, marker_problems = _completion_details(marker)
    violations = [*instance["violations"], *marker_problems]
    # init 可重跑同一版本的新装；已有旧库必须显式走 upgrade。
    if selected == "init" and not fresh and not marker:
        violations.append("目标含既有数据/结构且无统一初始化标记，请使用 upgrade 并核对专项迁移")
    if selected == "init" and marker and prior_details.get("contract_sha256") != contract_digest():
        violations.append("结构契约已变化，请使用 upgrade")
    return {
        "ok": not violations,
        "mode": selected,
        "fresh": fresh,
        "violations": violations,
        "instance": instance,
        "completion_marker": bool(marker),
        "contract_sha256": contract_digest(),
        "fresh_install": fresh or bool(prior_details.get("fresh_install")),
    }


def seed_platform_profiles(duck, pg) -> dict[str, int]:
    """统一平台槽三类预设入口；复用既有版本判定，不复制方案内容。"""
    from backend.scoring.score_profile import ScoreProfileRepo
    from backend.screening.profile import ProfileRepo
    from backend.signals.trade_profile import TradeProfileRepo
    from backend.storage.pg_ddl import PUBLIC_BOARD_OWNER

    tenant, owner = PUBLIC_BOARD_OWNER
    with storage_client_scope(duck, pg):
        return {
            "screen": ProfileRepo(pg=pg, tenant_id=tenant, owner_user_id=owner).seed_presets(),
            "score": ScoreProfileRepo(
                market=duck, pg=pg, tenant_id=tenant, owner_user_id=owner
            ).seed_defaults(),
            "trade": TradeProfileRepo(
                market=duck, pg=pg, tenant_id=tenant, owner_user_id=owner
            ).seed_defaults(),
        }


def seed_report(
    duck, pg, *, require_pg_routes: bool = False, allow_runtime_rollback: bool = False
) -> dict:
    """核对必需稳定键、归属及引用；可编辑标题/配置不与默认值比较。"""
    from backend.indicators.registry import REGISTRY
    from backend.scoring.score_profile import DEFAULT_SCORE_PROFILES
    from backend.screening.profile import PRESET_PROFILES
    from backend.services.migrate_config_storage import CONFIG_STORAGE_MARKER
    from backend.signals.trade_profile import DEFAULT_TRADE_PROFILES
    from backend.storage import pg_ddl
    from backend.storage.ddl import _DIMENSION_SEED
    from backend.storage.layout_config import BUILTIN_PRESETS
    from backend.storage.task_runtime import TASK_RUNTIME_MIGRATION_MARKER

    violations = []

    # 专项资源回滚属于受支持状态，不能被通用 seed 验收误判为缺失并要求复活。
    discipline_marker = pg.query_df(
        "SELECT value FROM app_config WHERE key=%s",
        [pg_ddl.TRADE_DISCIPLINE_RBAC_MARKER],
    )
    discipline_rolled_back = False
    if not discipline_marker.empty:
        state, _ = pg_ddl._trade_discipline_marker_state(discipline_marker.iloc[0]["value"])
        discipline_rolled_back = state == "rolled_back"
        if state == "invalid":
            violations.append("交易纪律权限迁移标记非法")

    def require_keys(client, sql, expected, label):
        actual = {str(row[0]) for row in client.query_df(sql).itertuples(index=False, name=None)}
        for key in sorted(set(expected) - actual):
            violations.append(f"{label}: 缺少 {key}")

    require_keys(
        duck,
        "SELECT dimension FROM data_dimension_registry",
        [row[0] for row in _DIMENSION_SEED],
        "数据维度",
    )
    require_keys(
        duck,
        "SELECT key FROM indicator_def WHERE is_builtin IS TRUE",
        [row.key for row in REGISTRY],
        "内置指标",
    )
    require_keys(pg, "SELECT id FROM sys_tenant", [pg_ddl.DEFAULT_TENANT_ID], "默认租户")
    if pg.query_df(
        "SELECT 1 FROM sys_user WHERE id=%s AND tenant_id=%s "
        "AND password_hash IS NOT NULL AND password_hash<>''",
        [pg_ddl.DEFAULT_OWNER_USER_ID, pg_ddl.DEFAULT_TENANT_ID],
    ).empty:
        violations.append("默认管理员不存在、归属错误或密码未初始化")
    require_keys(
        pg, "SELECT code FROM sys_role", [row[0] for row in pg_ddl._SEED_ROLES], "内置角色"
    )
    for code, _name, kind, locked, _assignable, _description in pg_ddl._SEED_ROLES:
        if pg.query_df(
            "SELECT 1 FROM sys_role WHERE id=%s AND code=%s AND kind=%s "
            "AND is_builtin IS TRUE AND is_locked=%s",
            [code, code, kind, locked],
        ).empty:
            violations.append(f"内置角色: {code} 的身份或锁定属性不符合契约")
    require_keys(
        pg,
        "SELECT code FROM sys_menu",
        [
            row["code"]
            for row in pg_ddl._flatten_menu_tree(pg_ddl._SEED_MENU_TREE)
            if not discipline_rolled_back or row["code"] != pg_ddl._TRADE_DISCIPLINE_MENU_ID
        ],
        "菜单",
    )
    require_keys(
        pg,
        "SELECT code FROM sys_resource",
        [
            row[1]
            for row in pg_ddl._SEED_RESOURCES
            if not discipline_rolled_back or row[1] not in pg_ddl.TRADE_DISCIPLINE_RESOURCE_CODES
        ],
        "功能点",
    )
    require_keys(
        pg,
        "SELECT key FROM app_config",
        [row[0] for row in pg_ddl._STAGE5_APP_CONFIG_DEFAULTS],
        "平台默认配置",
    )
    require_keys(
        pg, "SELECT code FROM dict_type", [row[0] for row in pg_ddl._SEED_DICT_TYPES], "字典类型"
    )
    require_keys(
        pg,
        "SELECT type_code || ':' || code FROM dict_item",
        [f"{row[0]}:{row[1]}" for row in pg_ddl._SEED_DICT_ITEMS],
        "字典项",
    )
    require_keys(
        pg, "SELECT key FROM layout_preset", [row["key"] for row in BUILTIN_PRESETS], "视觉预设"
    )
    if pg.query_df(
        "SELECT 1 FROM layout_preset WHERE key=%s AND enabled IS TRUE AND is_builtin IS TRUE",
        [BUILTIN_PRESETS[0]["key"]],
    ).empty:
        violations.append("默认视觉预设未启用或不再是内置预设")
    from backend.storage.app_config import _FIELD_BY_PATH, ConfigValidationError, _coerce

    for row in pg.query_df(
        "SELECT key,value FROM app_config WHERE key=ANY(%s)",
        [[row[0] for row in pg_ddl._STAGE5_APP_CONFIG_DEFAULTS]],
    ).to_dict("records"):
        try:
            _coerce(_FIELD_BY_PATH[row["key"]], json.loads(row["value"]))
        except (ConfigValidationError, ValueError, TypeError):
            violations.append(f"平台默认配置: {row['key']} 的值不符合类型或范围契约")
    for table, profiles in (
        ("screen_profile", PRESET_PROFILES),
        ("score_profile", DEFAULT_SCORE_PROFILES),
        ("trade_profile", DEFAULT_TRADE_PROFILES),
    ):
        ids = pg.query_df(
            f"SELECT id FROM {table} WHERE tenant_id=%s AND owner_user_id=%s "
            "AND is_preset IS TRUE AND visibility='public' "
            "AND published_at IS NOT NULL AND published_by IS NOT NULL",
            list(pg_ddl.PUBLIC_BOARD_OWNER),
        )["id"]
        for key in sorted({row["id"] for row in profiles} - set(ids)):
            violations.append(f"{table}: 缺少公开平台预设 {key}")
    if require_pg_routes:
        states = ["applied", "rolled_back"] if allow_runtime_rollback else ["applied"]
        if pg.query_df(
            "SELECT 1 FROM storage_migration WHERE marker=%s AND state=ANY(%s)",
            [TASK_RUNTIME_MIGRATION_MARKER, states],
        ).empty:
            violations.append("新装任务运行态未启用 PostgreSQL")
        if pg.query_df("SELECT 1 FROM app_config WHERE key=%s", [CONFIG_STORAGE_MARKER]).empty:
            violations.append("新装平台配置未启用 PostgreSQL")
    return {"ok": not violations, "violations": violations}


def verify_database(
    duck,
    pg,
    *,
    require_pg_routes: bool = False,
    require_completion: bool = True,
    allow_runtime_rollback: bool = True,
) -> dict:
    """只读验收：实例、完整结构、基础数据及数据目录必须全部通过。"""
    from backend.storage.catalog import build_catalog_payload, catalog_contract_report

    checks = {"instance": inspect_instance(pg), "schema": schema_report(duck, pg)}
    # 结构缺失时不执行依赖这些表/字段的数据检查，避免掩盖原始漂移路径。
    if checks["schema"]["ok"]:
        marker = pg.query_df(
            "SELECT state,details FROM storage_migration WHERE marker=%s", [LIFECYCLE_MARKER]
        ).to_dict("records")
        details, marker_problems = _completion_details(marker)
        if require_completion:
            problems = list(marker_problems)
            if not marker or marker[0]["state"] != "applied":
                problems.append("数据库完整初始化尚未完成，请执行 database upgrade")
            elif details.get("contract_sha256") != contract_digest():
                problems.append("数据库完成标记与当前结构契约版本不一致，请执行 database upgrade")
            checks["completion"] = {"ok": not problems, "violations": problems}
        checks["seeds"] = seed_report(
            duck,
            pg,
            require_pg_routes=require_pg_routes or bool(details.get("fresh_install")),
            allow_runtime_rollback=allow_runtime_rollback,
        )
        if checks["seeds"]["ok"]:
            # 目录的运行态指标也会读取有效配置，必须使用本次明确绑定的 PG。
            with storage_client_scope(duck, pg):
                payload = build_catalog_payload(
                    client=duck, pg_client=pg, database="all", include_legacy=True
                )
            checks["catalog"] = catalog_contract_report(payload["tables"])
    return {"ok": all(check["ok"] for check in checks.values()), "checks": checks}


def initialize_database(duck, pg, *, mode: str = "auto") -> dict:
    """唯一完整初始化入口；不采集行情，不创建测试账号，不替代旧资产搬迁。"""
    from backend.indicators.definition import IndicatorDefRepo
    from backend.services.migrate_config_storage import CONFIG_STORAGE_MARKER
    from backend.storage.ddl import init_db
    from backend.storage.layout_config import LayoutConfigRepo
    from backend.storage.pg_ddl import init_pg_db
    from backend.storage.task_runtime import (
        TASK_RUNTIME_MIGRATION_MARKER,
        reset_task_runtime_backend_cache,
    )

    if duck.read_only:
        raise StorageError("完整初始化需要可写 DuckDB；只读服务必须使用已初始化数据库")
    load_contract()  # 写库前确认基线可用。
    with storage_client_scope(duck, pg), pg.transaction():
        pg.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [INIT_LOCK])
        plan = lifecycle_plan(duck, pg, mode=mode)
        if not plan["ok"]:
            raise StorageError("；".join(plan["violations"]))
        if plan["fresh"] and not os.environ.get("AI_STOCKS_ADMIN_PASSWORD"):
            env = os.environ.get("AI_STOCKS_ENV", os.environ.get("ENV", "")).lower()
            if env not in {"dev", "test", "local"}:
                raise StorageError("新装非开发环境必须显式设置 AI_STOCKS_ADMIN_PASSWORD")
        init_db(duck)
        IndicatorDefRepo(duck).seed_builtins()
        init_pg_db(pg)
        if plan["fresh"]:
            # 新装不经过“历史迁移”猜测：没有旧数据可搬，直接登记当前事实源。
            pg.execute(
                "INSERT INTO storage_migration(marker,state,details) VALUES (%s,'applied',%s)",
                [TASK_RUNTIME_MIGRATION_MARKER, Jsonb({"source": "fresh-install"})],
            )
            pg.execute(
                "INSERT INTO app_config(key,value,updated_at) VALUES (%s,%s,now())",
                [CONFIG_STORAGE_MARKER, '{"applied":true,"source":"fresh-install"}'],
            )
        LayoutConfigRepo(client=duck, pg=pg)
        seed_platform_profiles(duck, pg)
        report = verify_database(
            duck,
            pg,
            require_pg_routes=plan["fresh_install"],
            require_completion=False,
            allow_runtime_rollback=not plan["fresh"],
        )
        if not report["ok"]:
            raise StorageError("数据库初始化验收失败：" + json.dumps(report, ensure_ascii=False))
        pg.execute(
            "INSERT INTO storage_migration(marker,state,details) VALUES (%s,'applied',%s) "
            "ON CONFLICT(marker) DO UPDATE SET state='applied',details=EXCLUDED.details,updated_at=now()",
            [
                LIFECYCLE_MARKER,
                Jsonb(
                    {
                        "contract_sha256": contract_digest(),
                        "mode": plan["mode"],
                        "fresh_install": plan["fresh_install"],
                    }
                ),
            ],
        )
    reset_task_runtime_backend_cache()
    return {**report, "mode": plan["mode"], "fresh": plan["fresh"]}
