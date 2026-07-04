"""阶段四 T3b：每日榜单公共特例（C1 已确认）。

覆盖：
- `board:view` / `board:compute` 守卫（无码 → 403，权限分离）；
- **公共读专项**：不同租户/用户读 `GET /api/scores/top` 得到**同一份**平台公共榜单（`PUBLIC_BOARD_OWNER`
  固定归属、不按当前用户过滤）——区别于私有资产的「跨账号不可见」隔离用例，故独立成文。
"""

from __future__ import annotations

import uuid

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
