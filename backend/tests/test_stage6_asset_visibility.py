"""阶段六 T5：通用资产可见性 helper。"""

from __future__ import annotations

import pytest

from backend.services.asset_visibility import (
    ASSET_BACKTEST_RUN,
    ASSET_SCREEN_PROFILE,
    ASSET_TRADE_PROFILE,
    VISIBILITY_PRIVATE,
    VISIBILITY_PUBLIC,
    VISIBILITY_TENANT,
    AssetRef,
    asset_source,
    decorate_asset_row,
    is_asset_visible,
    make_asset_ref,
    parse_asset_ref,
    resolve_asset_ref_or_legacy_id,
    visible_params,
    visible_sql,
)


def test_stage6_asset_ref_roundtrip_and_type_mismatch_rejected():
    ref = make_asset_ref(ASSET_SCREEN_PROFILE, "tenant_a", "owner_a", "profile_1")

    parsed = parse_asset_ref(ref, expected_type=ASSET_SCREEN_PROFILE)

    assert parsed == AssetRef(ASSET_SCREEN_PROFILE, "tenant_a", "owner_a", "profile_1")
    with pytest.raises(ValueError, match="类型不匹配"):
        parse_asset_ref(ref, expected_type=ASSET_TRADE_PROFILE)


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
    assert tenant_out["owner_label"] == "owner_b"
    assert tenant_out["tenant_id"] == "tenant_a"
    assert asset_source(preset, tenant_id="tenant_a", owner_user_id="owner_a") == "preset"


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
