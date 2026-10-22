"""行情请求的统一配置与按实际来源共享的起始限流。

限流在真实 HTTP 发送处执行，分页和重试同样计入；不占有网络请求期间的锁。
BaoStock 使用独立会话锁，但消费同一份请求策略。
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from urllib.parse import urlsplit

from backend.config import get_effective_settings

_DEFAULT_TIMEOUT_GETTER = None


@dataclass(frozen=True)
class RequestPolicy:
    rate: float
    timeout: float
    attempts: int
    backoff: float
    overrides: tuple[str, ...] = ()


def request_policy(group: str, settings=None) -> RequestPolicy:
    """旧板块显式覆盖继续有效；空值统一继承通用参数，不迁移或改写用户配置。"""
    settings = settings or get_effective_settings()
    source = settings.datasource
    rate = float(source.rate_limit_per_sec)
    timeout, attempts, backoff = (
        float(source.socket_timeout_sec),
        int(source.max_retries),
        float(source.retry_backoff_sec),
    )
    overrides = []
    if group == "ths_board":
        board = settings.ths_board
        rate = min(rate, 1 / float(board.min_interval_sec))
        for field, value in (
            ("timeout_sec", board.timeout_sec),
            ("max_retries", board.max_retries),
            ("retry_backoff_sec", board.retry_backoff_sec),
        ):
            if value is not None:
                overrides.append(f"ths_board.{field}")
        timeout = timeout if board.timeout_sec is None else float(board.timeout_sec)
        attempts = attempts if board.max_retries is None else int(board.max_retries)
        backoff = backoff if board.retry_backoff_sec is None else float(board.retry_backoff_sec)
    return RequestPolicy(rate, timeout, attempts, backoff, tuple(overrides))


def source_group(url: str) -> str | None:
    """接入库不作为限流单位；同花顺股票分钟与板块接口分别保护。"""
    host = (urlsplit(url).hostname or "").lower()
    for domain, group in (
        ("sina.com.cn", "sina"),
        ("sina.cn", "sina"),
        ("eastmoney.com", "eastmoney"),
        ("sse.com.cn", "sse"),
    ):
        if host == domain or host.endswith("." + domain):
            return group
    if host == "10jqka.com.cn" or host.endswith(".10jqka.com.cn"):
        return "ths" if "/line/hs_" in url else "ths_board"
    return None


# Redis TIME 提供跨进程共同时间。只有实际可启动时更新，取消不会预占未来时隙。
_PACE = """
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local last = tonumber(redis.call('GET', KEYS[1]) or '0')
local wait = tonumber(ARGV[1]) - (now - last)
if wait > 0 then return math.ceil(wait * 1000) end
redis.call('SET', KEYS[1], string.format('%.6f', now), 'EX', 86400)
return 0
"""
_HTTP_SCOPE: ContextVar[tuple[str, RequestPolicy] | None] = ContextVar("market_http", default=None)


@contextmanager
def http_policy_scope(group: str, policy: RequestPolicy):
    """同一次来源尝试使用同一策略快照，避免并发共享可变超时。"""
    token = _HTTP_SCOPE.set((group, policy))
    try:
        yield
    finally:
        _HTTP_SCOPE.reset(token)


def pause(seconds: float, check=None, sleep=time.sleep):
    deadline = time.monotonic() + max(0, seconds)
    while True:
        if check:
            check()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        sleep(min(0.1, remaining))


def wait_for_source(
    group: str, policy: RequestPolicy, *, client=None, check=None, sleep=time.sleep
):
    """Redis 不可用时不绕过限流；等待支持取消，HTTP 返回前其它请求可继续启动。"""
    if client is None:
        from backend.storage import get_redis_client

        client = get_redis_client().client
    while True:
        if check:
            check()
        wait_ms = int(client.eval(_PACE, 1, f"market:source:rate:v1:{group}", 1 / policy.rate))
        if wait_ms <= 0:
            return
        pause(wait_ms / 1000, check, sleep)


def prepare_http(url: str, kwargs: dict):
    """供现有 requests 唯一包装入口调用；其它站点保持原调用参数。"""
    group = source_group(url)
    if group is None:
        return
    scope = _HTTP_SCOPE.get()
    if scope is not None and scope[0] == group:
        # 分时编排已经在源调用前限流，真实请求只补充相同快照的超时。
        policy = scope[1]
    else:
        from backend.datasource.base import check_thread_cancel

        policy = request_policy(group)
        wait_for_source(group, policy, check=check_thread_cancel)
    kwargs["timeout"] = policy.timeout


def install_http_policy(default_timeout=None):
    """统一安装一次发送拦截；适配器只提供默认超时兼容入口，不各自包装requests。"""
    import requests

    from backend.config import get_settings

    global _DEFAULT_TIMEOUT_GETTER
    if default_timeout is not None:
        _DEFAULT_TIMEOUT_GETTER = default_timeout
    session = requests.sessions.Session
    if getattr(session, "_ai_stocks_timeout_patched", False):
        return
    original = session.request

    def request_with_policy(self, *args, **kwargs):
        url = kwargs.get("url") or (args[1] if len(args) > 1 else "")
        prepare_http(str(url), kwargs)
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = (
                _DEFAULT_TIMEOUT_GETTER()
                if _DEFAULT_TIMEOUT_GETTER
                else get_settings().datasource.socket_timeout_sec
            )
        return original(self, *args, **kwargs)

    session.request = request_with_policy
    session._ai_stocks_timeout_patched = True
