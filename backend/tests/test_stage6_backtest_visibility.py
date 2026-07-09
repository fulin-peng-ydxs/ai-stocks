"""阶段六 T8：回测记录公开、只读保护和子表真实归属读取。"""

from __future__ import annotations

from datetime import date, datetime
import json
import uuid

import pandas as pd
import pytest
from fastapi.testclient import TestClient

_SECRET = "test-secret-backtest-visibility-0123456789abcdef"


@pytest.fixture()
def client(monkeypatch, pg, redis_cli):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.main import create_app

    return TestClient(create_app())


def _auth(uid: str, tid: str, pv: int = 0) -> dict:
    from backend.auth.jwt_tokens import issue_access

    return {"Authorization": "Bearer " + issue_access(uid, tid, pv)}


def _mk_user(pg, codes: list[str], tenant: str | None = None) -> tuple[str, str, str]:
    tid = tenant or ("btv_t_" + uuid.uuid4().hex[:8])
    uid = "btv_u_" + uuid.uuid4().hex[:8]
    rid = "btv_r_" + uuid.uuid4().hex[:8]
    pg.execute(
        "INSERT INTO sys_tenant (id,name,status) VALUES (%s,'t','active') ON CONFLICT DO NOTHING",
        [tid],
    )
    pg.execute(
        "INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
        "VALUES (%s,%s,%s,'normal',0,'active')",
        [uid, tid, uid],
    )
    pg.execute(
        "INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
        "VALUES (%s,%s,'btv','custom',FALSE,FALSE)",
        [rid, rid],
    )
    pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)", [uid, rid])
    for code in codes:
        pg.execute(
            "INSERT INTO sys_role_resource (role_id,resource_id) VALUES (%s,%s) "
            "ON CONFLICT DO NOTHING",
            [rid, code],
        )
    return uid, tid, rid


def _rm_user(pg, uid: str, tid: str, rid: str) -> None:
    pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    pg.execute("DELETE FROM sys_role WHERE id=%s", [rid])
    pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])


def _insert_run(
    pg,
    *,
    tenant: str,
    owner: str,
    run_id: str,
    status: str = "done",
    params: dict | None = None,
) -> None:
    params = params or {
        "date_start": "2024-01-01",
        "date_end": "2024-01-31",
        "profile_id": None,
        "score_profile_id": None,
        "trade_profile_id": None,
        "top_n": 5,
        "initial_capital": 1000000,
    }
    now = datetime(2024, 2, 1, 9, 30)
    pg.execute(
        "INSERT INTO backtest_run ("
        "id, tenant_id, owner_user_id, kind, profile_id, score_profile_id, trade_profile_id, "
        "date_start, date_end, params, status, created_at, finished_at) "
        "VALUES (%s,%s,%s,'strategy',%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        [
            run_id,
            tenant,
            owner,
            params.get("profile_id"),
            params.get("score_profile_id"),
            params.get("trade_profile_id"),
            date(2024, 1, 1),
            date(2024, 1, 31),
            json.dumps(params),
            status,
            now,
            now,
        ],
    )
    pg.execute(
        "INSERT INTO backtest_metrics ("
        "run_id, tenant_id, owner_user_id, total_return, hit_rate_by_grade) "
        "VALUES (%s,%s,%s,%s,%s)",
        [
            run_id,
            tenant,
            owner,
            0.12,
            json.dumps(
                {
                    "horizons": [10],
                    "thresholds": [0.1],
                    "min_samples": 30,
                    "total_signals": 1,
                    "base_rate": {},
                    "by_grade": {},
                    "grades_order": [],
                },
            ),
        ],
    )
    pg.execute(
        "INSERT INTO backtest_equity ("
        "run_id, tenant_id, owner_user_id, trade_date, equity, cash, position_value, "
        "n_positions, drawdown, benchmark_equity) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        [run_id, tenant, owner, date(2024, 1, 2), 1010000, 1000, 1009000, 1, 0, 1000000],
    )
    pg.execute(
        "INSERT INTO backtest_trade ("
        "run_id, tenant_id, owner_user_id, seq, code, entry_date, entry_price, "
        "exit_date, exit_price, exit_reason, shares, return_pct, pnl, hold_days, grade) "
        "VALUES (%s,%s,%s,1,'000001.SZ',%s,10,%s,11,'take_profit',100,0.1,1000,5,'观察')",
        [run_id, tenant, owner, date(2024, 1, 2), date(2024, 1, 9)],
    )


