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

import json
import threading
from datetime import date, timedelta

import akshare as ak
import pandas as pd
import py_mini_racer
import requests

from backend.common.logging import get_logger
from backend.common.timeutil import fmt_date, to_date
from backend.config import get_effective_settings, get_settings
from backend.datasource.base import (
    SINA_INTRADAY_REQUEST_LIMIT,
    DataSource,
    rate_limited,
    with_retry,
)

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

# 新浪不复权/后复权请求必须描述同一批成交事实。并发抓取曾出现响应串票：某股票的
# OHLC 来自相邻股票的后复权响应，而成交量额来自另一响应。若不在适配层拒绝，调用方会
# 把请求代码补到错误行情上，直到涨跌停门禁才暴露。成交量额不随复权变化，适合作为配对指纹。
_DAILY_SIGNATURE_REL_TOL = 1e-8


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
    """兼容已有安装入口；实际发送包装由统一请求策略维护。

    支持的行情网站按实时生效策略限流并设置超时，覆盖AKShare内部未传超时及
    写死超时的调用；其它网站仅在未指定超时时补充原有默认值。
    """
    from backend.datasource.request_policy import install_http_policy
    install_http_policy(lambda: _DEFAULT_REQUEST_TIMEOUT)


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


def dejitter_adj_factor(adj_factor: pd.Series, close: pd.Series | None = None,
                        pre_close: pd.Series | None = None) -> pd.Series:
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
    refs = None if pre_close is None else pd.to_numeric(pre_close, errors="coerce").to_numpy(dtype=float)
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
        # 调用方只能传经来源/同次收盘校验的独立参考价，禁止传旧派生 pre_close；
        # 换码前因子被来源填成 1 时，也能按真实参考价恢复分红而非制造跨代码跳变。
        if refs is not None and refs[i] > 0:
            implied_ref = refs[i]
        if implied_ref == implied_ref and abs(implied_ref - prev_close) < _MIN_REF_PRICE_DIFF:
            out[i] = prev  # 非除权日：沿用前值，消除四舍五入噪声
        else:
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
    capabilities = {"daily", "index", "calendar", "stock_list", "valuation", "share_capital", "intraday_1m"}

    def __init__(self) -> None:
        # 读"生效配置"(YAML ⊕ 前端 app_config 覆盖)，让前端改「请求限流/超时/重试」
        # 对新建实例即时生效，无需重启。限流/重试走实例属性（被 @rate_limited / @with_retry
        # 优先采用）；超时刷新模块级 requests 默认值。失败回落导入期默认。
        self._share_timeout_sec = _s.socket_timeout_sec
        try:
            eff = get_effective_settings().datasource
            self._min_interval_sec = 1.0 / max(eff.rate_limit_per_sec, 0.1)
            self._max_retries = eff.max_retries
            self._retry_backoff_sec = eff.retry_backoff_sec
            self._share_timeout_sec = eff.socket_timeout_sec
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

    def get_intraday_1m(
        self, code: str, provider: str = "sina", *, timeout_sec: float | None = None,
        request_year: int | None = None,
    ) -> pd.DataFrame:
        """读取免费源的近期 1 分钟不复权窗口，并把成交量统一为手。"""
        code6 = code.split(".")[0]
        # 编排层传入同一轮生效快照，保证锁预算和实际 HTTP 超时一致。
        timeout = (
            get_effective_settings().datasource.socket_timeout_sec
            if timeout_sec is None else timeout_sec
        )
        if provider == "ths":
            from backend.datasource.ths_intraday import fetch_ths_minutes

            return fetch_ths_minutes(code, request_year or pd.Timestamp.now(tz="Asia/Shanghai").year, timeout=timeout)
        if provider == "sina":
            url = "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData"
            response = requests.get(
                url,
                params={
                    "symbol": to_sina_symbol(code6),
                    "scale": "1",
                    "ma": "no",
                    "datalen": str(SINA_INTRADAY_REQUEST_LIMIT),
                },
                timeout=timeout,
            )
            response.raise_for_status()
            text = response.text
            try:
                payload = json.loads(text.split("=(", 1)[1].rsplit(");", 1)[0])
            except (IndexError, json.JSONDecodeError) as exc:
                raise ValueError("新浪分钟行情响应格式异常") from exc
            frame = pd.DataFrame(payload)
            if frame.empty:
                return pd.DataFrame(
                    columns=["timestamp", "open", "high", "low", "close", "volume", "amount"]
                )
            frame = frame.rename(columns={"day": "timestamp"})
            # 新浪分钟接口的 volume 为股；分时统一契约使用手，保留零碎股形成的小数手。
            frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce") / 100
        elif provider == "eastmoney":
            # AKShare 当前封装在 1 分钟分支内写死 timeout=15，无法兑现项目配置；
            # 这里直连同一公开接口，统一使用系统 datasource.socket_timeout_sec 的生效值。
            response = requests.get(
                "https://push2his.eastmoney.com/api/qt/stock/trends2/get",
                params={
                    "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
                    "ut": "7eea3edcaed734bea9cbfc24409ed989",
                    "ndays": "5",
                    "iscr": "0",
                    "secid": f"{1 if code6.startswith('6') else 0}.{code6}",
                },
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            trends = ((payload.get("data") or {}).get("trends") or [])
            frame = pd.DataFrame(
                [item.split(",") for item in trends],
                columns=["timestamp", "open", "close", "high", "low", "volume", "amount", "average"],
            )
        else:
            raise ValueError(f"未知分钟行情源: {provider}")

        required = ["timestamp", "open", "high", "low", "close", "volume", "amount"]
        if not set(required).issubset(frame.columns):
            raise ValueError(f"{provider} 分钟行情缺失必要字段")
        out = frame[required].copy()
        out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
        for field in required[1:]:
            out[field] = pd.to_numeric(out[field], errors="coerce")
        # 不在适配层静默丢弃坏行，归档与查询共用清洗入口并保留拒用诊断。
        return out.reset_index(drop=True)

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

    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    def _sina_daily_pair(
        self, code6: str, start: date, end: date
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """成对获取并校验不复权/后复权响应；语义串票也按数据源失败自动重试。"""
        raw = self._sina_daily(code6, start, end, "")
        if raw is None or raw.empty or "date" not in raw.columns:
            return pd.DataFrame(), pd.DataFrame()
        hfq = self._sina_daily(code6, start, end, "hfq")
        self._validate_daily_pair(code6, raw, hfq)
        return raw, hfq

    @staticmethod
    def _validate_daily_pair(code6: str, raw: pd.DataFrame, hfq: pd.DataFrame) -> None:
        required = {"date", "open", "high", "low", "close", "volume", "amount"}
        if hfq is None or hfq.empty or not required.issubset(hfq.columns):
            raise ValueError(f"{code6} 后复权响应缺失必要行情字段")
        if not required.issubset(raw.columns):
            raise ValueError(f"{code6} 不复权响应缺失必要行情字段")

        raw_rows = raw.copy()
        hfq_rows = hfq.copy()
        raw_rows["date"] = pd.to_datetime(raw_rows["date"]).dt.date
        hfq_rows["date"] = pd.to_datetime(hfq_rows["date"]).dt.date
        raw_rows = raw_rows.set_index("date")
        hfq_rows = hfq_rows.set_index("date")
        common_dates = raw_rows.index.intersection(hfq_rows.index)
        if len(common_dates) != len(raw_rows.index):
            raise ValueError(f"{code6} 不复权/后复权响应日期集合不一致")

        for field in ("volume", "amount"):
            raw_values = pd.to_numeric(raw_rows.loc[common_dates, field], errors="coerce")
            hfq_values = pd.to_numeric(hfq_rows.loc[common_dates, field], errors="coerce")
            tolerance = raw_values.abs().clip(lower=1.0) * _DAILY_SIGNATURE_REL_TOL
            mismatch = raw_values.isna() | hfq_values.isna() | (
                (raw_values - hfq_values).abs() > tolerance
            )
            if mismatch.any():
                sample = common_dates[mismatch.to_numpy()][0]
                raise ValueError(
                    f"{code6} 不复权/后复权响应疑似串票：{sample} {field} 不一致"
                )

        # 成交均价应落在当日价格区间内；允许 1% 误差吸收成交额/成交量单位舍入。
        volume = pd.to_numeric(raw_rows["volume"], errors="coerce")
        amount = pd.to_numeric(raw_rows["amount"], errors="coerce")
        low = pd.to_numeric(raw_rows["low"], errors="coerce")
        high = pd.to_numeric(raw_rows["high"], errors="coerce")
        traded = volume > 0
        average = amount / volume.where(traded)
        invalid_average = traded & (
            average.isna() | (average < low * 0.99) | (average > high * 1.01)
        )
        if invalid_average.any():
            sample = raw_rows.index[invalid_average.to_numpy()][0]
            raise ValueError(f"{code6} 行情响应疑似串票：{sample} 成交均价超出价格区间")

    def get_daily_bar(
        self, code: str, start: date, end: date, adjust: str = ""
    ) -> pd.DataFrame:
        code6 = code.split(".")[0]
        # 向前多取一段"锚定"交易日：使请求区间首日也有上一交易日，从而正确推算
        # pre_close / 复权因子（否则窗口首日 shift(1) 为 NaN → pre_close 缺失 →
        # 涨跌幅算不出）。锚定段仅用于计算，最后裁掉、不入库。
        fetch_start = start - timedelta(days=_PRECLOSE_ANCHOR_DAYS)
        raw, hfq = self._sina_daily_pair(code6, fetch_start, end)
        # 空数据或返回结构异常（无 date 列，如无效 symbol）→ 视为无数据，不重试
        if raw is None or raw.empty or "date" not in raw.columns:
            return pd.DataFrame()

        raw = raw.copy()
        raw["trade_date"] = pd.to_datetime(raw["date"]).dt.date

        # 复权因子 = 后复权收盘 / 不复权收盘（比例，前复权计算时再按最新因子归一）
        try:
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
        # 新浪不直接提供官方除权参考价，只能由两条均已按分位舍入的价格序列
        # 反推。记录真实因子切换日，让入库层仅在“参考价精度足以改变合法
        # 涨跌停边界”时向带官方 preclose 的备用源做定向校准。
        out["_pre_close_factor_event"] = (
            pre_close_factor.div(pre_close_factor.shift(1)).sub(1).abs().gt(1e-10)
        )

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
        from backend.datasource.share_capital import fetch_daily_valuation

        self._last_valuation_prices = (code, {})
        df = fetch_daily_valuation(code, timeout=self._share_timeout_sec)
        if df is None or df.empty or "数据日期" not in df.columns:
            return pd.DataFrame()
        df = df.copy()
        df["trade_date"] = pd.to_datetime(df["数据日期"]).dt.date
        mask = (df["trade_date"] >= start) & (df["trade_date"] <= end)
        df = df[mask]
        # 保留同次市值响应的价格证据，区分股本差异与行情源价格差异。
        if "CLOSE_PRICE" in df:
            self._last_valuation_prices = (code, dict(zip(
                df.trade_date, pd.to_numeric(df.CLOSE_PRICE, errors="coerce"), strict=True,
            )))
        return pd.DataFrame(
            {
                "code": to_full_code(code6),
                "trade_date": df["trade_date"],
                "total_mv": pd.to_numeric(df["总市值"], errors="coerce"),
                "float_mv": pd.to_numeric(df["流通市值"], errors="coerce"),
                "valuation_close": pd.to_numeric(df.get("CLOSE_PRICE"), errors="coerce"),
                "total_share": pd.to_numeric(df["总股本"], errors="coerce"),
                "float_share": pd.to_numeric(df["流通股本"], errors="coerce"),
            }
        ).reset_index(drop=True)

    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL)
    def get_share_capital(self, code: str, dates) -> pd.DataFrame:
        """完整股本变动分页按变动日期展开，公告日期保留用于溯源。"""
        from backend.datasource.share_capital import expand_equity_events, fetch_equity_events

        events = fetch_equity_events(code, timeout=self._share_timeout_sec)
        self._last_share_events = (code, events)
        return expand_equity_events(code, events, dates)

    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL)
    def get_float_share_history(self, code: str, dates) -> pd.DataFrame:
        """仅补流通股本缺口，不重采完整行情。"""
        from backend.datasource.share_capital import fetch_sina_float_shares

        return fetch_sina_float_shares(code, dates, timeout=self._share_timeout_sec)

    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL)
    def get_share_capital_fallback(self, code: str, dates) -> pd.DataFrame:
        """独立历史股本源补缺，沿用同一变动日期口径。"""
        from backend.datasource.share_capital import expand_equity_events, fetch_sina_equity_events

        events = fetch_sina_equity_events(code, timeout=self._share_timeout_sec)
        self._last_fallback_share_events = (code, events)
        return expand_equity_events(code, events, dates)

    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL)
    def get_exchange_share_capital(self, code: str, dates) -> pd.DataFrame:
        """自动发现沪市转债，使用转股前基准和交易所日统计补总股本。"""
        from backend.datasource.share_capital import fetch_equity_events
        from backend.datasource.share_conversion import (
            fetch_convertible_bonds,
            fetch_sse_conversions,
            reconstruct_conversion_shares,
        )
        self._exchange_share_evidence = {}
        if not code.endswith(".SH") or not len(dates):
            return pd.DataFrame()
        cached = getattr(self, "_last_share_events", None)
        events = cached[1] if cached is not None and cached[0] == code else fetch_equity_events(
            code, timeout=self._share_timeout_sec)
        if events.empty or not events.CHANGE_REASON.fillna("").str.contains("债转股|转债转股").any():
            self._exchange_share_evidence = {"not_applicable": "no_convertible_capital_events"}
            return pd.DataFrame()
        bonds = fetch_convertible_bonds(code, timeout=self._share_timeout_sec)
        return reconstruct_conversion_shares(
            code, dates, events, bonds,
            lambda bond, year: fetch_sse_conversions(bond, year, timeout=self._share_timeout_sec),
            evidence=self._exchange_share_evidence,
        )

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
