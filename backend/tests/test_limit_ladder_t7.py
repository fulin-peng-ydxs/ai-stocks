"""T7: limit-ladder page entry and RBAC deployment contracts."""

from pathlib import Path

from backend.auth.constants import (
    BUSINESS_RESOURCE_CODES,
    EXPLICIT_SYSTEM_ONLY_RESOURCE_CODES,
    STAGED_FRONTEND_MENU_CODES,
)
from backend.storage.pg_ddl import (
    _BUSINESS_MENU_CODES,
    _SEED_MENU_TREE,
    _SEED_RESOURCES,
    _flatten_menu_tree,
)

ROOT = Path(__file__).resolve().parents[2]


def test_limit_ladder_menu_and_resources_have_correct_authorization_anchors():
    menus = {row["code"]: row for row in _flatten_menu_tree(_SEED_MENU_TREE)}
    resources = {row[1]: row for row in _SEED_RESOURCES}

    menu = menus["/limit-ladder"]
    assert menu["parent_code"] == "quotes"
    assert menu["route_path"] == "/limit-ladder"
    assert menu["visible"] == "login"

    view = resources["limit-ladder:view"]
    recompute = resources["limit-ladder:recompute"]
    assert view[0] == "/limit-ladder" and view[4:] == ("GET", "/api/limit-ladder/{trade_date}")
    assert recompute[0] == "/limit-ladder"
    assert recompute[4:] == ("POST", "/api/limit-ladder/{trade_date}/recompute")
    assert "limit-ladder:recompute" in EXPLICIT_SYSTEM_ONLY_RESOURCE_CODES


def test_default_grants_only_include_view_and_completed_t10_menu_is_released():
    assert "/limit-ladder" in _BUSINESS_MENU_CODES
    assert "limit-ladder:view" in BUSINESS_RESOURCE_CODES
    assert "limit-ladder:recompute" not in BUSINESS_RESOURCE_CODES
    assert "/limit-ladder" not in STAGED_FRONTEND_MENU_CODES


def test_rbac_upgrade_is_marker_guarded_append_only_and_invalidates_permissions():
    sql = (ROOT / "agent-works/limit-up-ladder/limit-ladder-rbac.sql").read_text()
    normalized = " ".join(sql.lower().split())

    assert "migration.limit_ladder_rbac_v1" in sql
    assert "pg_advisory_xact_lock" in sql
    assert "on conflict do nothing" in normalized
    assert "perm_ver=perm_ver+1" in normalized
    assert "inserted_role_resources" in sql
    assert "update sys_menu" not in normalized
    assert "update sys_resource" not in normalized
    assert "delete from sys_menu" not in normalized
    assert "delete from sys_resource" not in normalized


def test_recompute_permission_is_visible_under_ladder_but_locked_for_non_system_roles():
    role_source = (ROOT / "frontend/src/views/system/RoleManageView.vue").read_text()
    menu_source = (ROOT / "frontend/src/views/system/MenuResourceView.vue").read_text()
    api_source = (ROOT / "frontend/src/api/menu.ts").read_text()

    assert "locked || !!res.system_locked" in role_source
    assert "r.system_locked" not in menu_source
    assert "mr-resource-name" not in menu_source
    assert "system_locked?: boolean" in api_source


def test_forward_and_rollback_sql_are_marker_owned_and_fail_closed():
    audit_sql = (
        ROOT / "agent-works/limit-up-ladder/limit-ladder-audit-ledger.sql"
    ).read_text()
    rollback_sql = (
        ROOT / "agent-works/limit-up-ladder/rollback-limit-ladder.sql"
    ).read_text()
    audit_normalized = " ".join(audit_sql.lower().split())
    rollback_normalized = " ".join(rollback_sql.lower().split())

    assert "migration.limit_ladder_audit_ledger_v1" in audit_sql
    assert "created_audit_column" in audit_sql
    assert "created_ledger_table" in audit_sql
    assert "pg_advisory_xact_lock(8410010007)" in audit_normalized
    assert "where status='pending'" in rollback_normalized
    assert "存在账本外角色授权" in rollback_sql
    assert "已被其他业务复用" in rollback_sql
    assert "perm_ver=perm_ver+1" in rollback_normalized
    assert "drop table if exists limit_ladder_audit_outbox" in rollback_normalized
    assert "drop table if exists limit_ladder_snapshot_stock" in rollback_normalized


def test_page_file_precedes_route_and_registry_registration():
    page = ROOT / "frontend/src/views/LimitLadderView.vue"
    router = (ROOT / "frontend/src/router/index.ts").read_text()
    registry = (ROOT / "frontend/src/layout/pageRegistry.ts").read_text()

    assert page.is_file()
    source = page.read_text()
    assert "<LayoutHost" in source and "getPageLayout('limit-ladder')" in source
    assert "<MarketMasterDetailWorkspace" in source
    assert "<AppStateBlock" in source
    assert "<PageSettingsDrawer" in source
    assert "data-scaffold-placeholder" not in source
    assert "<StockAnalysisPanel" in source
    assert 'size="full"' in source
    assert "v-permission=\"'limit-ladder:recompute'\"" in source
    assert "recomputeLimitLadder" in source
    assert "name: 'limit-ladder'" in router
    assert "component: () => import('@/views/LimitLadderView.vue')" in router
    assert "pageKey: 'limit-ladder'" in registry
