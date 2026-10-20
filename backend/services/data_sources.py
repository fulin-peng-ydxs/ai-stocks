"""数据源连通性（FR-DM-5，M2.8-B）。

对 primary / fallback 源做轻量 ping（拉最近几日交易日历，足够判活且开销小），
返回 up/down + 最近成功时间 + 超时配置。免费源无稳定配额 API，不做精确配额计量（DM 暂不实现）。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.common.logging import get_logger
from backend.config import get_effective_settings
from backend.datasource.base import get_source
from backend.storage.data_source_health_repository import DataSourceHealthRepository

log = get_logger("services.data_sources")

def _ping(name: str, timeout: float) -> tuple[bool, str | None]:
    """轻量探活：行情源拉近 7 天日历；板块源拉一页行业字典。"""
    import socket
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        if name.startswith("intraday_"):
            from backend.services.intraday_source import IntradaySourceService
            quotes = IntradaySourceService()
            df = quotes._fetch_provider(quotes.source_factory(), "600000.SH", name.removeprefix("intraday_"))
        elif name == "ths_board":
            from backend.datasource.ths_board import ThsBoardSource

            df = ThsBoardSource(timeout=timeout, max_retries=1).get_board_dict("industry")
        else:
            src = get_source(name)
            end = datetime.now().astimezone().date()
            df = src.get_trade_calendar(end - timedelta(days=7), end)
        if df is None or df.empty:
            return False, "数据源返回空结果"
        return True, None
    except Exception as e:  # noqa: BLE001
        log.warning("数据源 %s 探活失败: %s", name, e)
        return False, str(e)
    finally:
        socket.setdefaulttimeout(old)


def source_status(
    do_ping: bool = True,
    *,
    repo: DataSourceHealthRepository | None = None,
) -> dict:
    """返回各数据源状态；探活结果持久化，普通查询直接读取最近记录。"""
    s = get_effective_settings().datasource
    timeout = float(s.socket_timeout_sec)
    roles = [(s.primary, "primary"), (s.fallback, "fallback"), ("ths_board", "board"),
             ("intraday_sina", "intraday"), ("intraday_eastmoney", "intraday"),
             ("intraday_ths", "intraday")]
    repo = repo or DataSourceHealthRepository()
    records = repo.list(list(dict.fromkeys(name for name, _role in roles)))
    out = []
    seen = set()
    for name, role in roles:
        if name in seen:
            continue
        seen.add(name)
        record = records.get(name, {})
        if do_ping:
            up, failure_reason = _ping(name, timeout)
            # 以探测完成时间落库；并发测试时后完成的请求才应成为“最近测试”。
            tested_at = datetime.now().astimezone()
            repo.record(name, up=up, tested_at=tested_at, failure_reason=failure_reason)
            record = {
                "up": up,
                "last_test_at": tested_at.isoformat(timespec="seconds"),
                "last_success_at": (
                    tested_at.isoformat(timespec="seconds")
                    if up else record.get("last_success_at")
                ),
                "failure_reason": failure_reason,
            }
        item = {
            "source": name,
            "role": role,
            "up": record.get("up"),
            "last_test_at": record.get("last_test_at"),
            "last_success_at": record.get("last_success_at"),
            "failure_reason": record.get("failure_reason"),
            "timeout_sec": timeout,
        }
        if name == "ths_board":
            from backend.services.ths_cookie_status import ths_cookie_status
            try:
                item["credential"] = ths_cookie_status(validate=do_ping)
            except Exception as exc:  # noqa: BLE001 -- 配置库异常不应让状态列表整体失败
                log.warning("同花顺 Cookie 状态读取失败: %s", exc)
                item["credential"] = {
                    "status": "unknown", "source": None, "validity_days": 30,
                    "saved_at": None, "checked_at": None, "expires_at": None,
                    "remaining_days": None,
                }
        out.append(item)
    return {"sources": out}
