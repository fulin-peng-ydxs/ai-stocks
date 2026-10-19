"""股本/市值全历史质量契约；扫描、概览、补采选择和修复复检共用。"""

from __future__ import annotations

import json

import pandas as pd

from backend.dataquality.checker import MV_REL_TOLERANCE

CAPITAL_ISSUE_TYPES = ("capital_gap", "capital_invalid", "capital_mismatch")
CAPITAL_LABELS = {
    "capital_gap": "股本/市值缺失",
    "capital_invalid": "股本/市值数值或日期非法",
    "capital_mismatch": "股本与市值不一致",
}
REASON_LABELS = {
    "not_yet_disclosed": "历史日期早于接口披露日",
    "no_prior_record": "接口缺少此前股本记录",
    "announcement_unknown": "接口未给出可用披露日",
    "source_unavailable": "当前来源未取得有效股数",
    "exchange_precision_conflict": "交易所统计精度与已有股数冲突",
    "exchange_count_conflict": "交易所统计与已有股数冲突",
    "source_conflict": "已有股数与另一项源端市值冲突",
    "price_basis_mismatch": "市值接口价格与本地日线不同",
    "capital_invalid": "股本/市值数值或日期仍非法",
    "share_mismatch": "市值与同日股本及原价不一致",
}


def reasons_for_issue(kind, reasons):
    """同股三类问题分别解释；采集证据和修复反馈共用分类。"""
    return {
        key: value
        for key, value in reasons.items()
        if (kind == "capital_invalid" and key == "capital_invalid")
        or (kind == "capital_mismatch" and key.endswith("mismatch"))
        or (kind == "capital_gap" and key != "capital_invalid" and not key.endswith("mismatch"))
    }


def capital_predicates() -> dict[str, str]:
    """只使用内部固定别名 b/s/m；金额容差与既有市值质检保持一致。"""
    invalid = ["s.float_share>s.total_share", f"m.total_mv<m.float_mv*(1-{MV_REL_TOLERANCE})"]
    mismatch = []
    for field in ("total", "float"):
        invalid.extend(
            [
                f"s.{field}_share<=0",
                f"m.{field}_mv<=0",
                f"NOT isfinite(m.{field}_mv)",
                (
                    f"(s.{field}_share IS NOT NULL AND (s.{field}_effective_date IS NULL "
                    f"OR s.{field}_available_date IS NULL OR s.{field}_source IS NULL "
                    f"OR s.{field}_effective_date>b.trade_date OR s.{field}_available_date>b.trade_date))"
                ),
            ]
        )
        mismatch.append(
            f"abs(m.{field}_mv-s.{field}_share*b.close)>greatest(abs(m.{field}_mv)*{MV_REL_TOLERANCE},1)"
        )
    return {
        "capital_gap": "s.total_share IS NULL OR s.float_share IS NULL OR m.total_mv IS NULL OR m.float_mv IS NULL",
        "capital_invalid": " OR ".join(invalid),
        "capital_mismatch": " OR ".join(mismatch),
    }


