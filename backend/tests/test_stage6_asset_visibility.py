"""阶段六 T5：通用资产可见性 helper。"""

from __future__ import annotations

import pytest

from backend.services.asset_visibility import (
    ASSET_BACKTEST_RUN,
    ASSET_SCREEN_PROFILE,
    ASSET_TRADE_PROFILE,
    SCOPE_MINE,
    SCOPE_PRESET,
    SCOPE_PUBLIC,
    SCOPE_TENANT,
    VISIBILITY_PRIVATE,
    VISIBILITY_PUBLIC,
    VISIBILITY_TENANT,
    AssetRef,
    asset_source,
    decorate_asset_row,
    is_asset_visible,
    make_asset_ref,
    parse_asset_ref,
    publish_platform_presets,
    resolve_asset_ref_or_legacy_id,
    scoped_where,
    summarize_asset_row,
    summarize_backtest_row,
    visible_params,
    visible_sql,
)

_SLOT = ("default", "admin")


class _CapturePG:
    """记录平台预设校准 SQL，避免单元测试依赖真实数据库。"""

    def __init__(self):
        self.calls: list[tuple[str, list]] = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return 2


def test_publish_platform_presets_is_scoped_and_allowlisted():
    pg = _CapturePG()
    assert publish_platform_presets(
        pg,
        table="screen_profile",
        preset_ids=["preset_a", "preset_b"],
        tenant_id="default",
        owner_user_id="admin",
        public_board_owner=_SLOT,
    ) == 2
    sql, params = pg.calls[0]
    assert "tenant_id=%s AND owner_user_id=%s" in sql
    assert "id IN (%s,%s)" in sql
    assert params == ["admin", "default", "admin", "preset_a", "preset_b", "admin"]

    assert publish_platform_presets(
        pg,
        table="screen_profile",
        preset_ids=["preset_a"],
        tenant_id="tenant_a",
        owner_user_id="owner_a",
        public_board_owner=_SLOT,
    ) == 0
    assert len(pg.calls) == 1
    with pytest.raises(ValueError, match="不支持的平台预设表"):
        publish_platform_presets(
            pg,
            table="unsafe_table",
            preset_ids=["preset_a"],
            tenant_id="default",
            owner_user_id="admin",
            public_board_owner=_SLOT,
        )


def test_stage6_asset_ref_roundtrip_and_type_mismatch_rejected():
    ref = make_asset_ref(ASSET_SCREEN_PROFILE, "tenant_a", "owner_a", "profile_1")

    parsed = parse_asset_ref(ref, expected_type=ASSET_SCREEN_PROFILE)

    assert parsed == AssetRef(ASSET_SCREEN_PROFILE, "tenant_a", "owner_a", "profile_1")
    with pytest.raises(ValueError, match="类型不匹配"):
        parse_asset_ref(ref, expected_type=ASSET_TRADE_PROFILE)


def test_asset_reference_rejects_wrong_python_type_separately_from_invalid_value():
    with pytest.raises(TypeError, match="不是有效的资产引用"):
        parse_asset_ref(None)
    with pytest.raises(ValueError, match="不是有效的资产引用"):
        parse_asset_ref("invalid-ref")


def test_stage6_asset_ref_legacy_id_resolves_to_current_owner_only():
    parsed = resolve_asset_ref_or_legacy_id(
        "legacy_profile_id",
        asset_type=ASSET_TRADE_PROFILE,
        tenant_id="tenant_a",
        owner_user_id="owner_a",
    )

    assert parsed == AssetRef(ASSET_TRADE_PROFILE, "tenant_a", "owner_a", "legacy_profile_id")
    bad_ref = "avr_not-base64"
    with pytest.raises(ValueError, match="资产引用"):
        resolve_asset_ref_or_legacy_id(
            bad_ref,
            asset_type=ASSET_TRADE_PROFILE,
            tenant_id="tenant_a",
            owner_user_id="owner_a",
        )


@pytest.mark.parametrize(
    ("row", "visible"),
    [
        ({"tenant_id": "tenant_a", "owner_user_id": "owner_a", "visibility": VISIBILITY_PRIVATE}, True),
        ({"tenant_id": "tenant_a", "owner_user_id": "owner_b", "visibility": VISIBILITY_TENANT}, True),
        ({"tenant_id": "tenant_b", "owner_user_id": "owner_b", "visibility": VISIBILITY_TENANT}, False),
        ({"tenant_id": "tenant_b", "owner_user_id": "owner_b", "visibility": VISIBILITY_PUBLIC}, True),
        ({"tenant_id": "tenant_a", "owner_user_id": "owner_b", "visibility": VISIBILITY_PRIVATE}, False),
    ],
)
def test_stage6_asset_visible_rules(row, visible):
    assert is_asset_visible(row, tenant_id="tenant_a", owner_user_id="owner_a") is visible


