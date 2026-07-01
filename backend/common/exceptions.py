"""统一异常类型。

按层划分，便于 API 层统一捕获并映射为 {code,msg,data} 响应。
"""

from __future__ import annotations


class AIStocksError(Exception):
    """系统基础异常。

    http_status：响应 HTTP 状态码。业务异常默认 200（配合 {code,msg,data} 软失败口径）；
    认证/鉴权/限流类（stage2）用真实 401/403/429，由 API 层异常处理器按此出码。
    """

    code: int = 5000
    http_status: int = 200

    def __init__(self, msg: str = "", *, code: int | None = None):
        super().__init__(msg)
        self.msg = msg or self.__class__.__name__
        if code is not None:
            self.code = code


class ConfigError(AIStocksError):
    """配置错误。"""

    code = 5001


class DataSourceError(AIStocksError):
    """数据源采集错误（限流/超时/字段缺失等）。"""

    code = 5002


class StorageError(AIStocksError):
    """存储层错误（DuckDB 连接/写入）。"""

    code = 5003


class DataQualityError(AIStocksError):
    """数据质量校验未通过。"""

    code = 5004


class LookAheadError(AIStocksError):
    """检测到未来函数风险（点时安全约束被违反）。"""

    code = 5005


class NotFoundError(AIStocksError):
    """资源不存在。"""

    code = 4004


class ValidationError(AIStocksError):
    """入参校验错误。"""

    code = 4000


# ── 认证与鉴权（多租户 RBAC stage2；映射真实 HTTP 状态码）──
class AuthError(AIStocksError):
    """认证失败：未登录 / token 缺失·无效·过期·被吊销 / perm_ver 失配。"""

    code = 4010
    http_status = 401


class ForbiddenError(AIStocksError):
    """已认证但无权限：角色不足（如非 system 访问系统级接口）/ 资源无授权。"""

    code = 4030
    http_status = 403


class RateLimitError(AIStocksError):
    """触发限流（按 IP/账号/接口维度）。"""

    code = 4290
    http_status = 429


class ServiceUnavailableError(AIStocksError):
    """鉴权关键依赖（Redis 黑名单/perm_ver 等）不可用 → fail-closed 503。

    与 StorageError（软失败 200）区分：认证链路的存储故障必须让请求失败，不静默放行。
    """

    code = 5030
    http_status = 503