def _cleanup_runs(pg, *owners: str) -> None:
    for owner in owners:
        for table in ("backtest_trade", "backtest_equity", "backtest_metrics", "backtest_run"):
            pg.execute(f"DELETE FROM {table} WHERE owner_user_id=%s", [owner])


def test_backtest_run_visibility_list_detail_and_owner_guards(client, pg):
    tenant = "bt_vis_tenant_" + uuid.uuid4().hex[:8]
    owner, tid, owner_role = _mk_user(
        pg,
        [
            "backtest:view",
            "backtest:delete",
            "backtest:publish-tenant",
        ],
        tenant=tenant,
    )
    viewer, _, viewer_role = _mk_user(pg, ["backtest:view", "backtest:delete"], tenant=tenant)
    outsider, otid, outsider_role = _mk_user(pg, ["backtest:view"])
    run_id = "bt_vis_" + uuid.uuid4().hex[:8]
    failed_run_id = "bt_failed_" + uuid.uuid4().hex[:8]
    viewer_run_id = "bt_no_publish_" + uuid.uuid4().hex[:8]
    try:
        _insert_run(pg, tenant=tenant, owner=owner, run_id=run_id)
        _insert_run(pg, tenant=tenant, owner=owner, run_id=failed_run_id, status="failed")
        _insert_run(pg, tenant=tenant, owner=viewer, run_id=viewer_run_id)

        bypass = client.post(
            f"/api/backtest/runs/{viewer_run_id}/visibility",
            json={"visibility": "tenant "},
            headers=_auth(viewer, tid),
        )
        assert bypass.status_code == 200 and bypass.json()["code"] == 403
        bypass_case = client.post(
            f"/api/backtest/runs/{viewer_run_id}/visibility",
            json={"visibility": "Tenant"},
            headers=_auth(viewer, tid),
        )
        assert bypass_case.status_code == 200 and bypass_case.json()["code"] == 403
        invalid = client.post(
            f"/api/backtest/runs/{viewer_run_id}/visibility",
            json={"visibility": "tenantx"},
            headers=_auth(viewer, tid),
        )
        assert invalid.status_code == 422
        row = pg.query_df(
            "SELECT visibility FROM backtest_run WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [tenant, viewer, viewer_run_id],
        )
        assert not row.empty and row.iloc[0]["visibility"] == "private"

        denied = client.post(
            f"/api/backtest/runs/{run_id}/visibility",
            json={"visibility": "public"},
            headers=_auth(owner, tid),
        )
        assert denied.status_code == 200 and denied.json()["code"] == 403

        failed_publish = client.post(
            f"/api/backtest/runs/{failed_run_id}/visibility",
            json={"visibility": "tenant"},
            headers=_auth(owner, tid),
        )
        assert failed_publish.status_code == 200 and failed_publish.json()["code"] == 400

        published = client.post(
            f"/api/backtest/runs/{run_id}/visibility",
            json={"visibility": "tenant"},
            headers=_auth(owner, tid),
        )
        assert published.status_code == 200 and published.json()["data"]["visibility"] == "tenant"
        run_ref = published.json()["data"]["run_ref"]
        assert run_ref.startswith("avr_")

        rows = client.get(
            "/api/backtest/runs?kind=strategy&source=tenant",
            headers=_auth(viewer, tid),
        ).json()["data"]["runs"]
        shared = next(r for r in rows if r["id"] == run_id)
        assert shared["readonly"] is True
        assert shared["source"] == "tenant"
        assert shared["run_ref"] == run_ref

        mine_rows = client.get(
            "/api/backtest/runs?kind=strategy&source=mine",
            headers=_auth(viewer, tid),
        ).json()["data"]["runs"]
        assert run_id not in {r["id"] for r in mine_rows}

        detail = client.get(f"/api/backtest/runs/{run_ref}", headers=_auth(viewer, tid))
        assert detail.status_code == 200
        data = detail.json()["data"]
        assert data["run"]["readonly"] is True
        assert data["equity"][0]["equity"] == 1010000
        assert data["trades"][0]["code"] == "000001.SZ"

        delete_denied = client.delete(f"/api/backtest/runs/{run_ref}", headers=_auth(viewer, tid))
        assert delete_denied.status_code == 200 and delete_denied.json()["code"] == 403

        publish_denied = client.post(
            f"/api/backtest/runs/{run_ref}/visibility",
            json={"visibility": "private"},
            headers=_auth(viewer, tid),
        )
        assert publish_denied.status_code == 200 and publish_denied.json()["code"] == 403

        outsider_rows = client.get(
            "/api/backtest/runs?kind=strategy",
            headers=_auth(outsider, otid),
        ).json()["data"]["runs"]
        assert run_id not in {r["id"] for r in outsider_rows}
    finally:
        _cleanup_runs(pg, owner, viewer, outsider)
        _rm_user(pg, owner, tid, owner_role)
        _rm_user(pg, viewer, tid, viewer_role)
        _rm_user(pg, outsider, otid, outsider_role)


