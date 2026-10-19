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


def limit_pct_for(
    board_limit_pct: float, is_st: bool, trade_date: date | str | None = None
) -> float:
    """有效涨跌幅限制；历史计算应显式传交易日。"""
    return price_limit_pct_for(board_limit_pct, is_st, trade_date)


def add_markers(
    df: pd.DataFrame,
    board_limit_pct: float,
    is_st: bool | list[bool] | pd.Series,
) -> pd.DataFrame:
    """为日线 df 计算 limit_status / is_one_word / is_st 列（不改原 df）。

    df 需含 close、open、high、low、pre_close。
    - limit_up_price = half_up(pre_close*(1+pct), 2)；close>=该价 → 涨停(1)。
    - limit_down_price = half_up(pre_close*(1-pct), 2)；close<=该价 → 跌停(-1)。
    - is_one_word：开=高=低=收 且 触及涨/跌停（一字板）。

    ``is_st`` 可以是单值（兼容单日/测试调用）或与 df 等长的逐日状态。每行都通过
    ``price_limit_pct_for`` 计算有效限制，因此主板 ST 的 2026-07-06 规则切换会真实
    作用于行情标记，而不是只存在于独立撮合代码里。
    """
    out = df.copy()
    if isinstance(is_st, pd.Series):
        st_values = is_st.reset_index(drop=True).astype(bool).tolist()
    elif isinstance(is_st, (list, tuple, np.ndarray)):
        st_values = [bool(value) for value in is_st]
    else:
        st_values = [bool(is_st)] * len(out)
    if len(st_values) != len(out):
        raise ValueError("is_st 逐日状态数量必须与行情行数一致")
    dates = out["trade_date"].tolist() if "trade_date" in out.columns else [None] * len(out)
    codes = out["code"].tolist() if "code" in out.columns else [None] * len(out)
    pcts = pd.Series(
        [
            price_limit_pct_for(board_limit_pct, st, trade_day, code=code)
            for st, trade_day, code in zip(st_values, dates, codes, strict=True)
        ],
        index=out.index,
        dtype="float64",
    )
    pre = out["pre_close"]
    limit_up = (pre * (1 + pcts)).map(round_price_to_cent)
    limit_down = (pre * (1 - pcts)).map(round_price_to_cent)

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
    out["is_st"] = st_values
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


# 市值来自不同免费行情接口且以浮点数存储；同值经独立换算会产生约 1e-16 的尾差，
# 数据源按展示精度取整时也可能有极小偏差。关系校验统一允许万分之一相对误差，超过才算倒挂。
MV_REL_TOLERANCE = 1e-4


def mv_inverted_sql(total_mv: str = "total_mv", float_mv: str = "float_mv") -> str:
    """返回统一的市值倒挂 SQL 条件；参数只接受调用方写死的内部列表达式。"""
    return f"{total_mv} < {float_mv} * (1 - {MV_REL_TOLERANCE})"


