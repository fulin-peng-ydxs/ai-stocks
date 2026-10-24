"""来源跨进程请求准入与聚合观测；频率、并发、冷却使用一次 Redis 原子判断。"""

from __future__ import annotations

import os
import socket
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from backend.common.exceptions import SourceRequestError
from backend.common.logging import get_logger
from backend.datasource.observability import record, work_state

log = get_logger("datasource.request_runtime")
_HOST = socket.gethostname()

# 活跃额度不按固定 TTL 擅自释放：请求可能仍在读响应。仅 finally 或已确认死亡的本机
# 进程可回收；其它主机的遗留额度保持 fail-closed，等待有界并显示错误。
_ADMIT = """
local t=redis.call('TIME')
local now=tonumber(t[1])+tonumber(t[2])/1000000
local cool=tonumber(redis.call('HGET',KEYS[3],'cooldown_until') or '0')
if cool>now then return math.min(1000,math.ceil((cool-now)*1000)) end
local cap=tonumber(ARGV[2])
if cool>0 then cap=1 end
if redis.call('HLEN',KEYS[1])>=cap then return 100 end
local last=tonumber(redis.call('GET',KEYS[2]) or '0')
local delay=tonumber(ARGV[1])-(now-last)
if delay>0 then return math.ceil(delay*1000) end
redis.call('HSET',KEYS[1],ARGV[3],ARGV[4])
redis.call('SET',KEYS[2],string.format('%.6f',now),'EX',86400)
redis.call('HINCRBY',KEYS[3],'requests',1)
redis.call('HSET',KEYS[3],'sampled_at',now)
redis.call('EXPIRE',KEYS[3],86400)
redis.call('ZADD',KEYS[4],now,ARGV[3])
redis.call('ZREMRANGEBYSCORE',KEYS[4],'-inf',now-60)
redis.call('EXPIRE',KEYS[4],120)
return 0
"""
_FINISH = """
redis.call('HDEL',KEYS[1],ARGV[1])
redis.call('HINCRBYFLOAT',KEYS[2],'network_seconds',ARGV[2])
local t=redis.call('TIME')
local now=tonumber(t[1])+tonumber(t[2])/1000000
if ARGV[3]=='1' then
 redis.call('HINCRBY',KEYS[2],'failures',1)
 local n=redis.call('HINCRBY',KEYS[2],'consecutive_failures',1)
 if n>=tonumber(ARGV[4]) or tonumber(ARGV[6])>0 then
  local until_time=now+math.max(tonumber(ARGV[5]),tonumber(ARGV[6]))
  local existing=tonumber(redis.call('HGET',KEYS[2],'cooldown_until') or '0')
  redis.call('HSET',KEYS[2],'cooldown_until',math.max(existing,until_time))
 end
else
 local cool=tonumber(redis.call('HGET',KEYS[2],'cooldown_until') or '0')
 if cool<=now then redis.call('HSET',KEYS[2],'consecutive_failures',0,'cooldown_until',0) end
end
redis.call('EXPIRE',KEYS[2],86400)
return 0
"""


def redis_client():
    from backend.storage import get_redis_client

    return get_redis_client().client


def _keys(group):
    # 统一 hash tag，保持未来 Redis Cluster 中原子脚本的同槽约束。
    prefix = f"market:requests:{{{group}}}:v1:"
    return [prefix + name for name in ("active", "last", "stats", "starts", "waiting")]


def _reap_dead(client, keys):
    for key in (keys[0], keys[4]):
        for token, owner in client.hgetall(key).items():
            try:
                host, pid = owner.rsplit(":", 1)
                if host != _HOST:
                    continue
                os.kill(int(pid), 0)
            except ProcessLookupError:
                client.hdel(key, token)
            except (ValueError, PermissionError):
                continue


