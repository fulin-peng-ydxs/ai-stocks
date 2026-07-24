"""本地调试数据操作与 E2E 写操作的 fail-closed 环境守卫。"""

from __future__ import annotations

import os

LOCAL_TEST_ENVIRONMENTS = frozenset({"dev", "development", "local", "test", "testing"})


def runtime_environment() -> str:
    return (os.environ.get("AI_STOCKS_ENV") or os.environ.get("ENV") or "").strip().lower()


def require_local_test_environment() -> str:
    """只有明确标记为本地/测试的进程可操作调试数据；空值和未知值一律拒绝。"""
    environment = runtime_environment()
    if environment not in LOCAL_TEST_ENVIRONMENTS:
        shown = environment or "<unset>"
        raise RuntimeError(
            f"当前环境 {shown} 未明确标记为 dev/test/local，拒绝执行调试数据操作"
        )
    return environment


def require_e2e_write_enabled() -> str:
    """E2E 物理清理还须具备独立显式开关，不能只凭环境名称放行。"""
    environment = require_local_test_environment()
    if os.environ.get("AI_STOCKS_E2E_WRITE") != "1":
        raise RuntimeError("未设置 AI_STOCKS_E2E_WRITE=1，拒绝执行 E2E 数据写入")
    return environment


def e2e_write_environment() -> str | None:
    """健康检查使用的非抛错判定；返回 None 表示 E2E 写入未获双重授权。"""
    try:
        return require_e2e_write_enabled()
    except RuntimeError:
        return None
