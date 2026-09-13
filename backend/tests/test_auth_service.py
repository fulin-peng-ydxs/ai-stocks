"""认证服务集成测试（多租户 RBAC stage2·T4）：注册/登录/刷新/登出/me/锁定。

真实 PG + Redis；JWT 密钥用 monkeypatch。账号与 **IP 均 uuid 化**（IP 用于限流键隔离，
避免固定窗口计数在反复运行时跨次累加误触限流），测试后清理创建的 sys_user/sys_tenant。
"""

from __future__ import annotations

import re
import uuid
from unittest.mock import MagicMock

import pytest

from backend.auth import session_store as ss
from backend.common.exceptions import (
    AuthError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationError,
)
from backend.common.mailer import MailError
from backend.services.auth_service import AuthService

_SECRET = "unit-test-jwt-secret-0123456789-abcdefghij"


@pytest.fixture()
def auth_env(monkeypatch, pg, redis_cli, app_cfg):
    """设 JWT 密钥 + 提供账号回收表；teardown 清理 sys_user/sys_tenant。"""
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    pg.execute("DELETE FROM app_config WHERE key LIKE %s", ["auth.%"])
    accounts: list[str] = []
    yield accounts
    for acc in accounts:
        df = pg.query_df("SELECT id, tenant_id FROM sys_user WHERE account=%s", [acc])
        if not df.empty:
            pg.execute("DELETE FROM sys_user WHERE id=%s", [df.iloc[0]["id"]])
            pg.execute("DELETE FROM sys_tenant WHERE id=%s", [df.iloc[0]["tenant_id"]])


def _ip() -> str:
    return f"ip_{uuid.uuid4().hex[:10]}"   # 每次唯一，隔离限流键


def _all_indexes(tree: list) -> set[str]:
    """递归收集菜单树全部节点 index（分组 code + 叶子 route_path）。"""
    out: set[str] = set()
    for n in tree:
        out.add(n["index"])
        out |= _all_indexes(n.get("children", []))
    return out


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
    assert re.fullmatch(r"[0-9a-f]{32}", out["user"]["id"])
    assert re.fullmatch(r"[0-9a-f]{32}", out["user"]["tenant_id"])
    assert out["user"]["id"] != out["user"]["tenant_id"]
    assert out["access_token"] and out["refresh_token"]


def test_register_rejects_bad_email_code(auth_env):
    svc = AuthService()
    acc = f"pytest_auth_{uuid.uuid4().hex[:10]}"
    with pytest.raises(ValidationError):
        svc.register(acc, "GoodPass1", email=f"{acc}@ex.com", email_code="000000", ip=_ip())


def test_register_failure_keeps_email_code(auth_env):
    # 业务闭环：验证码正确但账号已存在 → 注册失败，但有效验证码不应被消费（可继续使用）。
    svc = AuthService()
    ip = _ip()
    acc, _ = _register(svc, auth_env, ip=ip)      # 先占用 account
    email2 = f"{acc}_2@ex.com"
    ss.save_email_code(email2, "445566", 300)
    with pytest.raises(ValidationError):           # 同 account + 新邮箱 + 有效码 → 账号已存在
        svc.register(acc, "GoodPass1", email=email2, email_code="445566", ip=ip)
    assert ss.check_email_code(email2, "445566") is True   # 未被烧掉


def test_register_success_consumes_email_code(auth_env):
    # 注册成功后验证码一次性消费，不能复用。
    svc = AuthService()
    acc, _ = _register(svc, auth_env, ip=_ip())
    assert ss.check_email_code(f"{acc}@ex.com", "112233") is False


def test_login_success_and_wrong_password(auth_env):
    svc = AuthService()
    ip = _ip()
    acc, _ = _register(svc, auth_env, ip=ip)
    out = svc.login(f"  {acc.upper()}  ", "GoodPass1", ip=ip)
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
    # 固定契约：{user, tenant, role(兼容单码), roles, menus(树), permissions(码)}
    assert me["user"]["account"] == acc
    assert me["tenant"]["id"] and me["role"] == "tenant_admin"
    # T5：注册即绑 sys_user_role(tenant_admin)，故解析出租管的菜单/功能（非空）
    assert "tenant_admin" in me["roles"]
    # T10：menus 为双过滤后的菜单树（MenuNode 形状）；tenant_admin 能见 /screen，permissions 含 user:list
    leaf_indexes = _all_indexes(me["menus"])
    assert "/screen" in leaf_indexes and "user:list" in me["permissions"]
    # 系统专属分支对 tenant_admin 隐藏：不含数据管理、角色/租户管理
    assert "data" not in leaf_indexes and "/system/roles" not in leaf_indexes


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
    # T6：开关开启后，登录失败达阈值需图形验证码（闭环：无码拒绝、正确码放行）。
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
    # 图形码强制阈值须下发，供后端达到阈值后强制要求验证码。
    assert isinstance(cfg["captcha_after_fails"], int) and cfg["captcha_after_fails"] >= 1
    assert cfg["appearance_presets"]
    allowed = re.compile(
        r"^tokens\.(?:light|dark)\.(?:primary|success|warning|danger)$"
    )
    for preset in cfg["appearance_presets"]:
        assert {"key", "name", "description", "config"} <= set(preset)
        assert all(allowed.fullmatch(key) or key == "responsiveDefaults.autoScaleResponsiveExponent"
                   for key in preset["config"]["values"])


def test_captcha_issue(auth_env):
    out = AuthService().issue_captcha()
    assert out["captcha_id"] and out["svg"].startswith("<svg")


# ── 邮箱验证码发送（P1/P2 加固后）：真实 Redis + monkeypatch send_email ──

def _email() -> str:
    return f"code_{uuid.uuid4().hex[:10]}@ex.com"


