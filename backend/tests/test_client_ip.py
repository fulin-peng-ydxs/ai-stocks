"""_client_ip 的 XFF 信任开关（防伪造 XFF 绕过 per-IP 限流）。纯函数，无 DB 依赖。"""

from __future__ import annotations

from types import SimpleNamespace

from backend.api import auth as auth_api


class _FakeReq:
    def __init__(self, xff: str | None, host: str):
        self.headers = {"x-forwarded-for": xff} if xff else {}
        self.client = SimpleNamespace(host=host)


def _settings(trust: bool):
    return SimpleNamespace(server=SimpleNamespace(trust_forwarded_for=trust))


def test_client_ip_ignores_xff_by_default(monkeypatch):
    monkeypatch.setattr(auth_api, "get_effective_settings", lambda: _settings(False))
    # 默认不信任 XFF：用不可伪造的 socket 连接地址
    assert auth_api._client_ip(_FakeReq(xff="1.2.3.4", host="10.0.0.9")) == "10.0.0.9"


def test_client_ip_uses_xff_when_trusted(monkeypatch):
    monkeypatch.setattr(auth_api, "get_effective_settings", lambda: _settings(True))
    # 可信反代后：取 XFF 首段
    assert auth_api._client_ip(_FakeReq(xff="1.2.3.4, 10.0.0.1", host="10.0.0.9")) == "1.2.3.4"


def test_client_ip_falls_back_when_no_client(monkeypatch):
    monkeypatch.setattr(auth_api, "get_effective_settings", lambda: _settings(False))
    req = _FakeReq(xff=None, host="127.0.0.1")
    req.client = None
    assert auth_api._client_ip(req) == "unknown"


# ── 全局 /api 限流中间件 _scope_ip：与认证端点同口径信任开关 ──

def _scope(xff: str | None, host: str | None):
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return {"headers": headers, "client": (host, 5555) if host else None}


def test_scope_ip_ignores_xff_by_default(monkeypatch):
    from backend.auth import middleware as mw
    monkeypatch.setattr(mw, "get_settings", lambda: _settings(False))
    assert mw._scope_ip(_scope("1.2.3.4", "10.0.0.9")) == "10.0.0.9"


def test_scope_ip_uses_xff_when_trusted(monkeypatch):
    from backend.auth import middleware as mw
    monkeypatch.setattr(mw, "get_settings", lambda: _settings(True))
    assert mw._scope_ip(_scope("1.2.3.4, 10.0.0.1", "10.0.0.9")) == "1.2.3.4"


def test_scope_ip_falls_back_when_no_client(monkeypatch):
    from backend.auth import middleware as mw
    monkeypatch.setattr(mw, "get_settings", lambda: _settings(False))
    assert mw._scope_ip(_scope(None, None)) == "unknown"
