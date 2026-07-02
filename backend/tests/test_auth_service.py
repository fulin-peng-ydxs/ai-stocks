"""认证服务集成测试（多租户 RBAC stage2·T4）：注册/登录/刷新/登出/me/锁定。

真实 PG + Redis；JWT 密钥用 monkeypatch。账号与 **IP 均 uuid 化**（IP 用于限流键隔离，
避免固定窗口计数在反复运行时跨次累加误触限流），测试后清理创建的 sys_user/sys_tenant。
"""

from __future__ import annotations

import uuid

import pytest

from backend.auth import session_store as ss
from backend.common.exceptions import AuthError, ValidationError
from backend.services.auth_service import AuthService

_SECRET = "unit-test-jwt-secret-0123456789-abcdefghij"


@pytest.fixture()
def auth_env(monkeypatch, pg, redis_cli):
    """设 JWT 密钥 + 提供账号回收表；teardown 清理 sys_user/sys_tenant。"""
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    accounts: list[str] = []
    yield accounts
    for acc in accounts:
        df = pg.query_df("SELECT id, tenant_id FROM sys_user WHERE account=%s", [acc])
        if not df.empty:
            pg.execute("DELETE FROM sys_user WHERE id=%s", [df.iloc[0]["id"]])
            pg.execute("DELETE FROM sys_tenant WHERE id=%s", [df.iloc[0]["tenant_id"]])


def _ip() -> str:
    return f"ip_{uuid.uuid4().hex[:10]}"   # 每次唯一，隔离限流键


def _register(svc, accounts, ip):
    acc = f"pytest_auth_{uuid.uuid4().hex[:10]}"
    email = f"{acc}@ex.com"
    ss.save_email_code(email, "112233", 300)          # require_email_code 默认开
    out = svc.register(acc, "GoodPass1", email=email, email_code="112233", ip=ip)
    accounts.append(acc)
    return acc, out


def test_register_creates_tenant_admin(auth_env):
    svc = AuthService()
    acc, out = _register(svc, auth_env, ip=_ip())
    assert out["user"]["role"] == "tenant_admin"
    assert out["user"]["account"] == acc
    assert out["access_token"] and out["refresh_token"]


def test_register_rejects_bad_email_code(auth_env):
    svc = AuthService()
    acc = f"pytest_auth_{uuid.uuid4().hex[:10]}"
    with pytest.raises(ValidationError):
        svc.register(acc, "GoodPass1", email=f"{acc}@ex.com", email_code="000000", ip=_ip())


def test_login_success_and_wrong_password(auth_env):
    svc = AuthService()
    ip = _ip()
    acc, _ = _register(svc, auth_env, ip=ip)
    out = svc.login(acc, "GoodPass1", ip=ip)
    assert out["user"]["account"] == acc and out["access_token"]
    with pytest.raises(AuthError):
        svc.login(acc, "WrongPass1", ip=ip)


def test_me_and_claims(auth_env):
    svc = AuthService()
    ip = _ip()
    acc, _ = _register(svc, auth_env, ip=ip)
    out = svc.login(acc, "GoodPass1", ip=ip)
    claims = svc.claims_from_bearer("Bearer " + out["access_token"])
    assert "role" not in claims   # 瘦令牌：角色不入 token
    me = svc.me(claims["sub"])
    # 固定契约：{user, tenant, role(兼容单码), roles, menus, permissions}
    assert me["user"]["account"] == acc
    assert me["tenant"]["id"] and me["role"] == "tenant_admin"
    # T5：注册即绑 sys_user_role(tenant_admin)，故解析出租管的菜单/功能（非空）
    assert "tenant_admin" in me["roles"]
    assert "/screen" in me["menus"] and "user:list" in me["permissions"]


def test_refresh_rotation_and_logout_revoke(auth_env):
    svc = AuthService()
    ip = _ip()
    acc, _ = _register(svc, auth_env, ip=ip)
    out = svc.login(acc, "GoodPass1", ip=ip)
    new = svc.refresh(out["refresh_token"])
    assert new["access_token"]
    with pytest.raises(AuthError):            # 旧 refresh 轮换后作废
        svc.refresh(out["refresh_token"])
    svc.logout(new["access_token"], new["refresh_token"])
    with pytest.raises(AuthError):            # 登出后 access 进黑名单
        svc.claims_from_bearer("Bearer " + new["access_token"])


def test_lockout_after_max_fail(auth_env):
    svc = AuthService()
    ip = _ip()
    acc, _ = _register(svc, auth_env, ip=ip)
    for _ in range(svc.cfg.max_login_fail):
        with pytest.raises(AuthError):
            svc.login(acc, "WrongPass1", ip=ip)
    assert ss.is_locked(acc) is True
    with pytest.raises(AuthError):            # 锁定后即使密码正确也拒绝
        svc.login(acc, "GoodPass1", ip=ip)
    ss.clear_login_failures(acc)


def test_login_captcha_required_after_fails_when_enabled(auth_env):
    # T6：开关开启后，登录失败达阈值需图形验证码（闭环：无码拒绝、正确码放行）
    svc = AuthService()
    svc.cfg = svc.cfg.model_copy(update={
        "login_captcha_enabled": True, "captcha_after_fails": 1, "max_login_fail": 99})
    ip = _ip()
    acc, _ = _register(svc, auth_env, ip=ip)
    with pytest.raises(AuthError):                 # 失败一次 → 触发验证码要求
        svc.login(acc, "WrongPass1", ip=ip)
    with pytest.raises(AuthError):                 # 需验证码却不带 → 拒绝
        svc.login(acc, "GoodPass1", ip=ip)
    cid = uuid.uuid4().hex                          # 备好一个已知验证码
    ss.save_captcha(cid, "AB12", 300)
    out = svc.login(acc, "GoodPass1", ip=ip, captcha_id=cid, captcha_code="AB12")
    assert out["access_token"]


def test_public_config(auth_env):
    cfg = AuthService().public_config()
    assert cfg["require_email_code"] is True
    assert cfg["login_captcha_enabled"] is False
    # 图形码触发阈值须下发，供前端 UI 显示时机与后端 login() 强制阈值对齐（Codex 再审整改）
    assert isinstance(cfg["captcha_after_fails"], int) and cfg["captcha_after_fails"] >= 1


def test_captcha_issue(auth_env):
    out = AuthService().issue_captcha()
    assert out["captcha_id"] and out["svg"].startswith("<svg")
