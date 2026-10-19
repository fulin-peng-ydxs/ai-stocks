"""撮合与组合记账（T-M5-4/5，SDD §6.4/§10.3）——防撮合失真核心。

成交约束（比"一字板"更精确）：
  - 买入：仅当 T+1 **开盘价 < 当日涨停价** 才可成交（开盘即封涨停就买不到）。
  - 卖出：仅当 T+1 **开盘价 > 当日跌停价** 才可成交，否则顺延。
  - 涨跌停价按板块/ST：limit = Decimal half-up(pre_close × (1 ± pct), 2)。
  - 停牌（当日无 bar）→ 不可交易。
交易规则：买入按 **100 股整手**取整（floor），余资金留存；方向性滑点（买入价上浮、卖出价下浮）；
  成本=佣金双边(率/最低)+印花税(仅卖)+过户费。
价格口径：引擎统一用**后复权(hfq)**记账（单调、无需 rebase），收益率与净值在 hfq 基准下正确。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from backend.config import CostConfig, get_effective_settings
from backend.market_rules import limit_prices


def can_buy_at_open(open_px: float, pre_close: float, pct: float, *, no_price_limit: bool = False) -> bool:
    """次日开盘可买：开盘价 < 涨停价（开盘即涨停买不到）。"""
    if no_price_limit:
        return math.isfinite(open_px) and open_px > 0
    up, _ = limit_prices(pre_close, pct)
    return open_px < up - 1e-9


def can_sell_at_open(open_px: float, pre_close: float, pct: float, *, no_price_limit: bool = False) -> bool:
    """次日开盘可卖：开盘价 > 跌停价（开盘即跌停卖不出）。"""
    if no_price_limit:
        return math.isfinite(open_px) and open_px > 0
    _, down = limit_prices(pre_close, pct)
    return open_px > down + 1e-9


@dataclass
class Position:
    code: str
    shares: int
    entry_date: object        # date
    entry_price: float        # 成交价（hfq，含滑点）
    cost_basis: float         # 买入总现金支出（含佣金/过户费）
    grade: str = ""
    entry_score: float | None = None  # 买入当日综合分（解释"无评级"档：分数未达观察阈值）
    entry_rank: int = 0       # 买入当日全市场评分榜名次（0=未知）
    entry_pick_rank: int = 0  # 方案内排名（命中票按分排序后的优先级）
    entry_pool: int = 0       # 当日候选池大小（方案命中数；无方案=全市场已评分数）
    last_price: float = 0.0   # 最近估值价（hfq close）

    def market_value(self) -> float:
        return self.shares * self.last_price


@dataclass
class Fill:
    code: str
    side: str                 # buy/sell
    date: object
    price: float              # 成交价（hfq，含滑点）
    shares: int
    gross: float              # 成交额（price×shares）
    cost: float               # 费用合计（佣金+印花+过户）
    cash_delta: float         # 现金变动（买<0/卖>0）


@dataclass
class Broker:
    """单账户撮合 + 记账。价格统一 hfq。"""
    cash: float
    cost: CostConfig = field(default_factory=lambda: get_effective_settings().backtest.cost)
    lot_size: int = field(default_factory=lambda: get_effective_settings().backtest.lot_size)
    positions: dict[str, Position] = field(default_factory=dict)
    fills: list[Fill] = field(default_factory=list)

    # ── 费用 ──
    def _buy_costs(self, gross: float) -> float:
        commission = max(gross * self.cost.commission_rate, self.cost.commission_min)
        transfer = gross * self.cost.transfer_fee_rate
        return commission + transfer

    def _sell_costs(self, gross: float) -> float:
        commission = max(gross * self.cost.commission_rate, self.cost.commission_min)
        stamp = gross * self.cost.stamp_tax_rate
        transfer = gross * self.cost.transfer_fee_rate
        return commission + stamp + transfer

    # ── 成交 ──
    def buy(self, code: str, date, open_px: float, target_amount: float,
            grade: str = "", rank: int = 0, pick_rank: int = 0, pool: int = 0,
            score: float | None = None) -> Fill | None:
        """以 open_px(hfq) 上浮滑点买入，目标金额取整手；资金/整手不足→不成交（返回 None）。"""
        price = open_px * (1 + self.cost.slippage)
        if price <= 0:
            return None
        # 整手取整，且预留费用空间（用粗略上限：gross×(1+rate)+min）
        raw_shares = int(target_amount // price)
        shares = (raw_shares // self.lot_size) * self.lot_size
        # 现金约束：逐步缩减直到买得起
        while shares > 0:
            gross = price * shares
            total = gross + self._buy_costs(gross)
            if total <= self.cash + 1e-6:
                break
            shares -= self.lot_size
        if shares <= 0:
            return None
        gross = price * shares
        cost = self._buy_costs(gross)
        total = gross + cost
        self.cash -= total
        if code in self.positions:  # 加仓：合并成本
            p = self.positions[code]
            p.cost_basis += total
            p.shares += shares
            p.entry_price = (p.entry_price * (p.shares - shares) + price * shares) / p.shares
        else:
            self.positions[code] = Position(
                code=code, shares=shares, entry_date=date, entry_price=price,
                cost_basis=total, grade=grade, entry_score=score, entry_rank=rank,
                entry_pick_rank=pick_rank, entry_pool=pool, last_price=open_px,
            )
        f = Fill(code, "buy", date, price, shares, gross, cost, -total)
        self.fills.append(f)
        return f

    def sell_all(self, code: str, date, open_px: float) -> Fill | None:
        """全部卖出某持仓，以 open_px(hfq) 下浮滑点。"""
        pos = self.positions.get(code)
        if not pos or pos.shares <= 0:
            return None
        price = open_px * (1 - self.cost.slippage)
        shares = pos.shares
        gross = price * shares
        cost = self._sell_costs(gross)
        proceeds = gross - cost
        self.cash += proceeds
        del self.positions[code]
        f = Fill(code, "sell", date, price, shares, gross, cost, proceeds)
        self.fills.append(f)
        return f

    # ── 估值 ──
    def mark(self, prices: dict[str, float]) -> None:
        """用当日 hfq close 更新持仓估值价（停牌无价→沿用上一次）。"""
        for code, pos in self.positions.items():
            if code in prices and prices[code] == prices[code]:  # 非 NaN
                pos.last_price = prices[code]

    def position_value(self) -> float:
        return sum(p.market_value() for p in self.positions.values())

    def equity(self) -> float:
        return self.cash + self.position_value()