def test_viewer_reuses_public_backtest_params_into_own_run(pg, market, monkeypatch):
    from backend.auth.context import AuthContext, reset_context, set_context
    from backend.screening.profile import ProfileRepo
    from backend.services.backtest_service import BacktestService

    tenant = "bt_reuse_tenant_" + uuid.uuid4().hex[:8]
    owner = "bt_reuse_owner_" + uuid.uuid4().hex[:8]
    viewer = "bt_reuse_viewer_" + uuid.uuid4().hex[:8]
    source_run_id = "bt_reuse_src_" + uuid.uuid4().hex[:8]
    profile_id = "bt_reuse_screen_" + uuid.uuid4().hex[:6]
    try:
        profile_repo = ProfileRepo(pg=pg, tenant_id=tenant, owner_user_id=owner)
        profile_repo.save(
            profile_id,
            "公开回测筛选",
            {"type": "col", "field": "rs_pct", "cmp": ">=", "value": 90},
        )
        shared_profile = profile_repo.set_visibility(profile_id, "tenant", published_by=owner)

        _insert_run(pg, tenant=tenant, owner=owner, run_id=source_run_id)
        owner_svc = BacktestService(client=market, tenant_id=tenant, owner_user_id=owner)
        source = owner_svc.set_run_visibility(source_run_id, "tenant", published_by=owner)
        assert source is not None
        source_ref = source["run_ref"]

        eq = pd.DataFrame([
            {
                "trade_date": date(2024, 1, 1),
                "equity": 1000000.0,
                "cash": 1000000.0,
                "position_value": 0.0,
                "n_positions": 0,
                "drawdown": 0.0,
                "benchmark_equity": 1000000.0,
            },
            {
                "trade_date": date(2024, 1, 2),
                "equity": 1005000.0,
                "cash": 1005000.0,
                "position_value": 0.0,
                "n_positions": 0,
                "drawdown": 0.0,
                "benchmark_equity": 1000000.0,
            },
        ])

        def fake_run(self, params):  # noqa: ARG001
            assert params["profile_id"] == shared_profile["profile_ref"]
            return {
                "equity": eq,
                "trades": [],
                "benchmark_code": "000905.SH",
                "initial_capital": 1000000,
            }

        def fake_layers(self, *args, **kwargs):  # noqa: ARG001
            return {
                "horizons": [10],
                "thresholds": [0.1],
                "min_samples": 30,
                "total_signals": 0,
                "base_rate": {},
                "by_grade": {},
                "grades_order": [],
            }

        monkeypatch.setattr("backend.backtest.engine.BacktestEngine.run", fake_run)
        monkeypatch.setattr("backend.backtest.signal.SignalAnalyzer.analyze", fake_layers)

        token = set_context(AuthContext(user_id=viewer, tenant_id=tenant, resources={"backtest:run"}))
        try:
            viewer_svc = BacktestService(client=market, tenant_id=tenant, owner_user_id=viewer)
            result = viewer_svc.run_strategy({
                "date_start": "2024-01-01",
                "date_end": "2024-01-02",
                "profile_id": shared_profile["profile_ref"],
                "top_n": 5,
                "initial_capital": 1000000,
                "source_run_ref": source_ref,
            })
        finally:
            reset_context(token)

        row = pg.query_df(
            "SELECT owner_user_id, params FROM backtest_run "
            "WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
            [result["run_id"], tenant, viewer],
        )
        assert not row.empty
        params = json.loads(row.iloc[0]["params"])
        assert params["profile_id"] == shared_profile["profile_ref"]
        assert params["source_run_ref"] == source_ref

        audit = pg.query_df(
            "SELECT action, resource_code, target_type, target_id, context FROM audit_log "
            "WHERE tenant_id=%s AND actor_user_id=%s AND event_type='asset_reuse' "
            "AND action='backtest_run_reuse' AND target_id=%s",
            [tenant, viewer, result["run_id"]],
        )
        assert not audit.empty
        assert audit.iloc[0]["resource_code"] == "backtest:run"
    finally:
        _cleanup_runs(pg, owner, viewer)
        for owner_id in (owner, viewer):
            pg.execute("DELETE FROM screen_profile WHERE owner_user_id=%s", [owner_id])
            pg.execute("DELETE FROM screen_profile_version WHERE owner_user_id=%s", [owner_id])


