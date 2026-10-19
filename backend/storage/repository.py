"""市场数据仓库（SDD §5 storage 层）。

职责：对底座表做**幂等写入**（INSERT ... ON CONFLICT DO UPDATE）、
增量起点查询、更新日志留痕。点时安全查询（get_*_asof）在 T-M1-9 追加。

幂等保证（需求 F-STO-02）：所有 upsert 按主键覆盖，重复运行不产生重复行。
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from backend.common.logging import get_logger
from backend.config import get_effective_settings
from backend.storage.duckdb_client import DuckDBClient, get_client

log = get_logger("storage.repository")

# 各表主键（用于 ON CONFLICT）
_PK: dict[str, list[str]] = {
    "stock_basic": ["code"],
    "daily_bar": ["code", "trade_date"],
    "daily_metrics": ["code", "trade_date"],
    "index_bar": ["index_code", "trade_date"],
    "trade_calendar": ["trade_date"],
    "indicator_def": ["key"],
    "screen_result": ["run_date", "profile_id", "code"],
    "score_result": ["trade_date", "model_id", "code"],
    "screen_profile_version": ["id", "version"],
    "score_profile_version": ["id", "version"],
    "trade_profile_version": ["id", "version"],
    "backtest_run": ["id"],
    "backtest_trade": ["run_id", "seq"],
    "backtest_equity": ["run_id", "trade_date"],
    "backtest_metrics": ["run_id"],
    "score_snapshot": ["trade_date", "profile_id", "profile_version", "code"],
}


class MarketRepository:
    def __init__(self, client: DuckDBClient | None = None):
        self.c = client or get_client()

    # ── 通用幂等 upsert ──────────────────────────────────────
    def upsert(self, table: str, df: pd.DataFrame) -> int:
        """把 df 幂等写入 table；df 列必须 ⊆ 表列，且含主键列。返回写入行数。"""
        if df is None or df.empty:
            return 0
        pk = _PK[table]
        cols = list(df.columns)
        non_pk = [c for c in cols if c not in pk]
        col_list = ", ".join(cols)
        with self.c.temp_view(df, prefix=f"up_{table}") as tmp:
            if non_pk:
                set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in non_pk)
                conflict = f"ON CONFLICT ({', '.join(pk)}) DO UPDATE SET {set_clause}"
            else:
                conflict = f"ON CONFLICT ({', '.join(pk)}) DO NOTHING"
            self.c.execute(
                f"INSERT INTO {table} ({col_list}) SELECT {col_list} FROM {tmp} {conflict}"
            )
        return len(df)

    # 语义化封装
    def upsert_stock_basic(self, df: pd.DataFrame) -> int:
        if df is not None and not df.empty and "delist_date" in df:
            df = df.copy()
            df["delist_date_reported"] = df["delist_date"]
            locked = self.c.query_df(
                "SELECT code,delist_date FROM stock_basic WHERE delist_date_manual=true")
            if not locked.empty:
                values = locked.set_index("code")["delist_date"]
                mask = df.code.isin(values.index)
                df.loc[mask, "delist_date"] = df.loc[mask, "code"].map(values)
        return self.upsert("stock_basic", df)

    def upsert_daily_bar(self, df: pd.DataFrame) -> int:
        return self.upsert("daily_bar", df)

    def upsert_daily_metrics(self, df: pd.DataFrame) -> int:
        return self.upsert("daily_metrics", df)

    def upsert_index_bar(self, df: pd.DataFrame) -> int:
        return self.upsert("index_bar", df)

    def upsert_trade_calendar(self, df: pd.DataFrame) -> int:
        return self.upsert("trade_calendar", df)

    # ── 增量起点 / 续跑辅助 ──────────────────────────────────
    def get_max_bar_date(self, code: str) -> date | None:
        """某股已入库的最新交易日（增量更新起点）。"""
        df = self.c.query_df(
            "SELECT max(trade_date) AS d FROM daily_bar WHERE code = ?", [code]
        )
        d = df.iloc[0]["d"]
        return None if pd.isna(d) else pd.Timestamp(d).date()

    def get_loaded_codes(self) -> set[str]:
        """daily_bar 中已有数据的股票代码集合（续跑跳过用）。"""
        df = self.c.query_df("SELECT DISTINCT code FROM daily_bar")
        return set(df["code"].tolist())

    def count_bars(self, code: str | None = None) -> int:
        if code:
            df = self.c.query_df("SELECT count(*) AS n FROM daily_bar WHERE code = ?", [code])
        else:
            df = self.c.query_df("SELECT count(*) AS n FROM daily_bar")
        return int(df.iloc[0]["n"])

    # ══════════════════════════════════════════════════════════
    # 点时安全访问层（T-M1-9，SDD §6.1/6.2：防未来函数/幸存者偏差总闸门）
    # 铁律：给定基准日 end_date/asof，只返回 trade_date <= 该日 的数据。
    # ══════════════════════════════════════════════════════════

    def get_bars(
        self,
        code: str,
        end_date: date,
        lookback: int | None = None,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """点时取个股日线（只含 <= end_date），并按需复权。

        adjust:
          - ""    不复权（原值）
          - "qfq" 前复权 = close × 干净因子 / (end_date 当日干净因子)  ← 点时归一，不引未来
          - "hfq" 后复权 = close × 干净因子
        复权用**去抖后的 adj_factor_clean**（分段恒定，消除源因子的逐日舍入噪声）；
        旧库该列为空时 COALESCE 回落原始 adj_factor，保证未回填前不报错。
        lookback: 仅返回最近 N 个交易日（在复权计算之后裁剪）。
        """
        df = self.c.query_df(
            "SELECT * FROM daily_bar WHERE code = ? AND trade_date <= ? ORDER BY trade_date",
            [code, end_date],
        )
        if df.empty:
            return df
        if adjust in ("qfq", "hfq"):
            factor = df["adj_factor_clean"].fillna(df["adj_factor"])
            base = factor.iloc[-1] if adjust == "qfq" else 1.0
            for col in ("open", "high", "low", "close", "pre_close"):
                df[col] = df[col] * factor / base
        if lookback:
            df = df.tail(lookback)
        return df.reset_index(drop=True)

    def get_suspension_days(self, code: str) -> list[date]:
        """推导某股停牌日：其首末行情区间内的"日历开市日 − 实际有行情日"。

        数据源对停牌日不返回行，故停牌 = 上市存续期内、开市但无行情的日子。
        （连续区间通常即一次真实停牌。）
        """
        span = self.c.query_df(
            "SELECT min(trade_date) AS lo, max(trade_date) AS hi FROM daily_bar WHERE code = ?",
            [code],
        ).iloc[0]
        if pd.isna(span["lo"]):
            return []
        df = self.c.query_df(
            "SELECT cal.trade_date FROM trade_calendar cal "
            "WHERE cal.is_open AND cal.trade_date BETWEEN ? AND ? "
            "  AND cal.trade_date NOT IN (SELECT trade_date FROM daily_bar WHERE code = ?) "
            "ORDER BY cal.trade_date",
            [span["lo"], span["hi"], code],
        )
        return [pd.Timestamp(d).date() for d in df["trade_date"]]

    def is_suspended_on(self, code: str, asof: date) -> bool:
        """某股在 asof 是否停牌：开市日但无行情行（且在存续期内）。"""
        cal = self.c.query_df(
            "SELECT is_open FROM trade_calendar WHERE trade_date = ?", [asof]
        )
        if cal.empty or not bool(cal.iloc[0]["is_open"]):
            return False  # 非交易日不算停牌
        span = self.c.query_df(
            "SELECT min(trade_date) AS lo, max(trade_date) AS hi FROM daily_bar WHERE code = ?",
            [code],
        ).iloc[0]
        if pd.isna(span["lo"]):
            return False
        lo, hi = pd.Timestamp(span["lo"]).date(), pd.Timestamp(span["hi"]).date()
        if asof < lo or asof > hi:
            return False
        bar = self.c.query_df(
            "SELECT 1 FROM daily_bar WHERE code = ? AND trade_date = ?", [code, asof]
        )
        return bar.empty

    def get_universe_asof(
        self, asof: date, filters: dict | None = None
    ) -> list[str]:
        """点时股票池：返回在 asof 当日"可交易、可纳入"的股票代码。

        含"当时存活、后来退市"的票（防幸存者偏差）——以 asof 当日有行情为存活判据，
        并叠加配置过滤：剔除 ST、次新（上市<min_list_days 交易日）、停牌（当日无行情）、
        一字涨停（可买不进）、流通市值区间、板块（默认剔除北交所）。

        filters 可覆盖配置默认值：exclude_st/min_list_days/exclude_one_word_limit/
        float_mv_min/float_mv_max。
        """
        u = get_effective_settings().universe
        f = filters or {}
        exclude_st = f.get("exclude_st", u.exclude_st)
        min_list_days = f.get("min_list_days", u.min_list_days)
        exclude_one_word = f.get("exclude_one_word_limit", u.exclude_one_word_limit)
        mv_min = f.get("float_mv_min", u.float_mv_min)
        mv_max = f.get("float_mv_max", u.float_mv_max)
        boards = f.get("boards", u.boards)

        from backend.services.stock_st_status import StockSTStatusService

        day_codes = self.c.query_df(
            "SELECT code FROM daily_bar WHERE trade_date=? ORDER BY code", [asof]
        )["code"].astype(str).tolist()
        StockSTStatusService(self.c).status_map(asof, day_codes)

        conds = ["b.trade_date = ?"]  # 当日有行情 = 已上市且未停牌（点时存活）
        params: list = [asof]

        # 板块（默认剔除北交所）
        if boards:
            placeholders = ", ".join(["?"] * len(boards))
            conds.append(f"sb.board IN ({placeholders})")
            params.extend(boards)
        if exclude_st:
            conds.append("st.is_st = FALSE")
        if exclude_one_word:
            conds.append("NOT (b.is_one_word AND b.limit_status = 1)")
        # 次新剔除：截至 asof 已有交易日数 >= min_list_days
        conds.append(
            "(SELECT count(*) FROM daily_bar d WHERE d.code = b.code AND d.trade_date <= ?) >= ?"
        )
        params.extend([asof, min_list_days])
        # 流通市值区间
        mv_join = "LEFT JOIN daily_metrics m ON m.code = b.code AND m.trade_date = b.trade_date"
        if mv_min is not None:
            conds.append("m.float_mv >= ?")
            params.append(mv_min)
        if mv_max is not None:
            conds.append("m.float_mv <= ?")
            params.append(mv_max)

        sql = (
            "SELECT b.code FROM daily_bar b "
            "JOIN stock_basic sb ON sb.code = b.code "
            "JOIN stock_st_status_daily st ON st.code=b.code AND st.trade_date=b.trade_date "
            f"{mv_join} "
            f"WHERE {' AND '.join(conds)} "
            "ORDER BY b.code"
        )
        df = self.c.query_df(sql, params)
        return df["code"].tolist()

    # ── 更新日志（留痕 + 断点续跑依据）──────────────────────
    def log_update(
        self,
        table_name: str,
        source: str,
        date_start: date | None,
        date_end: date | None,
        row_count: int,
        status: str,
        detail: str = "",
    ) -> None:
        self.c.execute(
            "INSERT INTO data_update_log "
            "(id, table_name, source, date_start, date_end, row_count, status, detail, updated_at) "
            "VALUES (nextval('seq_update_log'), ?, ?, ?, ?, ?, ?, ?, ?)",
            [table_name, source, date_start, date_end, row_count, status, detail, datetime.now()],
        )
