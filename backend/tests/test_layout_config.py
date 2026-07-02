"""可配置布局系统 M4：后端持久化、校验和 API。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import backend.storage.duckdb_client as dc
from backend.main import app
from backend.storage.ddl import init_db, list_tables
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.layout_config import LayoutConfigRepo, LayoutConfigValidationError


@pytest.fixture()
def client(tmp_path, monkeypatch):
    c = DuckDBClient(db_path=str(tmp_path / "layout.duckdb"))
    init_db(c)
    monkeypatch.setattr(dc, "_client", c)
    yield c
    c.close()
    monkeypatch.setattr(dc, "_client", None)


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


def test_builtin_presets_seed_and_custom_preset_roundtrip(client):
    repo = LayoutConfigRepo(client)
    keys = {p["key"] for p in repo.list_presets()}
    assert {"professional", "government", "technology", "finance", "high-contrast"} <= keys

    saved = repo.upsert_preset(
        key="dense-lab",
        name="高密实验",
        config={"values": {"density": "compact"}},
    )
    assert saved["config"]["values"]["density"] == "compact"
    assert repo.get_preset("dense-lab")["name"] == "高密实验"


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
        preset_key="finance",
        config={"values": {"slots.table.minH": 360, "density": "standard"}},
    )
    repo.set_user_config("board", {"values": {"density": "comfortable"}}, user_id="u1")

    effective = repo.effective_config("board", user_id="u1")
    assert effective["presetKey"] == "finance"
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
    # 组件配置：取值域
    with pytest.raises(LayoutConfigValidationError, match="不能小于"):
        repo.set_page_config("board", {"values": {"slots.table.config.pageSize": 5}})
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

    eff = repo.effective_config("board", user_id="u1")
    assert eff["values"]["slots.settings.config.size"] == "lg"
    assert eff["values"]["slots.settings.config.bodyScroll"] is False
    assert eff["values"]["slots.settings.config.collapsibleSections"] is True
    assert eff["source"]["slots.settings.config.collapsibleSections"] == "page"
    assert eff["values"]["slots.settings.config.defaultCollapsed"] == ["layout", "business"]
    assert eff["source"]["slots.settings.config.defaultCollapsed"] == "user"


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
        json={"presetKey": "finance", "config": {"values": {"slots.table.minH": 420}}},
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
