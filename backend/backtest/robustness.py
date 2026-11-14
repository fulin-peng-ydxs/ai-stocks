"""稳健性测试（T-M7-4，SDD §10.5）。

回答"结果是否稳健、是否过拟合"：
  - 参数敏感性：固定其它参数，扫一个参数的多个取值，看绩效是否平滑（而非靠某个魔法值）。
  - 样本内外切分：把区间一分为二，分别回测，看样本外是否仍成立（防过拟合）。
  - 对照组：每次回测已含同期基准（中证500）作"全市场"对照，超额即相对对照的优势。

复用 `BacktestService.run_strategy(persist=False)`，不污染历史。
"""

from __future__ import annotations

from backend.common.logging import get_logger
from backend.services.backtest_service import BacktestService

log = get_logger("backtest.robustness")

_KEYS = ("total_return", "annual_return", "max_drawdown", "sharpe",
         "win_rate", "n_trades", "benchmark_return", "excess_return")


class RobustnessAnalyzer:
    def __init__(self, client=None):
        self.svc = BacktestService(client)

    def _metrics(self, params: dict) -> dict:
        r = self.svc.run_strategy(params, persist=False)
        m = r.get("metrics", {})
        return {k: m.get(k) for k in _KEYS}

    def param_sweep(self, base_params: dict, param: str, values: list) -> dict:
        """扫描单参数多取值，返回 {param: 值, rows: [{value, <metrics>}]}。"""
        rows = []
        for v in values:
            p = {**base_params, param: v}
            log.info("[robust] 参数敏感性 %s=%s", param, v)
            rows.append({"value": v, **self._metrics(p)})
        return {"param": param, "values": values, "rows": rows}

    def in_out_sample(self, params: dict, split_date: str) -> dict:
        """样本内（start~split）/样本外（split~end）分别回测，对比防过拟合。"""
        ins = {**params, "date_end": split_date}
        oos = {**params, "date_start": split_date}
        log.info("[robust] 样本内 %s~%s / 样本外 %s~%s",
                 params["date_start"], split_date, split_date, params["date_end"])
        return {"split": split_date,
                "in_sample": {"range": [params["date_start"], split_date], **self._metrics(ins)},
                "out_sample": {"range": [split_date, params["date_end"]], **self._metrics(oos)}}
