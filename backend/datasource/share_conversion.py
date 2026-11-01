"""上交所逐日转股补充源；基准股本和债券映射来自接口，不内置股票名单。"""

from __future__ import annotations

import pandas as pd
import requests

from backend.datasource.base import check_thread_cancel

SSE_PAGE = "https://bond.sse.com.cn/data/statistics/Statistics/debtstock/index_his.shtml"


def fetch_convertible_bonds(code: str, *, timeout=15) -> list[dict]:
    """包含已退市转债的正股映射；明确空返回与请求失败分开。"""
    rows = []
    for page in range(1, 101):
        check_thread_cancel()
        r = requests.get(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            params={
                "reportName": "RPT_BOND_CB_LIST",
                "columns": "SECURITY_CODE,CONVERT_STOCK_CODE,TRANSFER_START_DATE,TRANSFER_END_DATE",
                "filter": f'(CONVERT_STOCK_CODE="{code.split(".")[0]}")',
                "pageSize": 100,
                "pageNumber": page,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        payload = r.json()
        result = payload.get("result")
        if result is None:
            if payload.get("code") == 9201:
                return []
            raise ValueError(f"{code} 转债映射接口异常")
        rows.extend(result.get("data") or [])
        if page >= int(result["pages"]):
            if len(rows) != int(result["count"]):
                raise ValueError("转债映射分页不完整")
            return rows
    raise ValueError("转债映射超过分页上限")


def fetch_sse_conversions(bond: str, year: int, *, timeout=15) -> pd.DataFrame:
    """日统计只列有转股的日期；全年完整分页后才能向后沿用累计量。"""
    rows = []
    for page in range(1, 101):
        check_thread_cancel()
        r = requests.get(
            "https://query.sse.com.cn/commonQuery.do",
            params={
                "sqlId": "COMMON_SSEBOND_SCSJ_SCTJ_ZXTJ_KZZZGTJ_CX_L",
                "YEAR": year,
                "BOND_CODE": bond,
                "isPagination": "true",
                "pageHelp.pageSize": 500,
                "pageHelp.pageNo": page,
                "pageHelp.beginPage": page,
                "pageHelp.endPage": page,
            },
            headers={"Referer": SSE_PAGE},
            timeout=timeout,
        )
        r.raise_for_status()
        payload = r.json()
        result = payload.get("pageHelp")
        if not isinstance(result, dict) or result.get("total") is None:
            raise ValueError(f"{bond}/{year} 上交所转股响应异常")
        rows.extend(result.get("data") or [])
        if page >= max(int(result.get("pageCount") or 0), 1):
            if len(rows) != int(result["total"]):
                raise ValueError(f"{bond}/{year} 转股分页不完整")
            out = pd.DataFrame(rows)
            if out.empty:
                return out
            if not out.CVTBOND_CODE.eq(bond).all():
                raise ValueError("转股响应包含其他债券")
            out["effective"] = pd.to_datetime(out.TRADING_DATE, errors="coerce")
            out["cumulative"] = pd.to_numeric(out.TOTAL_ZG_NUM, errors="coerce") * 10000
            if (
                out.effective.isna().any()
                or out.cumulative.isna().any()
                or not out.effective.dt.year.eq(year).all()
                or out.cumulative.lt(0).any()
            ):
                raise ValueError("转股响应存在无效日期或累计股数")
            return out.sort_values("effective")
    raise ValueError("转股统计超过分页上限")


def reconstruct_conversion_shares(code, dates, events, bonds, fetch, *, evidence=None):
    """在转股前历史基准到下一次其他股本变动之间重建总股本。

    拒绝重叠转债，避免漏计；仅使用转股开始前的历史记录，不推导流通股本。
    TOTAL_ZG_NUM 精度 100 股，来源标签和诊断均保留精度。
    """
    report = evidence if evidence is not None else {}
    report.update(bonds=len(bonds), precision_shares=100, skipped={}, anchors=[])
    days = pd.DatetimeIndex(pd.to_datetime(list(dates))).sort_values().unique()
    if not len(days) or events.empty:
        return pd.DataFrame()
    ev = events.copy()
    ev["effective"] = pd.to_datetime(ev.END_DATE, errors="coerce")
    ev["available"] = pd.to_datetime(ev.NOTICE_DATE, errors="coerce")
    ev["shares"] = pd.to_numeric(ev.TOTAL_SHARES, errors="coerce")
    ev = ev.dropna(subset=["effective", "shares"]).sort_values("effective")
    result = []
    for bond in bonds:
        check_thread_cancel()
        start = pd.to_datetime(bond.get("TRANSFER_START_DATE"), errors="coerce")
        end = pd.to_datetime(bond.get("TRANSFER_END_DATE"), errors="coerce")
        number = str(bond["SECURITY_CODE"])
        if pd.isna(start) or pd.isna(end):
            report["skipped"][number] = "missing_conversion_period"
            continue
        target = days[(days >= start) & (days <= end)]
        if not len(target):
            continue
        overlaps, unknown_periods = [], []
        for other_bond in bonds:
            if other_bond is bond:
                continue
            other_start = pd.to_datetime(other_bond.get("TRANSFER_START_DATE"), errors="coerce")
            other_end = pd.to_datetime(other_bond.get("TRANSFER_END_DATE"), errors="coerce")
            # 日期缺失不能参与 Timestamp 比较，也不能据此断言两只转债不重叠。
            # 已知一端足以排除目标区间时允许继续，其余情况保留未知并拒绝重建。
            if pd.notna(other_start) and other_start > target.max():
                continue
            if pd.notna(other_end) and other_end < start:
                continue
            if pd.isna(other_start) or pd.isna(other_end):
                unknown_periods.append(str(other_bond["SECURITY_CODE"]))
            else:
                overlaps.append(other_bond)
        if unknown_periods:
            report["skipped"][number] = "unknown_other_conversion_period"
            report.setdefault("unknown_period_bonds", {})[number] = unknown_periods
            continue
        if overlaps:
            report["skipped"][number] = "overlapping_convertible_bonds"
            continue
        prior = ev[ev.effective.lt(start)]
        if prior.empty:
            report["skipped"][number] = "no_preconversion_anchor"
            continue
        anchor = prior.iloc[-1]
        # 非转股的真实数量变动使旧基准失效；同值季报不产生新边界。
        changed = ev.shares.ne(ev.shares.shift())
        other = ev[
            ev.effective.ge(start)
            & changed
            & ~ev.CHANGE_REASON.fillna("").isin(["债转股上市", "可转债转股", "债转股", "转债转股"])
        ]
        if not other.empty:
            target = target[target < other.effective.min()]
        if not len(target):
            report["skipped"][number] = "other_capital_change_invalidates_anchor"
            continue
        report["anchors"].append(
            {
                "bond": number,
                "effective_date": str(anchor.effective.date()),
                "available_date": str(anchor.available.date()),
                "total_share": int(anchor.shares),
                "conversion_start": str(start.date()),
                "conversion_end": str(end.date()),
                "source_ref": SSE_PAGE,
            }
        )
        pieces = [fetch(number, year) for year in range(start.year, target.max().year + 1)]
        nonempty = [piece for piece in pieces if not piece.empty]
        if not nonempty:
            report["skipped"][number] = "exchange_has_no_daily_conversion_rows"
            continue
        series = pd.concat(nonempty).sort_values("effective")
        if series.effective.duplicated().any() or series.cumulative.diff().lt(0).any():
            raise ValueError(f"{number} 累计转股重复或倒退，拒绝重建")
        series = series[series.effective.ge(start)]
        out = pd.merge_asof(
            pd.DataFrame({"trade_date": target}),
            series,
            left_on="trade_date",
            right_on="effective",
            direction="backward",
        )
        out = out.dropna(subset=["cumulative"])
        for row in out.itertuples():
            result.append(
                {
                    "code": code,
                    "trade_date": row.trade_date.date(),
                    "total_share": round(anchor.shares + row.cumulative),
                    "total_effective_date": row.effective.date(),
                    "total_available_date": (max(row.effective, anchor.available) if pd.notna(anchor.available) else row.effective).date(),
                    "total_mv_eligible": False,
                    "evidence_source": f"sse_conversion_100share:{number}",
                    "anchor_date": str(anchor.effective.date()),
                    "anchor_total_share": int(anchor.shares),
                }
            )
    report["expanded_rows"] = len(result)
    return pd.DataFrame(result)