class CapitalQualityService:
    def __init__(self, client):
        self.c = client

    def aggregate(self, codes=None) -> pd.DataFrame:
        """数据库内聚合；只返回每股每类问题，不把千万日线加载到 Python。"""
        scope = "WHERE b.code IN (SELECT unnest(?::VARCHAR[]))" if codes is not None else ""
        flags = ",".join(
            f"coalesce(({sql}),false) AS {kind}" for kind, sql in capital_predicates().items()
        )
        return self.c.query_df(
            "WITH facts AS (SELECT b.code,b.trade_date," + flags + ","
            "s.total_share IS NULL missing_total_share,s.float_share IS NULL missing_float_share,"
            "m.total_mv IS NULL missing_total_mv,m.float_mv IS NULL missing_float_mv "
            "FROM daily_bar b LEFT JOIN stock_share_capital_daily s USING(code,trade_date) "
            "LEFT JOIN daily_metrics m USING(code,trade_date) " + scope + ") "
            "SELECT code,issue_type,count(*) issue_days,min(trade_date) date_start,max(trade_date) date_end,"
            "count(*) FILTER(WHERE missing_total_share) missing_total_share,"
            "count(*) FILTER(WHERE missing_float_share) missing_float_share,"
            "count(*) FILTER(WHERE missing_total_mv) missing_total_mv,"
            "count(*) FILTER(WHERE missing_float_mv) missing_float_mv "
            "FROM facts CROSS JOIN LATERAL (VALUES "
            "('capital_gap',capital_gap),('capital_invalid',capital_invalid),"
            "('capital_mismatch',capital_mismatch)) kinds(issue_type,hit) "
            "WHERE hit GROUP BY code,issue_type ORDER BY code,issue_type",
            [codes] if codes is not None else [],
        )

    def issues(self, codes=None) -> list[dict]:
        frame = self.aggregate(codes)
        if frame.empty:
            return []
        log_sources = [
            f"{prefix}:{code}"
            for code in frame.code.unique()
            for prefix in ("capital_collect", "capital_review")
        ]
        logs = self.c.query_df(
            "SELECT source,detail,date_start,date_end,updated_at FROM data_update_log "
            "WHERE source IN (SELECT unnest(?::VARCHAR[])) "
            "QUALIFY row_number() OVER(PARTITION BY split_part(source,':',2) ORDER BY id DESC)=1",
            [log_sources],
        )
        # 每个聚合问题只取首个异常日；大规模缺口不会把所有日线带到内存或响应。
        with self.c.temp_view(
            frame[["code", "issue_type", "date_start"]], prefix="capital_findings"
        ) as view:
            samples = self.c.query_df(
                f"SELECT f.issue_type,b.code,b.trade_date,b.close,s.* EXCLUDE(code,trade_date),"
                f"m.total_mv,m.float_mv FROM {view} f JOIN daily_bar b "
                "ON b.code=f.code AND b.trade_date=f.date_start "
                "LEFT JOIN stock_share_capital_daily s ON s.code=b.code AND s.trade_date=b.trade_date "
                "LEFT JOIN daily_metrics m ON m.code=b.code AND m.trade_date=b.trade_date"
            )
        sample_map = {
            (row["code"], row["issue_type"]): row
            for row in json.loads(samples.to_json(orient="records", date_format="iso"))
        }
        evidence = {}
        for row in logs.itertuples():
            try:
                detail = json.loads(row.detail or "{}")
            except (TypeError, ValueError):
                detail = {}
            evidence[row.source.partition(":")[2]] = {
                "diagnostics": detail,
                "date_start": str(row.date_start),
                "date_end": str(row.date_end),
                "checked_at": str(row.updated_at),
            }
        issues = []
        for row in frame.to_dict("records"):
            kind, code = row["issue_type"], row["code"]
            counts = {key: int(value) for key, value in row.items() if key.startswith("missing_")}
            message = f"全历史{CAPITAL_LABELS[kind]} {int(row['issue_days'])} 个交易日（{str(row['date_start'])[:10]}~{str(row['date_end'])[:10]}）"
            proof = evidence.get(code)
            if proof:
                # 一个股票的缺失、非法和不一致分开解释，不能把另一类问题的原因混入当前行。
                all_reasons = proof["diagnostics"].get("remaining", {})
                reasons = reasons_for_issue(kind, all_reasons)
                proof = {**proof, "diagnostics": {**proof["diagnostics"], "remaining": reasons}}
                labels = list(
                    dict.fromkeys(
                        label
                        for reason in reasons
                        for suffix, label in REASON_LABELS.items()
                        if reason.endswith(suffix)
                    )
                )
                if labels:
                    message += "；最近采集核验：" + "、".join(labels)
                if proof["diagnostics"].get("errors"):
                    message += "；存在来源请求失败，需重试"
            else:
                message += "；尚无采集原因诊断，修复时按多来源核验"
            detail = {
                "message": message,
                "scope": "all_stored_history_including_delisted",
                "issue_days": int(row["issue_days"]),
                "date_start": str(row["date_start"])[:10],
                "date_end": str(row["date_end"])[:10],
                "missing_fields": counts,
                "last_collection": proof,
                "sample": sample_map.get((code, kind)),
            }
            # 聚合问题用固定空日期作为身份，缺口起止改变时不生成新的问题 ID。
            issues.append(
                {
                    "code": code,
                    "trade_date": None,
                    "issue_type": kind,
                    "detail": json.dumps(detail, ensure_ascii=False),
                }
            )
        return issues

    def sync(self, codes=None) -> dict:
        """复用质量台账的幂等合并；定向补采只收敛指定股票。"""
        from backend.services.data_report import DataIntegrityReport

        rows = self.issues(codes)
        with self.c.transaction():
            DataIntegrityReport(self.c)._upsert_scan_issues(rows, CAPITAL_ISSUE_TYPES, codes=codes)
        scope = " AND code IN (SELECT unnest(?::VARCHAR[]))" if codes is not None else ""
        active = self.c.query_df(
            "SELECT issue_type,count(*) AS n FROM data_quality_issue "
            "WHERE status IN ('open','fixing') "
            "AND issue_type IN (SELECT unnest(?::VARCHAR[]))" + scope + " GROUP BY issue_type",
            [list(CAPITAL_ISSUE_TYPES)] + ([codes] if codes is not None else []),
        )
        counts = dict(zip(active.issue_type, active.n))
        return {kind: int(counts.get(kind, 0)) for kind in CAPITAL_ISSUE_TYPES}

    def clean(self, issue_type, code) -> bool:
        frame = self.aggregate([code])
        return not frame.issue_type.eq(issue_type).any()
