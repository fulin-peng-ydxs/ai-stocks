"""baostock 数据源适配器（T-M1-4，需求附录 A：补退市股 + 上市/退市日）。

baostock 优势（探针实测）：
- query_stock_basic 提供 ipoDate(上市日)/outDate(退市日)/status(1上市0退市)/type ——
  补上新浪缺的上市/退市日期，且含 1125 只退市股（防幸存者偏差核心）。
- query_history_k_data_plus 可取**退市股历史日线**，含 preclose/turn/tradestatus/isST。

代码格式：baostock 用 'sh.600000' / 'sz.000001'（点分隔）。
登录态为进程级；本类惰性 login，析构/close 时 logout。
"""

from __future__ import annotations

import socket
import threading
import time
from contextlib import contextmanager
from datetime import date

import pandas as pd

from backend.common.exceptions import DataSourceError
from backend.common.logging import get_logger
from backend.common.timeutil import fmt_date, to_date
from backend.config import get_settings
from backend.config.request_snapshot import get_request_settings as get_effective_settings
from backend.datasource.akshare_source import classify_board
from backend.datasource.base import DataSource, rate_limited, with_retry

log = get_logger("datasource.baostock")

_s = get_settings().datasource
_MIN_INTERVAL = 1.0 / max(_s.rate_limit_per_sec, 0.1)

# 进程级单例 + 会话复用：baostock 登录 ~6s，且 bs.login/logout 是库级全局单会话。若每个任务/每只
# 股都新建实例重登，既慢又会互相踩（一个实例析构 logout 掉全局会话）。统一走 shared_baostock()。
_SHARED: "BaostockSource | None" = None
# 会话复用上限：超过则重登——_collect 在会话失效时返回空表(不抛错)，靠 TTL 重登从"过期后一直空"恢复。
_LOGIN_TTL_SEC = 25 * 60

# ── 挂起看门狗 ──
# baostock 客户端在源端丢弃连接时会空转：`socketutil.send_msg` 的收包循环等不到结束分隔符，
# 而 `recv` 持续返回空字节——既不阻塞也不抛错，于是 socket 超时、重试、协作式取消检查全部失效，
# 调用线程永远出不来。唯一能解除的手段是把这条进程级 socket 关掉（`recv` 随即抛错）。
# 阈值取「socket 超时的倍数」并留足余量：单只查询亚秒级，最慢的全市场查询实测约 33s，
# 默认 90s 不会误伤；一旦超过就判定会话已被源端丢弃，断开会话让调用方按"查询失败"重试或放弃。
_HANG_BREAK_FACTOR = 3.0
_HANG_MIN_SOCKET_TIMEOUT_SEC = 20.0
_WATCHDOG_POLL_SEC = 1.0
_SESSION_LOCK = threading.RLock()
_watchdog_lock = threading.Lock()
_watchdog_deadline = 0.0  # monotonic 截止时刻；0 表示当前没有在途调用
_watchdog_limit = 0.0  # 本次在途调用的挂起阈值（秒），仅用于日志
_watchdog_thread: threading.Thread | None = None


def _break_stalled_session() -> None:
    """关闭进程级 baostock socket，让空转中的收包循环立刻抛错退出。"""
    try:
        import baostock.common.context as ctx

        sock = getattr(ctx, "default_socket", None)
        if sock is not None:
            sock.close()
        setattr(ctx, "default_socket", None)
    except Exception as exc:  # noqa: BLE001
        log.debug("看门狗断开会话失败: %s", exc)


def _watchdog_loop() -> None:
    """单进程一个看门狗线程：在途调用超过截止时刻仍未返回即断开会话。"""
    global _watchdog_deadline

    while True:
        time.sleep(_WATCHDOG_POLL_SEC)
        with _watchdog_lock:
            deadline = _watchdog_deadline
            if not deadline or time.monotonic() <= deadline:
                continue
            limit = _watchdog_limit
            _watchdog_deadline = 0.0  # 只触发一次，避免同一调用被反复断开
        log.warning(
            "baostock 查询在途超过 %.0fs 仍未返回，判定会话被源端丢弃，"
            "断开会话以解除空转；本次按查询失败重试",
            limit,
        )
        _break_stalled_session()


def _ensure_watchdog() -> None:
    global _watchdog_thread
    if _watchdog_thread is not None and _watchdog_thread.is_alive():
        return
    with _watchdog_lock:
        if _watchdog_thread is None or not _watchdog_thread.is_alive():
            _watchdog_thread = threading.Thread(
                target=_watchdog_loop, name="baostock-hang-watchdog", daemon=True
            )
            _watchdog_thread.start()


