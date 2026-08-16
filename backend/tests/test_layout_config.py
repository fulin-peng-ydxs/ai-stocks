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
        name="高密实验",
        config={"values": {"density": "compact"}},
    )
    assert saved["config"]["values"]["density"] == "compact"
    assert repo.get_preset("dense-lab")["name"] == "高密实验"

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

    assert repo.get_page_config("board")["presetKey"] == "balanced"
    assert repo.get_preset("finance") is None

    repo.upsert_preset(key="finance", name="用户自定义 Finance", config={"values": {}})
    repo.set_page_config("stocks", preset_key="finance", config={"values": {}})
    repo.seed_builtin_presets()
    assert repo.get_page_config("stocks")["presetKey"] == "finance"
    assert repo.get_preset("finance")["is_builtin"] is False


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
    assert repo.get_preset("legacy-duck")["config"]["values"]["density"] == "compact"
    assert repo.get_page_config("duck-page")["presetKey"] == "legacy-duck"
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
        assert repo.get_preset("legacy-duck")["config"]["values"]["density"] == "compact"
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


def test_preset_tokens_and_references(client):
    repo = LayoutConfigRepo(client)
    repo.upsert_preset(
        key="custom-red",
        name="自定义红",
        config={"values": {"tokens.light.primary": "#ef4444", "tokens.shared.pageGap": 10, "componentDefaults.drawerSize": "lg"}},
    )
    repo.set_page_config("board", preset_key="custom-red", config={"density": "standard"})

    preset = repo.get_preset("custom-red")
    assert preset["config"]["values"]["tokens.light.primary"] == "#ef4444"
    assert preset["referencedPages"] == ["board"]
    assert preset["referenceCount"] == 1


def test_page_user_effective_config_priority(client):
    repo = LayoutConfigRepo(client)
    repo.set_page_config(
        "board",
        preset_key="balanced",
        config={"values": {"slots.table.minH": 360, "density": "standard"}},
    )
    repo.set_user_config("board", {"values": {"density": "comfortable"}}, user_id="u1")

    effective = repo.effective_config("board", user_id="u1")
    assert effective["presetKey"] == "balanced"
    assert effective["values"]["slots.table.minH"] == 360
    assert effective["values"]["density"] == "comfortable"
    assert effective["source"]["density"] == "user"
    assert effective["source"]["slots.table.minH"] == "page"


def test_invalid_config_rejected(client):
    repo = LayoutConfigRepo(client)
    # 组件配置：未登记字段被拒
    with pytest.raises(LayoutConfigValidationError, match="未登记的组件配置项"):
        repo.set_page_config("board", {"values": {"slots.table.config.bogus": 1}})
    # 组件配置：越权层级（defaultSort 仅 page/user，preset 层覆盖被拒；pageSize 已放开 preset）
    with pytest.raises(LayoutConfigValidationError, match="不允许在 preset 层"):
        repo.upsert_preset("cc-bad", "越权预设", config={"values": {"slots.table.config.defaultSort": "x"}})
    # 组件配置：表格边框只允许页面级统一配置，禁止预设/个人层覆盖
    with pytest.raises(LayoutConfigValidationError, match="不允许在 preset 层"):
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
    with pytest.raises(LayoutConfigValidationError, match="包含非法取值"):
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
            {"id": "table", "component": "data-table"},
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

    chart_layout = {"slots": [{"id": "chart", "component": "chart"}]}
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


def test_component_config_page_user_priority(client):
    repo = LayoutConfigRepo(client)
    board_layout = {"slots": [{"id": "table", "component": "data-table"}]}
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
    """P11/P13：settings-drawer 默认折叠态进入四层组件配置，页面默认 + 个人折叠可覆盖。"""
    repo = LayoutConfigRepo(client)
    layout = {"slots": [{"id": "settings", "component": "settings-drawer"}]}
    repo.set_page_config(
        "board",
        config={
            "values": {
                "slots.settings.config.size": "lg",
                "slots.settings.config.bodyScroll": False,
                "slots.settings.config.collapsibleSections": True,
                "slots.settings.config.defaultCollapsed": ["components"],
            }
        },
        layout=layout,
    )
    repo.set_user_config(
        "board",
        {"values": {"slots.settings.config.defaultCollapsed": ["layout", "business"]}},
        user_id="u1",
        layout=layout,
    )
    with pytest.raises(LayoutConfigValidationError, match="不允许在 user 层"):
        repo.set_user_config(
            "board",
            {"values": {"slots.settings.config.bodyScroll": False}},
            user_id="u2",
            layout=layout,
        )

    eff = repo.effective_config("board", user_id="u1")
    assert eff["values"]["slots.settings.config.size"] == "lg"
    assert eff["values"]["slots.settings.config.bodyScroll"] is False
    assert eff["values"]["slots.settings.config.collapsibleSections"] is True
    assert eff["source"]["slots.settings.config.collapsibleSections"] == "page"
    assert eff["values"]["slots.settings.config.defaultCollapsed"] == ["layout", "business"]
    assert eff["source"]["slots.settings.config.defaultCollapsed"] == "user"


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
            }, ensure_ascii=False),
            1,
        ],
    )

    try:
        eff = repo.effective_config("board", user_id="u-stale")
        assert eff["values"]["slots.settings.config.bodyScroll"] is True
        assert eff["source"]["slots.settings.config.bodyScroll"] == "page"
        assert eff["values"]["slots.settings.config.defaultCollapsed"] == ["layout"]
        assert eff["source"]["slots.settings.config.defaultCollapsed"] == "user"
        user_layer = next(layer for layer in eff["layers"] if layer["layer"] == "user")
        assert "slots.settings.config.bodyScroll" not in user_layer["config"]["values"]
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


