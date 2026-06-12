"""数据源抽象接口（SDD §5：屏蔽供应商差异，可插拔 F-DAT-11）。

所有适配器（AKShareSource/BaostockSource/…）实现 DataSource 抽象，
统一返回 pandas DataFrame，列名遵循下方"统一 schema"约定，
上层（采集/入库）只依赖抽象，不感知具体供应商。

统一 schema（适配器须把各源字段映射到这些列名）：
- daily_bar:   code, trade_date, open, high, low, close, pre_close,
               volume, amount, adj_factor, turnover_rate
- stock_list:  code, name
- stock_info:  code, name, exchange, board, list_date, delist_date,
               total_share, float_share, industry
- index_bar:   index_code, trade_date, open, high, low, close, volume, amount
- calendar:    trade_date, is_open
- delist_list: code, name, delist_date

复权约定：daily_bar 返回**不复权**原值；复权因子单列 adj_factor。
日期列统一为 datetime.date 或可被 to_date 解析的字符串。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import date
from functools import wraps
from typing import Callable

import pandas as pd

from backend.common.exceptions import DataSourceError
from backend.common.logging import get_logger

log = get_logger("datasource.base")


# ── 限流 / 重试 装饰器（应对公开接口频率/稳定性限制，需求 §10.1）──


def rate_limited(min_interval_sec: float) -> Callable:
    """方法级简单限流：相邻两次调用间隔 >= min_interval_sec。

    用实例属性记录上次调用时间（按方法名隔离），单线程 EOD 场景足够。
    """

    def deco(fn: Callable) -> Callable:
        attr = f"_last_call_{fn.__name__}"

        @wraps(fn)
        def wrapper(self, *args, **kwargs):
            last = getattr(self, attr, 0.0)
            wait = min_interval_sec - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            try:
                return fn(self, *args, **kwargs)
            finally:
                setattr(self, attr, time.monotonic())

        return wrapper

    return deco


def with_retry(max_retries: int = 3, backoff_sec: float = 2.0) -> Callable:
    """失败重试 + 指数退避；最终失败抛 DataSourceError。"""

    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            last_err: Exception | None = None
            for attempt in range(1, max_retries + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    if attempt < max_retries:
                        sleep = backoff_sec * (2 ** (attempt - 1))
                        log.warning(
                            "%s 第%d次失败: %s，%.1fs 后重试", fn.__name__, attempt, e, sleep
                        )
                        time.sleep(sleep)
            raise DataSourceError(
                f"{fn.__name__} 重试 {max_retries} 次仍失败: {last_err}"
            ) from last_err

        return wrapper

    return deco


# ── 抽象基类 ───────────────────────────────────────────────────


class DataSource(ABC):
    """数据源统一抽象接口。"""

    #: 数据源名称（akshare/baostock）
    name: str = "base"

    @abstractmethod
    def get_stock_list(self) -> pd.DataFrame:
        """全市场股票代码+名称。列：code, name。"""

    @abstractmethod
    def get_stock_info(self, code: str) -> pd.DataFrame:
        """个股基础信息。列见模块 docstring stock_info。"""

    @abstractmethod
    def get_daily_bar(
        self, code: str, start: date, end: date, adjust: str = ""
    ) -> pd.DataFrame:
        """个股日线（不复权 + 换手）。列见 daily_bar。adjust: ''/qfq/hfq。"""

    @abstractmethod
    def get_index_bar(self, index_code: str, start: date, end: date) -> pd.DataFrame:
        """指数日线。列见 index_bar。"""

    @abstractmethod
    def get_trade_calendar(self, start: date, end: date) -> pd.DataFrame:
        """交易日历。列：trade_date, is_open。"""

    def get_delisted_list(self) -> pd.DataFrame:
        """退市股清单（防幸存者偏差）。默认空，由支持的源覆盖。列：code, name, delist_date。"""
        return pd.DataFrame(columns=["code", "name", "delist_date"])

    def get_adj_factor(self, code: str, start: date, end: date) -> pd.DataFrame:
        """复权因子序列。默认空，由支持的源覆盖。列：code, trade_date, adj_factor。"""
        return pd.DataFrame(columns=["code", "trade_date", "adj_factor"])

    # ── 源专属能力（纳入契约：缺则明确报错，不再隐式硬绑定到某具体源）──
    def get_valuation(self, code: str, start: date, end: date) -> pd.DataFrame:
        """每日估值/市值。列：code,trade_date,total_mv,float_mv,total_share,float_share。"""
        raise NotImplementedError(f"{self.name} 不支持 valuation 能力")

    def get_basic_dates(self) -> pd.DataFrame:
        """全市场上市/退市日期（含退市股）。列：code,name,list_date,delist_date,is_delisted。"""
        raise NotImplementedError(f"{self.name} 不支持 basic_dates 能力")

    def get_industry(self) -> pd.DataFrame:
        """全市场行业分类。列：code,industry。"""
        raise NotImplementedError(f"{self.name} 不支持 industry 能力")

    # ── 能力声明（供编排层按能力选源，见 IngestionService._source_for）──
    # 约定能力名：daily/index/calendar/stock_list/valuation/basic_dates/industry/delisted/adj_factor
    def supports(self, capability: str) -> bool:
        """是否支持某能力。"""
        return capability in getattr(self, "capabilities", set())


def get_source(name: str) -> DataSource:
    """按名称工厂获取数据源实例（适配器在各自模块注册后由此分发）。

    M1 骨架阶段：AKShare/baostock 适配器实现后接入；现仅暴露接口避免循环依赖。
    """
    name = name.lower()
    if name == "akshare":
        from backend.datasource.akshare_source import AKShareSource

        return AKShareSource()
    if name == "baostock":
        from backend.datasource.baostock_source import BaostockSource

        return BaostockSource()
    raise DataSourceError(f"未知数据源: {name}")
