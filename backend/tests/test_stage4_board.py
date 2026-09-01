"""阶段四 T3b：每日榜单公共特例（C1 已确认）。

覆盖：
- `board:view` / `board:compute` 守卫（无码 → 403，权限分离）；
- **公共读专项**：不同租户/用户读 `POST /api/board/run`（评分快照公共榜单，`PUBLIC_BOARD_OWNER`
  固定归属、不按当前用户过滤）——区别于私有资产的「跨账号不可见」隔离用例，故独立成文。
  注：旧固定模型公共读 `/api/scores/top`、`/api/scores`（读 `score_result`）已废弃删除。
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from threading import Barrier, Lock

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


def test_board_compute_accepts_visible_score_profile_ref(client, pg, market, monkeypatch):
    """/board/compute 支持可见评分方案 profile_ref，供回测明细榜单按同一方案看排名。"""
    from backend.scoring.score_profile import ScoreProfileRepo

    uid, tid, rid = _mk_user(pg, codes=["board:compute"])
    owner = "s4_profile_owner_" + uuid.uuid4().hex[:6]
    items = [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}]
    repo = ScoreProfileRepo(market=market, pg=pg, tenant_id=tid, owner_user_id=owner)
    repo.save("compute_shared", "公开计算评分", items)
    shared = repo.set_visibility("compute_shared", "tenant", published_by=owner)

    def fake_score_day(_c, _run_date, _profile):
        return pd.DataFrame([{
            "code": "T3B_COMPUTE.SZ",
            "total_score": 95.0,
            "grade": "主升浪核心",
            "rank": 1,
            "sub_scores": "{}",
        }])

    monkeypatch.setattr("backend.scoring.snapshot.score_day", fake_score_day)
    try:
        r = client.get(
            "/api/board/compute",
            params={"date": _PUB_DATE, "top": 5, "score_profile_id": shared["profile_ref"]},
            headers=_auth(uid, tid),
        )
        assert r.status_code == 200
        assert r.json()["data"]["list"][0]["code"] == "T3B_COMPUTE.SZ"
        assert "related_boards" not in r.json()["data"]["list"][0]
    finally:
        pg.execute("DELETE FROM score_profile WHERE owner_user_id=%s", [owner])
        pg.execute("DELETE FROM score_profile_version WHERE owner_user_id=%s", [owner])
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
            "VALUES (%s,%s,%s,%s,1,%s,'{}',%s,%s,"
            "CASE WHEN %s THEN now() ELSE NULL END,%s,now(),now()) ON CONFLICT DO NOTHING",
            [
                pid, ptid, pown, pid,
                '[{"indicator":"rs_pct","weight":1.0,"scoring":{"type":"linear","min":0,"max":100}}]',
                is_preset,
                "public" if is_preset else "private",
                is_preset,  # published_at 仅公开预设有值,私有行保持 NULL(P6 一致性约束)
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


def test_board_run_reads_fresh_public_snapshot_only(
    client,
    pg,
    market,
    public_preset,
    monkeypatch,
):
    """/board/run 对 fresh 快照直接读取，并按榜单日期批量附加冠军摘要。"""
    preset_id, _priv_id = public_preset
    ptid, pown = PUBLIC_BOARD_OWNER
    uid, tid, rid = _mk_user(pg, codes=["board:view"])
    c = market
    monkeypatch.setattr("backend.api.board.get_client", lambda: c)
    try:
        from backend.indicators.compute import build_params, param_hash
        ph = param_hash(build_params())
        pg.execute(
            "INSERT INTO score_snapshot_meta "
            "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,computed_at,stale,n_codes,param_hash) "
            "VALUES (%s,%s,1,%s,%s,%s,FALSE,1,%s)",
            [_PUB_DATE, preset_id, ptid, pown, datetime.now(), ph])
        pg.execute(
            "INSERT INTO score_snapshot "
            "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,code,total_score,grade,rank,sub_scores) "
            "VALUES (%s,%s,1,%s,%s,'600099.SH',91.5,'A',1,'{}')",
            [_PUB_DATE, preset_id, ptid, pown])
        c.execute(
            "INSERT INTO stock_basic (code, name, board) VALUES "
            "('600099.SH', '测试榜一股', '主板')",
        )
        c.execute(
            "INSERT INTO board_dict (board_code,name,board_type) VALUES "
            "('T3B_BOARD','测试行业','industry')"
        )
        c.execute(
            "INSERT INTO stock_board_correlation_state VALUES "
            "('600099.SH',?,TIMESTAMP '2099-01-02 10:00:00','stock-board-correlation-v2',"
            "'000001.SH',false,true,false)",
            [_PUB_DATE],
        )
        c.execute(
            "INSERT INTO stock_board_correlation VALUES "
            "('600099.SH','industry','T3B_BOARD',0.8,0.8,0.8,20,60,'high','000001.SH',"
            "false,?,TIMESTAMP '2099-01-02 10:00:00','stock-board-correlation-v2')",
            [_PUB_DATE],
        )

        r = client.post("/api/board/run",
                        json={"profile_id": preset_id, "run_date": _PUB_DATE, "top": 10},
                        headers=_auth(uid, tid))
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["count"] == 1
        assert data["list"][0]["code"] == "600099.SH"
        assert data["list"][0]["name"] == "测试榜一股"
        assert data["list"][0]["board"] == "主板"
        assert data["list"][0]["related_boards"]["industry"]["name"] == "测试行业"

        c.execute(
            "UPDATE stock_board_correlation SET as_of_date=DATE '2099-01-02' "
            "WHERE code='600099.SH'"
        )
        c.execute(
            "UPDATE stock_board_correlation_state SET as_of_date=DATE '2099-01-02' "
            "WHERE code='600099.SH'"
        )
        historical = client.post(
            "/api/board/run",
            json={"profile_id": preset_id, "run_date": _PUB_DATE, "top": 10},
            headers=_auth(uid, tid),
        ).json()["data"]["list"][0]["related_boards"]
        assert historical["industry"] is None
        assert historical["unavailable_reason"] == "as_of_mismatch"
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


def test_board_run_materialize_uses_advisory_lock(pg, public_preset, monkeypatch):
    """同一 owner/profile/version/date 并发物化时只计算一次，第二个请求等锁后读 fresh。"""
    from backend.scoring.snapshot import ScoreSnapshotRepo

    preset_id, _priv_id = public_preset
    ptid, pown = PUBLIC_BOARD_OWNER
    target = date.fromisoformat(_PUB_DATE)
    calls = 0
    calls_lock = Lock()
    barrier = Barrier(2)
    prof = {
        "id": preset_id,
        "version": 1,
        "items": [{"indicator": "rs_pct", "weight": 1.0, "scoring": {"type": "linear", "min": 0, "max": 100}}],
        "grade_thresholds": {},
    }

    def fake_score_day(_c, run_date, _profile):
        nonlocal calls
        assert run_date == target
        with calls_lock:
            calls += 1
        return pd.DataFrame([{
            "code": "T3B_LOCK.SZ",
            "total_score": 99.0,
            "grade": "主升浪核心",
            "rank": 1,
            "sub_scores": "{}",
        }])

    def worker():
        barrier.wait(timeout=5)
        repo = ScoreSnapshotRepo(pg=pg, tenant_id=ptid, owner_user_id=pown)
        return repo.get_board(target, preset_id, top=10, profile=prof)["code"].tolist()

    monkeypatch.setattr("backend.scoring.snapshot.score_day", fake_score_day)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result(timeout=10) for f in [pool.submit(worker), pool.submit(worker)]]

    assert results == [["T3B_LOCK.SZ"], ["T3B_LOCK.SZ"]]
    assert calls == 1
    meta = pg.query_df(
        "SELECT count(*) AS n, bool_or(stale) AS stale FROM score_snapshot_meta "
        "WHERE trade_date=%s AND profile_id=%s AND profile_version=1 "
        "AND tenant_id=%s AND owner_user_id=%s",
        [target, preset_id, ptid, pown],
    )
    rows = pg.query_df(
        "SELECT code FROM score_snapshot WHERE trade_date=%s AND profile_id=%s "
        "AND profile_version=1 AND tenant_id=%s AND owner_user_id=%s",
        [target, preset_id, ptid, pown],
    )
    assert int(meta.iloc[0]["n"]) == 1
    assert bool(meta.iloc[0]["stale"]) is False
    assert rows["code"].tolist() == ["T3B_LOCK.SZ"]


def test_result_maintenance_only_invalidates_board_snapshot(pg, public_preset, monkeypatch):
    """每日榜单结果维护只标记失效，不在任务内重新生产榜单。"""
    from backend.services import async_task

    preset_id, _priv_id = public_preset
    ptid, pown = PUBLIC_BOARD_OWNER
    target = date(2099, 1, 3)
    monkeypatch.setattr(
        "backend.services.result_maintenance.resolve_target_date",
        lambda _params, _client=None: target,
    )

    class Ctx:
        svc = type("Svc", (), {"c": None})()
        def log(self, *_args, **_kwargs): ...
        def progress(self, *_args, **_kwargs): ...
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
        {"target_mode": "fixed", "trade_date": str(target)}, Ctx())
    assert res["snapshots_marked_stale"] == 1
    assert res["trade_date"] == str(target)

    meta = pg.query_df(
        "SELECT stale, n_codes FROM score_snapshot_meta WHERE trade_date=%s AND profile_id=%s "
        "AND profile_version=1 AND tenant_id=%s AND owner_user_id=%s",
        [target, preset_id, ptid, pown])
    rows = pg.query_df(
        "SELECT code FROM score_snapshot WHERE trade_date=%s AND profile_id=%s "
        "AND profile_version=1 AND tenant_id=%s AND owner_user_id=%s",
        [target, preset_id, ptid, pown])
    assert bool(meta.iloc[0]["stale"]) is True
    assert int(meta.iloc[0]["n_codes"]) == 1
    assert rows["code"].tolist() == ["T3B_OLD.SZ"]


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
