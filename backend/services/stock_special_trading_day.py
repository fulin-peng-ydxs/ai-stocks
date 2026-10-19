"""经公告核验的特殊交易日事实；通过互斥异步任务维护，不从价格/名称推断。"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlparse
from uuid import uuid4

import pandas as pd

from backend.storage.duckdb_client import DuckDBClient


def normalize_special_day_params(params: dict) -> dict:
    """限制单次导入规模、事实类型和来源；撤销使用 active=false 保留事实记录。"""
    records = params.get("records")
    if not isinstance(records, list) or not 1 <= len(records) <= 100:
        raise ValueError("records 必须包含 1～100 条经公告核验的特殊交易日事实")
    normalized, keys = [], set()
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("特殊交易日记录必须为对象")  # noqa: TRY004 -- API 参数校验统一 ValueError
        code = str(item.get("code", ""))
        if not re.fullmatch(r"\d{6}\.(SH|SZ)", code):
            raise ValueError("特殊交易日仅支持沪深股票标准代码")
        try:
            day = date.fromisoformat(str(item.get("trade_date", "")))
            announced = date.fromisoformat(str(item.get("announcement_date", "")))
        except ValueError as exc:
            raise ValueError("交易日和公告日期必须为 YYYY-MM-DD") from exc
        if announced > day:
            raise ValueError("公告日期不得晚于特殊交易日")
        if item.get("event_type") not in {"delisting_first_day", "resumption_no_limit"}:
            raise ValueError("仅支持公告确认的退市整理首日或恢复交易无涨跌幅限制日")
        source_ref = str(item.get("source_ref", "")).strip()
        url = urlparse(source_ref)
        if (
            url.scheme != "https"
            or url.username
            or url.password
            or url.hostname
            not in {
                "disc.static.szse.cn",
                "www.szse.cn",
                "www.sse.com.cn",
                "static.sse.com.cn",
                "static.cninfo.com.cn",
            }
        ):
            raise ValueError("source_ref 必须为交易所或巨潮资讯官方 HTTPS 公告链接")
        note = str(item.get("note", "")).strip()
        if not note or len(note) > 1000 or len(source_ref) > 2000:
            raise ValueError("必须填写不超过 1000 字的核验说明，公告链接不超过 2000 字")
        active = item.get("active", True)
        if not isinstance(active, bool):
            raise ValueError("active 必须为布尔值")  # noqa: TRY004 -- API 参数校验统一 ValueError
        key = (code, day)
        if key in keys:
            raise ValueError("同一批次股票与交易日不得重复")
        keys.add(key)
        normalized.append(
            {
                "code": code,
                "trade_date": day.isoformat(),
                "announcement_date": announced.isoformat(),
                "event_type": item["event_type"],
                "source_ref": source_ref,
                "note": note,
                "active": active,
            }
        )
    return {"records": normalized}


class StockSpecialTradingDayService:
    """事实更新与失效 outbox 同事务提交，重放幂等；任务参数保留维护审计。"""

    def __init__(self, client: DuckDBClient):
        self.c = client

    def import_records(self, params: dict, *, task_id: str) -> dict:
        from backend.services.limit_ladder_snapshot import LimitLadderSnapshotService

        records = normalize_special_day_params(params)["records"]
        # 上次事实已提交但失效处理失败时，幂等重放也必须先完成通知。
        LimitLadderSnapshotService(self.c).process_pending_invalidations()
        frame = pd.DataFrame(records)
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
        frame["announcement_date"] = pd.to_datetime(frame["announcement_date"]).dt.date
        with self.c.temp_view(frame, "special_days") as view:
            invalid = self.c.query_df(f"""
                SELECT v.code,v.trade_date FROM {view} v
                LEFT JOIN stock_basic b ON b.code=v.code
                LEFT JOIN trade_calendar t ON t.trade_date=v.trade_date AND t.is_open
                WHERE b.code IS NULL OR b.list_date IS NULL OR b.list_date>v.trade_date
                   OR (b.delist_date IS NOT NULL AND b.delist_date<v.trade_date)
                   OR t.trade_date IS NULL
            """)
            if not invalid.empty:
                raise ValueError(f"股票或交易日不属于点时股票池: {invalid.to_dict('records')}")
            with self.c.transaction():
                changed = self.c.query_df(f"""
                    SELECT v.* FROM {view} v
                    LEFT JOIN stock_special_trading_day s USING (code,trade_date)
                    WHERE s.code IS NULL OR (s.event_type,s.announcement_date,s.source_ref,s.note,s.active)
                        IS DISTINCT FROM
                        (v.event_type,v.announcement_date,v.source_ref,v.note,v.active)
                """)
                if changed.empty:
                    return {"changed_count": 0, "message": "特殊交易日事实未变化"}
                with self.c.temp_view(changed, "changed_special_days") as changes:
                    self.c.execute(
                        f"""
                        INSERT INTO stock_special_trading_day
                        SELECT code,trade_date,event_type,announcement_date,source_ref,note,active,
                               ?,current_timestamp FROM {changes}
                        ON CONFLICT (code,trade_date) DO UPDATE SET
                            event_type=excluded.event_type,announcement_date=excluded.announcement_date,
                            source_ref=excluded.source_ref,note=excluded.note,active=excluded.active,
                            task_id=excluded.task_id,updated_at=excluded.updated_at
                    """,
                        [task_id],
                    )
                from backend.services.stock_st_status import StockSTStatusService

                # 变更与撤销均重算精确日期标记，防止旧涨跌停标记继续影响下游。
                for row in changed.itertuples(index=False):
                    StockSTStatusService(self.c).rebuild_daily_bar_markers(
                        codes=[row.code], start=row.trade_date, end=row.trade_date
                    )
                affected = pd.Timestamp(changed["trade_date"].min()).date()
                self.c.execute(
                    """
                    INSERT INTO limit_ladder_invalidation_outbox
                    (event_id,affected_from,reason,status,attempt_count,created_at,updated_at)
                    VALUES (?,?,'special_trading_day_changed','pending',0,
                            current_timestamp,current_timestamp)
                """,
                    [uuid4().hex, affected],
                )
        invalidated = LimitLadderSnapshotService(self.c).process_pending_invalidations()
        return {
            "changed_count": len(changed),
            "invalidated_count": invalidated,
            "affected_from": affected.isoformat(),
            "message": f"已维护 {len(changed)} 条特殊交易日事实，失效 {invalidated} 个快照",
        }


def apply_special_day_markers(client: DuckDBClient, frame: pd.DataFrame) -> pd.DataFrame:
    """采集和因子重算共用公告事实，按股票/日期精确匹配，不扩散到相邻日。"""
    if frame.empty:
        return frame
    keys = frame[["code", "trade_date"]].drop_duplicates().copy()
    keys["trade_date"] = pd.to_datetime(keys["trade_date"]).dt.date
    with client.temp_view(keys, "marker_special_keys") as view:
        facts = client.query_df(
            f"SELECT s.code,s.trade_date FROM stock_special_trading_day s "
            f"JOIN {view} k USING(code,trade_date) WHERE s.active"
        )
    special = {(r.code, pd.Timestamp(r.trade_date).date()) for r in facts.itertuples()}
    result = frame.copy()
    mask = [(r.code, pd.Timestamp(r.trade_date).date()) in special for r in result.itertuples()]
    result.loc[mask, "limit_status"] = 0
    result.loc[mask, "is_one_word"] = False
    return result