# 质检问题严重度映射（DM-D10）：复权跳变最伤回测=high；修补痕迹=low；其余=mid。
SEVERITY_BY_TYPE: dict[str, str] = {
    "adj_jump": "high",
    "abnormal_change": "mid",
    "price_volume_mismatch": "high",
    "ohl_repaired": "low",
    "null_close": "mid",       # 收盘价空/非正被丢弃——原始数据缺损（M2.9 L1 入库闸门）
    "mv_missing": "low",       # 市值字段整股缺失——字段契约不全（M2.9.2 L2）
    "mv_gap": "mid",           # 近端逐日市值字段缺口（total_mv/float_mv）——逐日缺、code 聚合
    "capital_raw_invalid": "high",
    "capital_gap": "mid",
    "capital_invalid": "high",
    "capital_mismatch": "mid",
    "mv_invalid": "high",       # 近端市值非正或总市值倒挂超容差——逐日异常、code 聚合
    "history_data_gap": "mid",
    "data_gap": "mid",         # 存续期缺口（疑似漏采，待重采反向确认）（M2.9.2 L4）
    "stale": "mid",            # 尾部鲜活滞后（最新<全局最新交易日）（M2.9.2 L4）
    "st_status_missing": "high",       # 行情/停牌事实存在但缺逐日 ST 权威事实
    "st_status_approximate": "high",   # 仍为名称推断等非权威兼容值
    "st_status_mismatch": "high",      # 过渡投影与唯一事实不一致
    "market_index_gap": "mid",  # 配置市场指数未追平全局最新交易日
    "market_index_gap_daily": "mid",  # 配置市场指数近端具体开市日缺失
    "market_index_invalid": "mid",  # 配置市场指数 OHLC/成交字段非法
    "board_index_gap": "mid",  # 板块指数缺口（board_bar 滞后全局最新交易日）（板块概念 R12）
    "board_index_gap_daily": "mid",  # 板块指数逐日缺口（近端窗口内具体某日缺失）
    "board_index_invalid": "mid",  # 板块指数 OHLC/成交字段非法（已有记录但内容不可用）
    "board_member_incomplete": "mid",  # 成分快照采集不完整/失败（只进不出模型完整性闸门，待重采）
    "board_fund_unmatched": "mid",  # 板块资金流未匹配到字典（源无稳定代码，待源侧收敛）
    "board_fund_missing": "mid",  # 板块资金流缺失（源未收录该板块，待源侧上线后重采收敛）
    "board_fund_stale": "mid",  # 板块资金流滞后（全源快照停留早于全局最新交易日，源停采/漏采）
}


def severity_for(issue_type: str) -> str:
    return SEVERITY_BY_TYPE.get(issue_type, "mid")


# ── 四层质量模型（M2.9，DM-D15）────────────────────────────────
# 把零散质检统一为分层体检：每个 issue_type 归一层，逐股/全局都按层展示。
# L2/L4 为聚合度量（非空率 / 缺口鲜活），不逐行落 issue，仅在 stock_quality / quality_model 计算。
QUALITY_LAYERS: list[dict] = [
    {"layer": "L1", "name_cn": "入库闸门", "desc": "新采行情的原始/复权响应配对一致，收盘价与开高低合法；除权边界按官方前收盘校准"},
    {"layer": "L2", "name_cn": "字段契约", "desc": "股本与市值全历史完整、合法且相互一致；市值关系允许万分之一相对误差"},
    {"layer": "L3", "name_cn": "正确性", "desc": "复权因子、涨跌停边界及成交价量口径一致"},
    {"layer": "L4", "name_cn": "覆盖鲜活", "desc": "存续期无缺口、数据更新到最新交易日"},
]
ISSUE_LAYER: dict[str, str] = {
    "null_close": "L1",
    "ohl_repaired": "L1",
    "mv_missing": "L2",
    "mv_gap": "L2",
    "capital_raw_invalid": "来源",
    "capital_gap": "L2",
    "capital_invalid": "L2",
    "capital_mismatch": "L2",
    "mv_invalid": "L2",
    "abnormal_change": "L3",
    "price_volume_mismatch": "L3",
    "adj_jump": "L3",
    "history_data_gap": "L4",
    "data_gap": "L4",
    "stale": "L4",
    "st_status_missing": "ST",
    "st_status_approximate": "ST",
    "st_status_mismatch": "ST",
    # 市场基准指数独立层：不混入逐股质量评分，但进入同一质量台账与恢复闭环。
    "market_index_gap": "指数",
    "market_index_gap_daily": "指数",
    "market_index_invalid": "指数",
    # 板块维度独立层（板块概念）：不混入个股 L1-L4 打分，仅质量页/概览按层归类展示。
    "board_index_gap": "板块",
    "board_index_gap_daily": "板块",
    "board_index_invalid": "板块",
    "board_member_incomplete": "板块",
    "board_fund_unmatched": "板块",
    "board_fund_missing": "板块",
    "board_fund_stale": "板块",
}
# 各层落 data_quality_issue 表的离散异常类型（M2.9.2：四层都落表，质检可反复扫并幂等覆盖）。
L1_ISSUE_TYPES: tuple[str, ...] = ("null_close", "ohl_repaired")
L2_ISSUE_TYPES: tuple[str, ...] = ("mv_missing", "mv_gap", "mv_invalid", "capital_gap", "capital_invalid", "capital_mismatch")
L3_ISSUE_TYPES: tuple[str, ...] = (
    "abnormal_change", "price_volume_mismatch", "adj_jump",
)
L4_ISSUE_TYPES: tuple[str, ...] = ("data_gap", "stale", "history_data_gap")
ST_ISSUE_TYPES: tuple[str, ...] = (
    "st_status_missing", "st_status_approximate", "st_status_mismatch",
)
# 「标记正常」的精确豁免类型：只豁免同一对象、同一问题类型、同一交易日。
# 其余状态型问题按对象与类型整体豁免，避免各扫描/采集入口自行写死而产生口径分叉。
EXACT_IGNORE_ISSUE_TYPES: frozenset[str] = frozenset(
    L1_ISSUE_TYPES + L3_ISSUE_TYPES
    + ("market_index_gap_daily", "market_index_invalid",
       "board_index_gap_daily", "board_index_invalid")
)
# 能进入质检台账的完整问题类型集。调度、恢复参数校验统一复用这一契约，
# 避免新增质量层问题后只能手工处理。
QUALITY_ISSUE_TYPES: tuple[str, ...] = (
    L1_ISSUE_TYPES + L2_ISSUE_TYPES + L3_ISSUE_TYPES + L4_ISSUE_TYPES + ST_ISSUE_TYPES + ("capital_raw_invalid",)  # 仅清理旧台账
    + ("market_index_gap", "market_index_gap_daily", "market_index_invalid",
       "board_index_gap", "board_index_gap_daily", "board_index_invalid", "board_member_incomplete",
       "board_fund_unmatched", "board_fund_missing", "board_fund_stale")
)
# 质检（scan_quality_issues）每次重扫并幂等覆盖的"自动问题"类型（L2/L3/L4）；
# L1 由入库闸门即时记录，质检只做防御性补扫，不在此清表。
# 板块自动扫描由 scan_board_quality 在同一事务内独立替换，避免扫描失败时先删旧问题。
SCAN_ISSUE_TYPES: tuple[str, ...] = (
    L2_ISSUE_TYPES + L3_ISSUE_TYPES + L4_ISSUE_TYPES + ST_ISSUE_TYPES + ("capital_raw_invalid",)  # 仅清理旧台账
)


