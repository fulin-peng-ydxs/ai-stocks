"""AKShare 数据源适配器（SDD §5）。

⚠️ 实测发现（2026-05-31 探针）：
东财系接口（stock_zh_a_hist / index_zh_a_hist / stock_individual_info_em，
均走 push2his.eastmoney.com）在本环境被限流/封禁，连接直接中断；
而**新浪系接口稳定可用**。故本适配器以新浪接口为主工作路径：
- 日线：stock_zh_a_daily（不复权 + 后复权两次取数，现算复权因子）
- 指数：stock_zh_index_daily
- 列表：stock_info_a_code_name
- 日历：tool_trade_date_hist_sina
个股基础信息（list_date/industry/股本）东财接口被封，板块由代码前缀判定，
每日流通股本改用新浪日线自带的 outstanding_share（且为时变值，更准）。

字段映射到 backend.datasource.base 约定的统一 schema。
"""

from __future__ import annotations

import threading
from datetime import date, timedelta

import akshare as ak
import pandas as pd
import py_mini_racer
import requests

from backend.common.logging import get_logger
from backend.common.timeutil import fmt_date, to_date
from backend.config import get_effective_settings, get_settings
from backend.datasource.base import DataSource, rate_limited, with_retry

log = get_logger("datasource.akshare")


# sina/东财对"无该标的/无区间数据"会抛空响应解码错误（如 "No value to decode"）而非返回空表。
# 这类错误重试必再失败、白等指数退避（2s+4s）——识别为"无数据"即当空返回，让 @with_retry 不再
# 无谓重试、上层（get_daily_bar/补市值）走"empty→快速降级/转兜底"。真网络错误（超时/断连）不在此
# 列、照旧抛出由 with_retry 重试。仅用于"无数据属正常结果"的单标的取数（日线/市值/单指数）；全市场
# 取数（股票列表/日历）空响应更可能是瞬时抖动，不走此函数、保留重试。
_AK_NO_DATA_SIGNS = ("no value to decode", "expected object or value", "no columns to parse")


def _ak_or_empty(fetch, who: str) -> "pd.DataFrame":
    try:
        return fetch()
    except Exception as e:  # noqa: BLE001
        if any(s in str(e).lower() for s in _AK_NO_DATA_SIGNS):
            log.info("%s 无数据(%s)，当空处理（跳过无谓重试，立即降级/转兜底）", who, type(e).__name__)
            return pd.DataFrame()
        raise

_s = get_settings().datasource
_MIN_INTERVAL = 1.0 / max(_s.rate_limit_per_sec, 0.1)

# 日线抓取向前多取的"锚定"日历天数：用于让请求区间首日也有上一交易日，
# 从而正确推算 pre_close / 复权因子（取完即裁掉，不入库）。覆盖最长休市
# （春节连休≈9 天 + 前后周末），20 天足以保证区间首日前必有一个交易日。
_PRECLOSE_ANCHOR_DAYS = 20

# 复权因子去抖阈值：现算因子=后复权收盘÷不复权收盘，两端皆四舍五入到分，
# 非除权日因子本应恒定却带噪声。不能用固定相对比例判断真实除权，因为小额
# 分红可能只有 0.1%~0.3%。这里改用"除权参考价是否偏离昨收至少 1 分"：
# 若用当日原始因子推导出的参考价与昨收差异不足 1 分，视为价格舍入噪声。
_MIN_REF_PRICE_DIFF = 0.01


# requests 默认超时（模块级可变；由 set_default_request_timeout 运行时更新，
# 配合前端「请求超时」配置——新建数据源实例时按生效配置刷新此值）。
_DEFAULT_REQUEST_TIMEOUT: float = max(float(_s.socket_timeout_sec), 1.0)

# AKShare 的新浪日线会为每次请求创建 MiniRacer。V8 的进程级 address pool 首次初始化
# 不是线程安全的；续跑会跳过日历/指数串行前置，若直接让多个工作线程同时首次进入，
# libmini_racer 会触发不可捕获的原生 FATAL 并杀死整个服务进程。保留一个进程级上下文，
# 并把首次初始化收敛到单线程；后续各工作线程仍使用 AKShare 自己的独立上下文并发解码。
_SINA_JS_RUNTIME_LOCK = threading.Lock()
_SINA_JS_RUNTIME_CONTEXT = None


