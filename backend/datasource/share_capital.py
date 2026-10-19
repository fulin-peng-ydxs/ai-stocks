"""东财股本变动的完整分页与逐日展开（单位股，不向前填充）。"""

from __future__ import annotations

import pandas as pd
import requests


def fetch_equity_events(code: str, *, timeout: float = 15) -> pd.DataFrame:
    """AKShare 同源接口；显式分页，不能使用其默认仅 20 条的包装。"""
    rows = []
    page = 1
    while True:
        response = requests.get(
            "https://datacenter.eastmoney.com/securities/api/data/v1/get",
            params={
                "reportName": "RPT_F10_EH_EQUITY",
                "columns": "ALL",
                "filter": f'(SECUCODE="{code}")',
                "pageSize": 500,
                "pageNumber": page,
                "sortTypes": "1",
                "sortColumns": "END_DATE",
                "source": "HSF10",
                "client": "PC",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("result")
        if result is None:
            if payload.get("message") in ("返回数据为空", "返回数据为空!"):
                return pd.DataFrame()
            raise ValueError(f"{code} 股本接口未返回有效结果: {payload.get('message')}")
        rows.extend(result.get("data") or [])
        if page >= int(result.get("pages") or 1):
            if result.get("count") is not None and len(rows) != int(result["count"]):
                raise ValueError(f"{code} 源端分页总数与返回行数不一致")
            break
        if not result.get("data") or page >= 100:
            raise ValueError(f"{code} 股本分页不完整")
        page += 1
    return pd.DataFrame(rows)


def expand_equity_events(code: str, events: pd.DataFrame, dates) -> pd.DataFrame:
    """按接口变动日期向后沿用到下一次变动；公告日期仅作溯源，不过滤历史股本。"""
    if events.empty:
        return pd.DataFrame()
    ev = events.copy()
    ev["effective"] = pd.to_datetime(ev.END_DATE, errors="coerce")
    ev["available"] = pd.to_datetime(ev.NOTICE_DATE, errors="coerce")
    # 同变动日采用接口最新修订；禁止用后来的变动日向前填充。
    ev = ev.dropna(subset=["effective"]).sort_values(["effective", "available"])
    ev = ev.drop_duplicates("effective", keep="last")
    days = pd.DataFrame({"trade_date": pd.to_datetime(list(dates))}).sort_values("trade_date")
    df = pd.DataFrame({"code": code, "trade_date": days.trade_date.dt.date})
    # 直接取最近一条源记录；相同股数的新记录也是确认，不能压缩掉后让旧备用源覆盖。
    out = pd.merge_asof(days, ev, left_on="trade_date", right_on="effective", direction="backward")
    valid = out.effective.notna() & (out.effective <= out.trade_date)
    for field, raw in [("total", "TOTAL_SHARES"), ("float", "LISTED_A_SHARES")]:
        df[f"{field}_share"] = pd.to_numeric(out[raw], errors="coerce").where(valid).to_numpy()
        df[f"{field}_effective_date"] = out.effective.dt.date.to_numpy()
        df[f"{field}_available_date"] = out.available.dt.date.to_numpy()
    df["total_mv_eligible"] = (
        pd.to_numeric(out.TOTAL_A_SHARES, errors="coerce")
        == pd.to_numeric(out.TOTAL_SHARES, errors="coerce")
    ).to_numpy() & valid.to_numpy()

    return df


def fetch_daily_valuation(code: str, *, timeout: float = 15) -> pd.DataFrame:
    """同 stock_value_em 接口，区分源端明确空数据与传输失败，并读取全部分页。"""
    rows = []
    page = 1
    while True:
        response = requests.get(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            params={
                "reportName": "RPT_VALUEANALYSIS_DET",
                "columns": "ALL",
                "filter": f'(SECURITY_CODE="{code.split(".")[0]}")',
                "pageSize": 5000,
                "pageNumber": page,
                "sortColumns": "TRADE_DATE",
                "sortTypes": "-1",
                "source": "WEB",
                "client": "WEB",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("result")
        if result is None:
            if payload.get("code") == 9201:
                return pd.DataFrame()
            raise ValueError(f"{code} 估值接口异常: {payload.get('message')}")
        rows.extend(result.get("data") or [])
        if page >= int(result.get("pages") or 1):
            if result.get("count") is not None and len(rows) != int(result["count"]):
                raise ValueError(f"{code} 源端分页总数与返回行数不一致")
            break
        if not result.get("data") or page >= 100:
            raise ValueError(f"{code} 估值分页不完整")
        page += 1
    return pd.DataFrame(rows).rename(
        columns={
            "TRADE_DATE": "数据日期",
            "TOTAL_MARKET_CAP": "总市值",
            "NOTLIMITED_MARKETCAP_A": "流通市值",
            "TOTAL_SHARES": "总股本",
            "FREE_SHARES_A": "流通股本",
        }
    )


def fetch_sina_float_shares(code: str, dates, *, timeout: float = 15) -> pd.DataFrame:
    """读取新浪日线同源的流通股本变动序列；仅向后展开，不重采价格或复权因子。"""
    import json

    symbol = code[-2:].lower() + code.split(".")[0]
    response = requests.get(
        f"https://stock.finance.sina.com.cn/stock/api/jsonp.php/var%20KKE_ShareAmount_{symbol}=/"
        f"StockService.getAmountBySymbol?_=20&symbol={symbol}",
        timeout=timeout,
    )
    response.raise_for_status()
    text = response.text
    if text.rstrip().endswith("=(null);"):
        return pd.DataFrame()
    lo, hi = text.find("["), text.rfind("]")
    if lo < 0 or hi < lo:
        raise ValueError(f"{code} 新浪股本响应格式异常")
    events = pd.DataFrame(json.loads(text[lo : hi + 1]))
    if events.empty:
        return pd.DataFrame()
    events["effective"] = pd.to_datetime(events["date"], errors="coerce")
    events = (
        events.dropna(subset=["effective"])
        .sort_values("effective")
        .drop_duplicates("effective", keep="last")
    )
    events["float_share"] = pd.to_numeric(events["amount"], errors="coerce") * 10000
    days = pd.DataFrame({"trade_date": pd.to_datetime(list(dates))}).sort_values("trade_date")
    out = pd.merge_asof(
        days, events, left_on="trade_date", right_on="effective", direction="backward"
    )
    return pd.DataFrame(
        {
            "code": code,
            "trade_date": out.trade_date.dt.date,
            "float_share": out.float_share,
            "float_effective_date": out.effective.dt.date,
            "float_available_date": out.trade_date.dt.date,
        }
    )


def fetch_sina_equity_events(code: str, *, timeout: float = 15) -> pd.DataFrame:
    """新浪历史股本结构；保留公告日，万股转股，不能把占位公告日期当成历史证据。"""
    from io import StringIO

    response = requests.get(
        "https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_StockStructure/stockid/"
        f"{code.split('.')[0]}.phtml", timeout=timeout,
    )
    response.raise_for_status()
    response.encoding = "gb18030"
    if "暂无数据" in response.text or "没有相关数据" in response.text:
        return pd.DataFrame()
    tables = pd.read_html(StringIO(response.text))
    records = []
    for table in tables:
        labels = table.iloc[:, 0].astype(str).str.replace("·", "", regex=False)
        if not labels.eq("变动日期").any():
            continue
        def row(label, table=table, labels=labels):
            match = table.loc[labels.eq(label)]
            if match.empty:
                return pd.Series(index=table.columns[1:], dtype=object)
            return match.iloc[0, 1:]

        def shares(label):
            raw = row(label).astype(str).str.replace("万股", "", regex=False).str.replace(",", "", regex=False)
            return pd.to_numeric(raw.str.strip(), errors="coerce") * 10000

        total = shares("总股本(历史记录)")
        floating = shares("流通A股(历史记录)")
        limited = shares("限售A股(历史记录)")
        # 只用 A 股组成的正向相等证据；页面横杠不代表所有其它股份都为零。
        total_a = floating + limited
        total_a = total_a.where(limited.notna(), floating.where(floating.eq(total)))
        # 页面万股最多保留三位小数，三项各有最多 5 股舍入误差；只校准显示精度。
        total_a = total_a.where((total_a - total).abs() > 15, total).where(total_a.notna())
        effective = pd.to_datetime(row("变动日期").astype(str), format="%Y%m%d", errors="coerce")
        available = pd.to_datetime(row("公告日期").astype(str), format="%Y%m%d", errors="coerce")
        available = available.where(available >= pd.Timestamp("1990-01-01"))
        for col in total.index:
            if pd.notna(effective[col]):
                records.append({"END_DATE": effective[col], "NOTICE_DATE": available[col],
                                "TOTAL_SHARES": total[col], "LISTED_A_SHARES": floating[col],
                                "TOTAL_A_SHARES": total_a[col], "CHANGE_REASON": str(row("变动原因").get(col, ""))})
    if not records:
        raise ValueError(f"{code} 新浪历史股本结构格式异常或无可解析记录")
    return pd.DataFrame(records)
