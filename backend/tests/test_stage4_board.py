"""阶段四 T3b：每日榜单公共特例（C1 已确认）。

覆盖：
- `board:view` / `board:compute` 守卫（无码 → 403，权限分离）；
- **公共读专项**：不同租户/用户读 `GET /api/scores/top` 得到**同一份**平台公共榜单（`PUBLIC_BOARD_OWNER`
  固定归属、不按当前用户过滤）——区别于私有资产的「跨账号不可见」隔离用例，故独立成文。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.storage.pg_ddl import PUBLIC_BOARD_OWNER

_SECRET = "test-secret-stage4-board-0123456789abcdef"   # ≥32B 免 HMAC 长度告警
_PUB_DATE = "2099-01-01"                       # 远期占位日，避开真实榜单数据；用后清理
_MODEL = "t3b_" + uuid.uuid4().hex[:8]         # 唯一 model_id，隔离本测数据


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.main import create_app
    return TestClient(create_app())


def _auth(uid: str, tid: str, pv: int = 0) -> dict:
    from backend.auth.jwt_tokens import issue_access
    return {"Authorization": "Bearer " + issue_access(uid, tid, pv)}


def _mk_user(pg, codes: list[str], tenant: str | None = None) -> tuple[str, str, str]:
    """建租户 + 用户 + 自定义角色（授予 codes）+ 关联，返回 (uid, tid, rid)。非 system。"""
    tid = tenant or ("s4t_" + uuid.uuid4().hex[:8])
    uid = "s4u_" + uuid.uuid4().hex[:8]
    rid = "s4r_" + uuid.uuid4().hex[:8]
    pg.execute("INSERT INTO sys_tenant (id,name,status) VALUES (%s,'t','active') ON CONFLICT DO NOTHING", [tid])
    pg.execute("INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
               "VALUES (%s,%s,%s,'normal',0,'active')", [uid, tid, uid])
    pg.execute("INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
               "VALUES (%s,%s,'t3b','custom',FALSE,FALSE)", [rid, rid])
    pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)", [uid, rid])
    for code in codes:
        pg.execute("INSERT INTO sys_role_resource (role_id,resource_id) VALUES (%s,%s) "
                   "ON CONFLICT DO NOTHING", [rid, code])
    return uid, tid, rid


def _rm_user(pg, uid: str, tid: str, rid: str) -> None:
    pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])       # CASCADE 清 user_role
    pg.execute("DELETE FROM sys_role WHERE id=%s", [rid])       # CASCADE 清 role_resource
    pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])


@pytest.fixture()
def public_board(pg):
    """在 PUBLIC_BOARD_OWNER（平台公共槽）下写一条公共榜单结果；用后清理。"""
    ptid, pown = PUBLIC_BOARD_OWNER
    pg.execute(
        "INSERT INTO score_result (trade_date, tenant_id, owner_user_id, model_id, code, "
        "total_score, sub_scores, rank, grade, buy_point, risk_flags) "
        "VALUES (%s,%s,%s,%s,'T3B000.SZ',88.0,NULL,1,'A',NULL,NULL) ON CONFLICT DO NOTHING",
        [_PUB_DATE, ptid, pown, _MODEL])
    yield
    pg.execute("DELETE FROM score_result WHERE model_id=%s", [_MODEL])


def test_scores_top_requires_board_view(client, pg):
    """无 board:view 的登录业务用户读榜单 → 403（baseline 注入不含 board:view）。"""
    uid, tid, rid = _mk_user(pg, codes=[])   # 仅 baseline，无 board:view
    try:
        r = client.get("/api/scores/top", headers=_auth(uid, tid))
        assert r.status_code == 403 and r.json()["code"] == 4030
    finally:
        _rm_user(pg, uid, tid, rid)


def test_board_public_read_shared_across_tenants(client, pg, public_board):
    """公共读专项：两个**不同租户**用户读同一 model_id → 都看到同一份平台公共榜单（非私有隔离）。"""
    ua, ta, ra = _mk_user(pg, codes=["board:view"])
    ub, tb, rb = _mk_user(pg, codes=["board:view"])
    assert ta != tb
    try:
        qa = client.get(f"/api/scores/top?date={_PUB_DATE}&model_id={_MODEL}&top=10", headers=_auth(ua, ta))
        qb = client.get(f"/api/scores/top?date={_PUB_DATE}&model_id={_MODEL}&top=10", headers=_auth(ub, tb))
        assert qa.status_code == 200 and qb.status_code == 200
        la = qa.json()["data"]["list"]
        lb = qb.json()["data"]["list"]
        # 有意不带用户归属过滤：两租户看到**同一份**公共结果（含刚写入的 T3B000.SZ）
        assert [x["code"] for x in la] == ["T3B000.SZ"]
        assert [x["code"] for x in lb] == ["T3B000.SZ"]
    finally:
        _rm_user(pg, ua, ta, ra)
        _rm_user(pg, ub, tb, rb)


def test_board_compute_separate_from_view(client, pg):
    """board:compute 与 board:view 权限分离：只有 view 的用户调用 /board/compute → 403。"""
    uid, tid, rid = _mk_user(pg, codes=["board:view"])   # 有 view 无 compute
    try:
        r = client.get(f"/api/board/compute?date={_PUB_DATE}&top=5", headers=_auth(uid, tid))
        assert r.status_code == 403 and r.json()["code"] == 4030
    finally:
        _rm_user(pg, uid, tid, rid)


def test_board_compute_allowed_with_code(client, pg):
    """有 board:compute → 通过守卫（进入业务层，非 401/403）。"""
    uid, tid, rid = _mk_user(pg, codes=["board:compute"])
    try:
        r = client.get(f"/api/board/compute?date={_PUB_DATE}&top=5", headers=_auth(uid, tid))
        assert r.status_code not in (401, 403)
    finally:
        _rm_user(pg, uid, tid, rid)


@pytest.fixture()
def public_preset(pg):
    """在 PUBLIC_BOARD_OWNER 下写一条**预设**方案 + 一条**非预设**方案；用后清理。"""
    ptid, pown = PUBLIC_BOARD_OWNER
    preset_id = "t3b_preset_" + uuid.uuid4().hex[:6]
    priv_id = "t3b_priv_" + uuid.uuid4().hex[:6]
    for pid, is_preset in [(preset_id, True), (priv_id, False)]:
        pg.execute(
            "INSERT INTO score_profile (id,tenant_id,owner_user_id,name,version,items,"
            "grade_thresholds,is_preset,visibility,published_at,published_by,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,1,%s,'{}',%s,%s,now(),%s,now(),now()) ON CONFLICT DO NOTHING",
            [
                pid, ptid, pown, pid,
                '[{"indicator":"rs_pct","weight":1.0,"scoring":{"type":"linear","min":0,"max":100}}]',
                is_preset,
                "public" if is_preset else "private",
                pown if is_preset else None,
            ])
    yield preset_id, priv_id
    pg.execute("DELETE FROM score_snapshot WHERE profile_id IN (%s,%s)", [preset_id, priv_id])
    pg.execute("DELETE FROM score_snapshot_meta WHERE profile_id IN (%s,%s)", [preset_id, priv_id])
    pg.execute("DELETE FROM score_profile WHERE id IN (%s,%s)", [preset_id, priv_id])


def test_board_profiles_requires_board_view(client, pg):
    """无 board:view → /board/profiles 403（榜单页方案列表也走 board:view，非 system-only 的 score-profile:view）。"""
    uid, tid, rid = _mk_user(pg, codes=[])   # 仅 baseline，无 board:view
    try:
        r = client.get("/api/board/profiles", headers=_auth(uid, tid))
        assert r.status_code == 403 and r.json()["code"] == 4030
    finally:
        _rm_user(pg, uid, tid, rid)


def test_board_profiles_shared_and_preset_only(client, pg, public_preset):
    """P1 回归（Codex 复审）：两个不同租户的**非 system**用户读 /board/profiles → 都看到同一份公共
    **预设**方案、且**非预设**方案不外泄（is_preset 过滤）。补齐 C1——普通用户无自建方案也能选公共预设看榜单
    （此前榜单页误用 /score-profiles=score-profile:view system-only + 按调用者归属 → 普通用户 403/空）。"""
    preset_id, priv_id = public_preset
    ua, ta, ra = _mk_user(pg, codes=["board:view"])
    ub, tb, rb = _mk_user(pg, codes=["board:view"])
    assert ta != tb
    try:
        qa = client.get("/api/board/profiles", headers=_auth(ua, ta))
        qb = client.get("/api/board/profiles", headers=_auth(ub, tb))
        assert qa.status_code == 200 and qb.status_code == 200
        ids_a = {p["id"] for p in qa.json()["data"]}
        ids_b = {p["id"] for p in qb.json()["data"]}
        assert preset_id in ids_a and preset_id in ids_b   # 公共预设全员可见、同一份
        assert priv_id not in ids_a and priv_id not in ids_b   # 非预设（含 admin 私有）不外泄
    finally:
        _rm_user(pg, ua, ta, ra)
        _rm_user(pg, ub, tb, rb)


def test_board_run_requires_view_and_rejects_non_preset(client, pg, public_preset):
    """/board/run 走 board:view；非预设/未知方案 → 404（不能借公共 run 跑私有/任意方案）。"""
    preset_id, priv_id = public_preset
    u0, t0, r0 = _mk_user(pg, codes=[])              # 无 board:view
    u1, t1, r1 = _mk_user(pg, codes=["board:view"])  # 有 board:view
    try:
        assert client.post("/api/board/run", json={"profile_id": preset_id},
                           headers=_auth(u0, t0)).status_code == 403
        # 非预设方案 → 404（err() 业务码走 HTTP 200 包 code=404）
        r = client.post("/api/board/run", json={"profile_id": priv_id}, headers=_auth(u1, t1))
        assert r.status_code == 200 and r.json()["code"] == 404
        r2 = client.post("/api/board/run", json={"profile_id": "nope"}, headers=_auth(u1, t1))
        assert r2.json()["code"] == 404
    finally:
        _rm_user(pg, u0, t0, r0)
        _rm_user(pg, u1, t1, r1)


def test_board_run_reads_fresh_public_snapshot_only(client, pg, public_preset):
    """/board/run 对 fresh 快照直接读取，不重复物化。"""
    preset_id, _priv_id = public_preset
    ptid, pown = PUBLIC_BOARD_OWNER
    uid, tid, rid = _mk_user(pg, codes=["board:view"])
    try:
        pg.execute(
            "INSERT INTO score_snapshot_meta "
            "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,computed_at,stale,n_codes) "
            "VALUES (%s,%s,1,%s,%s,%s,FALSE,1)",
            [_PUB_DATE, preset_id, ptid, pown, datetime.now()])
        pg.execute(
            "INSERT INTO score_snapshot "
            "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,code,total_score,grade,rank,sub_scores) "
            "VALUES (%s,%s,1,%s,%s,'T3B001.SZ',91.5,'A',1,'{}')",
            [_PUB_DATE, preset_id, ptid, pown])

        r = client.post("/api/board/run",
                        json={"profile_id": preset_id, "run_date": _PUB_DATE, "top": 10},
                        headers=_auth(uid, tid))
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["count"] == 1
        assert data["list"][0]["code"] == "T3B001.SZ"
    finally:
        _rm_user(pg, uid, tid, rid)


def test_board_run_without_date_uses_latest_market_date_and_materializes(
    client, pg, public_preset, monkeypatch
):
    """不传 run_date 时取行情最新日；该日缺 fresh 快照则按 visible 方案物化。"""
    preset_id, _priv_id = public_preset
    ptid, pown = PUBLIC_BOARD_OWNER
    uid, tid, rid = _mk_user(pg, codes=["board:view"])
    fresh_date = "2099-01-01"
    target = date(2099, 1, 3)

    def fake_score_day(_c, run_date, _profile):
        assert run_date == target
        return pd.DataFrame([{
            "code": "T3B_LATEST.SZ",
            "total_score": 98.0,
            "grade": "主升浪核心",
            "rank": 1,
            "sub_scores": "{}",
        }])

    monkeypatch.setattr("backend.api.board.latest_market_date", lambda _c: target)
    monkeypatch.setattr("backend.scoring.snapshot.score_day", fake_score_day)
    try:
        pg.execute(
            "INSERT INTO score_snapshot_meta "
            "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,computed_at,stale,n_codes) "
            "VALUES (%s,%s,1,%s,%s,%s,FALSE,1)",
            [fresh_date, preset_id, ptid, pown, datetime.now()])

        r = client.post("/api/board/run",
                        json={"profile_id": preset_id, "top": 10},
                        headers=_auth(uid, tid))
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["run_date"] == str(target)
        assert data["cache_status"] == "materialized"
        assert data["count"] == 1
        assert data["list"][0]["code"] == "T3B_LATEST.SZ"
    finally:
        _rm_user(pg, uid, tid, rid)


def test_board_run_materializes_stale_snapshot_with_view(client, pg, public_preset, monkeypatch):
    """visible 方案 stale/缺失快照可由 board:view 触发受控物化，写回方案 owner 槽。"""
    preset_id, _priv_id = public_preset
    ptid, pown = PUBLIC_BOARD_OWNER
    uid, tid, rid = _mk_user(pg, codes=["board:view"])

    def fake_score_day(_c, run_date, _profile):
        assert run_date == date.fromisoformat(_PUB_DATE)
        return pd.DataFrame([{
            "code": "T3B_REFRESH.SZ",
            "total_score": 97.0,
            "grade": "主升浪核心",
            "rank": 1,
            "sub_scores": "{}",
        }])

    monkeypatch.setattr("backend.scoring.snapshot.score_day", fake_score_day)
    try:
        pg.execute(
            "INSERT INTO score_snapshot_meta "
            "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,computed_at,stale,n_codes) "
            "VALUES (%s,%s,1,%s,%s,%s,TRUE,1)",
            [_PUB_DATE, preset_id, ptid, pown, datetime.now()])
        pg.execute(
            "INSERT INTO score_snapshot "
            "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,code,total_score,grade,rank,sub_scores) "
            "VALUES (%s,%s,1,%s,%s,'T3B_STALE.SZ',77.0,'B',1,'{}')",
            [_PUB_DATE, preset_id, ptid, pown])

        r = client.post("/api/board/run",
                        json={"profile_id": preset_id, "run_date": _PUB_DATE, "top": 10},
                        headers=_auth(uid, tid))
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["count"] == 1
        assert data["cache_status"] == "materialized"
        assert data["list"][0]["code"] == "T3B_REFRESH.SZ"

        meta = pg.query_df(
            "SELECT stale, n_codes FROM score_snapshot_meta WHERE trade_date=%s AND profile_id=%s "
            "AND profile_version=1 AND tenant_id=%s AND owner_user_id=%s",
            [_PUB_DATE, preset_id, ptid, pown])
        rows = pg.query_df(
            "SELECT code FROM score_snapshot WHERE trade_date=%s AND profile_id=%s "
            "AND profile_version=1 AND tenant_id=%s AND owner_user_id=%s",
            [_PUB_DATE, preset_id, ptid, pown])
        assert bool(meta.iloc[0]["stale"]) is False
        assert int(meta.iloc[0]["n_codes"]) == 1
        assert rows["code"].tolist() == ["T3B_REFRESH.SZ"]
    finally:
        _rm_user(pg, uid, tid, rid)


def test_recompute_produces_public_board_and_restores_view(client, pg, public_preset, monkeypatch):
    """评分维护生产 PUBLIC_BOARD_OWNER 公共预设快照；stale 后 /board/run 恢复可读数据。"""
    from backend.services import async_task

    preset_id, _priv_id = public_preset
    ptid, pown = PUBLIC_BOARD_OWNER
    uid, tid, rid = _mk_user(pg, codes=["board:view"])
    target = date(2099, 1, 3)

    class Ctx:
        def log(self, *_args, **_kwargs): ...
        def progress(self, *_args, **_kwargs): ...

    def mark_only_this_profile():
        pg.execute(
            "UPDATE score_snapshot_meta SET stale=true WHERE trade_date=%s AND profile_id=%s "
            "AND profile_version=1 AND tenant_id=%s AND owner_user_id=%s",
            [target, preset_id, ptid, pown])
        return 1

    def fake_score_day(_c, run_date, _profile):
        assert run_date == target
        return pd.DataFrame([{
            "code": "T3B_NEW.SZ",
            "total_score": 96.0,
            "grade": "主升浪核心",
            "rank": 1,
            "sub_scores": "{}",
        }])

    monkeypatch.setattr(async_task, "_mark_snapshots_stale", mark_only_this_profile)
    monkeypatch.setattr("backend.scoring.snapshot.score_day", fake_score_day)

    try:
        pg.execute(
            "INSERT INTO score_snapshot_meta "
            "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,computed_at,stale,n_codes) "
            "VALUES (%s,%s,1,%s,%s,%s,FALSE,1)",
            [target, preset_id, ptid, pown, datetime.now()])
        pg.execute(
            "INSERT INTO score_snapshot "
            "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,code,total_score,grade,rank,sub_scores) "
            "VALUES (%s,%s,1,%s,%s,'T3B_OLD.SZ',70.0,'B',1,'{}')",
            [target, preset_id, ptid, pown])

        res = async_task._h_recompute(
            {"run_date": str(target), "profile_ids": [preset_id]}, Ctx())
        assert res["public_board"]["run_date"] == str(target)
        assert res["public_board"]["profile_count"] == 1
        assert res["public_board"]["total_rows"] == 1

        meta = pg.query_df(
            "SELECT stale, n_codes FROM score_snapshot_meta WHERE trade_date=%s AND profile_id=%s "
            "AND profile_version=1 AND tenant_id=%s AND owner_user_id=%s",
            [target, preset_id, ptid, pown])
        rows = pg.query_df(
            "SELECT code FROM score_snapshot WHERE trade_date=%s AND profile_id=%s "
            "AND profile_version=1 AND tenant_id=%s AND owner_user_id=%s",
            [target, preset_id, ptid, pown])
        assert bool(meta.iloc[0]["stale"]) is False
        assert int(meta.iloc[0]["n_codes"]) == 1
        assert rows["code"].tolist() == ["T3B_NEW.SZ"]

        r = client.post("/api/board/run",
                        json={"profile_id": preset_id, "run_date": str(target), "top": 10},
                        headers=_auth(uid, tid))
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["count"] == 1
        assert data["list"][0]["code"] == "T3B_NEW.SZ"
    finally:
        _rm_user(pg, uid, tid, rid)


def test_data_admin_latest_board_date_reads_pg_public_preset(pg, public_preset):
    """数据总览榜单新鲜度读取 PG 公共预设 fresh 快照，不读 DuckDB 旧口径/非预设。"""
    from backend.api.data_admin import _latest_board_date

    preset_id, priv_id = public_preset
    ptid, pown = PUBLIC_BOARD_OWNER
    pg.execute(
        "INSERT INTO score_snapshot_meta "
        "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,computed_at,stale,n_codes) "
        "VALUES (%s,%s,1,%s,%s,%s,FALSE,1)",
        ["2099-01-04", preset_id, ptid, pown, datetime.now()])
    pg.execute(
        "INSERT INTO score_snapshot_meta "
        "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,computed_at,stale,n_codes) "
        "VALUES (%s,%s,1,%s,%s,%s,FALSE,1)",
        ["2099-01-05", priv_id, ptid, pown, datetime.now()])

    assert _latest_board_date() == "2099-01-04"
