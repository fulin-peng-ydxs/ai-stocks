"""行情请求的统一配置与按实际来源共享的起始限流。

限流在真实 HTTP 发送处执行，分页和重试同样计入；不占有网络请求期间的锁。
BaoStock 使用独立会话锁，但消费同一份请求策略。
"""

from __future__ import annotations

import copy
import hashlib
import math
import re
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date
from functools import wraps
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backend.config.request_snapshot import get_request_settings as get_effective_settings
from backend.config.source_registry import SOURCE_GROUPS

_DEFAULT_TIMEOUT_GETTER = None
_HTTP_SEND = None
_INSTALL_LOCK = threading.RLock()


@dataclass(frozen=True)
class RequestPolicy:
    rate: float
    timeout: float
    attempts: int
    backoff: float
    overrides: tuple[str, ...] = ()
    concurrency: int = 6
    wait_timeout: float = 300
    cooldown: float = 30
    max_response_mb: int = 32


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
    concurrency = int(getattr(source, "network_concurrency", 6))
    specific = getattr(source, "sources", {}).get(group)
    if specific:
        fields = {"rate_limit_per_sec": "rate", "socket_timeout_sec": "timeout",
                  "max_retries": "attempts", "retry_backoff_sec": "backoff",
                  "network_concurrency": "concurrency"}
        values = {"rate": rate, "timeout": timeout, "attempts": attempts, "backoff": backoff,
                  "concurrency": concurrency}
        for field, key in fields.items():
            value = getattr(specific, field)
            if value is not None:
                values[key] = value
                overrides.append(f"datasource.sources.{group}.{field}")
        rate, timeout, attempts, backoff, concurrency = (values[key] for key in
            ("rate", "timeout", "attempts", "backoff", "concurrency"))
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
    if SOURCE_GROUPS.get(group, {}).get("serial"):
        concurrency = 1
    return RequestPolicy(rate, timeout, attempts, backoff, tuple(overrides), concurrency,
                         getattr(source, "request_wait_timeout_sec", 300),
                         getattr(source, "cooldown_sec", 30),
                         getattr(source, "max_response_mb", 32))


def source_group(url: str) -> str | None:
    """按实际网站限流；股票列表SDK内部访问的交易所也需保护。

    同花顺股票分钟与板块分别保护；交易所分组不改变业务股票池范围。
    """
    host = (urlsplit(url).hostname or "").lower()
    for group, definition in SOURCE_GROUPS.items():
        if any(host == domain or host.endswith("." + domain)
               for domain in definition["domains"]):
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
_HTTP_SCOPE: ContextVar[tuple | None] = ContextVar("market_http", default=None)
_REUSE_SCOPE = ContextVar("sina_daily_materials", default=None)
_ATTEMPT_BUDGET = ContextVar("source_http_attempt_budget", default=None)


def request_budgeted(fn):
    """同一业务取源的语义重取与传输重试共用逐URL预算，分页按真实URL分别计数。"""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        # 探活/CLI可能在冷进程中先访问股本源，不能依赖先导入AKShare才安装发送控制。
        install_http_policy()
        if _ATTEMPT_BUDGET.get() is not None:
            return fn(*args, **kwargs)
        token = _ATTEMPT_BUDGET.set({})
        try:
            return fn(*args, **kwargs)
        finally:
            _ATTEMPT_BUDGET.reset(token)
    return wrapped


@contextmanager
def daily_materials(symbol: str):
    """同股同次日线复用材料；不跨股、不跨重试、不跨日期操作缓存响应。

    SDK 原始/后复权解析仍各自执行，但复用的量额不再作为独立证据。三个真实响应
    的 JS 变量名必须绑定请求标的，补上独立的来源身份验证后才能复用。
    """
    import requests

    _install_daily_decoder_reuse()
    with requests.Session() as session:
        token = _REUSE_SCOPE.set({"symbol": symbol, "cache": {}, "session": session})
        try:
            yield
        finally:
            _REUSE_SCOPE.reset(token)


