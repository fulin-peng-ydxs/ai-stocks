"""统一异常类型。

按层划分，便于 API 层统一捕获并映射为 {code,msg,data} 响应。
"""

from __future__ import annotations


class AIStocksError(Exception):
    """系统基础异常。"""

    code: int = 5000

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