def test_viewer_reuses_public_score_check_params_records_audit(pg, market, monkeypatch):
    from backend.auth.context import AuthContext, reset_context, set_context
    from backend.services.backtest_service import BacktestService

    tenant = "bt_reuse_signal_tenant_" + uuid.uuid4().hex[:8]
    owner = "bt_reuse_signal_owner_" + uuid.uuid4().hex[:8]
    viewer = "bt_reuse_signal_viewer_" + uuid.uuid4().hex[:8]
    source_run_id = "bt_reuse_signal_src_" + uuid.uuid4().hex[:8]
    try:
        _insert_run(pg, tenant=tenant, owner=owner, run_id=source_run_id)
        source = BacktestService(
            client=market,
            tenant_id=tenant,
            owner_user_id=owner,
        ).set_run_visibility(source_run_id, "tenant", published_by=owner)
        assert source is not None

        def fake_analyze(self, *args, **kwargs):  # noqa: ARG001
            return {
                "date_start": "2024-01-01",
                "date_end": "2024-01-02",
                "model_id": "default",
                "horizons": [10],
                "thresholds": [0.1],
                "min_samples": 30,
                "total_signals": 0,
                "base_rate": {},
                "by_grade": {},
                "grades_order": [],
            }

        monkeypatch.setattr("backend.backtest.signal.SignalAnalyzer.analyze", fake_analyze)

        token = set_context(AuthContext(user_id=viewer, tenant_id=tenant, resources={"backtest:run"}))
        try:
            result = BacktestService(
                client=market,
                tenant_id=tenant,
                owner_user_id=viewer,
            ).run_signal({
                "date_start": "2024-01-01",
                "date_end": "2024-01-02",
                "horizons": [10],
                "thresholds": [0.1],
                "source_run_ref": source["run_ref"],
            })
        finally:
            reset_context(token)

        audit = pg.query_df(
            "SELECT action, resource_code, target_type, target_id, context FROM audit_log "
            "WHERE tenant_id=%s AND actor_user_id=%s AND event_type='asset_reuse' "
            "AND action='backtest_run_reuse' AND target_id=%s",
            [tenant, viewer, result["run_id"]],
        )
        assert not audit.empty
        assert audit.iloc[0]["resource_code"] == "backtest:run"
    finally:
        _cleanup_runs(pg, owner, viewer)