def test_stage6_asset_decorate_row_outputs_source_readonly_and_ref():
    mine = {
        "id": "screen_1",
        "tenant_id": "tenant_a",
        "owner_user_id": "owner_a",
        "visibility": VISIBILITY_PRIVATE,
        "is_preset": False,
        "name": "我的筛选",
    }
    tenant_public = {
        "id": "bt_1",
        "tenant_id": "tenant_a",
        "owner_user_id": "owner_b",
        "visibility": VISIBILITY_TENANT,
        "is_preset": False,
    }
    preset = {
        "id": "trade_default",
        "tenant_id": "tenant_b",
        "owner_user_id": "system",
        "visibility": VISIBILITY_PUBLIC,
        "is_preset": True,
    }

    mine_out = decorate_asset_row(
        mine,
        asset_type=ASSET_SCREEN_PROFILE,
        tenant_id="tenant_a",
        owner_user_id="owner_a",
    )
    tenant_out = decorate_asset_row(
        tenant_public,
        asset_type=ASSET_BACKTEST_RUN,
        tenant_id="tenant_a",
        owner_user_id="owner_a",
        include_owner=True,
    )

    assert mine_out["source"] == "mine"
    assert mine_out["readonly"] is False
    assert mine_out["owner_label"] == "我"
    assert "tenant_id" not in mine_out
    assert parse_asset_ref(mine_out["asset_ref"], expected_type=ASSET_SCREEN_PROFILE).asset_id == "screen_1"
    assert tenant_out["source"] == VISIBILITY_TENANT
    assert tenant_out["readonly"] is True
    assert tenant_out["owner_label"] == "同租户用户"  # 同租户他人脱敏,不回显内部 user_id(P5)
    assert tenant_out["tenant_id"] == "tenant_a"
    assert asset_source(preset, tenant_id="tenant_a", owner_user_id="owner_a") == "preset"


def test_stage6_asset_owner_label_masks_cross_tenant_public_owner():
    public_cross_tenant = {
        "id": "bt_public_1",
        "tenant_id": "tenant_b",
        "owner_user_id": "owner_b",
        "visibility": VISIBILITY_PUBLIC,
        "is_preset": False,
    }

    out = decorate_asset_row(
        public_cross_tenant,
        asset_type=ASSET_BACKTEST_RUN,
        tenant_id="tenant_a",
        owner_user_id="owner_a",
    )

    assert out["source"] == VISIBILITY_PUBLIC
    assert out["readonly"] is True
    assert out["owner_label"] == "其他租户用户"
    assert "owner_b" not in out.values()


def test_stage6_asset_visible_sql_fragment_and_params():
    assert visible_sql("p") == (
        "((p.tenant_id=%s AND p.owner_user_id=%s) "
        "OR p.visibility='public' "
        "OR (p.visibility='tenant' AND p.tenant_id=%s))"
    )
    assert visible_params(tenant_id="tenant_a", owner_user_id="owner_a") == [
        "tenant_a",
        "owner_a",
        "tenant_a",
    ]


# ── T1A：四来源互斥取数口径 scoped_where ─────────────────────────────
def _scoped(source, alias="p", has_preset=True):
    return scoped_where(
        source,
        tenant_id="tenant_a",
        owner_user_id="owner_a",
        public_board_owner=_SLOT,
        alias=alias,
        has_preset=has_preset,
    )


def test_scoped_where_mine_excludes_platform_slot_preset():
    # 方案类 mine：纯 owner，且强制排除平台槽全部预设。历史 private preset 也不能
    # 泄漏到平台管理员下拉；其公开状态由统一 seed 修复。
    sql, params = _scoped(SCOPE_MINE)
    assert sql == (
        "(p.tenant_id=%s AND p.owner_user_id=%s "
        "AND NOT (p.is_preset=true AND p.tenant_id=%s AND p.owner_user_id=%s))"
    )
    assert params == ["tenant_a", "owner_a", "default", "admin"]


def test_scoped_where_preset_strict_public_platform_slot():
    sql, params = _scoped(SCOPE_PRESET)
    # 系统内置段：严格 is_preset AND public AND 平台槽，永不泄露 private
    assert sql == (
        "(p.is_preset=true AND p.visibility='public' "
        "AND p.tenant_id=%s AND p.owner_user_id=%s)"
    )
    assert params == ["default", "admin"]


