"""行情消费的复权换算；不生成因子，不查询或修改数据库。

输入按证券、交易日升序。批量和单股共用同一选择、校验及归一化规则；
研究计算缺因子时拒绝执行，展示可显式选择返回缺数，禁止默认补 1。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.common.exceptions import DataQualityError

PRICE_COLUMNS = ("open", "high", "low", "close", "pre_close")
PRICE_CONSUMPTION_VERSION = "clean-factor-consumption-v1"


def effective_factors(
    frame: pd.DataFrame, *, strict: bool = True, factor_column: str = "adj_factor"
) -> pd.Series:
    """优先 clean、为空才回落源因子；无效 clean 不得被源值掩盖。"""
    if factor_column == "adj_factor" and "_effective_factor" in frame:
        factor_column = "_effective_factor"  # 数据库已按 COALESCE 选择，保留 SQL NaN 语义。
    if factor_column == "adj_factor" and "adj_factor_clean" in frame:
        # 先按 NULL 合并再转换，与 SQL COALESCE 一致，不把非法字符串当作 NULL 回落。
        selected = frame["adj_factor_clean"].where(
            frame["adj_factor_clean"].notna(), frame[factor_column]
        )
    else:
        selected = frame[factor_column]
    factor = pd.to_numeric(selected, errors="coerce").astype(float, copy=False)
    valid = np.isfinite(factor) & factor.gt(0)
    all_valid = bool(valid.all())
    if strict and not all_valid:
        keys = [col for col in ("code", "trade_date") if col in frame]
        sample = frame.loc[~valid, keys].head(3).to_dict("records") if keys else []
        raise DataQualityError(
            f"复权因子未就绪：{int((~valid).sum())} 行缺失或不是正有限数；"
            f"请先完成行情因子修复，示例 {sample}"
        )
    # 正常批量输入不额外复制整列；只有展示缺数分支才创建掩码结果。
    return factor if all_valid else factor.where(valid)


def price_scale(
    frame: pd.DataFrame,
    adjust: str,
    *,
    strict: bool = True,
    base_factor: float | None = None,
    factor_column: str = "adj_factor",
) -> pd.Series:
    """返回 HFQ 乘数或按股末日/显式固定基准归一的 QFQ 乘数。

    末日因子缺失时，展示模式整股 QFQ 缺数；不能跳到上一有效因子作为基准。
    不按股调用 Python 函数，保留批量向量路径及原行索引。
    """
    if adjust not in ("qfq", "hfq"):
        raise ValueError(f"不支持的复权模式：{adjust}")
    factor = effective_factors(frame, strict=strict, factor_column=factor_column)
    if adjust == "hfq" or frame.empty:
        return factor
    return factor / _normalization_base(frame, factor, base_factor, strict=strict)


def _normalization_base(
    frame: pd.DataFrame, factor: pd.Series, base_factor: float | None, *, strict: bool
) -> float | pd.Series:
    """末行是唯一归一锚点；与 price_scale/逐列换算共享，避免 NULL 被跳过。"""
    if base_factor is not None:
        if not np.isfinite(base_factor) or base_factor <= 0:
            raise DataQualityError("固定复权基准未就绪：必须是正有限数")
        base = base_factor
    elif "code" in frame:
        if strict:
            # 已校验全列有效，复用原批量路径的单次分组，避免 duplicated+map 两轮哈希。
            base = factor.groupby(frame["code"], sort=False).transform("last")
        else:
            last = ~frame["code"].duplicated(keep="last")
            anchors = pd.Series(factor.loc[last].to_numpy(), index=frame.loc[last, "code"])
            base = frame["code"].map(anchors)
    else:
        base = factor.iloc[-1]
    return base


def adjust_price_columns(
    frame: pd.DataFrame,
    adjust: str,
    *,
    columns: tuple[str, ...] = PRICE_COLUMNS,
    suffix: str = "",
    strict: bool = True,
    base_factor: float | None = None,
    factor_column: str = "adj_factor",
) -> pd.DataFrame:
    """原地换算指定价格列，避免批量大帧额外复制；原始模式无需因子。"""
    if adjust == "" or frame.empty:
        return frame
    if adjust not in ("qfq", "hfq"):
        raise ValueError(f"不支持的复权模式：{adjust}")
    factor = effective_factors(frame, strict=strict, factor_column=factor_column)
    base = _normalization_base(frame, factor, base_factor, strict=strict) if adjust == "qfq" else None
    for col in columns:
        if col in frame:
            # 保留原查询链路先乘再除的浮点运算顺序，避免阈值附近出现额外信号差异。
            value = frame[col] * factor
            frame[col + suffix] = value / base if adjust == "qfq" else value
    return frame


def hfq_price_sql(price: str, factor: str) -> str:
    """可信内部 SQL 表达式的展示换算；非法因子显式缺数，不注入默认值。

    SQL 聚合/批量关联消费者保留库内计算，避免为复用改成逐股查询。
    需要拒绝整个研究任务的消费者使用上面的严格向量入口。
    """
    return f"CASE WHEN isfinite({factor}) AND ({factor})>0 THEN ({price})*({factor}) END"