def test_public_backtest_publish_strips_source_run_ref_for_cross_tenant_viewer(pg, market):
    from backend.services.asset_visibility import ASSET_BACKTEST_RUN, make_asset_ref
    from backend.services.backtest_service import BacktestService

    owner_tenant = "bt_src_owner_tenant_" + uuid.uuid4().hex[:8]
    viewer_tenant = "bt_src_viewer_tenant_" + uuid.uuid4().hex[:8]
    owner = "bt_src_owner_" + uuid.uuid4().hex[:8]
    viewer = "bt_src_viewer_" + uuid.uuid4().hex[:8]
    source_run_id = "bt_src_private_" + uuid.uuid4().hex[:8]
    public_run_id = "bt_src_public_" + uuid.uuid4().hex[:8]
    source_run_ref = make_asset_ref(
        ASSET_BACKTEST_RUN,
        owner_tenant,
        owner,
        source_run_id,
    )
    params = {
        "date_start": "2024-01-01",
        "date_end": "2024-01-31",
        "top_n": 5,
        "initial_capital": 1000000,
        "source_run_ref": source_run_ref,
    }
    try:
        _insert_run(pg, tenant=owner_tenant, owner=owner, run_id=source_run_id)
        _insert_run(pg, tenant=owner_tenant, owner=owner, run_id=public_run_id, params=params)

        owner_svc = BacktestService(client=market, tenant_id=owner_tenant, owner_user_id=owner)
        published = owner_svc.set_run_visibility(public_run_id, "public", published_by=owner)
        assert published is not None and published["visibility"] == "public"

        stored = pg.query_df(
            "SELECT params FROM backtest_run WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [owner_tenant, owner, public_run_id],
        )
        stored_params = json.loads(stored.iloc[0]["params"])
        assert "source_run_ref" not in stored_params

        viewer_svc = BacktestService(client=market, tenant_id=viewer_tenant, owner_user_id=viewer)
        visible_run = viewer_svc.get_run(published["run_ref"])
        assert visible_run is not None
        visible_params = json.loads(visible_run["run"]["params"])
        assert "source_run_ref" not in visible_params
        assert source_run_ref not in json.dumps(visible_run, ensure_ascii=False, default=str)
    finally:
        _cleanup_runs(pg, owner, viewer)


