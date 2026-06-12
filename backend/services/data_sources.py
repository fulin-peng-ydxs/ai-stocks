"""数据源连通性（FR-DM-5，M2.8-B）。

对 primary / fallback 源做轻量 ping（拉最近几日交易日历，足够判活且开销小），
返回 up/down + 最近成功时间 + 超时配置。免费源无稳定配额 API，不做精确配额计量（DM 暂不实现）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from backend.common.logging import get_logger
from backend.config import get_effective_settings
from backend.datasource.base import get_source

log = get_logger("services.data_sources")

# 最近成功时间（进程内缓存，避免每次都真打）
_last_success: dict[str, str] = {}


def _ping(name: str, timeout: float) -> bool:
    """轻量探活：拉最近 7 天交易日历。成功即视为连通。"""
    import socket
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        src = get_source(name)
        end = date.today()
        df = src.get_trade_calendar(end - timedelta(days=7), end)
        ok = df is not None and not df.empty
        if ok:
            _last_success[name] = str(datetime.now())
        return ok
    except Exception as e:  # noqa: BLE001
        log.warning("数据源 %s 探活失败: %s", name, e)
        return False
    finally:
        socket.setdefaulttimeout(old)


def source_status(do_ping: bool = True) -> dict:
    """返回各数据源状态。do_ping=False 时只回配置 + 缓存的最近成功时间（不真打）。"""
    s = get_effective_settings().datasource
    timeout = float(s.socket_timeout_sec)
    roles = [(s.primary, "primary"), (s.fallback, "fallback")]
    out = []
    seen = set()
    for name, role in roles:
        if name in seen:
            continue
        seen.add(name)
        up = _ping(name, timeout) if do_ping else None
        out.append({
            "source": name,
            "role": role,
            "up": up,
            "last_success_at": _last_success.get(name),
            "timeout_sec": timeout,
        })
    return {"sources": out}
