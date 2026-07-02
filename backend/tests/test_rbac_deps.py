"""多租户 RBAC 阶段三 · T4：require_perm / require_system 守卫。

覆盖 §6.4：system 恒过 / 授权码过 / 无授权 403 / 无上下文 401 / system-only 非 system 403。
纯上下文单测（不依赖 PG/Redis）：直接 set_context 后调用依赖可调用体。
"""

from __future__ import annotations

import pytest

from backend.auth.context import AuthContext, reset_context, set_context
from backend.auth.deps import require_perm, require_system
from backend.common.exceptions import AuthError, ForbiddenError


def _with_ctx(ctx: AuthContext | None):
    """上下文管理：set 指定上下文（None=不 set，模拟无上下文）。"""
    class _C:
        def __enter__(self):
            self.tok = set_context(ctx) if ctx is not None else None
            return self

        def __exit__(self, *a):
            if self.tok is not None:
                reset_context(self.tok)
    return _C()


_SYSTEM = AuthContext(user_id="admin", tenant_id="default", roles=("system",), is_system=True)
_TADMIN = AuthContext(
    user_id="u1", tenant_id="t1", roles=("tenant_admin",), is_system=False,
    resources=frozenset({"user:list", "user:create"}))


# ── require_system ──

def test_require_system_passes_for_system():
    with _with_ctx(_SYSTEM):
        assert require_system() is None


def test_require_system_forbids_non_system():
    with _with_ctx(_TADMIN):
        with pytest.raises(ForbiddenError):
            require_system()


def test_require_system_401_without_context():
    with _with_ctx(None):
        with pytest.raises(AuthError):
            require_system()


# ── require_perm ──

def test_require_perm_system_always_passes():
    dep = require_perm("user:delete")   # system 未显式授予该码，仍恒过
    with _with_ctx(_SYSTEM):
        assert dep() is None


def test_require_perm_passes_when_code_granted():
    dep = require_perm("user:list")
    with _with_ctx(_TADMIN):
        assert dep() is None


def test_require_perm_forbids_when_code_missing():
    dep = require_perm("user:delete")   # tadmin 未被授予
    with _with_ctx(_TADMIN):
        with pytest.raises(ForbiddenError):
            dep()


def test_require_perm_401_without_context():
    dep = require_perm("user:list")
    with _with_ctx(None):
        with pytest.raises(AuthError):
            dep()


def test_require_perm_exact_match_no_wildcard():
    """精确匹配：拥有 user:list 不代表拥有 user:list-all（防前缀/通配误放行）。"""
    dep = require_perm("user:list-all")
    with _with_ctx(_TADMIN):
        with pytest.raises(ForbiddenError):
            dep()
