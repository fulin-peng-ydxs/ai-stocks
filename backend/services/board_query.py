"""板块行情查询服务（板块概念需求 R7-R10/R13/R14，plan §6.8 T8）。

只读聚合：单次全查内存合并（板块数 <600，符合 plan §4 双库边界——只读 DuckDB，
成分股现价/涨跌幅/换手取个股行情表同库关联，不跨库 JOIN）。

口径（需求 §6.2 / plan §4 双口径边界）：
- **涨幅 pct_today/pct_5d/pct_10d/pct_20d 从 `board_bar` 实时计算**（最近交易日收盘 vs
  N 个交易日前收盘），不从 `board_fund_flow` 周期表读（资金流周期 net_ratio 是资金面数据，
  不参与价格排序）。
- **领涨股默认取 `board_fund_flow.leader_stock/leader_pct` 且与「即时净流入」同一
  `(snapshot_date, period='即时')` 行**；无资金流数据的板块该列空值「—」。
- **成分数** = `board_member` 该板块当前有效成员数（只进不出模型每板块一行累积）。
- **上涨/下跌家数** = 该交易日有效成分股个股 `close` vs `pre_close`；平盘/停牌/缺行情不计入。

所有日期/空值口径：涨幅与资金流数据日期分别显式返回；空值统一 None（前端「—」）。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from backend.storage.duckdb_client import DuckDBClient, get_client

# 周期 → 交易日回溯天数（含当日）：今日=当天、5日=5个交易日、10日=10、20日=20。
# 板块指数为交易日序列，N 日涨幅 = 最近收盘 vs 往前 N 个交易日收盘（如 5 日 = 最近 vs 第 5 个交易日）。
_PCT_WINDOW = {"pct_today": 1, "pct_5d": 5, "pct_10d": 10, "pct_20d": 20}

# 列表可排序字段码（需求 §6.2 稳定字段码；前端中文标签仅 UI 映射）
SORT_FIELDS = ("pct_today", "pct_5d", "pct_10d", "pct_20d", "net_inflow", "up_count")


class BoardQueryService:
    """板块行情只读查询（板块概念 T8）。"""

    def __init__(self, client: DuckDBClient | None = None):
        self.c = client or get_client()

    # ── 列表 ────────────────────────────────────────────────

    def list_sectors(
        self,
        trade_date: date | None = None,
        board_type: str | None = None,
        sort_by: str = "pct_today",
        order: str = "desc",
        keyword: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """板块列表：涨幅/成分数/即时净流入/领涨股 + 分页排序。

        返回 {"list": [...], "total": n, "trade_date": 涨幅截面日期,
              "fund_flow_date": 资金流快照日, "page": p, "size": s}。
        空值字段统一 None（前端「—」）；列表只展示 has_members 或 has_bar 的板块。
        """
        # 涨幅截面：指定交易日或最新；资金流快照日单独取
        bar_date = trade_date or self._latest_bar_date()
        fund_date = self._latest_fund_date()
        rows = self._sector_rows(bar_date, fund_date)

        # 过滤
        if board_type:
            rows = [r for r in rows if r["board_type"] == board_type]
        if keyword:
            kw = keyword.lower()
            rows = [r for r in rows if kw in str(r["name"]).lower() or kw in str(r["board_code"]).lower()]

        # 排序（稳定字段码；未知排序字段在接口层 400，此处默认 pct_today）
        if sort_by in SORT_FIELDS:
            rows.sort(key=lambda r: r.get(sort_by) if r.get(sort_by) is not None else float("-inf"),
                      reverse=order == "desc")

        total = len(rows)
        start = (page - 1) * size
        page_rows = rows[start:start + size]
        return {
            "list": page_rows, "total": total,
            "trade_date": str(bar_date) if bar_date else None,
            "fund_flow_date": str(fund_date) if fund_date else None,
            "page": page, "size": size,
        }

    def _sector_rows(self, bar_date: date | None, fund_date: date | None) -> list[dict]:
        """板块列表全量行（<600 单次全查内存合并）。"""
        # 1. board_dict 基础 + 成分数（board_member 每板块累积）
        df = self.c.query_df(
            """
            SELECT d.board_code, d.app_code, d.name, d.board_type,
                   d.has_members, d.has_bar, d.has_fund_flow, d.member_count,
                   (SELECT count(*) FROM board_member m WHERE m.board_code = d.board_code) AS member_n
            FROM board_dict d
            WHERE d.has_members OR d.has_bar
            """)
        # 2. board_bar 涨幅（最近 vs N 交易日前收盘，截面 bar_date）
        bar_ts = self._bar_close_series(bar_date)
        # 3. board_fund_flow 即时净流入 + 领涨股（最新 snapshot_date period='即时'）
        fund_df = self._immediate_fund_flow(fund_date)

        rows = []
        for _, r in df.iterrows():
            code = str(r["board_code"])
            bar = bar_ts.get(code)
            row: dict = {
                "board_code": code,
                "app_code": str(r["app_code"]) if r["app_code"] is not None and str(r["app_code"]) != "nan" else None,
                "name": str(r["name"]),
                "board_type": str(r["board_type"]),
                "member_count": int(r["member_n"]) if r["member_n"] is not None else None,
                "has_members": bool(r["has_members"]),
                "has_bar": bool(r["has_bar"]),
                "has_fund_flow": bool(r["has_fund_flow"]),
            }
            # 涨幅：历史不足该周期 → None（前端「—」，不缩短周期代算）
            if bar is not None:
                for key, lookback in _PCT_WINDOW.items():
                    row[key] = _pct_change(bar, lookback)
            else:
                for key in _PCT_WINDOW:
                    row[key] = None
            # 即时资金流 + 领涨股（同一 snapshot 行）
            ff = fund_df.get(code)
            if ff is not None:
                row["net_inflow"] = ff["net_inflow"]
                row["leader_stock"] = ff["leader_stock"]
                row["leader_pct"] = ff["leader_pct"]
            else:
                row["net_inflow"] = None
                row["leader_stock"] = None
                row["leader_pct"] = None
            # 涨跌家数（该交易日有效成分股 close vs pre_close）
            row["up_count"], row["down_count"] = self._board_advance_decline(code, bar_date)
            rows.append(row)
        return rows

    def _bar_close_series(self, bar_date: date | None) -> dict[str, pd.Series]:
        """每板块指数收盘序列（升序），key=board_code。bar_date None → 空。"""
        if bar_date is None:
            return {}
        df = self.c.query_df(
            "SELECT board_code, trade_date, close FROM board_bar "
            "WHERE trade_date <= ? ORDER BY board_code, trade_date", [bar_date])
        out: dict[str, pd.Series] = {}
        for code, g in df.groupby("board_code"):
            out[str(code)] = g["close"].reset_index(drop=True)
        return out

    def _immediate_fund_flow(self, fund_date: date | None) -> dict[str, dict]:
        """最新 snapshot_date 的 period='即时' 行（净流入 + 领涨股），key=board_code。"""
        if fund_date is None:
            return {}
        df = self.c.query_df(
            "SELECT board_code, net_inflow, leader_stock, leader_pct "
            "FROM board_fund_flow WHERE snapshot_date = ? AND period = '即时'", [fund_date])
        out: dict[str, dict] = {}
        for _, r in df.iterrows():
            out[str(r["board_code"])] = {
                "net_inflow": r["net_inflow"],
                "leader_stock": None if r["leader_stock"] is None or str(r["leader_stock"]) == "nan" else str(r["leader_stock"]),
                "leader_pct": r["leader_pct"],
            }
        return out

    def _board_advance_decline(self, board_code: str, bar_date: date | None) -> tuple[int | None, int | None]:
        """板块涨跌家数：该交易日有效成分股 close vs pre_close。bar_date None → (None, None)。"""
        if bar_date is None:
            return None, None
        df = self.c.query_df(
            """
            SELECT count(*) FILTER (WHERE b.close > b.pre_close) AS up,
                   count(*) FILTER (WHERE b.close < b.pre_close) AS down
            FROM board_member m
            JOIN daily_bar b ON b.code = m.code AND b.trade_date = ?
            WHERE m.board_code = ?
            """, [bar_date, board_code])
        if df.empty:
            return None, None
        up = int(df.iloc[0]["up"]) if df.iloc[0]["up"] is not None else 0
        down = int(df.iloc[0]["down"]) if df.iloc[0]["down"] is not None else 0
        return up, down

    def _latest_bar_date(self) -> date | None:
        """board_bar 全局最新交易日。"""
        v = self.c.query_df("SELECT max(trade_date) AS t FROM board_bar").iloc[0]["t"]
        return None if v is None or str(v) == "NaT" else pd.Timestamp(v).date()

    def _latest_fund_date(self) -> date | None:
        """board_fund_flow 最新 snapshot_date。"""
        v = self.c.query_df("SELECT max(snapshot_date) AS t FROM board_fund_flow").iloc[0]["t"]
        return None if v is None or str(v) == "NaT" else pd.Timestamp(v).date()

    # ── 详情 ────────────────────────────────────────────────

    def get_sector(self, code: str, trade_date: date | None = None) -> dict | None:
        """单板块详情摘要（含能力字段）。不存在返回 None。"""
        df = self.c.query_df(
            "SELECT board_code, app_code, name, board_type, has_members, has_bar, has_fund_flow, "
            "member_count FROM board_dict WHERE board_code = ?", [code])
        if df.empty:
            return None
        r = df.iloc[0]
        bar_date = trade_date or self._latest_bar_date()
        fund_date = self._latest_fund_date()
        bar = self._bar_close_series(bar_date).get(code)
        ff = self._immediate_fund_flow(fund_date).get(code)
        up, down = self._board_advance_decline(code, bar_date)
        out = {
            "board_code": str(r["board_code"]),
            "app_code": str(r["app_code"]) if r["app_code"] is not None and str(r["app_code"]) != "nan" else None,
            "name": str(r["name"]),
            "board_type": str(r["board_type"]),
            "member_count": int(self.c.query_df(
                "SELECT count(*) AS n FROM board_member WHERE board_code=?", [code]).iloc[0]["n"]),
            "has_members": bool(r["has_members"]),
            "has_bar": bool(r["has_bar"]),
            "has_fund_flow": bool(r["has_fund_flow"]),
            "trade_date": str(bar_date) if bar_date else None,
            "fund_flow_date": str(fund_date) if fund_date else None,
            "up_count": up, "down_count": down,
        }
        if bar is not None:
            for key, lookback in _PCT_WINDOW.items():
                out[key] = _pct_change(bar, lookback)
        else:
            for key in _PCT_WINDOW:
                out[key] = None
        if ff is not None:
            out["net_inflow"] = ff["net_inflow"]
            out["leader_stock"] = ff["leader_stock"]
            out["leader_pct"] = ff["leader_pct"]
        else:
            out["net_inflow"] = None
            out["leader_stock"] = None
            out["leader_pct"] = None
        return out

    # ── 指数区间序列 ─────────────────────────────────────────

    def get_bars(self, code: str, start: date, end: date) -> list[dict]:
        """板块指数区间序列（原值）。"""
        df = self.c.query_df(
            "SELECT trade_date, open, high, low, close, volume, amount FROM board_bar "
            "WHERE board_code = ? AND trade_date >= ? AND trade_date <= ? "
            "ORDER BY trade_date", [code, start, end])
        return [
            {"trade_date": str(pd.Timestamp(r["trade_date"]).date()),
             "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
             "volume": r["volume"], "amount": r["amount"]}
            for _, r in df.iterrows()
        ]

    # ── 成分股分页 ───────────────────────────────────────────

    def get_members(self, code: str, trade_date: date | None = None,
                    page: int = 1, size: int = 20) -> dict:
        """成分股统一分页：成分股 + 该交易日现价/涨跌幅/换手（个股行情表同库关联）。

        返回 {"list": [{code, name, close, pct_chg, turnover_rate}], "total": n}。
        """
        bar_date = trade_date or self._latest_bar_date()
        total = int(self.c.query_df(
            "SELECT count(*) AS n FROM board_member WHERE board_code=?", [code]).iloc[0]["n"])
        if total == 0:
            return {"list": [], "total": 0, "trade_date": str(bar_date) if bar_date else None}
        cond = "b.trade_date = ?" if bar_date is not None else "1=0"
        df = self.c.query_df(
            f"""
            SELECT m.code, sb.name, b.close, b.pre_close, b.turnover_rate
            FROM board_member m
            LEFT JOIN stock_basic sb ON sb.code = m.code
            LEFT JOIN daily_bar b ON b.code = m.code AND {cond}
            WHERE m.board_code = ?
            ORDER BY m.code
            LIMIT ? OFFSET ?
            """, ([bar_date] if bar_date is not None else []) + [code, size, (page - 1) * size])
        rows = []
        for _, r in df.iterrows():
            rows.append({
                "code": str(r["code"]),
                "name": str(r["name"]) if r["name"] is not None and str(r["name"]) != "nan" else None,
                "close": r["close"],
                "pct_chg": _pct_chg(r["close"], r["pre_close"]),
                "turnover_rate": r["turnover_rate"],
            })
        return {"list": rows, "total": total, "trade_date": str(bar_date) if bar_date else None}


def _pct_change(series: pd.Series, lookback: int) -> float | None:
    """序列最近收盘 vs 往前 lookback 个交易日收盘的涨幅（%）。历史不足返回 None。"""
    if len(series) < lookback + 1:
        return None
    last = float(series.iloc[-1])
    ref = float(series.iloc[-(lookback + 1)])
    if ref == 0:
        return None
    return round((last / ref - 1) * 100, 2)


def _pct_chg(close, pre_close):
    """个股涨跌幅（%）；缺行情返回 None。"""
    if close is None or pre_close is None or float(pre_close) == 0:
        return None
    return round((float(close) / float(pre_close) - 1) * 100, 2)
