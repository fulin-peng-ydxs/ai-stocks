"""数据质量模块（需求 §5.3 / SDD §6.4 撮合前提）。

两类能力：
1. 标记计算 add_markers()：给日线补 limit_status/is_one_word/is_st —— 回测可否成交的前提。
   涨跌停价按板块计算（主板±10%、科创创业±20%），A股按 half-up 到分取整。
2. 质检规则：缺失检测、异常涨跌幅、复权跳变 → 写 data_quality_issue（人工复核）。

注意：停牌在本数据口径下表现为"日历有该交易日但该股无行情行"，
属缺失检测范畴（check_missing）；逐行 is_suspended 默认 False。
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd

from backend.common.logging import get_logger
from backend.market_rules import price_limit_pct_for, round_price_to_cent
from backend.storage.duckdb_client import DuckDBClient, get_client

log = get_logger("dataquality.checker")

_EPS = 1e-4  # 涨跌停价比较容差（已 2 位小数取整）


def limit_pct_for(board_limit_pct: float, is_st: bool) -> float:
    """有效涨跌幅限制（未知日期按 2026-07-06 前历史 ST 口径）。"""
    return price_limit_pct_for(board_limit_pct, is_st)


def add_markers(
    df: pd.DataFrame, board_limit_pct: float, is_st: bool
) -> pd.DataFrame:
    """为日线 df 计算 limit_status / is_one_word / is_st 列（不改原 df）。

    df 需含 close、open、high、low、pre_close。
    - limit_up_price = half_up(pre_close*(1+pct), 2)；close>=该价 → 涨停(1)。
    - limit_down_price = half_up(pre_close*(1-pct), 2)；close<=该价 → 跌停(-1)。
    - is_one_word：开=高=低=收 且 触及涨/跌停（一字板）。

    ⚠️ ST 时变局限（需求 §14.1 / SDD §6.2）：免费源只给"当前"ST 状态，
    无法还原历史每日 ST。若按当前 ST 状态(5%)倒灌全部历史，会把该股历史上
    非 ST 时期的正常 5~10% 涨幅误判为涨跌停。故 **limit_status 一律按板块涨跌幅
    计算**（不应用 ST 5% 折扣）；`is_st` 列仍记录当前状态供 universe 过滤用。
    ST 股本就被 exclude_st 过滤排除，其 limit_status 不参与回测撮合，无副作用。
    """
    out = df.copy()
    pct = board_limit_pct  # 仅按板块；不倒灌当前 ST 状态（见上）
    pre = out["pre_close"]
    limit_up = (pre * (1 + pct)).map(round_price_to_cent)
    limit_down = (pre * (1 - pct)).map(round_price_to_cent)

    is_up = out["close"] >= (limit_up - _EPS)
    is_down = out["close"] <= (limit_down + _EPS)
    # pre_close 缺失（首日）→ 无法判定，置 0
    valid = pre.notna()
    out["limit_status"] = np.where(valid & is_up, 1, np.where(valid & is_down, -1, 0)).astype("int8")

    flat = (
        (out["open"] == out["high"])
        & (out["high"] == out["low"])
        & (out["low"] == out["close"])
    )
    out["is_one_word"] = (flat & (out["limit_status"] != 0)).fillna(False)
    out["is_st"] = bool(is_st)
    out["is_suspended"] = False
    return out


def sanitize_bars(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """入库前自清洗 + 行级校验（入库闸门，非事后手动）。

    规则：
    - 丢弃 close 为空/≤0 的行（无效行情，无法用）。
    - 零成交量日的 amount/turnover_rate 空值填 0（其正确值）。
    - 开/高/低 为空或≤0 但 close 有效 → 用 close 回填（如新浪偶发 OHL=0）。
      ⚠️ 这类"修补行"真实振幅未知，故打标 `_ohl_repaired`，下游强制不标一字板，
         并由 ingest 记入 data_quality_issue（修补不静默、不臆造形态）。
    返回 (清洗后df, 统计)。统计供 ingest 记日志，使数据问题"入库即暴露"。
    """
    if df is None or df.empty:
        return df, {"dropped": 0, "fixed_ohl": 0, "filled_zerovol": 0, "dropped_dates": []}
    out = df.copy()
    n0 = len(out)

    # 1) close 无效 → 丢弃（记下被丢弃的交易日，供 ingest 落 L1 质量问题，不静默）
    bad_close = out["close"].isna() | (out["close"] <= 0)
    dropped = int(bad_close.sum())
    dropped_dates = (out.loc[bad_close, "trade_date"].tolist()
                     if dropped and "trade_date" in out.columns else [])
    out = out[~bad_close]

    # 2) 开/高/低 缺失或≤0 但 close 有效 → 用 close 回填（标记修补行）
    fixed_ohl = 0
    repaired = pd.Series(False, index=out.index)
    for col in ("open", "high", "low"):
        m = out[col].isna() | (out[col] <= 0)
        repaired |= m
        fixed_ohl += int(m.sum())
        out.loc[m, col] = out.loc[m, "close"]
    out["_ohl_repaired"] = repaired

    # 3) 零成交量日 amount/turnover 空 → 0
    filled = 0
    if "volume" in out.columns:
        zv = out["volume"] == 0
        for col in ("amount", "turnover_rate"):
            if col in out.columns:
                m = zv & out[col].isna()
                filled += int(m.sum())
                out.loc[m, col] = 0.0

    stats = {"dropped": dropped, "fixed_ohl": fixed_ohl, "filled_zerovol": filled,
             "in": n0, "out": len(out), "dropped_dates": dropped_dates}
    return out.reset_index(drop=True), stats


# 质检问题严重度映射（DM-D10）：复权跳变最伤回测=high；修补痕迹=low；其余=mid。
SEVERITY_BY_TYPE: dict[str, str] = {
    "adj_jump": "high",
    "abnormal_change": "mid",
    "ohl_repaired": "low",
    "null_close": "mid",       # 收盘价空/非正被丢弃——原始数据缺损（M2.9 L1 入库闸门）
    "mv_missing": "low",       # 市值字段整股缺失——字段契约不全（M2.9.2 L2）
    "mv_gap": "mid",           # 近端逐日市值字段缺口（total_mv/float_mv）——逐日缺、code 聚合
    "data_gap": "mid",         # 存续期缺口（疑似漏采，待重采反向确认）（M2.9.2 L4）
    "stale": "mid",            # 尾部鲜活滞后（最新<全局最新交易日）（M2.9.2 L4）
    "board_index_gap": "mid",  # 板块指数缺口（board_bar 滞后全局最新交易日）（板块概念 R12）
    "board_member_incomplete": "mid",  # 成分快照采集不完整/失败（只进不出模型完整性闸门，待重采）
}


def severity_for(issue_type: str) -> str:
    return SEVERITY_BY_TYPE.get(issue_type, "mid")


# ── 四层质量模型（M2.9，DM-D15）────────────────────────────────
# 把零散质检统一为分层体检：每个 issue_type 归一层，逐股/全局都按层展示。
# L2/L4 为聚合度量（非空率 / 缺口鲜活），不逐行落 issue，仅在 stock_quality / quality_model 计算。
QUALITY_LAYERS: list[dict] = [
    {"layer": "L1", "name_cn": "入库闸门", "desc": "原始行情合法性：收盘价非空且为正、开高低合法（坏行入库即拦截/修补）"},
    {"layer": "L2", "name_cn": "字段契约", "desc": "市值字段完整：总市值与流通市值都非空（流通市值供选股池过滤）"},
    {"layer": "L3", "name_cn": "正确性", "desc": "复权口径一致、涨跌停约束、无异常单日涨跌"},
    {"layer": "L4", "name_cn": "覆盖鲜活", "desc": "存续期无缺口、数据更新到最新交易日"},
]
ISSUE_LAYER: dict[str, str] = {
    "null_close": "L1",
    "ohl_repaired": "L1",
    "mv_missing": "L2",
    "mv_gap": "L2",
    "abnormal_change": "L3",
    "adj_jump": "L3",
    "data_gap": "L4",
    "stale": "L4",
    # 板块维度独立层（板块概念）：不混入个股 L1-L4 打分，仅质量页/概览按层归类展示。
    "board_index_gap": "板块",
    "board_member_incomplete": "板块",
    "board_fund_unmatched": "板块",
}
# 各层落 data_quality_issue 表的离散异常类型（M2.9.2：四层都落表，质检可反复扫并幂等覆盖）。
L1_ISSUE_TYPES: tuple[str, ...] = ("null_close", "ohl_repaired")
L2_ISSUE_TYPES: tuple[str, ...] = ("mv_missing", "mv_gap")
L3_ISSUE_TYPES: tuple[str, ...] = ("abnormal_change", "adj_jump")
L4_ISSUE_TYPES: tuple[str, ...] = ("data_gap", "stale")
# 能进入质检台账的完整问题类型集。调度、恢复参数校验统一复用这一契约，
# 避免新增质量层问题后只能手工处理。
QUALITY_ISSUE_TYPES: tuple[str, ...] = (
    L1_ISSUE_TYPES + L2_ISSUE_TYPES + L3_ISSUE_TYPES + L4_ISSUE_TYPES
    + ("board_index_gap", "board_member_incomplete", "board_fund_unmatched")
)
# 质检（scan_quality_issues）每次重扫并幂等覆盖的"自动问题"类型（L2/L3/L4）；
# L1 由入库闸门即时记录，质检只做防御性补扫，不在此清表。
# 板块自动扫描由 scan_board_quality 在同一事务内独立替换，避免扫描失败时先删旧问题。
SCAN_ISSUE_TYPES: tuple[str, ...] = (
    L2_ISSUE_TYPES + L3_ISSUE_TYPES + L4_ISSUE_TYPES
)


def layer_for(issue_type: str) -> str:
    return ISSUE_LAYER.get(issue_type, "L3")


class QualityChecker:
    """质检规则：写 data_quality_issue。"""

    def __init__(self, client: DuckDBClient | None = None):
        self.c = client or get_client()

    def _record(self, issues: list[dict]) -> int:
        if not issues:
            return 0
        df = pd.DataFrame(issues)
        df.insert(0, "id", [self._next_id() for _ in range(len(df))])
        df["detected_at"] = datetime.now()
        df["severity"] = df["issue_type"].map(severity_for)
        df["status"] = "open"
        with self.c.temp_view(df, prefix="issue") as tmp:
            self.c.execute(
                "INSERT INTO data_quality_issue "
                "(id, code, trade_date, issue_type, detail, detected_at, severity, status) "
                "SELECT id, code, trade_date, issue_type, detail, detected_at, severity, status "
                f"FROM {tmp}"
            )
        return len(df)

    def _next_id(self) -> int:
        return int(self.c.query_df("SELECT nextval('seq_quality_issue') AS v").iloc[0]["v"])

    def check_abnormal_change(self, code: str, board_limit_pct: float) -> int:
        """单日涨跌幅超出板块上限（+0.5% 容差，新股/无 pre_close 除外）→ 异常。"""
        df = self.c.query_df(
            "SELECT code, trade_date, close, pre_close FROM daily_bar WHERE code = ? AND pre_close IS NOT NULL",
            [code],
        )
        if df.empty:
            return 0
        chg = (df["close"] / df["pre_close"] - 1).abs()
        bad = df[chg > board_limit_pct + 0.005]
        issues = [
            {
                "code": r["code"],
                "trade_date": r["trade_date"],
                "issue_type": "abnormal_change",
                "detail": f"涨跌幅 {(r['close']/r['pre_close']-1)*100:.2f}% 超板块上限 {board_limit_pct*100:.0f}%",
            }
            for _, r in bad.iterrows()
        ]
        return self._record(issues)


    def check_adj_jump(self, code: str, threshold: float = 0.5) -> int:
        """前复权价相邻日跳变超阈值（剔除涨跌停正常波动后）→ 复权异常。"""
        df = self.c.query_df(
            "SELECT trade_date, close, COALESCE(adj_factor_clean, adj_factor) AS adj_factor "
            "FROM daily_bar WHERE code = ? ORDER BY trade_date",
            [code],
        )
        if len(df) < 2:
            return 0
        # 前复权价 = close × 干净因子 / 最新干净因子
        latest = df["adj_factor"].iloc[-1]
        qfq = df["close"] * df["adj_factor"] / latest
        ratio = (qfq / qfq.shift(1) - 1).abs()
        bad = df[ratio > threshold]
        issues = [
            {
                "code": code,
                "trade_date": r["trade_date"],
                "issue_type": "adj_jump",
                "detail": f"前复权价跳变 {ratio.loc[i]*100:.1f}%",
            }
            for i, r in bad.iterrows()
        ]
        return self._record(issues)