def _install_daily_decoder_reuse():
    """仅复用同股同次已校验压缩材料的解码；不复制SDK的复权及日期处理。"""
    import py_mini_racer

    with _INSTALL_LOCK:
        original = py_mini_racer.MiniRacer.call
        if getattr(original, "_ai_stocks_daily_decode", False):
            return

        @wraps(original)
        def call(context, name, *args, **kwargs):
            scope = _REUSE_SCOPE.get()
            if (scope is None or name != "d" or len(args) != 1 or kwargs
                    or not scope.get("encoded_daily") or args[0] != scope["encoded_daily"]):
                return original(context, name, *args, **kwargs)
            from backend.datasource.observability import measure, record

            with measure("sina_decode"):
                if "decoded_daily" in scope:
                    record(sina_decode_cache_hits=1)
                else:
                    scope["decoded_daily"] = original(context, name, *args, **kwargs)
                    decoded = scope["decoded_daily"]
                    scope["decoded_flat"] = isinstance(decoded, list) and all(
                        isinstance(row, dict) and all(
                            value is None or isinstance(value, (str, int, float, date))
                            for value in row.values()
                        ) for row in decoded
                    )
                # SDK会修改中间数据，返回独立副本，不能使后复权污染原始解码结果。
                # 已确认的标量记录只复制行字典；未知嵌套结构仍完整深拷贝。
                if scope["decoded_flat"]:
                    return [row.copy() for row in scope["decoded_daily"]]
                return copy.deepcopy(scope["decoded_daily"])

        call._ai_stocks_daily_decode = True
        py_mini_racer.MiniRacer.call = call


@contextmanager
def http_policy_scope(group: str, policy: RequestPolicy, *, client=None):
    """同一次来源尝试使用同一策略快照，避免并发共享可变超时。"""
    token = _HTTP_SCOPE.set((group, policy, client))
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
        # 分时编排传递策略快照；真实请求仍在发送层统一准入。
        policy = scope[1]
    else:

        policy = request_policy(group)
        # 准入统一在 HTTPAdapter.send 执行，覆盖 SDK 分页、重定向和 PreparedRequest。
    kwargs["timeout"] = policy.timeout


def install_http_policy(default_timeout=None):
    """冷启动的并发取源也只安装一次，避免把发送包装器再次当成底层发送函数。"""
    with _INSTALL_LOCK:
        _install_http_policy(default_timeout)


