"""按真实接口能力展示来源、请求配置及显式连通测试；普通读取不触网。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import requests

from backend.common.logging import get_logger
from backend.config import get_effective_settings
from backend.datasource.base import get_source, with_retry
from backend.datasource.request_policy import request_policy
from backend.storage.data_source_health_repository import DataSourceHealthRepository

log = get_logger("services.data_sources")

# 稳定ID保留既有探活记录；展示名明确网站与接口能力，不能将接入库当全链路主源。
SOURCE_DEFINITIONS = (
    (
        "akshare",
        "新浪行情（AKShare）",
        "sina",
        "日线、指数、日历；主备选择仅适用于支持切换的行情能力",
        "primary",
    ),
    (
        "baostock",
        "BaoStock",
        "baostock",
        "逐日ST、上市退市资料、历史行情与参考价；共享会话串行",
        "fallback",
    ),
    (
        "eastmoney_capital",
        "东财股本与估值",
        "eastmoney",
        "逐日估值、股本变动及转债映射；不受行情主备选择控制",
        "reference",
    ),
    ("sse_capital", "上交所股本核验", "sse", "转股统计；用于历史股本补充核验", "reference"),
    (
        "ths_board",
        "同花顺板块",
        "ths_board",
        "板块字典、成分、指数和资金流；独立Cookie、会话串行",
        "board",
    ),
    ("intraday_sina", "新浪分时", "sina", "常规分时采集主源；逐股1分钟窗口", "intraday"),
    ("intraday_ths", "同花顺分时", "ths", "仅质检修复备用；按目标年份取1分钟数据", "intraday"),
    ("intraday_eastmoney", "东财分时", "eastmoney", "仅质检修复备用；最近5个交易日", "intraday"),
)


def _ping(name: str, timeout: float) -> tuple[bool, str | None]:
    """只核验本行能力的代表接口；连通不能证明其它接口或全市场数据完整。"""
    try:
        if name.startswith("intraday_"):
            from backend.services.intraday_source import IntradaySourceService

            quotes = IntradaySourceService()
            df = quotes._fetch_provider(
                quotes.source_factory(), "600000.SH", name.removeprefix("intraday_")
            )
        elif name == "ths_board":
            from backend.datasource.ths_board import ThsBoardSource

            df = ThsBoardSource().get_board_dict("industry")
        elif name in {"eastmoney_capital", "sse_capital"}:

            class Probe:
                # with_retry与适配器使用同一请求策略；HTTP发送层负责逐次限流。
                _max_retries = get_effective_settings().datasource.max_retries
                _retry_backoff_sec = get_effective_settings().datasource.retry_backoff_sec

                @with_retry()
                def fetch(self):
                    if name == "eastmoney_capital":
                        response = requests.get(
                            "https://datacenter-web.eastmoney.com/api/data/v1/get",
                            params={
                                "reportName": "RPT_VALUEANALYSIS_DET",
                                "columns": "ALL",
                                "filter": '(SECURITY_CODE="600000")',
                                "pageSize": 1,
                                "pageNumber": 1,
                            },
                            timeout=timeout,
                        )
                        response.raise_for_status()
                        return pd.DataFrame((response.json().get("result") or {}).get("data") or [])
                    from backend.datasource.share_conversion import SSE_PAGE

                    response = requests.get(
                        "https://query.sse.com.cn/commonQuery.do",
                        params={
                            "sqlId": "COMMON_SSEBOND_SCSJ_SCTJ_ZXTJ_KZZZGTJ_CX_L",
                            "YEAR": datetime.now().astimezone().year,
                            "isPagination": "true",
                            "pageHelp.pageSize": 1,
                            "pageHelp.pageNo": 1,
                        },
                        headers={"Referer": SSE_PAGE},
                        timeout=timeout,
                    )
                    response.raise_for_status()
                    page = response.json().get("pageHelp")
                    if not isinstance(page, dict) or page.get("total") is None:
                        raise ValueError("上交所转股统计响应格式异常")
                    return pd.DataFrame([{"total": page["total"]}])

            df = Probe().fetch()
        else:
            src = get_source(name)
            end = datetime.now().astimezone().date()
            df = src.get_trade_calendar(end - timedelta(days=7), end)
        if df is None or df.empty:
            return False, "代表接口返回空结果，无法确认本项能力可用"
        return True, None
    except Exception as exc:  # noqa: BLE001 -- 一项故障不影响其它来源展示
        log.warning("数据源 %s 探活失败: %s", name, exc)
        return False, str(exc)[:1000]


def source_status(do_ping: bool = True, *, repo=None, source: str | None = None) -> dict:
    settings = get_effective_settings()
    s = settings.datasource
    definitions = [item for item in SOURCE_DEFINITIONS if source is None or item[0] == source]
    if not definitions:
        raise ValueError("未知数据源能力")
    repo = repo or DataSourceHealthRepository()
    records = repo.list([item[0] for item in definitions])
    out = []
    for name, label, group, scope, role in definitions:
        if name in {s.primary, s.fallback}:
            role = "primary" if name == s.primary else "fallback"
        policy = request_policy(group, settings)
        record = records.get(name, {})
        if do_ping:
            up, failure_reason = _ping(name, policy.timeout)
            tested_at = datetime.now().astimezone()
            repo.record(name, up=up, tested_at=tested_at, failure_reason=failure_reason)
            record = {
                "up": up,
                "last_test_at": tested_at.isoformat(timespec="seconds"),
                "last_success_at": tested_at.isoformat(timespec="seconds")
                if up
                else record.get("last_success_at"),
                "failure_reason": failure_reason,
            }
        item = {
            "source": name,
            "label": label,
            "role": role,
            "scope": scope,
            "up": record.get("up"),
            "last_test_at": record.get("last_test_at"),
            "last_success_at": record.get("last_success_at"),
            "failure_reason": record.get("failure_reason"),
            "timeout_sec": policy.timeout,
            "rate_limit_per_sec": policy.rate,
            "max_attempts": policy.attempts,
            "retry_backoff_sec": policy.backoff,
            "serial_required": group in {"baostock", "ths_board"},
            "concurrency": 1 if group in {"baostock", "ths_board"} else s.update_concurrency,
            "rate_group": group,
            "policy_overrides": list(policy.overrides),
            "policy_origin": (
                ("保留旧显式覆盖" if policy.overrides else "继承通用配置")
                + (" + 板块频率限制" if group == "ths_board" else "")
            ),
            "login_timeout_sec": s.baostock_login_timeout_sec if group == "baostock" else None,
            "probe_scope": "仅核验代表接口；成功不等于所有接口和数据覆盖均正常",
        }
        if name == "ths_board":
            from backend.services.ths_cookie_status import ths_cookie_status

            try:
                item["credential"] = ths_cookie_status(validate=do_ping)
            except Exception as exc:  # noqa: BLE001 -- 脱敏状态旁路不影响清单
                log.warning("同花顺 Cookie 状态读取失败: %s", exc)
                item["credential"] = {"status": "unknown", "remaining_days": None}
        out.append(item)
    return {"sources": out}