def test_backtest_publish_requires_reusable_legacy_dependencies(pg, market):
    from backend.screening.profile import ProfileRepo
    from backend.services.backtest_service import BacktestService

    tenant = "bt_dep_tenant_" + uuid.uuid4().hex[:8]
    owner = "bt_dep_owner_" + uuid.uuid4().hex[:8]
    viewer = "bt_dep_viewer_" + uuid.uuid4().hex[:8]
    run_id = "bt_dep_run_" + uuid.uuid4().hex[:8]
    profile_id = "bt_dep_screen_" + uuid.uuid4().hex[:6]
    params = {
        "date_start": "2024-01-01",
        "date_end": "2024-01-31",
        "profile_id": profile_id,
        "top_n": 5,
        "initial_capital": 1000000,
    }
    try:
        profile_repo = ProfileRepo(pg=pg, tenant_id=tenant, owner_user_id=owner)
        profile_repo.save(
            profile_id,
            "私有 legacy 筛选",
            {"type": "col", "field": "rs_pct", "cmp": ">=", "value": 90},
        )
        viewer_profile_repo = ProfileRepo(pg=pg, tenant_id=tenant, owner_user_id=viewer)
        viewer_profile_repo.save(
            profile_id,
            "viewer 私有同名筛选",
            {"type": "col", "field": "pct_chg", "cmp": ">=", "value": 5},
        )
        _insert_run(pg, tenant=tenant, owner=owner, run_id=run_id, params=params)
        svc = BacktestService(client=market, tenant_id=tenant, owner_user_id=owner)

        with pytest.raises(ValueError, match="筛选方案"):
            svc.set_run_visibility(run_id, "tenant")
        row = pg.query_df(
            "SELECT visibility FROM backtest_run WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [tenant, owner, run_id],
        )
        assert row.iloc[0]["visibility"] == "private"

        shared_profile = profile_repo.set_visibility(profile_id, "tenant", published_by=owner)
        canonical_run_id = "bt_dep_canonical_" + uuid.uuid4().hex[:8]
        canonical_params = {**params, "profile_id": shared_profile["profile_ref"]}
        canonical_signature = svc._signature(
            "strategy",
            canonical_params,
            {
                "profile_version": int(shared_profile["version"]),
                "score_profile_version": None,
                "trade_profile_version": None,
            },
        )
        _insert_run(pg, tenant=tenant, owner=owner, run_id=canonical_run_id, params=canonical_params)
        pg.execute(
            "UPDATE backtest_run SET profile_id=%s, profile_version=%s, signature=%s "
            "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [
                shared_profile["profile_ref"],
                int(shared_profile["version"]),
                canonical_signature,
                tenant,
                owner,
                canonical_run_id,
            ],
        )

        published = svc.set_run_visibility(run_id, "tenant", published_by=owner)
        assert published is not None and published["visibility"] == "tenant"
        row = pg.query_df(
            "SELECT profile_id, profile_version, params, signature FROM backtest_run "
            "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [tenant, owner, run_id],
        )
        stored_params = json.loads(row.iloc[0]["params"])
        assert stored_params["profile_id"] == shared_profile["profile_ref"]
        assert row.iloc[0]["profile_id"] == shared_profile["profile_ref"]
        assert int(row.iloc[0]["profile_version"]) == int(shared_profile["version"])
        assert row.iloc[0]["signature"] == svc._signature(
            "strategy",
            stored_params,
            {
                "profile_version": int(shared_profile["version"]),
                "score_profile_version": None,
                "trade_profile_version": None,
            },
        )
        assert row.iloc[0]["signature"] == canonical_signature
        duplicates = pg.query_df(
            "SELECT id FROM backtest_run "
            "WHERE tenant_id=%s AND owner_user_id=%s AND signature=%s",
            [tenant, owner, canonical_signature],
        )
        assert set(duplicates["id"].tolist()) == {run_id}
        assert pg.query_df(
            "SELECT 1 FROM backtest_metrics "
            "WHERE tenant_id=%s AND owner_user_id=%s AND run_id=%s",
            [tenant, owner, canonical_run_id],
        ).empty

        viewer_svc = BacktestService(client=market, tenant_id=tenant, owner_user_id=viewer)
        visible_run = viewer_svc.get_run(published["run_ref"])
        visible_params = json.loads(visible_run["run"]["params"])
        assert visible_params["profile_id"] == shared_profile["profile_ref"]
        resolved_profile = viewer_svc._visible_screen_profile(visible_params["profile_id"])
        assert resolved_profile["owner_user_id"] == owner

        with pytest.raises(ValueError, match="公开到全体"):
            svc.set_run_visibility(run_id, "public")
    finally:
        _cleanup_runs(pg, owner, viewer)
        for owner_id in (owner, viewer):
            pg.execute("DELETE FROM screen_profile WHERE owner_user_id=%s", [owner_id])
            pg.execute("DELETE FROM screen_profile_version WHERE owner_user_id=%s", [owner_id])


