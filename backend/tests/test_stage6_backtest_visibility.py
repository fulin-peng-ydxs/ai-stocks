"""阶段六 T8：回测记录公开、只读保护和子表真实归属读取。"""

from __future__ import annotations

from datetime import date, datetime
import json
import uuid

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


def _insert_run(pg, *, tenant: str, owner: str, run_id: str, status: str = "done") -> None:
    params = {
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
        "id, tenant_id, owner_user_id, kind, date_start, date_end, params, status, "
        "created_at, finished_at) VALUES (%s,%s,%s,'strategy',%s,%s,%s,%s,%s,%s)",
        [
            run_id,
            tenant,
            owner,
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
    try:
        _insert_run(pg, tenant=tenant, owner=owner, run_id=run_id)
        _insert_run(pg, tenant=tenant, owner=owner, run_id=failed_run_id, status="failed")

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
