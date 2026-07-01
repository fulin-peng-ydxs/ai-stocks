"""认证上下文归属解析测试（多租户 RBAC stage2·T5 整改）：

评审 P0-2 回归——请求链内缺上下文必须报错（不静默回落 admin）；非请求路径才回落 default/admin。
"""

from __future__ import annotations

import pytest

from backend.auth.context import (
    AuthContext,
    enter_request,
    exit_request,
    get_current_owner,
    reset_context,
    set_context,
)
from backend.common.exceptions import AuthError


def test_non_request_falls_back_to_default():
    # CLI/后台/测试：无中间件、无上下文 → 回落 default/admin
    assert get_current_owner() == ("default", "admin")


def test_in_request_without_context_raises():
    # 请求链内（enter_request）却无认证上下文 → 报错，防掩盖成 admin
    tok = enter_request()
    try:
        with pytest.raises(AuthError):
            get_current_owner()
    finally:
        exit_request(tok)


def test_context_owner_used_when_set():
    rt = enter_request()
    ct = set_context(AuthContext(user_id="u9", tenant_id="t9", role="tenant_admin"))
    try:
        assert get_current_owner() == ("t9", "u9")
    finally:
        reset_context(ct)
        exit_request(rt)
