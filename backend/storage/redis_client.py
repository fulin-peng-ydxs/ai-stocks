"""Redis 连接层（短状态库：限流/验证码/token 黑名单/perm_ver）。

stage1 仅建底座 + 启动自检；具体业务用途（限流、验证码、token 黑名单、权限版本号）
由后续阶段（认证/鉴权/安全）消费。

设计要点：
- redis-py（同步）+ from_url 连接池，契合 FastAPI 同步线程池现状。
- URL/密码走环境变量（见 backend.config.Settings.redis_url），不入库不入码。
- decode_responses=True：读写统一为 str，省去上层手工解码。
"""

from __future__ import annotations

import redis

from backend.common.exceptions import StorageError
from backend.common.logging import get_logger
from backend.config import get_settings

log = get_logger("storage.redis")


class RedisClient:
    """Redis 客户端封装（连接池由 redis-py 内部维护）。"""

    def __init__(self, url: str | None = None):
        self.url = url or get_settings().redis_url()
        self._client: redis.Redis | None = None

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            try:
                self._client = redis.Redis.from_url(self.url, decode_responses=True)
                log.info("Redis client created")
            except Exception as e:
                raise StorageError(f"Redis 连接失败: {e}") from e
        return self._client

    def ping(self) -> bool:
        """连通性自检（启动期调用）。"""
        try:
            return bool(self.client.ping())
        except Exception as e:
            raise StorageError(f"Redis ping 失败: {e}") from e

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            log.info("Redis client closed")


_client: RedisClient | None = None


def get_redis_client() -> RedisClient:
    """模块级单例客户端。"""
    global _client
    if _client is None:
        _client = RedisClient()
    return _client
