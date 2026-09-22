"""技术指标注册表（v2.0 §5）——指标的"定义"层（元数据，非值表）。

v2.0 决策 D1：删除 indicator 预计算值表，指标全部动态实时计算。本注册表只登记
每个指标的**定义**（标识/中文名/类型/可配参数/方向/说明），供：
  - 配置管理「技术指标」页展示与选择；
  - 策略筛选 / 评分规则 / 买卖指标 从这里取指标元数据（前端显示 name_cn）；
  - `GET /api/indicators/registry` 输出目录。

注意：实际计算逻辑在 `compute.py`（单股宽表）。本期注册表的 key 与 compute 产出列对齐；
后续里程碑（M2.2~M2.4）由注册表驱动动态传参计算。股东数等数据源未接入项见 D2，预留扩展。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Param:
    name: str
    label: str
    type: str          # "int" | "float"
    default: float | int
    min: float | int | None = None
    max: float | int | None = None
    unit: str = ""
    description: str = ""


@dataclass(frozen=True)
class IndicatorDef:
    key: str                       # 英文标识（后端/AST 用）
    name_cn: str                   # 中文显示名（前端用）
    dtype: str                     # "number" | "bool"
    category: str                  # 分类：价格/均线/新高/量/涨幅/市值/强度/换手/趋势/事件
    direction: str | None = None   # "higher_better" | "lower_better" | None（布尔型无方向）
    params: list[Param] = field(default_factory=list)
    desc: str = ""
    enabled: bool = True
    kind: str = "builtin"          # "builtin"(映射动态计算列) | "expr"(DSL 表达式，可参数化)
    expression: str | None = None  # kind=expr 的表达式模板，含 {param} 占位
    is_builtin: bool = True        # 内置（不可删，仅可启停）
    layer: str | None = None       # field | metric | signal | preset；None 时由治理映射推导
    parent_key: str | None = None  # preset 对应的通用指标 key
    preset_params: dict = field(default_factory=dict)


# ── 本期内置指标（与 compute.py 产出对齐；可动态传参的标注参数 schema）──
REGISTRY: list[IndicatorDef] = [
    # 行情基础字段
    IndicatorDef("close", "股价", "number", "价格", None, [],
                 "口径:当日未复权收盘价(元)。是什么:股票在指定交易日的收盘价格。"
                 "怎么用:按绝对价格区间筛选或评分；涉及收益、均线和形态时应使用对应技术指标。"),
    # 均线
    IndicatorDef("ma", "日均线(自定周期)", "number", "均线", None,
                 [Param("period", "周期", "int", 20, 2, 1000)],
                 "N日收盘价(前复权)的简单移动平均。是什么:价格中枢/趋势线。怎么用:周期任意可调,"
                 "常配合「收盘 vs 均线」「贴近/站上均线」使用。", kind="expr",
                 expression="MA(C, {period})"),
    # 常用固定均线：计算语义统一继承 ma + preset_params，物理执行复用同名向量化列。
    IndicatorDef("ma5", "MA5", "number", "均线", None, [], "5日均线(常用固定周期)。"),
    IndicatorDef("ma10", "MA10", "number", "均线", None, [], "10日均线(常用固定周期)。"),
    IndicatorDef("ma20", "MA20", "number", "均线", None, [], "20日均线(常用固定周期)。"),
    IndicatorDef("ma30", "MA30", "number", "均线", None, [], "30日均线(常用固定周期)。"),
    IndicatorDef("ma60", "MA60", "number", "均线", None, [], "60日均线(常用固定周期)。"),
    IndicatorDef("bull_arrange", "多头排列", "bool", "趋势", None, [],
                 "口径:MA5>MA10>MA20>MA60 同时成立(短中期均线向上发散)。是什么:典型强势"
                 "上升结构。怎么用:筛选/评分中作「趋势走强」的硬条件或高权重项。"),
    IndicatorDef("ma20_up", "MA20向上", "bool", "趋势", None, [],
                 "口径:MA20 较前若干日抬升。是什么:短期均线方向向上。怎么用:确认短线趋势,"
                 "常与回踩MA20买点配合。"),
    IndicatorDef("ma60_up", "MA60向上", "bool", "趋势", None, [],
                 "口径:MA60 较前若干日抬升。是什么:中期均线向上。怎么用:过滤中期走弱标的。"),
    IndicatorDef("ma_up", "均线向上", "bool", "趋势", None,
                 [Param("n", "均线周期", "int", 20, 2, 250), Param("k", "回看天数", "int", 5, 1, 60)],
                 "口径:MA(C,N) > REF(MA(C,N),K),N日均线较K日前抬升。是什么:指定均线方向向上。"
                 "怎么用:N、回看K 均可调,替代固定的 MA20/MA60 向上。", kind="expr",
                 expression="MA(C, {n}) > REF(MA(C, {n}), {k})"),
    IndicatorDef("above_ma250", "站上年线", "bool", "趋势", None, [],
                 "口径:收盘>MA250(年线)。是什么:长期多头标志。怎么用:作长期趋势过滤(牛熊线)。"),
    # MACD（固定 12/26/9，与动态计算宽表同名，不开放方案级参数）
    IndicatorDef("macd_diff", "MACD DIFF", "number", "趋势", None, [],
                 "口径:EMA(前复权收盘,12)-EMA(前复权收盘,26)。固定参数12/26/9。"
                 "是什么:MACD快慢线差值。怎么用:结合DEA、零轴和交叉事件判断趋势动量。"),
    IndicatorDef("macd_dea", "MACD DEA", "number", "趋势", None, [],
                 "口径:EMA(DIFF,9)，DIFF基于前复权收盘的EMA12与EMA26。固定参数12/26/9。"
                 "是什么:MACD信号线。怎么用:结合DIFF判断趋势方向与交叉。"),
    IndicatorDef("macd_hist", "MACD柱", "number", "趋势", None, [],
                 "口径:2×(DIFF-DEA)，基于前复权日线，固定参数12/26/9。"
                 "是什么:多空动量柱。怎么用:正负和柱体变化用于衡量动量强弱。"),
    IndicatorDef("macd_golden_cross", "MACD金叉", "bool", "趋势", None, [],
                 "口径:基于前复权日线，同股相邻有效交易日DIFF由不高于DEA变为高于DEA，"
                 "固定参数12/26/9。"
                 "是什么:MACD向上交叉事件。怎么用:作为筛选、评分或买入条件。"),
    IndicatorDef("macd_dead_cross", "MACD死叉", "bool", "趋势", None, [],
                 "口径:基于前复权日线，同股相邻有效交易日DIFF由不低于DEA变为低于DEA，"
                 "固定参数12/26/9。"
                 "是什么:MACD向下交叉事件。怎么用:作为风险过滤或卖出条件。"),
    # 新高 / 位置
    IndicatorDef("hhv", "N日最高点", "number", "新高", "higher_better",
                 [Param("window", "窗口", "int", 480, 5, 1200)],
                 "口径:近N日最高价(半年120/一年240/两年480/三年720)。是什么:压力位/前高。"
                 "怎么用:窗口任意可调,与收盘比较判断突破前高,或作压力/止盈参照。", kind="expr",
                 expression="HHV(H, {window})"),
    IndicatorDef("is_high_120", "半年新高", "bool", "新高", None, [],
                 "口径:收盘≥近120日最高价。是什么:创半年新高。怎么用:突破强势信号(布尔)。"),
    IndicatorDef("is_high_1y", "一年新高", "bool", "新高", None, [],
                 "口径:收盘≥近240日最高价。是什么:创一年新高。怎么用:更强的突破信号。"),
    IndicatorDef("is_high_2y", "两年新高", "bool", "新高", None, [],
                 "口径:收盘≥近480日最高价。是什么:创两年新高(主升浪常见特征)。怎么用:龙头筛选硬条件。"),
    IndicatorDef("new_high", "创N日新高", "bool", "新高", None,
                 [Param("n", "窗口", "int", 120, 5, 1200)],
                 "口径:收盘 ≥ HHV(H,N)。是什么:创近N日新高(N 任意可调)。怎么用:突破/强势筛选,"
                 "N=120半年、240一年、480两年。", kind="expr",
                 expression="C >= HHV(H, {n})"),
    IndicatorDef("dist_to_high_2y", "距两年高", "number", "新高", "lower_better", [],
                 "口径:(两年最高-收盘)/两年最高。是什么:距两年高点的回撤比例,0=正在创新高。"
                 "怎么用:评分按「越接近新高分越高」(越小越好),衡量位置。"),
    # 量
    IndicatorDef("volume", "成交量", "number", "量", "higher_better", [],
                 "口径:当日成交量。是什么:市场参与度。怎么用:多与均量比较判断放/缩量。"),
    IndicatorDef("vol_change_pct", "成交量变化幅度", "number", "量", "higher_better",
                 [Param("window", "对比窗口", "int", 5, 1, 250)],
                 "口径:(当日量/N日均量-1)×100,单位%。是什么:放量(>0)或缩量(<0)程度。"
                 "怎么用:筛选放量,如 >50 即放量50%。", kind="expr",
                 expression="(V / MA(V, {window}) - 1) * 100"),
    IndicatorDef("is_vol_breakout", "放量突破(固定20×2)", "bool", "量", None, [],
                 "口径:量>20日均量×2(N和倍数由全局配置固定)。如需自定义请用「放量突破」。"),
    IndicatorDef("vol_break", "放量突破", "bool", "量", None,
                 [Param("n", "均量窗口", "int", 20, 2, 250), Param("x", "放量倍数", "float", 2, 1, 10)],
                 "口径:成交量 > MA(V,N)×倍数。是什么:相对N日均量放量X倍。怎么用:启动放量确认,"
                 "N、倍数均可调。", kind="expr",
                 expression="V > MA(V, {n}) * {x}"),
    # 涨幅
    IndicatorDef("pct_change", "N日涨跌幅", "number", "涨幅", "higher_better",
                 [Param("n", "天数", "int", 1, 1, 250)],
                 "口径:(收盘/N日前收盘-1)×100,单位%。是什么:区间动量。怎么用:筛选涨幅区间(如近5日>10%),"
                 "或评分给动量加分;天数任意可调。", kind="expr",
                 expression="(C / REF(C, {n}) - 1) * 100"),
    IndicatorDef("range_amplitude_pct", "N日区间振幅", "number", "涨幅", "lower_better",
                 [Param("window", "统计周期", "int", 20, 2, 1200, "交易日",
                        "使用最近多少个交易日的最高价和最低价计算区间振幅。")],
                 "口径:(近N日最高价/近N日最低价-1)×100，单位%。是什么:指定区间内的价格波动范围。"
                 "怎么用:筛选窄幅整理可配置结果<=阈值；一年口径使用N=240。", kind="expr",
                 expression="(HHV(H, {window}) / LLV(L, {window}) - 1) * 100"),
    # 市值 / 股本
    IndicatorDef("float_mv", "流通市值", "number", "市值", None, [],
                 "口径:流通股本×收盘价(元)。是什么:可交易盘子大小。怎么用:筛选市值区间(如100-1000亿)避开过大/过小。"),
    IndicatorDef("total_mv", "总市值", "number", "市值", None, [],
                 "口径:指定交易日由估值数据源采集的总市值(元)。是什么:公司总规模。"
                 "怎么用:市值分层、筛选或评分；缺口由 valuation 回补与数据体检识别。"),
    IndicatorDef("float_share", "流通股本", "number", "股本", None, [],
                 "口径:指定交易日流通市值÷当日未复权收盘价，单位股。是什么:当日可交易股份数量。"
                 "怎么用:筛选或评分流通盘规模；市值或收盘价缺失时结果为空。"),
    IndicatorDef("total_share", "总股本", "number", "股本", None, [],
                 "口径:指定交易日总市值÷当日未复权收盘价，单位股。是什么:当日公司已发行股份总量。"
                 "怎么用:筛选或评分总盘规模；市值或收盘价缺失时结果为空。"),
    # 强度
    IndicatorDef("rs_pct", "相对强度RS", "number", "强度", "higher_better", [],
                 "口径:近W日收益在全市场的横截面百分位(0~100),W由全局配置(当前120日)。是什么:相对全市场"
                 "强弱排名,越高越强。怎么用:选龙头核心,常要求RS≥80/90。注:RS是跨股票截面排名,"
                 "窗口W为全局设置、不支持逐方案传参(这是唯一真正受向量化/截面限制的指标)。"),
    # 换手
    IndicatorDef("turnover_rate", "换手率", "number", "换手", None, [],
                 "口径:当日成交占流通股比例%。是什么:活跃度。怎么用:筛选活跃度区间。"),
    IndicatorDef("is_turnover_healthy", "换手健康", "bool", "换手", None, [],
                 "口径:换手率落在配置的健康区间内。是什么:不滞涨也不过热。怎么用:过滤换手异常标的。"),
    # 突破
    IndicatorDef("is_platform_breakout", "平台突破(固定60)", "bool", "趋势", None, [],
                 "口径:收盘突破前期60日平台高点(N由全局配置固定,不可传参)。如需自定义N请用「平台突破」。"),
    IndicatorDef("platform_break", "平台突破", "bool", "趋势", None,
                 [Param("n", "平台窗口", "int", 60, 5, 500)],
                 "口径:C > REF(HHV(H,{n}),1),收盘突破前N日最高(shift防自指)。是什么:横盘N日后向上突破。"
                 "怎么用:突破买点,N 可调(60/120…)。", kind="expr",
                 expression="C > REF(HHV(H, {n}), 1)"),
    # ── 表达式型内置指标（kind=expr，可参数化；也示范如何自定义）──
    IndicatorDef("consec_up", "连续上涨N天", "bool", "形态", None,
                 [Param("n", "天数", "int", 5, 2, 60)],
                 "口径:近N个交易日每天收盘都比前一日高。是什么:连阳/连续走强形态。"
                 "怎么用:筛选/评分作短期强势条件,N 可动态改(这次5、下次6)。", kind="expr",
                 expression="COUNT(C > REF(C,1), {n}) == {n}"),
    IndicatorDef("consec_down", "连续下跌N天", "bool", "形态", None,
                 [Param("n", "天数", "int", 5, 2, 60)],
                 "口径:近N个交易日每天收盘都比前一日低。是什么:连阴/连续走弱形态。"
                 "怎么用:规避或抄底信号,N 可动态改。", kind="expr",
                 expression="COUNT(C < REF(C,1), {n}) == {n}"),
    IndicatorDef("ma_bias", "MA乖离率", "number", "均线", "higher_better",
                 [Param("n", "均线周期", "int", 20, 2, 250)],
                 "口径:C/MA(C,n)-1,收盘相对N日均线的偏离。是什么:正=高于均线、负=低于均线。"
                 "怎么用:衡量超买超卖/回踩程度,N 可动态改。", kind="expr",
                 expression="C / MA(C, {n}) - 1"),
    IndicatorDef("near_ma", "贴近均线", "bool", "均线", None,
                 [Param("n", "均线周期", "int", 5, 2, 250), Param("tol", "容差%", "float", 1, 0, 50)],
                 "口径:|收盘/MA(n)-1| ≤ 容差%。是什么:价格贴近N日均线(回踩/支撑)。"
                 "怎么用:如 N=5、容差=1 即「距5日线1%以内」,作回踩买点。", kind="expr",
                 expression="ABS(C / MA(C, {n}) - 1) <= {tol} / 100"),
    IndicatorDef("below_ma", "跌破均线", "bool", "均线", None,
                 [Param("n", "均线周期", "int", 10, 2, 250)],
                 "口径:收盘 < MA(n)。是什么:价格跌破N日均线。怎么用:如 N=10 即「跌破10日线」,作卖出/止损信号。",
                 kind="expr", expression="C < MA(C, {n})"),
    IndicatorDef("above_ma", "站上均线", "bool", "均线", None,
                 [Param("n", "均线周期", "int", 20, 2, 250)],
                 "口径:收盘 > MA(n)。是什么:价格站上N日均线。怎么用:作多头确认/买入过滤。",
                 kind="expr", expression="C > MA(C, {n})"),
    # 事件
    IndicatorDef("days_since_xrxd", "距最近除权日", "number", "事件", None, [],
                 "口径:距最近一次除权除息的交易日数(预留,待接入)。", enabled=False),
    # 预留：股东数（D2 暂不纳入）
    IndicatorDef("holder_num", "股东户数", "number", "股东", "lower_better", [],
                 "口径:股东户数(待接入数据源,D2 暂不纳入)。是什么:筹码集中度,越少越集中。", enabled=False),
    IndicatorDef("holder_change_pct", "股东数变化幅度", "number", "股东", "lower_better", [],
                 "口径:股东户数环比变化(待接入)。是什么:筹码集中趋势,下降=集中。", enabled=False),
]


# ── 指标分类预设（多分类/打标签；按"角度"划分，一个指标可属多类）──
# 预设角度：价格 / 趋势 / 动量 / 量能 / 位置 / 均线 / 突破 / 估值 / 换手 / 形态 / 强度
# 用户可在前端为任意指标增删分类、或自定义新分类名（存库覆盖预设）。
PRESET_CATEGORIES: dict[str, list[str]] = {
    "close": ["价格"],
    "ma": ["均线"], "ma5": ["均线"], "ma10": ["均线"], "ma20": ["均线"], "ma30": ["均线"], "ma60": ["均线"],
    "ma_bias": ["均线", "动量"], "near_ma": ["均线", "位置"], "below_ma": ["均线"], "above_ma": ["均线", "趋势"],
    "bull_arrange": ["趋势", "均线"], "ma20_up": ["趋势", "均线"], "ma60_up": ["趋势", "均线"],
    "ma_up": ["趋势", "均线"], "above_ma250": ["趋势", "均线"],
    "macd_diff": ["趋势", "动量"], "macd_dea": ["趋势", "动量"],
    "macd_hist": ["趋势", "动量"], "macd_golden_cross": ["趋势", "动量"],
    "macd_dead_cross": ["趋势", "动量"],
    "hhv": ["位置", "新高"], "is_high_120": ["位置", "新高"], "is_high_1y": ["位置", "新高"],
    "is_high_2y": ["位置", "新高"], "new_high": ["位置", "新高", "突破"], "dist_to_high_2y": ["位置"],
    "volume": ["量能"], "vol_change_pct": ["量能"], "is_vol_breakout": ["量能", "突破"], "vol_break": ["量能", "突破"],
    "pct_change": ["动量"], "range_amplitude_pct": ["动量", "形态"],
    "consec_up": ["动量", "形态"], "consec_down": ["形态"],
    "float_mv": ["估值"], "total_mv": ["估值"],
    "float_share": ["股本", "估值"], "total_share": ["股本", "估值"],
    "rs_pct": ["动量", "强度"], "turnover_rate": ["换手"], "is_turnover_healthy": ["换手"],
    "is_platform_breakout": ["突破", "趋势"], "platform_break": ["突破", "趋势"],
    "days_since_xrxd": ["事件"], "holder_num": ["筹码"], "holder_change_pct": ["筹码"],
}


# 业务层级与计算方式、输出类型正交。固定 key 继续兼容，只在目录中作为快捷预设归组。
_FIELD_KEYS = {
    "close", "volume", "float_mv", "total_mv", "float_share", "total_share", "turnover_rate",
}
_NON_KLINE_PERIOD_KEYS = _FIELD_KEYS | {
    "is_turnover_healthy",
    "days_since_xrxd",
    "holder_num",
    "holder_change_pct",
}
PRESET_RELATIONS: dict[str, tuple[str, dict]] = {
    "ma5": ("ma", {"period": 5}),
    "ma10": ("ma", {"period": 10}),
    "ma20": ("ma", {"period": 20}),
    "ma30": ("ma", {"period": 30}),
    "ma60": ("ma", {"period": 60}),
    "is_high_120": ("new_high", {"n": 120}),
    "is_high_1y": ("new_high", {"n": 240}),
    "is_high_2y": ("new_high", {"n": 480}),
    "is_vol_breakout": ("vol_break", {"n": "全局配置", "x": "全局配置"}),
    "is_platform_breakout": ("platform_break", {"n": "全局配置"}),
    "ma20_up": ("ma_up", {"n": 20, "k": "全局配置"}),
    "ma60_up": ("ma_up", {"n": 60, "k": "全局配置"}),
    "above_ma250": ("above_ma", {"n": 250}),
}

_PRESET_GLOBAL_PARAM_KEYS: dict[tuple[str, str], str] = {
    ("is_vol_breakout", "n"): "vol_breakout_n",
    ("is_vol_breakout", "x"): "vol_breakout_x",
    ("is_platform_breakout", "n"): "platform_breakout_n",
    ("ma20_up", "k"): "ma_up_lookback",
    ("ma60_up", "k"): "ma_up_lookback",
}


def indicator_calculation_period(key: str, kind: str) -> str | None:
    """返回指标实际消费的 K 线周期；快照和事件字段不伪装为 K 线指标。"""
    if kind == "expr":
        return "day"
    return None if key in _NON_KLINE_PERIOD_KEYS else "day"


def governance_metadata(d: IndicatorDef) -> tuple[str, str | None, dict]:
    """返回稳定业务层级；旧注册项无需为新增字段改写所有位置参数。"""
    if d.layer:
        return d.layer, d.parent_key, dict(d.preset_params)
    relation = PRESET_RELATIONS.get(d.key)
    if relation:
        return "preset", relation[0], dict(relation[1])
    if d.key in _FIELD_KEYS:
        return "field", None, {}
    return ("signal" if d.dtype == "bool" else "metric"), None, {}


def normalize_indicator_reference(
    key: str, params: dict | None = None, calculation_params: dict | None = None
) -> tuple[str, dict, str | None]:
    """把历史固定 key 归一为父指标引用，同时保留可走快列的预设 key。

    preset_params 是固定参数，不能被方案里遗留的 params 覆盖；非预设指标保持原引用。
    返回 (逻辑指标 key, 有效参数, 物理预设 key)。
    """
    relation = PRESET_RELATIONS.get(key)
    if relation is None:
        return key, dict(params or {}), None
    parent_key, preset_params = relation
    effective = dict(preset_params)
    if "全局配置" in effective.values():
        if calculation_params is None:
            from backend.indicators.compute import build_params
            calculation_params = build_params()
        for param_name, value in effective.items():
            if value != "全局配置":
                continue
            setting_key = _PRESET_GLOBAL_PARAM_KEYS[(key, param_name)]
            effective[param_name] = calculation_params[setting_key]
    return parent_key, effective, key


def preset_categories(key: str, fallback_single: str) -> list[str]:
    """指标的预设多分类；无预设则用其单一 category 兜底。"""
    return PRESET_CATEGORIES.get(key) or ([fallback_single] if fallback_single else [])


def list_registry(include_disabled: bool = False) -> list[dict]:
    """返回指标目录（dict 列表），供 API 与前端使用。"""
    items = REGISTRY if include_disabled else [d for d in REGISTRY if d.enabled]
    return [_to_dict(d) for d in items]


def _to_dict(d: IndicatorDef) -> dict:
    out = asdict(d)
    out["params"] = [asdict(p) for p in d.params]
    out["layer"], out["parent_key"], out["preset_params"] = governance_metadata(d)
    return out


def get_def(key: str) -> IndicatorDef | None:
    for d in REGISTRY:
        if d.key == key:
            return d
    return None