def bs_to_full(bs_code: str) -> str:
    """'sh.600000' -> '600000.SH'。"""
    market, code6 = bs_code.split(".")
    return f"{code6}.{market.upper()}"


def full_to_bs(full: str) -> str:
    """'600000.SH' -> 'sh.600000'。"""
    code6, exch = full.split(".")
    return f"{exch.lower()}.{code6}"


def _collect(rs) -> pd.DataFrame:
    """把 baostock ResultData 收集为 DataFrame。"""
    if rs.error_code != "0":
        raise DataSourceError(
            f"baostock 查询失败[{rs.error_code}]: {rs.error_msg or '未知错误'}"
        )
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    # baostock may only surface a socket/protocol failure while advancing the cursor.
    # Returning rows accumulated before that point would publish a truncated interval as complete.
    if rs.error_code != "0":
        raise DataSourceError(
            f"baostock 读取失败[{rs.error_code}]: {rs.error_msg or '未知错误'}"
        )
    return pd.DataFrame(rows, columns=rs.fields)


class BaostockSource(DataSource):
    name = "baostock"
    # baostock：日线/指数/日历 + 退市股 + 上市退市日 + 行业
    capabilities = {
        "daily", "index", "calendar", "delisted", "adj_factor", "basic_dates",
        "industry", "st_status",
    }

    def __init__(self):
        self._logged_in = False
        self._login_at = 0.0   # 上次登录的 monotonic 时刻，配合 _LOGIN_TTL_SEC 触发重登
        self._min_interval_sec = _MIN_INTERVAL
        self._max_retries = _s.max_retries
        self._retry_backoff_sec = _s.retry_backoff_sec
        self._socket_timeout_sec = _s.socket_timeout_sec
        self._login_timeout_sec = _s.baostock_login_timeout_sec
        # 限流/重试读生效配置(含前端覆盖)，前端改「请求限流/重试」对新建实例即时生效；
        # 失败回落导入期默认。（baostock 登录态为进程级单连接，仍只能串行使用。）
        try:
            eff = get_effective_settings().datasource
            self._min_interval_sec = 1.0 / max(eff.rate_limit_per_sec, 0.1)
            self._max_retries = eff.max_retries
            self._retry_backoff_sec = eff.retry_backoff_sec
            self._socket_timeout_sec = eff.socket_timeout_sec
            self._login_timeout_sec = getattr(eff, "baostock_login_timeout_sec", self._login_timeout_sec)
        except Exception as exc:  # noqa: BLE001
            log.debug("读取 Baostock 生效配置失败，使用启动基线: %s", exc)
        self._hang_policy = (self._socket_timeout_sec, self._login_timeout_sec)
        # 看门狗阈值随 socket 超时联动；测试可下调该属性以缩短等待。
        self._hang_break_sec = (
            max(max(float(self._socket_timeout_sec), _HANG_MIN_SOCKET_TIMEOUT_SEC) * _HANG_BREAK_FACTOR,
                float(self._login_timeout_sec) + float(self._socket_timeout_sec))
        )

    @contextmanager
    def _hang_guard(self, seconds: float):
        """登记本次调用的截止时刻，交给进程级看门狗在超时时断开会话。"""
        global _watchdog_deadline, _watchdog_limit

        _ensure_watchdog()
        with _watchdog_lock:
            _watchdog_deadline = time.monotonic() + seconds
            _watchdog_limit = seconds
        try:
            yield
        finally:
            with _watchdog_lock:
                _watchdog_deadline = 0.0

    def _ensure_login(self) -> None:
        import baostock as bs

        now = time.monotonic()
        if self._logged_in and (now - self._login_at) < _LOGIN_TTL_SEC:
            self._apply_socket_timeout()
            return
        if self._logged_in:   # 已超过会话复用上限 → 先登出再重登，刷新会话（防长时空闲后服务端已失效）
            try:
                bs.logout()
            except Exception:  # noqa: BLE001
                pass
            self._logged_in = False
        # SDK 每次 login 都会新建 socket，登录后 settimeout 来不及保护登录收包。
        # 仅替换 SDK 单例的本次连接器，不修改进程 socket 默认超时，避免影响并发 HTTP。
        from baostock.common import contants, context
        from baostock.util.socketutil import SocketUtil

        connector = SocketUtil()
        previous = connector.__dict__.get("connect")
        def connect_for_login():
            context.default_socket = socket.create_connection(
                (contants.BAOSTOCK_SERVER_IP, contants.BAOSTOCK_SERVER_PORT),
                timeout=float(self._login_timeout_sec),
            )
        connector.connect = connect_for_login
        try:
            lg = bs.login()
        finally:
            if previous is None:
                del connector.connect
            else:
                connector.connect = previous
        if lg.error_code != "0":
            raise DataSourceError(f"baostock 登录失败: {lg.error_msg}")
        self._logged_in = True
        self._login_at = now
        self._apply_socket_timeout()

    def _apply_socket_timeout(self) -> None:
        """baostock uses a process-global raw socket; set a read timeout explicitly."""
        try:
            import baostock.common.context as ctx

            sock = getattr(ctx, "default_socket", None)
            if sock is not None:
                sock.settimeout(float(self._socket_timeout_sec))
        except Exception as e:  # noqa: BLE001
            log.debug("设置 baostock socket timeout 失败: %s", e)

    def _invalidate_login(self) -> None:
        """Discard a broken process-global socket so the retry performs a fresh login."""
        self._logged_in = False
        self._login_at = 0.0
        try:
            import baostock.common.context as ctx

            sock = getattr(ctx, "default_socket", None)
            if sock is not None:
                sock.close()
            setattr(ctx, "default_socket", None)
        except Exception as exc:  # noqa: BLE001
            log.debug("清理失效 baostock socket 失败: %s", exc)

    def _query_frame(self, query) -> pd.DataFrame:
        """Run one SDK query and make transport failures recoverable by ``with_retry``.

        整段（登录 + 查询 + 游标遍历）都在看门狗保护内：源端丢弃连接时客户端会空转，
        只有断开会话才会抛错，才能落到下面的失效重登与 ``with_retry`` 重试。
        """
        from backend.datasource.base import check_thread_cancel
        from backend.datasource.request_policy import request_policy
        from backend.datasource.request_runtime import request_slot, session_lock

        # 锁覆盖登录、查询、游标读取及断线清理；探活也必须遵守，不能只靠采集调用方加锁。
        with session_lock(_SESSION_LOCK, "baostock"):
            try:
                policy = request_policy("baostock")
                self._socket_timeout_sec = policy.timeout
                self._login_timeout_sec = get_effective_settings().datasource.baostock_login_timeout_sec
                current = (policy.timeout, self._login_timeout_sec)
                if current != self._hang_policy:
                    self._hang_break_sec = max(max(policy.timeout, _HANG_MIN_SOCKET_TIMEOUT_SEC)
                                               * _HANG_BREAK_FACTOR,
                                               self._login_timeout_sec + policy.timeout)
                    self._hang_policy = current
                with request_slot("baostock", policy, check=check_thread_cancel), self._hang_guard(self._hang_break_sec):
                    self._ensure_login()
                    return _collect(query())
            except Exception:
                self._invalidate_login()
                raise

    def close(self) -> None:
        with _SESSION_LOCK:
            if self._logged_in:
                import baostock as bs
                bs.logout()
                self._logged_in = False

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass

    # ── 基础信息（上市/退市日 + 退市股清单）──
    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    def _query_basic(self) -> pd.DataFrame:
        import baostock as bs

        df = self._query_frame(bs.query_stock_basic)
        # 只保留股票（type==1），排除指数/其他
        df = df[df["type"] == "1"].copy()
        df["code_full"] = df["code"].apply(bs_to_full)
        df["list_date"] = df["ipoDate"].apply(lambda x: to_date(x) if x else None)
        df["delist_date"] = df["outDate"].apply(lambda x: to_date(x) if x else None)
        df["is_delisted"] = df["status"] == "0"
        return df[["code_full", "code_name", "list_date", "delist_date", "is_delisted"]].rename(
            columns={"code_full": "code", "code_name": "name"}
        )

    def get_basic_dates(self) -> pd.DataFrame:
        """全市场（含退市）上市/退市日期表。列：code,name,list_date,delist_date,is_delisted。"""
        return self._query_basic()

    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    def get_industry(self) -> pd.DataFrame:
        """全市场行业分类（证监会行业）。列：code(带后缀), industry。"""
        import baostock as bs

        df = self._query_frame(bs.query_stock_industry)
        if df.empty:
            return pd.DataFrame(columns=["code", "industry"])
        df["code"] = df["code"].apply(bs_to_full)
        df["industry"] = df["industry"].replace("", None)
        return df[["code", "industry"]]

    def get_delisted_list(self) -> pd.DataFrame:
        df = self._query_basic()
        out = df[df["is_delisted"]][["code", "name", "delist_date"]].copy()
        return out.reset_index(drop=True)

    def get_stock_list(self) -> pd.DataFrame:
        df = self._query_basic()
        live = df[~df["is_delisted"]][["code", "name"]].copy()
        live["code6"] = live["code"].apply(lambda c: c.split(".")[0])
        return live[["code", "code6", "name"]].reset_index(drop=True)

    def get_stock_info(self, code: str) -> pd.DataFrame:
        df = self._query_basic()
        row = df[df["code"] == code]
        code6 = code.split(".")[0]
        exch, board, limit = classify_board(code6)
        name = row["name"].iloc[0] if not row.empty else None
        list_date = row["list_date"].iloc[0] if not row.empty else None
        delist_date = row["delist_date"].iloc[0] if not row.empty else None
        return pd.DataFrame(
            [
                {
                    "code": code, "name": name, "exchange": exch, "board": board,
                    "list_date": list_date, "delist_date": delist_date,
                    "total_share": None, "float_share": None, "industry": None,
                    "price_limit_pct": limit,
                }
            ]
        )

    # ── 日线（退市股也可取；raw + 算复权因子）──
    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL)
    def _k_data(self, code: str, start: date, end: date, adjustflag: str) -> pd.DataFrame:
        import baostock as bs

        fields = "date,open,high,low,close,preclose,volume,amount,turn,tradestatus,isST"
        return self._query_frame(
            lambda: bs.query_history_k_data_plus(
                full_to_bs(code), fields,
                start_date=fmt_date(start), end_date=fmt_date(end),
                frequency="d", adjustflag=adjustflag,
            )
        )

    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL, start_to_start=True)
    def _st_data(self, code: str, start: date, end: date) -> pd.DataFrame:
        """Fetch only the three columns required by the ST identity timeline.

        ST 取数在生产路径上已被 `_BAO_FALLBACK_LOCK` 全进程串行（见 ingest._fetch_st_status_rows），
        此处限流只用于守住请求速率：若仍按调用结束记时，间隔之外再叠加一次往返耗时，会把实际
        速率压到配置值以下，而串行已经限住了并发，重复叠加没有额外防封收益。其余 baostock
        方法不经该锁，保持默认的结束记时。
        """
        import baostock as bs

        return self._query_frame(
            lambda: bs.query_history_k_data_plus(
                full_to_bs(code),
                "date,tradestatus,isST",
                start_date=fmt_date(start),
                end_date=fmt_date(end),
                frequency="d",
                adjustflag="3",
            )
        )

    def get_daily_bar(self, code: str, start: date, end: date, adjust: str = "") -> pd.DataFrame:
        raw = self._k_data(code, start, end, "3")  # 3=不复权
        if raw is None or raw.empty:
            return pd.DataFrame()
        raw = raw.replace("", None)
        for col in ["open", "high", "low", "close", "preclose", "amount", "turn"]:
            raw[col] = pd.to_numeric(raw[col], errors="coerce")
        raw["volume"] = pd.to_numeric(raw["volume"], errors="coerce").fillna(0).astype("int64")
        raw["trade_date"] = raw["date"].apply(to_date)

        # 停牌日过滤（兜底源根治"直线K线"）：baostock tradestatus 1=正常交易 0=停牌。
        # 停牌日 baostock 仍返回行（价格横在前收、量为0），若入库即成一串横线，且破坏全系统
        # "有行=可交易 / 无行=停牌"口径。此处只保留交易状态行，停牌交由 stock_suspension 记账。
        raw = raw[raw["tradestatus"].astype(str) == "1"]
        if raw.empty:
            return pd.DataFrame()

        # 复权因子 = 后复权收盘 / 不复权收盘
        try:
            hfq = self._k_data(code, start, end, "1")  # 1=后复权
            hfq["trade_date"] = hfq["date"].apply(to_date)
            hfq["close"] = pd.to_numeric(hfq["close"], errors="coerce")
            factor = hfq.set_index("trade_date")["close"] / raw.set_index("trade_date")["close"]
            raw["adj_factor"] = raw["trade_date"].map(factor)
        except Exception as e:  # noqa: BLE001
            log.warning("%s baostock 复权因子失败，置 1.0: %s", code, e)
            raw["adj_factor"] = 1.0

        out = pd.DataFrame(
            {
                "code": code,
                "trade_date": raw["trade_date"],
                "open": raw["open"], "high": raw["high"], "low": raw["low"], "close": raw["close"],
                "pre_close": raw["preclose"],
                "reference_pre_close": raw["preclose"],
                "reference_close": raw["close"],
                "reference_source": "baostock",
                "volume": raw["volume"], "amount": raw["amount"],
                "adj_factor": raw["adj_factor"].fillna(1.0),
                "turnover_rate": raw["turn"],  # baostock turn 已是百分比
            }
        ).sort_values("trade_date")
        # 零成交日（退市整理/停牌）成交额、换手率应为 0，而非 NaN
        zero_vol = out["volume"] == 0
        out.loc[zero_vol, "amount"] = out.loc[zero_vol, "amount"].fillna(0.0)
        out.loc[zero_vol, "turnover_rate"] = out.loc[zero_vol, "turnover_rate"].fillna(0.0)
        return out.reset_index(drop=True)

    def get_st_status(self, code: str, start: date, end: date) -> pd.DataFrame:
        """读取 baostock 的逐日 isST 字段，包含停牌返回行。

        ST 是证券在该交易日的身份事实，与“是否有可交易行情行”无关。因此这里不能复用
        ``get_daily_bar`` 的停牌过滤，否则停牌期间会制造 ST 时间线缺口。
        """
        raw = self._st_data(code, start, end)
        if raw is None or raw.empty:
            return pd.DataFrame(columns=["code", "trade_date", "is_st", "trade_status"])
        raw = raw.replace("", None)
        status = pd.to_numeric(raw["isST"], errors="coerce")
        invalid = status.isna() | ~status.isin([0, 1])
        if invalid.any():
            bad_dates = raw.loc[invalid, "date"].astype(str).head(5).tolist()
            raise DataSourceError(f"{code} baostock isST 非法，示例日期: {bad_dates}")
        return pd.DataFrame(
            {
                "code": code,
                "trade_date": raw["date"].apply(to_date),
                "is_st": status.astype("int8").astype(bool),
                # 未知交易状态绝不能填成 0（停牌）；保留 NaN，交由证据校验拒绝确认。
                "trade_status": pd.to_numeric(
                    raw["tradestatus"], errors="coerce"
                ).where(lambda values: values.isin([0, 1])),
            }
        ).sort_values("trade_date").reset_index(drop=True)

    # ── 指数 ──
    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    @rate_limited(_MIN_INTERVAL)
    def get_index_bar(self, index_code: str, start: date, end: date) -> pd.DataFrame:
        import baostock as bs

        # 指数代码带后缀（'000905.SH'）→ baostock 'sh.000905'
        if "." in index_code:
            code6, exch = index_code.split(".")
            bs_code = f"{exch.lower()}.{code6}"
        elif index_code.startswith("000"):
            bs_code = f"sh.{index_code}"
        else:
            bs_code = index_code
        df = self._query_frame(
            lambda: bs.query_history_k_data_plus(
                bs_code, "date,open,high,low,close,volume,amount",
                start_date=fmt_date(start), end_date=fmt_date(end), frequency="d",
            )
        )
        if df.empty:
            return df
        for col in ["open", "high", "low", "close", "amount"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return pd.DataFrame(
            {
                "index_code": index_code,
                "trade_date": df["date"].apply(to_date),
                "open": df["open"], "high": df["high"], "low": df["low"], "close": df["close"],
                "volume": pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64"),
                "amount": df["amount"],
            }
        )

    # ── 交易日历 ──
    @with_retry(max_retries=_s.max_retries, backoff_sec=_s.retry_backoff_sec)
    def get_trade_calendar(self, start: date, end: date) -> pd.DataFrame:
        import baostock as bs

        df = self._query_frame(
            lambda: bs.query_trade_dates(start_date=fmt_date(start), end_date=fmt_date(end))
        )
        return pd.DataFrame(
            {
                "trade_date": df["calendar_date"].apply(to_date),
                "is_open": df["is_trading_day"] == "1",
            }
        )


def shared_baostock() -> "BaostockSource":
    """进程级单例 baostock 源（复用登录会话）。所有 get_source('baostock') 经此返回同一实例，
    避免每个任务/每只股重登 ~6s；会话型，调用方仍经 _BAO_FALLBACK_LOCK 串行使用。"""
    global _SHARED
    with _SESSION_LOCK:
        if _SHARED is None:
            _SHARED = BaostockSource()
        return _SHARED