# 新任务选项仅提供统一类型；旧参数仍通过 QUALITY_ISSUE_TYPES 校验并在执行时映射。
from backend.dataquality.consolidation import QUALITY_TYPE_ALIASES

ACTIVE_QUALITY_ISSUE_TYPES = tuple(
    kind for kind in QUALITY_ISSUE_TYPES
    if kind not in QUALITY_TYPE_ALIASES and kind != "capital_raw_invalid"
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
        """按交易所分价后的涨跌停价检查越界行情（新股/无 pre_close 由上层排除）。"""
        from backend.market_rules import limit_prices, round_price_to_cent

        df = self.c.query_df(
            "SELECT b.code,b.trade_date,b.close,b.pre_close,st.is_st,st.quality "
            "FROM daily_bar b LEFT JOIN stock_st_status_daily st "
            "ON st.code=b.code AND st.trade_date=b.trade_date "
            "WHERE b.code = ? AND b.pre_close IS NOT NULL",
            [code],
        )
        if df.empty:
            return 0
        issues = []
        for _, row in df.iterrows():
            if pd.isna(row["is_st"]) or row["quality"] != "accurate":
                continue  # ST completeness is reported by the dedicated ST contract scan.
            pct = price_limit_pct_for(
                board_limit_pct, bool(row["is_st"]), row["trade_date"], code=code
            )
            up, down = limit_prices(float(row["pre_close"]), pct)
            close = round_price_to_cent(float(row["close"]))
            if down - 0.011 <= close <= up + 0.011:
                continue
            issues.append({
                "code": row["code"],
                "trade_date": row["trade_date"],
                "issue_type": "abnormal_change",
                "detail": f"收盘价 {close:.2f} 超出合法区间 {down:.2f}~{up:.2f}",
            })
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