def _response_cooldown(response, policy):
    """429缺少有效提示时用配置兜底；5xx只有明确Retry-After才影响整个来源。"""
    from email.utils import parsedate_to_datetime

    status = response.status_code
    if status != 429 and status < 500:
        return 0.0
    value = response.headers.get("Retry-After", "").strip()
    try:
        delay = float(value)
    except ValueError:
        try:
            # 已经过期的HTTP日期不应回退为额外30秒冷却。
            delay = max(0, parsedate_to_datetime(value).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            delay = None
    if delay is None or not math.isfinite(delay) or delay < 0:
        return min(600, max(1, policy.cooldown)) if status == 429 else 0.0
    return min(600, max(1, delay))


def _install_http_policy(default_timeout=None):
    """统一安装一次发送拦截；适配器只提供默认超时兼容入口，不各自包装requests。"""
    import requests

    from backend.config import get_settings

    global _DEFAULT_TIMEOUT_GETTER, _HTTP_SEND
    if default_timeout is not None:
        _DEFAULT_TIMEOUT_GETTER = default_timeout
    session = requests.sessions.Session
    if getattr(session, "_ai_stocks_timeout_patched", False):
        return
    original = session.request

    adapter = requests.adapters.HTTPAdapter
    original_send = adapter.send
    _HTTP_SEND = original_send

    def send_with_policy(self, request, *args, **kwargs):
        from backend.datasource.base import check_thread_cancel
        from backend.datasource.request_runtime import request_slot

        group = source_group(request.url)
        if group is None:
            if _ATTEMPT_BUDGET.get() is not None:
                from backend.common.exceptions import SourceRequestError
                raise SourceRequestError("采集请求的实际来源未登记，已停止发送")
            return _HTTP_SEND(self, request, *args, **kwargs)
        scope = _HTTP_SCOPE.get()
        policy = scope[1] if scope and scope[0] == group else request_policy(group)
        kwargs["timeout"] = policy.timeout
        # 隐藏的 urllib3 自动重试既无法准确计数也可能放大预算，明确拒绝旁路配置。
        if self.max_retries.total not in (0, False):
            raise ValueError("行情 HTTPAdapter 不允许隐藏自动重试，请使用统一尝试预算")
        from redis import RedisError

        from backend.common.exceptions import SourceRequestError

        for attempt in range(policy.attempts):
            check_thread_cancel()
            budget = _ATTEMPT_BUDGET.get()
            parsed = urlsplit(request.url)
            query = urlencode(sorted((key, value) for key, value in parse_qsl(parsed.query)
                                     if key not in {"_", "callback", "cb", "random"}))
            address = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))
            body = request.body or b""
            if isinstance(body, str):
                body = body.encode()
            budget_key = (request.method, address, hashlib.sha256(body).hexdigest())
            if budget is not None:
                used = budget.get(budget_key, 0)
                if used >= policy.attempts:
                    raise SourceRequestError(f"{group} 同一请求的语义与网络尝试预算已耗尽")
                budget[budget_key] = used + 1
            try:
                with request_slot(group, policy, client=scope[2] if scope and scope[0] == group else None,
                                  check=check_thread_cancel) as outcome:
                    response = _HTTP_SEND(self, request, *args, **kwargs)
                    outcome["failed"] = response.status_code == 429 or response.status_code >= 500
                    outcome["retry_after"] = _response_cooldown(response, policy)
                    # 行情响应有界读完再释放额度，包括 SDK stream=True；释放前仍占网络槽。
                    try:
                        chunks, size = [], 0
                        for chunk in response.iter_content(65536):
                            size += len(chunk)
                            if size > policy.max_response_mb * 1024 * 1024:
                                raise SourceRequestError("来源响应超过配置容量，请缩小请求分页或区间")
                            chunks.append(chunk)
                        response._content = b"".join(chunks)
                        response._content_consumed = True
                    except BaseException:
                        response.close()
                        raise
                    check_thread_cancel()
                    if outcome["failed"]:
                        response.raise_for_status()
                    if response.status_code in (400, 403, 404, 405, 410, 422):
                        # 确定的 HTTP 拒绝不由语义层原样放大；401 留给来源刷新，429 走共享冷却。
                        raise SourceRequestError(
                            f"{group} HTTP {response.status_code}，本次请求已停止；"
                            "请核查来源地址、权限或响应协议"
                        )
                    return response
            except SourceRequestError:
                raise
            except RedisError as exc:
                raise SourceRequestError(f"{group} 请求保护不可用，已停止发送") from exc
            except requests.RequestException as exc:
                if attempt + 1 >= policy.attempts:
                    raise SourceRequestError(
                        f"{group} HTTP请求已尝试 {policy.attempts} 次，技术失败："
                        f"{type(exc).__name__}: {str(exc)[:300]}"
                    ) from exc
                if budget is not None and budget.get(budget_key, 0) >= policy.attempts:
                    raise SourceRequestError(f"{group} 同一请求的语义与网络尝试预算已耗尽") from exc
                from backend.datasource.observability import record
                record(network_retries=1)
                pause(policy.backoff * 2 ** attempt, check_thread_cancel)

    adapter.send = send_with_policy

    def request_with_policy(self, *args, **kwargs):
        url = kwargs.get("url") or (args[1] if len(args) > 1 else "")
        prepare_http(str(url), kwargs)
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = (
                _DEFAULT_TIMEOUT_GETTER()
                if _DEFAULT_TIMEOUT_GETTER
                else get_settings().datasource.socket_timeout_sec
            )
        reuse = _REUSE_SCOPE.get()
        target = self
        key = None
        if reuse and source_group(str(url)) == "sina":
            target = reuse["session"]
            key = (str(url), repr(kwargs.get("params")))
            cached = reuse["cache"].get(key)
            if cached is not None:
                return copy.copy(cached)
        response = original(target, *args, **kwargs)
        if reuse and key is not None:
            response.raise_for_status()
            # 此上下文只容许日线三种已知材料，SDK 接口变化时明确失败，不能误用缓存。
            symbol = reuse["symbol"]
            path = urlsplit(str(url)).path
            if path.endswith("/hisdata_klc2/klc_kl.js"):
                expected = f"KLC_K2_{symbol}"
            elif path.endswith("/StockService.getAmountBySymbol"):
                expected = f"KKE_ShareAmount_{symbol}"
            elif path.endswith("/hfq.js"):
                expected = f"{symbol}hfq"
            else:
                raise ValueError("新浪日线材料接口未登记，拒绝复用")
            declaration = re.search(r"^\s*var\s+(\w+)\s*=", response.text, re.MULTILINE)
            if declaration is None or declaration[1] != expected:
                raise ValueError(f"{symbol} 新浪日线材料响应标的不匹配")
            if len(response.content) > get_effective_settings().datasource.max_response_mb * 1024 * 1024:
                raise ValueError("新浪日线材料超过单股响应容量")
            reuse["cache"][key] = response
            if path.endswith("/hisdata_klc2/klc_kl.js"):
                # 与SDK当前传给d()的材料完全匹配才允许复用；协议变化自然回到原调用。
                reuse["encoded_daily"] = response.text.split("=")[1].split(";")[0].replace('"', "")
        return response

    session.request = request_with_policy
    session._ai_stocks_timeout_patched = True