def _sent_code(mock_send) -> str:
    """从 send_email 收到的正文里取回 6 位验证码。"""
    body = mock_send.call_args.args[2]
    m = re.search(r"验证码是 (\d{6})", body)
    assert m, f"正文未含验证码: {body}"
    return m.group(1)


def test_send_email_code_success_saves_verifiable_code(auth_env, monkeypatch):
    send = MagicMock()
    monkeypatch.setattr("backend.services.auth_service.send_email", send)
    svc = AuthService()
    email = _email()
    svc.send_email_code(email, ip=_ip())
    send.assert_called_once()
    code = _sent_code(send)
    # 发出的码必须可验证（先存后发保证一致）
    assert ss.verify_email_code(email, code) is True


def test_send_email_code_mail_error_leaves_no_code(auth_env, monkeypatch):
    monkeypatch.setattr("backend.services.auth_service.send_email",
                        MagicMock(side_effect=MailError("smtp down")))
    svc = AuthService()
    email = _email()
    with pytest.raises(MailError):
        svc.send_email_code(email, ip=_ip())
    # 发信失败必须作废刚存的码：Redis 里不留可验证的残码
    assert ss._r().get(f"auth:emailcode:{email}") is None


def test_send_email_code_redis_save_failure_does_not_send(auth_env, monkeypatch):
    send = MagicMock()
    monkeypatch.setattr("backend.services.auth_service.send_email", send)
    # 先存后发：save 阶段 Redis 不可用应在发信前 503，且绝不发信
    monkeypatch.setattr("backend.auth.session_store.save_email_code",
                        MagicMock(side_effect=ServiceUnavailableError("redis down")))
    svc = AuthService()
    with pytest.raises(ServiceUnavailableError):
        svc.send_email_code(_email(), ip=_ip())
    send.assert_not_called()


def test_send_email_code_failed_delete_keeps_concurrent_code(auth_env, monkeypatch):
    # 并发交错：A 存码后、发信失败前，B 已覆盖为新码并成功发信；A 的回滚按值比较，不得误删 B 的有效码。
    svc = AuthService()
    email = _email()

    def fake_send(_to, _subject, _body):
        ss.save_email_code(email, "999999", 600)   # 模拟 B 覆盖为新码（并成功发出）
        raise MailError("A 发信失败")               # A 本次发信失败
    monkeypatch.setattr("backend.services.auth_service.send_email", fake_send)

    with pytest.raises(MailError):
        svc.send_email_code(email, ip=_ip())
    # B 的验证码必须仍可验证（A 的失败回滚没有误删它）
    assert ss.verify_email_code(email, "999999") is True


def test_send_email_code_disabled_when_require_off(auth_env, monkeypatch):
    # require_email_code=false 时停用发码：不真实发信、抛错。
    send = MagicMock()
    monkeypatch.setattr("backend.services.auth_service.send_email", send)
    svc = AuthService()
    svc.cfg = svc.cfg.model_copy(update={"require_email_code": False})
    with pytest.raises(ValidationError):
        svc.send_email_code(_email(), ip=_ip())
    send.assert_not_called()


def test_send_email_code_registered_email_suppressed(auth_env, monkeypatch):
    # 已注册邮箱：统一成功但不真实发信、不落码（防枚举 + 不骚扰）。
    send = MagicMock()
    monkeypatch.setattr("backend.services.auth_service.send_email", send)
    svc = AuthService()
    acc, _ = _register(svc, auth_env, ip=_ip())
    email = f"{acc}@ex.com"
    svc.send_email_code(email, ip=_ip())
    send.assert_not_called()
    assert ss._r().get(f"auth:emailcode:{email}") is None


def test_send_email_code_normalizes_email(auth_env, monkeypatch):
    send = MagicMock()
    monkeypatch.setattr("backend.services.auth_service.send_email", send)
    svc = AuthService()
    base = _email()
    svc.send_email_code(f"  {base.upper()}  ", ip=_ip())
    code = _sent_code(send)
    # 规范化后码存于小写去空白的键；send_email 收件人也应是规范化后的地址
    assert ss._r().get(f"auth:emailcode:{base}") is not None
    assert send.call_args.args[0] == base
    assert ss.verify_email_code(base, code) is True


def test_send_email_code_rejects_bad_format(auth_env, monkeypatch):
    send = MagicMock()
    monkeypatch.setattr("backend.services.auth_service.send_email", send)
    svc = AuthService()
    with pytest.raises(ValidationError):
        svc.send_email_code("not-an-email", ip=_ip())
    send.assert_not_called()


def test_send_email_code_case_variant_shares_email_limit(auth_env, monkeypatch):
    monkeypatch.setattr("backend.services.auth_service.send_email", MagicMock())
    svc = AuthService()
    svc.cfg = svc.cfg.model_copy(update={"email_code_rate_per_hour": 1})
    base = _email()
    ip = _ip()
    svc.send_email_code(base, ip=ip)
    with pytest.raises(RateLimitError):            # 大小写/空白变体应命中同一邮箱限流键
        svc.send_email_code(f" {base.upper()} ", ip=ip)


def test_send_email_code_ip_limit_blocks_many_emails(auth_env, monkeypatch):
    monkeypatch.setattr("backend.services.auth_service.send_email", MagicMock())
    svc = AuthService()
    svc.cfg = svc.cfg.model_copy(update={"email_code_ip_rate_per_hour": 2})
    ip = _ip()
    svc.send_email_code(_email(), ip=ip)
    svc.send_email_code(_email(), ip=ip)
    with pytest.raises(RateLimitError):            # 同一 IP 对不同邮箱超过 IP 上限即拒
        svc.send_email_code(_email(), ip=ip)
