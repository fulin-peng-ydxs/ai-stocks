"""采集层包：统一 DataSource 抽象 + 各供应商适配器。"""

from backend.datasource.base import DataSource, get_source

__all__ = ["DataSource", "get_source"]
