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


def e2e_login_rate_bypass_enabled() -> bool:
    """E2E 套件并发登录豁免判定（非抛错）。

    仅当进程同时满足三重门控才放行：①本地/测试环境白名单（`AI_STOCKS_ENV` ∈ dev/test/local）；
    ②显式 `AI_STOCKS_E2E_WRITE=1`；③显式 `AI_STOCKS_E2E_LOGIN_BYPASS=1`。三者均为进程级环境变量，
    不入库、不污染日常 dev；生产（`start.sh prod` 强制移除 E2E_WRITE）永不满足。
    用于全量 Playwright 三视口并行：多 worker 进程各自密集 `POST /auth/login`（同源 127.0.0.1），
    不豁免会撞 `login_rate_per_min` 单 IP 上限导致大面积登录失败。仅放开 login 的 IP 限流，
    账号锁定/失败计数/验证码等其余防滥用逻辑不受影响。
    """
    if e2e_write_environment() is None:
        return False
    return os.environ.get("AI_STOCKS_E2E_LOGIN_BYPASS") == "1"