@contextmanager
def request_slot(group, policy, *, client=None, check=None):
    """只覆盖网络实际占用；额度等待不占网络槽，取消/失败均释放本请求所有权。"""
    from backend.datasource.request_policy import pause, request_policy

    client = client if client is not None else redis_client()
    keys, token = _keys(group), uuid4().hex
    started = time.monotonic()
    acquired = False
    client.hset(keys[4], token, f"{_HOST}:{os.getpid()}")
    try:
        with work_state("source_wait"):
            next_reap = started
            while True:
                if check:
                    check()
                now = time.monotonic()
                if now - started >= policy.wait_timeout:
                    raise SourceRequestError(f"{group} 等待来源额度超时，检查来源冷却或遗留请求")
                if now >= next_reap:
                    _reap_dead(client, keys)
                    next_reap = now + 10
                # 长等待期间来源降额必须生效；timeout/attempts 仍沿用本次尝试快照。
                current = request_policy(group)
                wait_ms = int(
                    client.eval(
                        _ADMIT,
                        4,
                        *keys[:4],
                        1 / current.rate,
                        current.concurrency,
                        token,
                        f"{_HOST}:{os.getpid()}",
                    )
                )
                if wait_ms <= 0:
                    acquired = True
                    break
                pause(min(wait_ms / 1000, 0.25), check)
        waited = time.monotonic() - started
        from backend.config.request_snapshot import request_settings_status
        from backend.datasource.observability import current_scope

        status = request_settings_status()
        scope = current_scope()
        if scope:
            with scope[0].lock:
                scope[0].meta.update(
                    policy_version=status["version"], policy_degraded=status["degraded"]
                )
        record(wait_seconds=waited, requests=1)
        client.hincrbyfloat(keys[2], "wait_seconds", waited)
        client.hdel(keys[4], token)
        network_started = time.monotonic()
        result = {"failed": False, "retry_after": 0.0}
        try:
            with work_state("network"):
                yield result
        except Exception as exc:
            from backend.services.async_task import TaskCancelled

            result["failed"] = not isinstance(exc, TaskCancelled)
            raise
        finally:
            elapsed = time.monotonic() - network_started
            record(network_seconds=elapsed, failures=int(result["failed"]))
            try:
                client.eval(
                    _FINISH,
                    2,
                    keys[0],
                    keys[2],
                    token,
                    elapsed,
                    int(result["failed"]),
                    policy.failure_threshold,
                    policy.cooldown,
                    result["retry_after"],
                )
            except Exception:  # noqa: BLE001 -- 释放失败不覆盖原始网络异常
                # 不隐瞒释放失败；遗留额度阻止超限，而不擅自超发。
                log.error("%s 来源额度释放失败，后续请求将受额度保护", group)
    finally:
        try:
            client.hdel(keys[4], token)
            if acquired:
                client.hdel(keys[0], token)
        except Exception:  # noqa: BLE001 -- 清理失败必须保持来源保护
            log.error("%s 来源准入状态清理失败", group)


def source_runtime(group):
    """只读来源短状态；没有样本返回 None，不能将 Redis 异常当成健康。"""
    try:
        client = redis_client()
        keys = _keys(group)
        stats = client.hgetall(keys[2])
        if not stats:
            return None
        now = time.time()
        return {
            "requests": int(stats.get("requests", 0)),
            "failures": int(stats.get("failures", 0)),
            "network_seconds": float(stats.get("network_seconds", 0)),
            "wait_seconds": float(stats.get("wait_seconds", 0)),
            "active": client.hlen(keys[0]),
            "waiting": client.hlen(keys[4]),
            "observed_rate": round(client.zcount(keys[3], now - 60, "+inf") / 60, 3),
            "cooldown_seconds": max(0, float(stats.get("cooldown_until", 0)) - now),
            "sampled_at": datetime.fromtimestamp(
                float(stats.get("sampled_at", now)), UTC
            ).isoformat(),
        }
    except Exception:  # noqa: BLE001 -- 普通状态读取不因 Redis 故障触发探活
        return None