def test_scoped_where_tenant_excludes_self():
    sql, params = _scoped(SCOPE_TENANT)
    assert sql == (
        "(p.visibility='tenant' AND p.tenant_id=%s "
        "AND NOT (p.tenant_id=%s AND p.owner_user_id=%s))"
    )
    assert params == ["tenant_a", "tenant_a", "owner_a"]


def test_scoped_where_public_force_excludes_platform_slot_preset():
    sql, params = _scoped(SCOPE_PUBLIC)
    # 强制补集：平台槽公开预设只归 preset 段，从 public 段剔除 → 四段互斥
    assert sql == (
        "(p.visibility='public' AND NOT (p.tenant_id=%s AND p.owner_user_id=%s) "
        "AND NOT (p.is_preset=true AND p.tenant_id=%s AND p.owner_user_id=%s))"
    )
    assert params == ["tenant_a", "owner_a", "default", "admin"]


def test_scoped_where_backtest_has_no_preset_source():
    # 回测无 is_preset：preset 段不支持
    with pytest.raises(ValueError, match="系统内置"):
        _scoped(SCOPE_PRESET, has_preset=False)
    # public 段省略平台槽预设补集（无 is_preset 列，避免 SQL 报错）
    sql, params = _scoped(SCOPE_PUBLIC, has_preset=False)
    assert sql == "(p.visibility='public' AND NOT (p.tenant_id=%s AND p.owner_user_id=%s))"
    assert params == ["tenant_a", "owner_a"]
    assert "is_preset" not in sql
    # mine 段同样省略预设补集：回测无 is_preset，退化为纯 owner
    mine_sql, mine_params = _scoped(SCOPE_MINE, has_preset=False)
    assert mine_sql == "(p.tenant_id=%s AND p.owner_user_id=%s)"
    assert mine_params == ["tenant_a", "owner_a"]
    assert "is_preset" not in mine_sql


def test_scoped_where_rejects_unknown_source():
    with pytest.raises(ValueError, match="来源"):
        _scoped("favorite")


def test_scoped_where_no_alias():
    sql, _ = _scoped(SCOPE_MINE, alias="", has_preset=False)
    assert sql == "(tenant_id=%s AND owner_user_id=%s)"


# ── T1A：summary 字段契约 ──────────────────────────────────────────
def test_summarize_asset_row_includes_updated_at():
    row = {
        "id": "score_1",
        "tenant_id": "tenant_a",
        "owner_user_id": "owner_a",
        "name": "我的评分",
        "version": 3,
        "is_preset": False,
        "visibility": VISIBILITY_PRIVATE,
        "updated_at": "2026-07-27 10:00:00",
    }
    summary = summarize_asset_row(
        row, asset_type=ASSET_SCREEN_PROFILE, tenant_id="tenant_a", owner_user_id="owner_a"
    )
    assert summary["updated_at"] == "2026-07-27 10:00:00"
    assert summary["version"] == 3
    # 缺列时回退 None，不抛错
    row.pop("updated_at")
    summary2 = summarize_asset_row(
        row, asset_type=ASSET_SCREEN_PROFILE, tenant_id="tenant_a", owner_user_id="owner_a"
    )
    assert summary2["updated_at"] is None


def test_summarize_backtest_row_independent_fields_and_owner_masked():
    row = {
        "id": "bt_1",
        "tenant_id": "tenant_b",
        "owner_user_id": "owner_b",
        "visibility": VISIBILITY_PUBLIC,
        "kind": "strategy",
        "date_start": "2025-01-01",
        "date_end": "2025-06-30",
        "status": "success",
        "created_at": "2026-07-01 09:00:00",
        "finished_at": "2026-07-01 09:05:00",
        "score_profile_name": "趋势分",
        "trade_profile_name": "均线卖出",
        "profile_name": "龙头筛选",
    }
    summary = summarize_backtest_row(
        row, tenant_id="tenant_a", owner_user_id="owner_a"
    )
    # 回测独立字段：无 name/version/is_preset
    assert "name" not in summary and "version" not in summary and "is_preset" not in summary
    assert summary["kind"] == "strategy"
    assert summary["date_start"] == "2025-01-01" and summary["date_end"] == "2025-06-30"
    assert summary["status"] == "success"
    assert summary["source"] == VISIBILITY_PUBLIC and summary["readonly"] is True
    # owner 脱敏：不回显真实 tenant/user
    assert summary["owner_label"] == "其他租户用户"
    assert "owner_b" not in summary.values() and "tenant_b" not in summary.values()
    # run_ref 可解析回原 id
    assert parse_asset_ref(summary["run_ref"], expected_type=ASSET_BACKTEST_RUN).asset_id == "bt_1"
    # 透传三类引用方案名供关键字/展示
    assert summary["score_profile_name"] == "趋势分"
