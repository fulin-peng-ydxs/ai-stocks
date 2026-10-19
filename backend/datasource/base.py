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
- st_status:   code, trade_date, is_st, trade_status
- delist_list: code, name, delist_date
- intraday_1m: timestamp, open, high, low, close, volume, amount
               （volume 固定为手，1 手 = 100 股；amount 固定为元）

复权约定：daily_bar 返回**不复权**原值；复权因子单列 adj_factor。
日期列统一为 datetime.date 或可被 to_date 解析的字符串。
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import contextmanager
from datetime import date
from functools import wraps

import pandas as pd

from backend.common.exceptions import DataSourceError
from backend.common.logging import get_logger

log = get_logger("datasource.base")


_CANCEL_LOCAL = threading.local()


def check_thread_cancel() -> None:
    """执行当前采集工作线程的协作式终止检查；普通调用未绑定检查器时为空操作。"""
    check = getattr(_CANCEL_LOCAL, "check", None)
    if check is not None:
        check()


def _cancel_aware_sleep(seconds: float) -> None:
    """把限流/重试等待切成短片，避免终止后仍完整等待指数退避。"""
    deadline = time.monotonic() + max(float(seconds), 0.0)
    while True:
        check_thread_cancel()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 0.1))


@contextmanager
def thread_cancel_scope(check):
    """仅在当前工作线程绑定取消检查器，退出时恢复原值，避免污染共享数据源实例。"""
    previous = getattr(_CANCEL_LOCAL, "check", None)
    _CANCEL_LOCAL.check = check
    try:
        yield
    finally:
        if previous is None:
            try:
                delattr(_CANCEL_LOCAL, "check")
            except AttributeError:
                pass
        else:
            _CANCEL_LOCAL.check = previous


# ── 限流 / 重试 装饰器（应对公开接口频率/稳定性限制，需求 §10.1）──


def rate_limited(min_interval_sec: float, *, start_to_start: bool = False) -> Callable:
    """方法级简单限流：相邻两次调用间隔 >= 间隔秒数（按方法名隔离记时）。

    间隔取值优先级：实例属性 `self._min_interval_sec`（运行时按生效配置注入，
    见各源 __init__）> 装饰器入参 min_interval_sec（导入期默认兜底）。这样前端
    改「请求限流」后，新建的数据源实例即按新值限流，无需重启进程。并发时每线程
    各自独立实例 → 限流按线程隔离，总速率≈并发数×单线程速率。

    `start_to_start=True` 按「调用起始」记时，使配置的每秒请求数就是真实起始间隔；
    默认按「调用结束」记时，间隔之外还会再叠加一次请求往返耗时，实际速率低于配置值。
    已被外部锁全进程串行的路径用前者：锁已保证不并发，再按结束记时会与串行重复叠加。
    """

    def deco(fn: Callable) -> Callable:
        attr = f"_last_call_{fn.__name__}"

        @wraps(fn)
        def wrapper(self, *args, **kwargs):
            interval = getattr(self, "_min_interval_sec", None)
            if interval is None:
                interval = min_interval_sec
            last = getattr(self, attr, 0.0)
            wait = interval - (time.monotonic() - last)
            if wait > 0:
                _cancel_aware_sleep(wait)
            started = time.monotonic()
            try:
                check_thread_cancel()
                result = fn(self, *args, **kwargs)
                check_thread_cancel()
                return result
            finally:
                setattr(self, attr, started if start_to_start else time.monotonic())

        return wrapper

    return deco


def with_retry(max_retries: int = 3, backoff_sec: float = 2.0) -> Callable:
    """失败重试 + 指数退避；最终失败抛 DataSourceError。

    次数/退避取值优先级：实例属性 `self._max_retries` / `self._retry_backoff_sec`
    （运行时按生效配置注入，见各源 __init__）> 装饰器入参（导入期默认兜底）。这样前端
    改「重试次数 / 退避」后，新建的数据源实例即按新值重试，无需重启进程（与 rate_limited 同款）。
    """

    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            self = args[0] if args else None
            retries = getattr(self, "_max_retries", None)
            if retries is None:
                retries = max_retries
            backoff = getattr(self, "_retry_backoff_sec", None)
            if backoff is None:
                backoff = backoff_sec
            last_err: Exception | None = None
            for attempt in range(1, retries + 1):
                check_thread_cancel()
                try:
                    result = fn(*args, **kwargs)
                    check_thread_cancel()
                    return result
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    check_thread_cancel()
                    if attempt < retries:
                        sleep = backoff * (2 ** (attempt - 1))
                        log.warning(
                            "%s 第%d次失败: %s，%.1fs 后重试", fn.__name__, attempt, e, sleep
                        )
                        _cancel_aware_sleep(sleep)
            raise DataSourceError(
                f"{fn.__name__} 重试 {retries} 次仍失败: {last_err}"
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

    def get_share_capital(self, code: str, dates) -> pd.DataFrame:
        """对应行情日的历史股本，含生效/公告日及总市值可补算标记。"""
        raise NotImplementedError(f"{self.name} 不支持逐日股本能力")

    def get_basic_dates(self) -> pd.DataFrame:
        """全市场上市/退市日期（含退市股）。列：code,name,list_date,delist_date,is_delisted。"""
        raise NotImplementedError(f"{self.name} 不支持 basic_dates 能力")

    def get_industry(self) -> pd.DataFrame:
        """全市场行业分类。列：code,industry。"""
        raise NotImplementedError(f"{self.name} 不支持 industry 能力")

    def get_st_status(self, code: str, start: date, end: date) -> pd.DataFrame:
        """每日点时 ST 状态。列：code,trade_date,is_st,trade_status。"""
        raise NotImplementedError(f"{self.name} 不支持 st_status 能力")

    def get_intraday_1m(self, code: str, provider: str = "sina") -> pd.DataFrame:
        """近期 1 分钟不复权行情窗口；不支持时显式报错。"""
        raise NotImplementedError(f"{self.name} 不支持 intraday_1m 能力")

    # ── 能力声明（供编排层按能力选源，见 IngestionService._source_for）──
    # 约定能力名：daily/index/calendar/stock_list/valuation/basic_dates/industry/delisted/
    # adj_factor/st_status
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
        # 进程级单例：复用登录会话（baostock 登录 ~6s 且为库级全局单会话），避免每任务/每股重登。
        from backend.datasource.baostock_source import shared_baostock

        return shared_baostock()
    raise DataSourceError(f"未知数据源: {name}")
