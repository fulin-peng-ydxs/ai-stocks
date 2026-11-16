"""可配置布局系统 M4：后端持久化、校验和 API。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import backend.storage.duckdb_client as dc
from backend.auth.context import enter_request, exit_request
from backend.common.exceptions import AuthError, StorageError
from backend.main import app
from backend.storage.ddl import init_db, list_tables
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.layout_config import LayoutConfigRepo, LayoutConfigValidationError
from backend.storage.pg_client import PostgresClient
from backend.storage.pg_ddl import init_pg_db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    c = DuckDBClient(db_path=str(tmp_path / "layout.duckdb"))
    init_db(c)
    monkeypatch.setattr(dc, "_client", c)
    yield c
    c.close()
    monkeypatch.setattr(dc, "_client", None)


@pytest.fixture(autouse=True)
def _layout_pg_snapshot():
    """布局平台层已迁 PG，测试前清空并在测试后恢复，避免污染真实平台配置。"""
    pg = PostgresClient()
    try:
        if not pg.ping():
            pytest.skip("PostgreSQL 未就绪")
    except StorageError:
        pytest.skip("PostgreSQL 未就绪")
    init_pg_db(pg)
    tables = ["layout_preset", "layout_page_config", "layout_field_policy", "layout_user_config", "app_config"]
    snapshots = {table: pg.query_df(f"SELECT * FROM {table}") for table in tables}
    for table in ["layout_user_config", "layout_field_policy", "layout_page_config", "layout_preset", "app_config"]:
        pg.execute(f"DELETE FROM {table}")
    yield
    for table in ["layout_user_config", "layout_field_policy", "layout_page_config", "layout_preset", "app_config"]:
        pg.execute(f"DELETE FROM {table}")
    for table in tables:
        df = snapshots[table]
        if df.empty:
            continue
        columns = list(df.columns)
        placeholders = ",".join(["%s"] * len(columns))
        quoted = ",".join(columns)
        for _, r in df.iterrows():
            pg.execute(
                f"INSERT INTO {table} ({quoted}) VALUES ({placeholders})",
                [r[col] for col in columns],
            )
    pg.close()


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    # stage2·T5：/api/layout/* 现受鉴权中间件保护，HTTP 用例需带 token
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", "unit-test-jwt-secret-0123456789-abcdefghij")


def _sys_headers() -> dict:
    """系统管理员(admin) access token 头，用于经鉴权中间件调 /api/layout/* 平台端点。"""
    from backend.auth.jwt_tokens import issue_access
    from backend.storage.pg_client import get_pg_client

    pv = int(get_pg_client().query_df(
        "SELECT perm_ver FROM sys_user WHERE id='admin'").iloc[0]["perm_ver"])
    return {"Authorization": "Bearer " + issue_access("admin", "default", pv)}


def test_layout_tables_created(client):
    tables = set(list_tables(client))
    assert {"layout_preset", "layout_page_config", "layout_user_config"} <= tables


def test_layout_http_reads_never_reexecute_market_schema_upgrade(client, monkeypatch):
    """运行期布局读取不得重放市场全库升级或重建行情索引和约束。"""
    from backend.storage import ddl

    def reject_runtime_upgrade(*_args, **_kwargs):
        pytest.fail("布局读取不得执行整库安装或升级")

    # 用例夹具已完成安装；只验证运行期请求，不在这里重放应用启动流程。
    http = TestClient(app)
    monkeypatch.setattr(ddl, "init_db", reject_runtime_upgrade)
    try:
        for path in ("/api/layout/presets", "/api/layout/effective/limit-ladder",
                     "/api/layout/users/limit-ladder"):
            response = http.get(path, headers=_sys_headers())
            assert response.status_code == 200
            assert response.json()["code"] == 0
    finally:
        http.close()


def test_builtin_presets_seed_and_custom_preset_roundtrip(client, monkeypatch):
    repo = LayoutConfigRepo(client)
    keys = {p["key"] for p in repo.list_presets()}
    assert "balanced" in keys
    assert not {
        "daylight",
        "nocturne",
        "professional",
        "government",
        "technology",
        "finance",
        "high-contrast",
    } & keys

    saved = repo.upsert_preset(
        key="dense-lab",
        name="圆角实验",
        config={"values": {"tokens.shared.cardRadius": 12}},
    )
    assert saved["config"]["values"]["tokens.shared.cardRadius"] == 12
    assert repo.get_preset("dense-lab")["name"] == "圆角实验"

    calls = {"execute": 0, "query": 0}
    original_execute = client.execute
    original_query = client.query_df

    def count_execute(sql, params=None):
        calls["execute"] += 1
        return original_execute(sql, params)

    def count_query(sql, params=None):
        calls["query"] += 1
        return original_query(sql, params)

    monkeypatch.setattr(client, "execute", count_execute)
    monkeypatch.setattr(client, "query_df", count_query)
    assert repo.seed_builtin_presets() == 0
    assert calls == {"execute": 0, "query": 0}


def test_platform_preset_read_is_public_but_user_tenant_stays_fail_closed(client):
    request_token = enter_request()
    try:
        repo = LayoutConfigRepo(client)
        assert any(preset["key"] == "balanced" for preset in repo.list_presets())
        with pytest.raises(AuthError, match="请求缺少认证上下文"):
            _ = repo.tenant_id
    finally:
        exit_request(request_token)


def test_legacy_builtin_preset_reference_migrates_to_single_builtin_system(client):
    repo = LayoutConfigRepo(client)
    repo.pg.execute(
        "INSERT INTO layout_preset "
        "(key, name, description, config, enabled, is_builtin, schema_version, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        ["finance", "旧金融数据", "旧内置预设", '{"density":"compact"}', True, True, 1],
    )
    repo.pg.execute(
        "INSERT INTO layout_page_config (page_key, preset_key, config, schema_version, updated_at) "
        "VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)",
        ["board", "finance", "{}", 1],
    )
    repo.pg.execute("DELETE FROM app_config WHERE key=%s", ["migration.layout_presets_single_blue_v1"])

    repo.seed_builtin_presets()

    assert repo.get_page_config("board")["presetKey"] is None
    assert repo.get_preset("finance") is None

    repo.upsert_preset(key="finance", name="用户自定义 Finance", config={"values": {}})
    with pytest.raises(LayoutConfigValidationError, match="不再支持绑定页面"):
        repo.set_page_config("stocks", preset_key="finance", config={"values": {}})
    repo.seed_builtin_presets()
    assert repo.get_page_config("stocks")["presetKey"] is None
    assert repo.get_preset("finance")["is_builtin"] is False


def test_visual_preset_split_migration_preserves_page_values_and_is_idempotent(client):
    repo = LayoutConfigRepo(client)
    legacy_values = {
        "tokens.light.primary": "#123456",
        "tokens.shared.pageGap": 14,
        "componentDefaults.density": "compact",
        "componentFieldDefaults.data-table.pageSize": 50,
        "responsiveDefaults.autoScaleResponsiveExponent": 0.25,
    }
    repo.pg.execute(
        "UPDATE layout_preset SET config=%s WHERE key=%s",
        [json.dumps(legacy_values), "balanced"],
    )
    repo.pg.execute(
        "INSERT INTO layout_page_config (page_key, preset_key, config, schema_version, updated_at) "
        "VALUES (%s,%s,%s,%s,CURRENT_TIMESTAMP) "
        "ON CONFLICT (page_key) DO UPDATE SET preset_key=EXCLUDED.preset_key, config=EXCLUDED.config",
        [
            "data-ingest",
            "balanced",
            json.dumps({"density": "comfortable", "slots.taskTable.config.pageSize": 100}),
            1,
        ],
    )
    repo.pg.execute(
        "DELETE FROM app_config WHERE key IN (%s,%s)",
        ["migration.layout_preset_visual_split_v1", "ui.display.auto_scale_exponent"],
    )
    repo.pg.execute(
        "INSERT INTO app_config (key, value, updated_at) VALUES (%s,%s,CURRENT_TIMESTAMP) "
        "ON CONFLICT (key) DO NOTHING",
        ["migration.config_storage_pg_v1", '{"applied":true}'],
    )

    repo._migrate_visual_preset_split()
    page = repo.get_page_config("data-ingest")
    assert page["presetKey"] is None
    assert page["config"]["values"]["density"] == "comfortable"
    assert page["config"]["values"]["slots.taskTable.config.pageSize"] == 100
    assert page["config"]["values"]["slots.logTable.config.pageSize"] == 50
    assert repo.get_preset("balanced")["config"]["values"] == {
        "tokens.light.primary": "#123456"
    }
    scale = repo.pg.query_df(
        "SELECT value FROM app_config WHERE key=%s", ["ui.display.auto_scale_exponent"]
    ).iloc[0]["value"]
    assert json.loads(scale) == 0.25

    before = repo.get_page_config("data-ingest")
    repo._migrate_visual_preset_split()
    assert repo.get_page_config("data-ingest")["config"] == before["config"]


def test_pg_empty_reads_duckdb_layout_until_config_migration(client):
    """迁移 marker 缺失且 PG 平台表为空时，布局平台配置临时只读回退 DuckDB。"""
    client.execute(
        "INSERT INTO app_config (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        ["migration.layout_presets_three_theme_v1", '{"applied":true}'],
    )
    client.execute(
        "INSERT INTO layout_preset "
        "(key, name, description, config, enabled, is_builtin, schema_version, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        ["legacy-duck", "旧库预设", "迁移前旧数据", '{"density":"compact"}', True, False, 1],
    )
    client.execute(
        "INSERT INTO layout_page_config (page_key, preset_key, config, schema_version, updated_at) "
        "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
        ["duck-page", "legacy-duck", '{"density":"comfortable"}', 1],
    )
    client.execute(
        "INSERT INTO layout_field_policy (component_kind, field, allowed_layers, updated_at) "
        "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
        ["data-table", "pageSize", '["page"]'],
    )

    repo = LayoutConfigRepo(client)

    assert any(p["key"] == "legacy-duck" for p in repo.list_presets(include_disabled=True))
    assert repo.get_preset("legacy-duck")["config"]["values"] == {}
    assert repo.get_page_config("duck-page")["presetKey"] is None
    policies = {(p["componentKind"], p["field"]): p for p in repo.list_field_policies()}
    assert policies[("data-table", "pageSize")]["allowedLayers"] == ["page"]


def test_duckdb_layout_fallback_survives_accidental_pg_write_before_migration(client):
    """即使迁移前 PG 被误写非空，marker 缺失时仍优先展示 DuckDB 存量。"""
    client.execute(
        "INSERT INTO layout_preset "
        "(key, name, description, config, enabled, is_builtin, schema_version, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        ["legacy-duck", "旧库预设", "迁移前旧数据", '{"density":"compact"}', True, False, 1],
    )
    pg = PostgresClient()
    try:
        pg.execute(
            "INSERT INTO layout_preset "
            "(key, name, description, config, enabled, is_builtin, schema_version, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            ["bad-pg", "迁移前误写", "不应击穿 DuckDB 回退", '{"density":"standard"}', True, False, 1],
        )

        repo = LayoutConfigRepo(client)
        keys = {p["key"] for p in repo.list_presets(include_disabled=True)}

        assert "legacy-duck" in keys
        assert "bad-pg" not in keys
        assert repo.get_preset("legacy-duck")["config"]["values"] == {}
        assert repo.get_preset("bad-pg") is None
    finally:
        pg.close()


def test_platform_layout_write_blocked_until_config_storage_migrated(client):
    """DuckDB 仍有待迁平台配置时，平台层写入必须拒绝，避免击穿只读回退。"""
    client.execute(
        "INSERT INTO layout_preset "
        "(key, name, description, config, enabled, is_builtin, schema_version, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        ["legacy-duck", "旧库预设", "迁移前旧数据", '{"density":"compact"}', True, False, 1],
    )

    repo = LayoutConfigRepo(client)

    with pytest.raises(LayoutConfigValidationError, match="配置存储迁移未完成"):
        repo.upsert_preset("new-preset", "迁移前误写", config={"values": {}})
    with pytest.raises(LayoutConfigValidationError, match="配置存储迁移未完成"):
        repo.set_page_config("board", {"values": {"density": "standard"}})
    with pytest.raises(LayoutConfigValidationError, match="配置存储迁移未完成"):
        repo.set_field_policy("data-table", "pageSize", ["page"])


def test_visual_preset_tokens_are_independent_from_pages(client):
    repo = LayoutConfigRepo(client)
    repo.upsert_preset(
        key="custom-red",
        name="自定义红",
        config={"values": {"tokens.light.primary": "#ef4444", "tokens.shared.cardRadius": 10}},
    )
    repo.set_page_config("board", config={"values": {"density": "standard"}})

    preset = repo.get_preset("custom-red")
    assert preset["config"]["values"]["tokens.light.primary"] == "#ef4444"
    assert "referencedPages" not in preset
    assert "referenceCount" not in preset
    assert repo.get_page_config("board")["presetKey"] is None


def test_page_user_effective_config_priority(client):
    repo = LayoutConfigRepo(client)
    repo.set_page_config(
        "board",
        config={"values": {"slots.table.minH": 360, "density": "standard"}},
    )
    repo.set_user_config("board", {"values": {"density": "comfortable"}}, user_id="u1")

    effective = repo.effective_config("board", user_id="u1")
    assert effective["presetKey"] is None
    assert effective["values"]["slots.table.minH"] == 360
    assert effective["values"]["density"] == "comfortable"
    assert effective["source"]["density"] == "user"
    assert effective["source"]["slots.table.minH"] == "page"


def test_invalid_config_rejected(client):
    repo = LayoutConfigRepo(client)
    # 组件配置：未登记字段被拒
    with pytest.raises(LayoutConfigValidationError, match="未登记的组件配置项"):
        repo.set_page_config("board", {"values": {"slots.table.config.bogus": 1}})
    # 视觉预设不再接受任何 slot 或组件配置。
    with pytest.raises(LayoutConfigValidationError, match="视觉预设不支持"):
        repo.upsert_preset("cc-bad", "越权预设", config={"values": {"slots.table.config.defaultSort": "x"}})
    with pytest.raises(LayoutConfigValidationError, match="视觉预设不支持"):
        repo.upsert_preset(
            "border-bad",
            "越权边框",
            config={"values": {"slots.table.config.border": False}},
        )
    # 组件配置：取值域
    with pytest.raises(LayoutConfigValidationError, match="不能小于"):
        repo.set_page_config("board", {"values": {"slots.table.config.pageSize": 5}})
    with pytest.raises(LayoutConfigValidationError, match="不能大于"):
        repo.set_page_config("board", {"values": {"slots.table.config.pageSize": 201}})
    with pytest.raises(LayoutConfigValidationError, match="不支持配置字段 defaultCollapsed"):
        repo.set_user_config(
            "board",
            {"values": {"slots.settings.config.defaultCollapsed": ["unknown"]}},
            layout={"slots": [{"id": "settings", "component": "settings-drawer"}]},
        )
    # config-panel 的折叠 key 由页面动态登记，不套用 settings-drawer 的固定三段值域。
    repo.set_user_config(
        "config",
        {"values": {"slots.panel.config.defaultCollapsed": ["page-specific-section"]}},
        layout={"slots": [{"id": "panel", "component": "config-panel"}]},
    )
    with pytest.raises(LayoutConfigValidationError, match="schemaVersion"):
        repo.set_user_config("board", {"schemaVersion": 999, "values": {"density": "compact"}})
    with pytest.raises(LayoutConfigValidationError, match="需为布尔值"):
        repo.set_user_config("board", {"values": {"slots.table.visible": "yes"}})


def test_component_config_ownership_boundary(client):
    repo = LayoutConfigRepo(client)
    board_layout = {
        "slots": [
            {"id": "head", "component": "filter-bar"},
            {"id": "table", "component": "data-table", "config": {"pagination": True}},
        ]
    }
    # 含组件配置却不传 layout：无法校验归属，直接拒绝（数据边界收口，非仅 UI 收口）
    with pytest.raises(LayoutConfigValidationError, match="需提供页面 layout"):
        repo.set_page_config("board", {"values": {"slots.table.config.pageSize": 50}})
    # 字段挂错组件种类：pageSize 不属于 filter-bar
    with pytest.raises(LayoutConfigValidationError, match="不支持配置字段"):
        repo.set_page_config(
            "board", {"values": {"slots.head.config.pageSize": 50}}, layout=board_layout
        )
    # defaultActive 是 tabs 字段，不属于 data-table
    with pytest.raises(LayoutConfigValidationError, match="不支持配置字段"):
        repo.set_page_config(
            "board", {"values": {"slots.table.config.defaultActive": "x"}}, layout=board_layout
        )
    # slot 不在该页布局
    with pytest.raises(LayoutConfigValidationError, match="不在该页面布局中"):
        repo.set_page_config(
            "board", {"values": {"slots.ghost.config.pageSize": 50}}, layout=board_layout
        )
    # 合法：data-table 的 pageSize + layout 提供 -> 通过
    saved = repo.set_page_config(
        "board", {"values": {"slots.table.config.pageSize": 50}}, layout=board_layout
    )
    assert saved["config"]["values"]["slots.table.config.pageSize"] == 50
    # 合法：data-table 的 border 是页面级开关
    saved = repo.set_page_config(
        "board", {"values": {"slots.table.config.border": False}}, layout=board_layout
    )
    assert saved["config"]["values"]["slots.table.config.border"] is False
    # 非法：border 不允许个人层覆盖
    with pytest.raises(LayoutConfigValidationError, match="不允许在 user 层"):
        repo.set_user_config(
            "board",
            {"values": {"slots.table.config.border": False}},
            user_id="u1",
            layout=board_layout,
        )
    # 非法：border 必须是布尔值
    with pytest.raises(LayoutConfigValidationError, match="需为布尔值"):
        repo.set_page_config(
            "board", {"values": {"slots.table.config.border": "false"}}, layout=board_layout
        )

    chart_layout = {"slots": [{"id": "chart", "component": "chart", "config": {"minHeight": 560}}]}
    saved = repo.set_user_config(
        "sectors-detail",
        {"values": {"slots.chart.config.minHeight": 620}},
        user_id="u1",
        layout=chart_layout,
    )
    assert saved["config"]["values"]["slots.chart.config.minHeight"] == 620
    with pytest.raises(LayoutConfigValidationError, match="不能小于"):
        repo.set_user_config(
            "sectors-detail",
            {"values": {"slots.chart.config.minHeight": 479}},
            user_id="u1",
            layout=chart_layout,
        )
    with pytest.raises(LayoutConfigValidationError, match="不能大于"):
        repo.set_page_config(
            "sectors-detail",
            {"values": {"slots.chart.config.minHeight": 901}},
            layout=chart_layout,
        )

    workspace_layout = {"slots": [{"id": "workspace", "component": "master-detail"}]}
    saved = repo.set_user_config(
        "stocks",
        {"values": {"slots.workspace.config.masterWidth": 520}},
        user_id="u1",
        layout=workspace_layout,
    )
    assert saved["config"]["values"]["slots.workspace.config.masterWidth"] == 520
    with pytest.raises(LayoutConfigValidationError, match="不能小于"):
        repo.set_user_config(
            "stocks",
            {"values": {"slots.workspace.config.masterWidth": 359}},
            user_id="u1",
            layout=workspace_layout,
        )
    with pytest.raises(LayoutConfigValidationError, match="不能大于"):
        repo.set_user_config(
            "stocks",
            {"values": {"slots.workspace.config.masterWidth": 1201}},
            user_id="u1",
            layout=workspace_layout,
        )

    profiles = {"profiles": [{"width": 1280, "ratio": 52}, {"width": 1920, "ratio": 46}]}
    saved = repo.set_user_config(
        "stocks",
        {"values": {"slots.workspace.config.masterRatioProfiles": profiles}},
        user_id="u1",
        layout=workspace_layout,
    )
    assert saved["config"]["values"]["slots.workspace.config.masterRatioProfiles"] == profiles
    with pytest.raises(LayoutConfigValidationError, match="ratio 需为 30～70"):
        repo.set_user_config(
            "stocks",
            {"values": {
                "slots.workspace.config.masterRatioProfiles": {
                    "profiles": [{"width": 1280, "ratio": 80}],
                },
            }},
            user_id="u1",
            layout=workspace_layout,
        )
    with pytest.raises(LayoutConfigValidationError, match="不允许在 page 层覆盖"):
        repo.set_page_config(
            "stocks",
            {"values": {"slots.workspace.config.masterRatioProfiles": profiles}},
            layout=workspace_layout,
        )

    saved = repo.set_user_config(
        "stocks",
        {"values": {"slots.workspace.config.masterRatio": 45}},
        user_id="u1",
        layout=workspace_layout,
    )
    assert saved["config"]["values"]["slots.workspace.config.masterRatio"] == 45
    with pytest.raises(LayoutConfigValidationError, match="不能小于"):
        repo.set_user_config(
            "stocks",
            {"values": {"slots.workspace.config.masterRatio": 29}},
            user_id="u1",
            layout=workspace_layout,
        )
    with pytest.raises(LayoutConfigValidationError, match="不能大于"):
        repo.set_user_config(
            "stocks",
            {"values": {"slots.workspace.config.masterRatio": 71}},
            user_id="u1",
            layout=workspace_layout,
        )


def test_validate_api_rejects_misplaced_component_field(client):
    api = TestClient(app)
    resp = api.post(
        "/api/layout/validate",
        json={
            "config": {"values": {"slots.toolbar.config.pageSize": 50}},
            "layout": {"slots": [{"id": "toolbar", "component": "toolbar"}]},
        },
        headers=_sys_headers(),
    )
    body = resp.json()
    assert body["data"]["valid"] is False
    assert any("不支持配置字段" in e for e in body["data"]["errors"])


def test_component_config_rejects_fields_not_applicable_to_slot_instance(client):
    """组件种类自动继承字段，但实例结构未启用的能力不得伪配置。"""
    repo = LayoutConfigRepo(client)
    with pytest.raises(LayoutConfigValidationError, match="未启用分页"):
        repo.set_user_config(
            "board",
            {"values": {"slots.table.config.pageSize": 50}},
            user_id="u1",
            layout={"slots": [{"id": "table", "component": "data-table", "config": {"pagination": False}}]},
        )
    with pytest.raises(LayoutConfigValidationError, match="自适应高度"):
        repo.set_user_config(
            "board",
            {"values": {"slots.chart.config.minHeight": 620}},
            user_id="u1",
            layout={"slots": [{"id": "chart", "component": "chart", "config": {}}]},
        )
    with pytest.raises(LayoutConfigValidationError, match="未启用默认排序"):
        repo.set_page_config(
            "board",
            {"values": {"slots.table.config.defaultSort": "score:desc"}},
            layout={"slots": [{"id": "table", "component": "data-table", "config": {"pagination": True}}]},
        )
    with pytest.raises(LayoutConfigValidationError, match="未启用涨跌测算"):
        repo.set_user_config(
            "backtest",
            {"values": {"slots.chart.config.returnMeasurementMode": "range"}},
            user_id="u1",
            layout={
                "slots": [
                    {"id": "chart", "component": "chart", "config": {"stockChart": {}}}
                ]
            },
        )
    with pytest.raises(LayoutConfigValidationError, match="不是联动走势工作台"):
        repo.set_user_config(
            "backtest",
            {"values": {"slots.chart.config.stockAnalysis": {"defaultChartMode": "kline"}}},
            user_id="u1",
            layout={
                "slots": [
                    {"id": "chart", "component": "chart", "config": {"stockChart": {}}}
                ]
            },
        )
    with pytest.raises(LayoutConfigValidationError, match="不是板块联动走势工作台"):
        repo.set_user_config(
            "backtest",
            {"values": {"slots.chart.config.sectorAnalysis": {"compareWindow": 120}}},
            user_id="u1",
            layout={
                "slots": [
                    {"id": "chart", "component": "chart", "config": {"stockChart": {}}}
                ]
            },
        )


def test_chart_period_and_return_measurement_defaults_require_enabled_chart_instance(client):
    repo = LayoutConfigRepo(client)
    layout = {
        "slots": [
            {
                "id": "chart",
                "component": "chart",
                "config": {
                    "stockChart": {},
                    "returnMeasurement": True,
                    "multiPeriodKline": True,
                },
            }
        ]
    }
    saved = repo.set_user_config(
        "stock-detail",
        {
            "values": {
                "slots.chart.config.klinePeriod": "week",
                "slots.chart.config.returnMeasurementMode": "range",
            }
        },
        user_id="u1",
        layout=layout,
    )
    assert saved["config"]["values"] == {
        "slots.chart.config.klinePeriod": "week",
        "slots.chart.config.returnMeasurementMode": "range",
    }
    with pytest.raises(LayoutConfigValidationError, match="未登记的组件配置项"):
        repo.set_user_config(
            "stock-detail",
            {"values": {"slots.chart.config.measurementOperationsExpanded": True}},
            user_id="u1",
            layout=layout,
        )
    with pytest.raises(LayoutConfigValidationError, match="取值非法"):
        repo.set_user_config(
            "stock-detail",
            {"values": {"slots.chart.config.returnMeasurementMode": "invalid"}},
            user_id="u1",
            layout=layout,
        )


def test_stock_chart_component_config_validates_instance_and_ratio_contract(client):
    repo = LayoutConfigRepo(client)
    valid = {
        "slot2": "volume",
        "slot3": "macd",
        "heightRatioProfileBasis": "visual-workspace-v1",
        "heightRatios": {
            "kline": [1],
            "kline|volume": [0.75, 0.25],
            "kline|macd": [0.75, 0.25],
            "kline|volume|macd": [0.6, 0.2, 0.2],
            "kline|macd|volume": [0.6, 0.2, 0.2],
        },
    }
    layout = {"slots": [{"id": "chart", "component": "chart", "config": {"stockChart": valid}}]}

    saved = repo.set_user_config(
        "stocks",
        {"values": {"slots.chart.config.stockChart": valid}},
        user_id="u1",
        layout=layout,
    )
    assert saved["config"]["values"]["slots.chart.config.stockChart"] == valid

    with_profiles = json.loads(json.dumps(valid))
    with_profiles["heightRatioProfiles"] = {
        "kline": [],
        "kline|volume": [],
        "kline|macd": [],
        "kline|volume|macd": [
            {"width": 1280, "height": 720, "ratios": [0.5, 0.3, 0.2]},
            {"width": 1600, "height": 900, "ratios": [0.55, 0.25, 0.2]},
        ],
        "kline|macd|volume": [],
    }
    saved_profiles = repo.set_user_config(
        "stocks",
        {"values": {"slots.chart.config.stockChart": with_profiles}},
        user_id="u1",
        layout=layout,
    )
    assert saved_profiles["config"]["values"]["slots.chart.config.stockChart"] == with_profiles

    legacy_profiles = json.loads(json.dumps(with_profiles))
    legacy_profiles.pop("heightRatioProfileBasis")
    saved_legacy = repo.set_user_config(
        "stocks",
        {"values": {"slots.chart.config.stockChart": legacy_profiles}},
        user_id="u1",
        layout=layout,
    )
    assert saved_legacy["config"]["values"]["slots.chart.config.stockChart"] == valid

    invalid_basis = json.loads(json.dumps(with_profiles))
    invalid_basis["heightRatioProfileBasis"] = "chart-panel-v0"
    with pytest.raises(LayoutConfigValidationError, match="尺寸比例档案基准非法"):
        repo.set_user_config(
            "stocks",
            {"values": {"slots.chart.config.stockChart": invalid_basis}},
            user_id="u1",
            layout=layout,
        )

    duplicate_size = json.loads(json.dumps(with_profiles))
    duplicate_size["heightRatioProfiles"]["kline|volume|macd"].append(
        {"width": 1280, "height": 720, "ratios": [0.6, 0.2, 0.2]}
    )
    with pytest.raises(LayoutConfigValidationError, match="宽高组合不能重复"):
        repo.set_user_config(
            "stocks",
            {"values": {"slots.chart.config.stockChart": duplicate_size}},
            user_id="u1",
            layout=layout,
        )

    duplicate = {**valid, "slot3": "volume"}
    with pytest.raises(LayoutConfigValidationError, match="辅助图不能重复"):
        repo.set_user_config(
            "stocks",
            {"values": {"slots.chart.config.stockChart": duplicate}},
            user_id="u1",
            layout=layout,
        )

    invalid_ratios = json.loads(json.dumps(valid))
    invalid_ratios["heightRatios"]["kline|volume"] = [0.8, 0.3]
    with pytest.raises(LayoutConfigValidationError, match="比例之和必须为 1"):
        repo.set_page_config(
            "stocks",
            {"values": {"slots.chart.config.stockChart": invalid_ratios}},
            layout=layout,
        )

    with pytest.raises(LayoutConfigValidationError, match="不是股票多图工作区"):
        repo.set_user_config(
            "stocks",
            {"values": {"slots.chart.config.stockChart": valid}},
            user_id="u1",
            layout={"slots": [{"id": "chart", "component": "chart", "config": {}}]},
        )


def test_component_config_page_user_priority(client):
    repo = LayoutConfigRepo(client)
    board_layout = {
        "slots": [{
            "id": "table",
            "component": "data-table",
            "config": {"pagination": True, "defaultSort": "score:desc"},
        }]
    }
    repo.set_page_config(
        "board",
        config={"values": {"slots.table.config.pageSize": 50, "slots.table.config.defaultSort": "score:desc"}},
        layout=board_layout,
    )
    repo.set_user_config(
        "board", {"values": {"slots.table.config.pageSize": 100}}, user_id="u1", layout=board_layout
    )

    eff = repo.effective_config("board", user_id="u1")
    assert eff["values"]["slots.table.config.pageSize"] == 100
    assert eff["source"]["slots.table.config.pageSize"] == "user"
    assert eff["values"]["slots.table.config.defaultSort"] == "score:desc"
    assert eff["source"]["slots.table.config.defaultSort"] == "page"


def test_settings_drawer_component_config_layers(client):
    """settings-drawer 只开放尺寸与滚动；折叠策略不允许写入布局配置。"""
    repo = LayoutConfigRepo(client)
    layout = {"slots": [{"id": "preferencesOverlay", "component": "settings-drawer"}]}
    repo.set_page_config(
        "board",
        config={
            "values": {
                "slots.preferencesOverlay.config.size": "lg",
                "slots.preferencesOverlay.config.bodyScroll": False,
            }
        },
        layout=layout,
    )
    with pytest.raises(LayoutConfigValidationError, match="不允许写入 layout_user_config"):
        repo.set_user_config(
            "board",
            {"values": {"slots.preferencesOverlay.config.size": "sm"}},
            user_id="u1",
            layout=layout,
        )
    for field, value in (("collapsibleSections", True), ("defaultCollapsed", ["layout"])):
        with pytest.raises(LayoutConfigValidationError, match=f"不支持配置字段 {field}"):
            repo.set_page_config(
                "board",
                {"values": {f"slots.preferencesOverlay.config.{field}": value}},
                layout=layout,
            )
    with pytest.raises(LayoutConfigValidationError, match="不允许在 user 层"):
        repo.set_user_config(
            "board",
            {"values": {"slots.preferencesOverlay.config.bodyScroll": False}},
            user_id="u2",
            layout=layout,
        )

    eff = repo.effective_config("board", user_id="u1")
    assert eff["values"]["slots.preferencesOverlay.config.size"] == "lg"
    assert eff["values"]["slots.preferencesOverlay.config.bodyScroll"] is False
    assert "slots.preferencesOverlay.config.collapsibleSections" not in eff["values"]
    assert "slots.preferencesOverlay.config.defaultCollapsed" not in eff["values"]


def test_effective_config_filters_stale_user_component_layer(client):
    """历史 user 层越权组件值读 effective_config 时也要按当前层级过滤。"""
    repo = LayoutConfigRepo(client)
    layout = {"slots": [{"id": "settings", "component": "settings-drawer"}]}
    repo.set_page_config(
        "board",
        config={"values": {"slots.settings.config.bodyScroll": True}},
        layout=layout,
    )
    repo.pg.execute(
        "INSERT INTO layout_user_config "
        "(user_id, tenant_id, owner_user_id, page_key, config, schema_version, updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP) "
        "ON CONFLICT (user_id, page_key) DO UPDATE SET "
        "tenant_id=EXCLUDED.tenant_id, owner_user_id=EXCLUDED.owner_user_id, "
        "config=EXCLUDED.config, schema_version=EXCLUDED.schema_version, "
        "updated_at=CURRENT_TIMESTAMP",
        [
            "u-stale",
            "default",
            "u-stale",
            "board",
            json.dumps({
                "slots.settings.config.bodyScroll": False,
                "slots.settings.config.defaultCollapsed": ["layout"],
                "slots.chart.config.measurementOperationsExpanded": True,
            }, ensure_ascii=False),
            1,
        ],
    )

    try:
        eff = repo.effective_config("board", user_id="u-stale")
        assert eff["values"]["slots.settings.config.bodyScroll"] is True
        assert eff["source"]["slots.settings.config.bodyScroll"] == "page"
        assert "slots.settings.config.defaultCollapsed" not in eff["values"]
        assert "slots.chart.config.measurementOperationsExpanded" not in eff["values"]
        user_layer = next(layer for layer in eff["layers"] if layer["layer"] == "user")
        assert "slots.settings.config.bodyScroll" not in user_layer["config"]["values"]
        assert "slots.settings.config.defaultCollapsed" not in user_layer["config"]["values"]
        assert (
            "slots.chart.config.measurementOperationsExpanded"
            not in user_layer["config"]["values"]
        )
    finally:
        repo.pg.execute(
            "DELETE FROM layout_user_config WHERE user_id=%s AND page_key=%s",
            ["u-stale", "board"],
        )


def test_config_panel_default_collapsed_accepts_section_keys(client):
    """config-panel defaultCollapsed 使用页面登记分区 key，不沿用 settings-drawer 固定枚举。"""
    repo = LayoutConfigRepo(client)
    layout = {"slots": [{"id": "configPanel", "component": "config-panel"}]}
    repo.set_page_config(
        "config-system",
        config={
            "values": {
                "slots.configPanel.config.collapsibleSections": True,
                "slots.configPanel.config.defaultCollapsed": ["auth", "auth.login"],
            }
        },
        layout=layout,
    )
    repo.set_user_config(
        "config-system",
        {
            "values": {
                "slots.configPanel.config.defaultCollapsed": ["datasource.request"],
                "slots.configPanel.config.showSectionDescription": False,
            }
        },
        user_id="u1",
        layout=layout,
    )

    eff = repo.effective_config("config-system", user_id="u1")
    assert eff["values"]["slots.configPanel.config.collapsibleSections"] is True
    assert eff["source"]["slots.configPanel.config.collapsibleSections"] == "page"
    assert eff["values"]["slots.configPanel.config.defaultCollapsed"] == ["datasource.request"]
    assert eff["source"]["slots.configPanel.config.defaultCollapsed"] == "user"
    assert eff["values"]["slots.configPanel.config.showSectionDescription"] is False


def test_visual_preset_can_be_disabled_or_deleted_without_page_references(client):
    repo = LayoutConfigRepo(client)
    config = {"values": {"tokens.shared.cardRadius": 12}}
    repo.upsert_preset("dense-lab", "圆角实验", config=config)
    repo.upsert_preset("dense-lab", "圆角实验", config=config, enabled=False)
    assert repo.get_preset("dense-lab")["enabled"] is False
    repo.delete_preset("dense-lab")
    assert repo.get_preset("dense-lab") is None


def test_validate_api_reports_layout_component_errors(client):
    api = TestClient(app)
    resp = api.post(
        "/api/layout/validate",
        json={
            "config": {"values": {"density": "compact"}},
            "layout": {"slots": [{"id": "main", "component": "unknown-widget"}]},
        },
        headers=_sys_headers(),
    )
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["valid"] is False
    assert any("组件未登记" in e for e in body["data"]["errors"])


def test_validate_api_reports_invalid_ideal_height_contract(client):
    api = TestClient(app)
    resp = api.post(
        "/api/layout/validate",
        json={
            "config": {"values": {}},
            "layout": {
                "slots": [
                    {
                        "id": "leading",
                        "component": "data-table",
                        "minH": 520,
                        "idealH": 519,
                    },
                    {
                        "id": "workspace",
                        "component": "tabs",
                        "growMain": True,
                        "idealH": 720,
                    },
                ]
            },
        },
        headers=_sys_headers(),
    )
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["valid"] is False
    assert any("idealH 不能低于有效最低高 520" in e for e in body["data"]["errors"])
    assert any("成长主区，不应再声明 idealH" in e for e in body["data"]["errors"])


def test_preset_per_mode_tokens_and_extras(client):
    """视觉预设只支持按模式颜色/阴影和共享圆角。"""
    repo = LayoutConfigRepo(client)
    saved = repo.upsert_preset(
        key="custom-x",
        name="自定义X",
        config={
            "values": {
                "tokens.light.primary": "#123456",
                "tokens.dark.primary": "#abcdef",
                "tokens.shared.cardRadius": 8,
                "tokens.light.shadow": "rgba(0, 0, 0, 0.10)",
            }
        },
    )
    v = saved["config"]["values"]
    assert v["tokens.light.primary"] == "#123456"
    assert v["tokens.dark.primary"] == "#abcdef"
    assert v["tokens.shared.cardRadius"] == 8
    assert v["tokens.light.shadow"] == "rgba(0, 0, 0, 0.10)"


def test_preset_rejects_bad_extras(client):
    """非法视觉 token 和所有废弃布局字段都被拒绝。"""
    repo = LayoutConfigRepo(client)
    with pytest.raises(LayoutConfigValidationError, match="token 路径"):
        repo.upsert_preset("p1", "P1", config={"values": {"tokens.mid.primary": "#fff"}})
    with pytest.raises(LayoutConfigValidationError, match="#RRGGBB"):
        repo.upsert_preset(
            "bad-color",
            "非法颜色",
            config={"values": {"tokens.light.primary": "#fff"}},
        )
    with pytest.raises(LayoutConfigValidationError, match="token 路径"):
        repo.upsert_preset(
            "text-color",
            "文字层级不可编辑",
            config={"values": {"tokens.dark.textMuted": "#c9d0d3"}},
        )
    with pytest.raises(LayoutConfigValidationError, match="视觉预设不支持"):
        repo.upsert_preset("p2", "P2", config={"values": {"responsiveDefaults.reflowBreakpoint": 999}})
    with pytest.raises(LayoutConfigValidationError, match="视觉预设不支持"):
        repo.upsert_preset("p3", "P3", config={"values": {"componentFieldDefaults.data-table.defaultSort": "x"}})


def test_field_policy_table_and_defaults(client):
    """P10：开放策略表存在；缺覆盖时回落代码最大集，overridden=False。"""
    assert "layout_field_policy" in set(list_tables(client))
    repo = LayoutConfigRepo(client)
    policies = {(p["componentKind"], p["field"]): p for p in repo.list_field_policies()}
    page_size = policies[("data-table", "pageSize")]
    assert page_size["maxLayers"] == ["page", "user"]
    assert page_size["allowedLayers"] == ["page", "user"]
    assert page_size["overridden"] is False


def test_field_policy_narrow_enforced_on_save(client):
    """P10：管理员把 pageSize 收紧为仅 page 后，user 层覆盖被拒、page 层仍可保存。"""
    repo = LayoutConfigRepo(client)
    board_layout = {
        "slots": [{"id": "table", "component": "data-table", "config": {"pagination": True}}]
    }
    repo.set_field_policy("data-table", "pageSize", ["page"])

    with pytest.raises(LayoutConfigValidationError, match="开放策略不允许在 user 层"):
        repo.set_user_config(
            "board", {"values": {"slots.table.config.pageSize": 100}}, user_id="u1", layout=board_layout
        )
    saved = repo.set_page_config(
        "board", {"values": {"slots.table.config.pageSize": 50}}, layout=board_layout
    )
    assert saved["config"]["values"]["slots.table.config.pageSize"] == 50


def test_field_policy_unknown_layer_rejected(client):
    """P10：旧 preset 层已从字段策略枚举移除。"""
    repo = LayoutConfigRepo(client)
    with pytest.raises(LayoutConfigValidationError, match="非法层级"):
        repo.set_field_policy("data-table", "defaultSort", ["preset"])
    with pytest.raises(LayoutConfigValidationError, match="开放层级不能为空"):
        repo.set_field_policy("data-table", "pageSize", [])
    with pytest.raises(LayoutConfigValidationError, match="无受控字段"):
        repo.set_field_policy("data-table", "bogus", ["page"])


def test_field_policy_reset_restores_max(client):
    """P10：重置开放策略回落代码最大集。"""
    repo = LayoutConfigRepo(client)
    repo.set_field_policy("data-table", "pageSize", ["page"])
    reset = repo.reset_field_policy("data-table", "pageSize")
    assert reset["overridden"] is False
    assert reset["allowedLayers"] == ["page", "user"]


def test_field_policy_api_roundtrip(client):
    """P10：开放策略 API 列表 / 保存 / 越界拒绝。"""
    api = TestClient(app)
    listed = api.get("/api/layout/field-policies", headers=_sys_headers()).json()["data"]["policies"]
    assert any(p["componentKind"] == "data-table" and p["field"] == "pageSize" for p in listed)

    ok_resp = api.post(
        "/api/layout/field-policies",
        json={"componentKind": "data-table", "field": "pageSize", "allowedLayers": ["page"]},
        headers=_sys_headers(),
    ).json()
    assert ok_resp["code"] == 0
    assert ok_resp["data"]["allowedLayers"] == ["page"]

    bad = api.post(
        "/api/layout/field-policies",
        json={"componentKind": "data-table", "field": "defaultSort", "allowedLayers": ["preset"]},
        headers=_sys_headers(),
    ).json()
    assert bad["code"] == 400


def test_layout_api_page_user_effective_roundtrip(client):
    api = TestClient(app)
    rejected = api.post(
        "/api/layout/pages/board",
        json={"presetKey": "balanced", "config": {"values": {"slots.table.minH": 420}}},
        headers=_sys_headers(),
    ).json()
    assert rejected["code"] == 400
    assert "不再支持绑定页面" in rejected["msg"]

    r1 = api.post(
        "/api/layout/pages/board",
        json={"presetKey": None, "config": {"values": {"slots.table.minH": 420}}},
        headers=_sys_headers(),
    ).json()
    assert r1["code"] == 0

    r2 = api.post(
        "/api/layout/users/board",
        json={"userId": "u1", "config": {"values": {"density": "comfortable"}}},
        headers=_sys_headers(),
    ).json()
    assert r2["code"] == 0

    data = api.get("/api/layout/effective/board?userId=u1", headers=_sys_headers()).json()["data"]
    assert data["values"]["density"] == "comfortable"
    assert data["source"]["density"] == "user"
    assert data["values"]["slots.table.minH"] == 420