def test_referenced_preset_cannot_be_disabled_or_deleted(client):
    repo = LayoutConfigRepo(client)
    repo.upsert_preset("dense-lab", "高密实验", config={"density": "compact"})
    repo.set_page_config("quality", preset_key="dense-lab", config={"density": "standard"})

    with pytest.raises(LayoutConfigValidationError, match="不能停用"):
        repo.upsert_preset("dense-lab", "高密实验", config={"density": "compact"}, enabled=False)
    with pytest.raises(LayoutConfigValidationError, match="不能删除"):
        repo.delete_preset("dense-lab")


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


def test_preset_per_mode_tokens_and_extras(client):
    """P11：预设支持按模式 token（light/dark/shared）+ 预设×组件默认 + 响应式默认（受控枚举）。"""
    repo = LayoutConfigRepo(client)
    saved = repo.upsert_preset(
        key="custom-x",
        name="自定义X",
        config={
            "values": {
                "tokens.light.primary": "#123456",
                "tokens.dark.primary": "#abcdef",
                "tokens.shared.cardRadius": 8,
                "componentFieldDefaults.data-table.pageSize": 50,
                "responsiveDefaults.reflowBreakpoint": 1100,
            }
        },
    )
    v = saved["config"]["values"]
    assert v["tokens.light.primary"] == "#123456"
    assert v["tokens.dark.primary"] == "#abcdef"
    assert v["tokens.shared.cardRadius"] == 8
    assert v["componentFieldDefaults.data-table.pageSize"] == 50
    assert v["responsiveDefaults.reflowBreakpoint"] == 1100


def test_preset_rejects_bad_extras(client):
    """P11：非法模式/越界断点/非 preset 层字段被拒。"""
    repo = LayoutConfigRepo(client)
    with pytest.raises(LayoutConfigValidationError, match="token 路径"):
        repo.upsert_preset("p1", "P1", config={"values": {"tokens.mid.primary": "#fff"}})
    with pytest.raises(LayoutConfigValidationError, match="#RRGGBB"):
        repo.upsert_preset(
            "bad-color",
            "非法颜色",
            config={"values": {"tokens.light.primary": "#fff"}},
        )
    with pytest.raises(LayoutConfigValidationError, match="必须成对覆盖"):
        repo.upsert_preset(
            "partial-text",
            "不完整文字层级",
            config={"values": {"tokens.dark.textMuted": "#c9d0d3"}},
        )
    with pytest.raises(LayoutConfigValidationError, match="相对亮度差"):
        repo.upsert_preset(
            "flat-text",
            "无文字层级",
            config={
                "values": {
                    "tokens.dark.text": "#8899aa",
                    "tokens.dark.textMuted": "#8899aa",
                }
            },
        )
    with pytest.raises(LayoutConfigValidationError, match="仅允许"):
        repo.upsert_preset("p2", "P2", config={"values": {"responsiveDefaults.reflowBreakpoint": 999}})
    # defaultSort 不允许 preset 层（仅 page/user）→ 预设组件默认拒绝
    with pytest.raises(LayoutConfigValidationError, match="不支持预设层默认"):
        repo.upsert_preset("p3", "P3", config={"values": {"componentFieldDefaults.data-table.defaultSort": "x"}})


def test_field_policy_table_and_defaults(client):
    """P10：开放策略表存在；缺覆盖时回落代码最大集，overridden=False。"""
    assert "layout_field_policy" in set(list_tables(client))
    repo = LayoutConfigRepo(client)
    policies = {(p["componentKind"], p["field"]): p for p in repo.list_field_policies()}
    page_size = policies[("data-table", "pageSize")]
    assert page_size["maxLayers"] == ["preset", "page", "user"]
    assert page_size["allowedLayers"] == ["preset", "page", "user"]
    assert page_size["overridden"] is False


def test_field_policy_narrow_enforced_on_save(client):
    """P10：管理员把 pageSize 收紧为仅 page 后，user 层覆盖被拒、page 层仍可保存。"""
    repo = LayoutConfigRepo(client)
    board_layout = {"slots": [{"id": "table", "component": "data-table"}]}
    repo.set_field_policy("data-table", "pageSize", ["page"])

    with pytest.raises(LayoutConfigValidationError, match="开放策略不允许在 user 层"):
        repo.set_user_config(
            "board", {"values": {"slots.table.config.pageSize": 100}}, user_id="u1", layout=board_layout
        )
    saved = repo.set_page_config(
        "board", {"values": {"slots.table.config.pageSize": 50}}, layout=board_layout
    )
    assert saved["config"]["values"]["slots.table.config.pageSize"] == 50


def test_field_policy_exceed_max_rejected(client):
    """P10：开放到代码最大集之外（defaultSort 最大集为 page/user，preset 越界）被拒。"""
    repo = LayoutConfigRepo(client)
    with pytest.raises(LayoutConfigValidationError, match="超出代码最大集"):
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
    assert reset["allowedLayers"] == ["preset", "page", "user"]


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
    r1 = api.post(
        "/api/layout/pages/board",
        json={"presetKey": "balanced", "config": {"values": {"slots.table.minH": 420}}},
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