def ensure_sina_js_runtime_ready() -> None:
    """在并发新浪日线请求前，幂等且串行地初始化 MiniRacer 进程运行时。"""
    global _SINA_JS_RUNTIME_CONTEXT
    if _SINA_JS_RUNTIME_CONTEXT is not None:
        return
    with _SINA_JS_RUNTIME_LOCK:
        if _SINA_JS_RUNTIME_CONTEXT is None:
            context = py_mini_racer.MiniRacer()
            context.eval("1 + 1")
            _SINA_JS_RUNTIME_CONTEXT = context


def set_default_request_timeout(timeout: float) -> None:
    """更新 requests 默认超时（秒）。运行时可调，不必重启。"""
    global _DEFAULT_REQUEST_TIMEOUT
    _DEFAULT_REQUEST_TIMEOUT = max(float(timeout), 1.0)


def _install_default_requests_timeout() -> None:
    """一次性给 requests 注入默认 timeout（仅当调用方未显式传 timeout）。

    AkShare 多处 requests 调用未传 timeout，遇到 TLS 握手/读挂起会无限等待，
    socket.setdefaulttimeout 并不总能兜住。这里在模块加载时一次性、幂等地在
    Session.request（requests.get/post 等顶层函数都经由它）外包一层，覆盖**所有**
    ak.* 网络调用（日线/市值/指数/日历/列表），而非只护住日线。包装体读模块级
    _DEFAULT_REQUEST_TIMEOUT（运行时可改），故只装一次、线程安全、不串行化并发。
    """
    Session = requests.sessions.Session
    if getattr(Session, "_ai_stocks_timeout_patched", False):
        return
    _orig_request = Session.request

    def request_with_timeout(self, *args, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = _DEFAULT_REQUEST_TIMEOUT
        return _orig_request(self, *args, **kwargs)

    Session.request = request_with_timeout
    Session._ai_stocks_timeout_patched = True


# 模块加载即安装：覆盖本进程所有 ak/requests 调用，统一请求超时
_install_default_requests_timeout()


# ── 代码 / 板块工具 ─────────────────────────────────────────────


def classify_board(code6: str) -> tuple[str, str, float]:
    """由 6 位代码判定 (exchange, board, price_limit_pct)。

    用号段首位/前两位归类，覆盖新号段（如创业板 302/303）：
    - 688/689        → 科创板（沪, ±20%）
    - 30xxxx          → 创业板（深, ±20%，含 300/301/302/303…）
    - 60xxxx          → 沪市主板（±10%，含 600/601/603/605/606/607/608…）
    - 00xxxx          → 深市主板（±10%，含 000/001/002/003/004…，原中小板已并入）
    - 4/8/920         → 北交所（±30%，本期默认排除）
    - 其余            → 兜底沪市主板 + 告警（出现新号段时提醒补规则）
    """
    if code6.startswith(("688", "689")):
        return "SH", "科创板", 0.20
    if code6.startswith("30"):
        return "SZ", "创业板", 0.20
    if code6.startswith("60"):
        return "SH", "主板", 0.10
    if code6.startswith("00"):
        return "SZ", "主板", 0.10
    if code6.startswith(("4", "8", "920")):
        return "BJ", "北交所", 0.30
    log.warning("未知代码号段 %s，暂归沪市主板（请补 classify_board 规则）", code6)
    return "SH", "主板", 0.10


def to_full_code(code6: str) -> str:
    """6 位代码 -> 带后缀 600000.SH。"""
    exch, _, _ = classify_board(code6)
    return f"{code6}.{exch}"


def to_sina_symbol(code6: str) -> str:
    """6 位代码 -> 新浪格式 sh600000 / sz000001。"""
    exch, _, _ = classify_board(code6)
    prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(exch, "sh")
    return f"{prefix}{code6}"


def dejitter_adj_factor(adj_factor: pd.Series, close: pd.Series | None = None) -> pd.Series:
    """复权因子去抖：把"现算因子"整理成分段常数（序列须按日期升序）。

    因子 = 新浪后复权收盘 ÷ 不复权收盘，两端都被新浪四舍五入到分，相除后
    在**非除权日**也会有微小抖动，进而让推算的 pre_close 偏离上一日真实
    收盘、令涨跌幅产生细微误差。

    若传入 close，则按价格可解释性判断真实除权：
      raw_ref = 昨收 × 昨日原始因子 / 当日原始因子
    raw_ref 与昨收差异 >= 1 分，才认作真实除权/送转。事件日不直接采用当日
    原始因子，而是先把 raw_ref 落到分位，再反推出与上一段干净因子连续的
    新因子，确保 compute_pre_close 能精确得到官方两位参考价。

    未传 close 时保留兼容行为：仅消除完全相等附近的浮点噪声。
    """
    f = pd.to_numeric(adj_factor, errors="coerce").to_numpy(dtype=float)
    out = f.copy()
    c = None if close is None else pd.to_numeric(close, errors="coerce").to_numpy(dtype=float)
    for i in range(1, len(f)):
        prev = out[i - 1]
        cur = f[i]
        if not (prev > 0):
            continue
        if cur != cur:
            out[i] = prev
            continue
        if c is None:
            if abs(cur / prev - 1.0) <= 1e-8:
                out[i] = prev
            continue
        prev_close = c[i - 1]
        if not (prev_close > 0):
            out[i] = prev
            continue
        raw_prev = f[i - 1]
        if not (raw_prev > 0):
            raw_prev = prev
        if not (raw_prev > 0):
            out[i] = prev
            continue
        implied_ref = prev_close * raw_prev / cur
        if implied_ref == implied_ref and abs(implied_ref - prev_close) < _MIN_REF_PRICE_DIFF:
            out[i] = prev  # 非除权日：沿用前值，消除四舍五入噪声
        else:
            cur_close = c[i]
            if (cur_close == cur_close and cur_close > 0
                    and abs(implied_ref / prev_close - 1.0) > 0.5
                    and abs(cur_close / prev_close - 1.0) <= 0.3):
                out[i] = prev  # 源端因子断层/重置：原始价未随参考价跳变，不当作除权。
                continue
            ref_price = round(float(implied_ref), 2)
            out[i] = prev_close * prev / ref_price if ref_price > 0 else cur
    return pd.Series(out, index=adj_factor.index)


def compute_pre_close(close: pd.Series, adj_factor: pd.Series) -> pd.Series:
    """官方前收盘（除权参考价）= 前日收盘 × 前日复权因子 / 当日复权因子。

    普通日因子不变 → 等于上一日收盘；除权除息/高送转日因子跳变 →
    得到调整后的参考价，使涨跌幅/涨跌停判定正确。序列须按日期升序。
    传入去抖后的因子（见 dejitter_adj_factor），非除权日可精确还原上一日收盘。
    """
    return (close.shift(1) * adj_factor.shift(1) / adj_factor).round(2)


def index_to_sina_symbol(index_code: str) -> str:
    """指数代码 -> 新浪 symbol。

    指数代码统一带交易所后缀（'000905.SH'），转 'sh000905'，
    杜绝与深市个股(000xxx)冲突。兼容裸代码（默认沪市）。
    """
    if "." in index_code:
        code6, exch = index_code.split(".")
        return f"{exch.lower()}{code6}"
    if index_code[:2] in ("sh", "sz"):
        return index_code
    return f"sh{index_code}"


class AKShareSource(DataSource):
    name = "akshare"
    # 新浪日线/指数/日历/列表 + 东财市值（valuation 单只历史）
    capabilities = {"daily", "index", "calendar", "stock_list", "valuation"}

    def __init__(self) -> None:
        # 读"生效配置"(YAML ⊕ 前端 app_config 覆盖)，让前端改「请求限流/超时/重试」
        # 对新建实例即时生效，无需重启。限流/重试走实例属性（被 @rate_limited / @with_retry
        # 优先采用）；超时刷新模块级 requests 默认值。失败回落导入期默认。
        try:
            eff = get_effective_settings().datasource
            self._min_interval_sec = 1.0 / max(eff.rate_limit_per_sec, 0.1)
            self._max_retries = eff.max_retries
            self._retry_backoff_sec = eff.retry_backoff_sec
            set_default_request_timeout(eff.socket_timeout_sec)
        except Exception:  # noqa: BLE001 —— 配置/DB 异常时回落 YAML 导入期默认
            self._min_interval_sec = _MIN_INTERVAL

    # ── 股票列表 ──
    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL)
    def get_stock_list(self) -> pd.DataFrame:
        df = ak.stock_info_a_code_name()  # columns: code, name
        df = df.rename(columns={"code": "code6"})
        df["code"] = df["code6"].apply(to_full_code)
        return df[["code", "code6", "name"]]

    # ── 个股基础信息（板块由代码判定；其余尽力而为）──
    def get_stock_info(self, code: str) -> pd.DataFrame:
        code6 = code.split(".")[0]
        exch, board, limit = classify_board(code6)
        return pd.DataFrame(
            [
                {
                    "code": to_full_code(code6),
                    "name": None,
                    "exchange": exch,
                    "board": board,
                    "list_date": None,
                    "delist_date": None,
                    "total_share": None,
                    "float_share": None,
                    "industry": None,
                    "price_limit_pct": limit,
                }
            ]
        )

    # ── 日线（新浪：不复权 + 后复权 → 现算复权因子）──
    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL)
    def _sina_daily(self, code6: str, start: date, end: date, adjust: str) -> pd.DataFrame:
        # 请求超时已由模块级 _install_default_requests_timeout 全局注入，
        # 此处无需再局部包裹（也就不会再用锁串行化并发日线请求）。
        ensure_sina_js_runtime_ready()
        return _ak_or_empty(
            lambda: ak.stock_zh_a_daily(
                symbol=to_sina_symbol(code6),
                start_date=fmt_date(start, compact=True),
                end_date=fmt_date(end, compact=True),
                adjust=adjust,
            ),
            f"{code6} sina日线",
        )

    def get_daily_bar(
        self, code: str, start: date, end: date, adjust: str = ""
    ) -> pd.DataFrame:
        code6 = code.split(".")[0]
        # 向前多取一段"锚定"交易日：使请求区间首日也有上一交易日，从而正确推算
        # pre_close / 复权因子（否则窗口首日 shift(1) 为 NaN → pre_close 缺失 →
        # 涨跌幅算不出）。锚定段仅用于计算，最后裁掉、不入库。
        fetch_start = start - timedelta(days=_PRECLOSE_ANCHOR_DAYS)
        raw = self._sina_daily(code6, fetch_start, end, "")
        # 空数据或返回结构异常（无 date 列，如无效 symbol）→ 视为无数据，不重试
        if raw is None or raw.empty or "date" not in raw.columns:
            return pd.DataFrame()

        raw = raw.copy()
        raw["trade_date"] = pd.to_datetime(raw["date"]).dt.date

        # 复权因子 = 后复权收盘 / 不复权收盘（比例，前复权计算时再按最新因子归一）
        try:
            hfq = self._sina_daily(code6, fetch_start, end, "hfq")
            hfq = hfq.copy()
            hfq["trade_date"] = pd.to_datetime(hfq["date"]).dt.date
            factor = hfq.set_index("trade_date")["close"] / raw.set_index("trade_date")["close"]
            raw["adj_factor"] = raw["trade_date"].map(factor)
        except Exception as e:  # noqa: BLE001
            log.warning("%s 复权因子获取失败，置 1.0: %s", code, e)
            raw["adj_factor"] = 1.0

        out = pd.DataFrame(
            {
                "code": to_full_code(code6),
                "trade_date": raw["trade_date"],
                "open": raw["open"].astype(float),
                "high": raw["high"].astype(float),
                "low": raw["low"].astype(float),
                "close": raw["close"].astype(float),
                "volume": raw["volume"].astype("int64"),
                "amount": raw["amount"].astype(float),
                "adj_factor": raw["adj_factor"].astype(float),
                # 新浪 turnover 为小数（流通占比），换算成百分比
                "turnover_rate": (raw["turnover"].astype(float) * 100.0),
                # 新浪自带每日流通股本（时变，用于历史市值）
                "float_share": raw["outstanding_share"].astype("int64"),
            }
        ).sort_values("trade_date").reset_index(drop=True)

        # pre_close 与 qfq 价格不能共用同一条"清洗后"因子：
        # - qfq 价格需要保留数据源复权因子，否则历史 K 线会被官方参考价重新拉齐。
        # - pre_close 需要用去抖后的参考因子，否则非除权日涨跌幅会被小数噪声带偏。
        pre_close_factor = dejitter_adj_factor(out["adj_factor"], out["close"])

        # 前收盘 = 官方除权参考价（除权除息/高送转日需按复权因子调整）：
        #   pre_close_t = close_{t-1} × adj_factor_{t-1} / adj_factor_t
        # 普通日因子不变 → 等于上一日收盘；除权日则得到调整后的参考价，
        # 保证涨跌幅/涨跌停判定正确（新浪不直接给 preclose，故由因子推算）。
        out["pre_close"] = compute_pre_close(out["close"], pre_close_factor)

        # 裁掉为锚定 pre_close/因子而多取的前置交易日，只返回请求区间
        out = out[out["trade_date"] >= start].reset_index(drop=True)
        return out

    # ── 每日估值/市值（东财 stock_value_em，含总市值/总股本）──
    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL)
    def get_valuation(self, code: str, start: date, end: date) -> pd.DataFrame:
        """每日总市值/总股本/流通市值/流通股本。

        列：code, trade_date, total_mv, float_mv, total_share, float_share。
        来源 stock_value_em（东财，与被封的 push2his 不同 endpoint，可用）。
        """
        code6 = code.split(".")[0]
        df = _ak_or_empty(lambda: ak.stock_value_em(symbol=code6), f"{code6} 市值")
        if df is None or df.empty or "数据日期" not in df.columns:
            return pd.DataFrame()
        df = df.copy()
        df["trade_date"] = pd.to_datetime(df["数据日期"]).dt.date
        mask = (df["trade_date"] >= start) & (df["trade_date"] <= end)
        df = df[mask]
        return pd.DataFrame(
            {
                "code": to_full_code(code6),
                "trade_date": df["trade_date"],
                "total_mv": pd.to_numeric(df["总市值"], errors="coerce"),
                "float_mv": pd.to_numeric(df["流通市值"], errors="coerce"),
                "total_share": pd.to_numeric(df["总股本"], errors="coerce"),
                "float_share": pd.to_numeric(df["流通股本"], errors="coerce"),
            }
        ).reset_index(drop=True)

    # ── 指数日线（新浪）──
    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL)
    def get_index_bar(self, index_code: str, start: date, end: date) -> pd.DataFrame:
        # 指数代码带后缀（'000905.SH'）→ 新浪 symbol 'sh000905'
        symbol = index_to_sina_symbol(index_code)
        df = _ak_or_empty(lambda: ak.stock_zh_index_daily(symbol=symbol), f"{index_code} 指数")
        if df is None or df.empty or "date" not in df.columns:
            return pd.DataFrame()
        df = df.copy()
        df["trade_date"] = pd.to_datetime(df["date"]).dt.date
        mask = (df["trade_date"] >= start) & (df["trade_date"] <= end)
        df = df[mask]
        out = pd.DataFrame(
            {
                "index_code": index_code,  # 保留带后缀的完整代码
                "trade_date": df["trade_date"],
                "open": df["open"].astype(float),
                "high": df["high"].astype(float),
                "low": df["low"].astype(float),
                "close": df["close"].astype(float),
                "volume": df["volume"].astype("int64"),
                "amount": df["amount"].astype(float) if "amount" in df.columns else None,
            }
        )
        return out.reset_index(drop=True)

    # ── 交易日历（新浪：仅列交易日 → is_open=True）──
    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL)
    def get_trade_calendar(self, start: date, end: date) -> pd.DataFrame:
        df = ak.tool_trade_date_hist_sina()
        df = df.copy()
        df["trade_date"] = df["trade_date"].apply(to_date)
        mask = (df["trade_date"] >= start) & (df["trade_date"] <= end)
        out = df[mask][["trade_date"]].copy()
        out["is_open"] = True
        return out.reset_index(drop=True)
