"""人工退市确认：受控修复任务内执行，来源值与人工有效值分别保存。"""

import json
from datetime import date

import pandas as pd

from backend.services.collection_quality import CollectionQualityBatch
from backend.services.eod_dates import shanghai_now
from backend.storage.repository import MarketRepository


def validate_delisting(client, issue_id, value, reason):
    if not str(reason or "").strip():
        raise ValueError("请填写确认依据或撤销原因")
    row = client.query_df("SELECT code,issue_type FROM data_quality_issue WHERE id=?", [issue_id])
    if row.empty or row.iloc[0].issue_type not in ("history_data_gap", "data_gap", "stale"):
        raise ValueError("仅行情缺口/滞后问题支持人工退市确认")
    code = row.iloc[0].code
    stock = client.query_df("SELECT * FROM stock_basic WHERE code=?", [code])
    if stock.empty:
        raise ValueError("股票基础资料不存在")
    old = stock.iloc[0]
    dl = date.fromisoformat(value) if value else None
    if dl:
        if dl > shanghai_now().date():
            raise ValueError("不能把未来退市日期当作已退市事实")
        if pd.notna(old.list_date) and dl <= pd.Timestamp(old.list_date).date():
            raise ValueError("退市日期必须晚于上市日期")
        last = (
            client.query_df("SELECT max(trade_date) d FROM daily_bar WHERE code=?", [code])
            .iloc[0]
            .d
        )
        if pd.notna(last) and dl <= pd.Timestamp(last).date():
            raise ValueError(
                f"退市日期与已有行情冲突，最后行情日期为 {last:%Y-%m-%d}；请先核实，不能据此隐藏行情"
            )
    elif not bool(old.delist_date_manual):
        raise ValueError("该股票没有可撤销的人工退市标记")
    return code, dl, old


def apply_delisting(client, params, ctx):
    with client.transaction():
        code, dl, old = validate_delisting(
            client, params["issue_id"], params.get("delist_date"), params.get("reason")
        )
        # 第一次人工修改前保存现有来源值；后续采集单独更新 reported。
        reported = old.delist_date_reported if bool(old.delist_date_manual) else old.delist_date
        effective = dl if dl else (None if pd.isna(reported) else pd.Timestamp(reported).date())
        client.execute(
            "UPDATE stock_basic SET delist_date=?,delist_date_manual=?,delist_date_reported=? WHERE code=?",
            [effective, dl is not None, None if pd.isna(reported) else reported, code],
        )
        MarketRepository(client).log_update(
            "stock_basic",
            "manual:delist_date",
            dl,
            dl,
            1,
            "success",
            json.dumps(
                {
                    "code": code,
                    "before": str(old.delist_date),
                    "after": str(effective),
                    "reason": params["reason"],
                    "actor": params.get("actor"),
                    "task_id": getattr(ctx, "tid", None),
                },
                ensure_ascii=False,
            ),
        )
        pending = client.query_df(
            "SELECT id FROM data_quality_issue WHERE code=? AND status='open'",
            [code],
        )
        # 存续期变化同时影响日线、ST 和分时；撤销覆盖也须重新检出实际缺口。
        # 复用采集收尾入口，不按类型盲目关闭；失败时日期和台账一并回滚。
        quality = CollectionQualityBatch()
        quality.include("stock", [code])
        quality.include("intraday", [code])
        quality.finish(client, _in_transaction=True)
        resolved = int(client.query_df(
            "SELECT count(*) n FROM data_quality_issue WHERE status='resolved' "
            "AND id IN (SELECT unnest(?::BIGINT[]))", [pending.id.tolist()],
        ).iloc[0, 0])
    return {
        "code": code,
        "delist_date": str(effective) if effective else None,
        "resolved": resolved,
        "message": f"{code} 人工退市标记已更新，日线、ST及分时已重新核验",
    }