def test_list_runs_batches_opaque_ref_profile_labels(pg, market, monkeypatch):
    from backend.scoring.score_profile import ScoreProfileRepo
    from backend.services.asset_visibility import ASSET_SCREEN_PROFILE, ASSET_TRADE_PROFILE, make_asset_ref
    from backend.services.backtest_service import BacktestService

    tenant = "bt_label_tenant_" + uuid.uuid4().hex[:8]
    owner = "bt_label_owner_" + uuid.uuid4().hex[:8]
    viewer = "bt_label_viewer_" + uuid.uuid4().hex[:8]
    run_id = "bt_label_run_" + uuid.uuid4().hex[:8]
    screen_id = "bt_label_screen_" + uuid.uuid4().hex[:6]
    score_id = "bt_label_score_" + uuid.uuid4().hex[:6]
    trade_id = "bt_label_trade_" + uuid.uuid4().hex[:6]
    screen_ref = make_asset_ref(ASSET_SCREEN_PROFILE, tenant, owner, screen_id)
    score_ref = ScoreProfileRepo.make_ref(tenant, owner, score_id)
    trade_ref = make_asset_ref(ASSET_TRADE_PROFILE, tenant, owner, trade_id)
    params = {
        "date_start": "2024-01-01",
        "date_end": "2024-01-31",
        "profile_id": screen_ref,
        "score_profile_id": score_ref,
        "trade_profile_id": trade_ref,
        "top_n": 5,
        "initial_capital": 1000000,
    }
    try:
        now = datetime(2024, 2, 1, 9, 30)
        pg.execute(
            "INSERT INTO screen_profile "
            "(id,tenant_id,owner_user_id,name,version,expression,is_preset,visibility,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,3,%s,FALSE,'tenant',%s,%s)",
            [screen_id, tenant, owner, "批量筛选", json.dumps({"type": "all"}), now, now],
        )
        pg.execute(
            "INSERT INTO score_profile "
            "(id,tenant_id,owner_user_id,name,version,items,grade_thresholds,is_preset,visibility,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,4,%s,%s,FALSE,'tenant',%s,%s)",
            [
                score_id,
                tenant,
                owner,
                "批量评分",
                json.dumps([]),
                json.dumps({"watch": 80}),
                now,
                now,
            ],
        )
        pg.execute(
            "INSERT INTO trade_profile "
            "(id,tenant_id,owner_user_id,name,version,buy_tree,sell_tree,backstop,is_preset,visibility,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,5,%s,%s,%s,FALSE,'tenant',%s,%s)",
            [
                trade_id,
                tenant,
                owner,
                "批量买卖",
                json.dumps({"type": "all"}),
                json.dumps({"type": "all"}),
                json.dumps({}),
                now,
                now,
            ],
        )
        _insert_run(pg, tenant=tenant, owner=owner, run_id=run_id, params=params)
        pg.execute(
            "UPDATE backtest_run SET visibility='tenant', profile_version=3, "
            "score_profile_version=4, trade_profile_version=5 "
            "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [tenant, owner, run_id],
        )

        def fail_n_plus_one(*args, **kwargs):  # noqa: ARG001
            raise AssertionError("list_runs must not resolve opaque profile labels row by row")

        svc = BacktestService(client=market, tenant_id=tenant, owner_user_id=viewer)
        monkeypatch.setattr(svc, "_visible_screen_profile", fail_n_plus_one)
        monkeypatch.setattr(svc, "_visible_score_profile", fail_n_plus_one)
        monkeypatch.setattr(svc, "_visible_trade_profile", fail_n_plus_one)

        rows = svc.list_runs(kind="strategy", source="tenant")
        row = next(r for r in rows if r["id"] == run_id)
        assert row["profile_name"] == "批量筛选"
        assert row["profile_version"] == 3
        assert row["score_profile_name"] == "批量评分"
        assert row["score_profile_version"] == 4
        assert row["trade_profile_name"] == "批量买卖"
        assert row["trade_profile_version"] == 5
    finally:
        _cleanup_runs(pg, owner, viewer)
        pg.execute("DELETE FROM screen_profile WHERE owner_user_id=%s", [owner])
        pg.execute("DELETE FROM screen_profile_version WHERE owner_user_id=%s", [owner])
        pg.execute("DELETE FROM score_profile WHERE owner_user_id=%s", [owner])
        pg.execute("DELETE FROM score_profile_version WHERE owner_user_id=%s", [owner])
        pg.execute("DELETE FROM trade_profile WHERE owner_user_id=%s", [owner])
        pg.execute("DELETE FROM trade_profile_version WHERE owner_user_id=%s", [owner])
