"""显式双库操作的上下文绑定，防止间接仓储回落到机器默认业务连接。"""

from contextlib import contextmanager
from contextvars import ContextVar

market_override = ContextVar("database_market_override", default=None)
postgres_override = ContextVar("database_postgres_override", default=None)


@contextmanager
def storage_client_scope(market, postgres):
    """只影响当前执行上下文；嵌套与异常退出均恢复原绑定，不替换全局单例。"""
    market_token = market_override.set(market)
    postgres_token = postgres_override.set(postgres)
    try:
        yield
    finally:
        postgres_override.reset(postgres_token)
        market_override.reset(market_token)
