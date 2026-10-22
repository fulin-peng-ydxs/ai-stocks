"""现有任务上下文的进度区间映射；日志、取消和检查点仍由原上下文维护。"""

from time import monotonic

PHASE_LABELS = {
    "daily_bar": "日线采集", "price_factor": "复权因子",
    "gap_reconcile": "日线缺口补采", "valuation_history": "历史市值补采",
    "valuation_latest": "最新日市值补采", "valuation_gap": "市值缺口补采",
    "valuation_invalid_history": "异常市值修复", "capital_review": "历史股本复查",
    "share_capital_history": "逐日股本采集", "board_dict": "板块字典",
    "board_members": "板块成分", "board_bar": "板块指数",
    "board_fund_flow": "板块资金流", "delisted_history": "退市股采集",
    "st_status": "ST 状态采集", "market_index": "市场指数采集",
    "stock_basic": "股票基础资料", "st_status_daily": "ST 逐日事实",
}


class TaskProgressScope:
    """映射子流程进度，避免嵌套采集抢占父任务的百分比或提前报告完成。

    phases 是已有处理阶段的显示权重，不控制采集顺序或执行策略。
    有阶段计数时优先使用真实计数，旧 progress 调用仅补充消息。
    """

    _LOCAL_FIELDS = frozenset({"_parent", "_start", "_end", "_ranges", "_phase", "_fraction",
                               "_last", "_sent", "_sent_at", "_phase_progress"})

    def __setattr__(self, name, value):
        if name in self._LOCAL_FIELDS:
            object.__setattr__(self, name, value)
        else:
            setattr(self._parent, name, value)

    def __init__(self, parent, start=0.0, end=1.0, *, phases=None, phase_progress=False):
        self._parent, self._start, self._end = parent, start, end
        self._phase_progress = phase_progress or phases is not None
        self._ranges = {}
        weights = phases or []
        total = sum(weight for _, weight in weights)
        offset = 0
        for phase, weight in weights:
            self._ranges[phase] = (offset / total, (offset + weight) / total)
            offset += weight
        self._phase = None
        self._fraction = None
        self._last = 0.0
        self._sent = None
        self._sent_at = 0.0

    def __getattr__(self, name):
        return getattr(self._parent, name)

    def progress(self, p, msg):
        if self._ranges and self._fraction is not None:
            p = self._fraction
        p = self._last = max(self._last, min(1.0, max(0.0, float(p))))
        mapped = round(self._start + (self._end - self._start) * p, 3)
        # 检查点仍逐对象保存，页面进度相同的千分位最多每秒更新一次消息。
        now = monotonic()
        if mapped != self._sent or now - self._sent_at >= 1:
            self._parent.progress(mapped, msg)
            self._sent, self._sent_at = mapped, now

    def set_checkpoint(self, **data):
        self._parent.set_checkpoint(**data)
        if "phase" in data:
            self._report_phase(data["phase"], data)

    def set_phase(self, phase, **data):
        self._parent.set_phase(phase, **data)
        self._report_phase(phase, data)

    def _report_phase(self, phase, data):
        if not self._phase_progress:
            return
        changed = phase != self._phase
        self._phase = phase
        total = data.get("phase_total", data.get("total"))
        done = data.get("phase_done", data.get("done"))
        if total is None or done is None:
            self._fraction = None
            return
        fraction = min(1.0, max(0.0, done / max(total, 1))) if total else 1.0
        if self._ranges:
            lo, hi = self._ranges.get(phase, (self._last, self._last))
            fraction = lo + (hi - lo) * fraction
        self._fraction = fraction
        if changed:
            self._sent = None
        label = PHASE_LABELS.get(phase, phase)
        item = data.get("current_item")
        self.progress(fraction, f"{label} {done}/{total}" + (f" · {item}" if item else ""))
