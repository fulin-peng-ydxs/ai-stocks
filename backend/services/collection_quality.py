"""采集批次收尾：合并嵌套阶段的对象范围，复用质检台账规则。"""

from __future__ import annotations

from functools import wraps
from inspect import signature

from backend.common.logging import get_logger
from backend.services.task_progress import TaskProgressScope

log = get_logger("services.collection_quality")


class CollectionQualityBatch:
    """只在编排线程登记范围；拉取线程和逐股写入不启动全套质检。"""

    def __init__(self, ctx=None):
        self.scopes: dict[str, set[str] | None] = {}
        self.ctx = ctx

    def include(self, domain: str, codes) -> None:
        if codes is None:
            self.scopes[domain] = None
        elif codes:
            if domain not in self.scopes:
                self.scopes[domain] = set(codes)
            elif self.scopes[domain] is not None:
                self.scopes[domain].update(codes)
        if self.ctx and hasattr(self.ctx, "set_checkpoint"):
            current = self.payload()
            if current != self.ctx.checkpoint.get("collection_quality_pending", {}):
                self.ctx.set_checkpoint(collection_quality_pending=current)

    def payload(self):
        return {domain: None if codes is None else sorted(codes)
                for domain, codes in self.scopes.items()}

    def finish(self, client, ctx=None) -> dict:
        """使用落库事实检查；源请求失败本身不转换为数据质量问题。"""
        from backend.services.data_report import DataIntegrityReport

        report = DataIntegrityReport(client)
        result = {}
        for index, (domain, scope) in enumerate(self.scopes.items()):
            label = {"stock": "个股", "market_index": "市场指数", "board": "板块"}.get(domain, domain)
            if ctx:
                ctx.check_cancel()
                ctx.set_phase("validate", phase_total=len(self.scopes), phase_done=index,
                              current_item=f"采集收尾质检：{label}")
                ctx.log(f"采集收尾质检：{label}，{'全量' if scope is None else str(len(scope)) + ' 个对象'}")
                ctx.flush()
            codes = None if scope is None else sorted(scope)
            progress = None
            if ctx and hasattr(ctx, "progress"):
                def progress(p, message, index=index, label=label):
                    ctx.progress((index + p) / max(len(self.scopes), 1),
                                 f"采集收尾质检：{label} · {message}")
            kwargs = {"progress": progress} if progress else {}
            if domain == "stock":
                result[domain] = report.scan_quality_issues(
                    codes=codes, include_intraday=False, **kwargs)
            elif domain == "market_index":
                result[domain] = report.scan_market_index_quality(codes=codes, **kwargs)
            elif domain == "board":
                result[domain] = report.scan_board_quality(codes=codes, **kwargs)
            else:
                raise ValueError(f"未知采集质检范围: {domain}")
        return result


def include_collection_scope(service, domain: str, codes) -> None:
    """登记已解析的采集计划，包含失败及断点跳过对象，空计划不触发全量扫描。"""
    batch = getattr(service, "_collection_quality_batch", None)
    if batch is not None:
        batch.include(domain, codes)


def checked_collection(method):
    """公开批次入口统一收尾；嵌套调用合并，异常/取消不发布成功收尾。"""
    sig = signature(method)

    @wraps(method)
    def run(self, *args, **kwargs):
        if getattr(self, "_collection_quality_batch", None) is not None:
            return method(self, *args, **kwargs)
        bound = sig.bind(self, *args, **kwargs)
        ctx = bound.arguments.get("ctx")
        batch = CollectionQualityBatch(ctx)
        self._collection_quality_batch = batch
        try:
            # 只检查同一任务留下的原始范围。先收敛已落库事实，再让采集按原断点跳过网络。
            pending = (getattr(ctx, "checkpoint", {}) or {}).get("collection_quality_pending", {})
            for domain, codes in pending.items():
                batch.include(domain, codes)
            if pending:
                ctx.log("续跑：先复检中断前已登记的采集范围，再继续未完成取数")
                batch.finish(self.c, TaskProgressScope(ctx, 0.05, 0.08))
                # 补偿成功后，当前批次在写入前重新登记自己的范围，不能把上一子流程的
                # 域冒充为本批次的检查成果（例如日常流程由板块中断后从日线入口续跑）。
                batch.scopes.clear()
                ctx.set_checkpoint(collection_quality_pending={})
            if ctx and hasattr(ctx, "set_checkpoint") and hasattr(ctx, "progress"):
                phases = collection_phases(method.__name__, bound.arguments)
                bound.arguments["ctx"] = TaskProgressScope(
                    ctx, 0.08, 0.90, phases=phases, phase_progress=True)
            result = method(*bound.args, **bound.kwargs)
            # 质检异常直接传播：采集写入保留，异步任务失败并保留断点，不误报整个流程成功。
            quality = batch.finish(self.c, TaskProgressScope(ctx, 0.90, 0.99)
                                   if ctx and hasattr(ctx, "progress") else ctx)
            if ctx and hasattr(ctx, "set_checkpoint"):
                ctx.set_checkpoint(collection_quality_pending={})
            if isinstance(result, dict):
                result["quality"] = quality
                result["quality_scopes"] = batch.payload()
            elif quality:
                log.info("采集收尾质检完成: %s", quality)
            return result
        finally:
            self._collection_quality_batch = None

    return run


def collection_phases(method, arguments):
    """显示权重预留收尾区间，复用已有阶段，不增加执行阶段或配置参数。"""
    if method == "ingest_board":
        from backend.services.board_ingest import BOARD_INGEST_STAGES, normalize_board_stages
        names = {"dict": "board_dict", "members": "board_members",
                 "bar": "board_bar", "fund": "board_fund_flow"}
        steps = normalize_board_stages(arguments.get("only"))
        return [(names[step], 1) for step in (BOARD_INGEST_STAGES if steps is None else steps)]
    if method == "update":
        return [("daily_bar", 12), ("gap_reconcile", 1), ("price_factor", 1),
                ("valuation_latest", 1), ("valuation_history", 1), ("capital_review", 1)]
    if method in ("backfill", "ingest_date"):
        return [("daily_bar", 9), ("price_factor", 1)]
    return None


def collection_summary(result: dict) -> dict:
    """任务提示保留计数，完整对象及逐股诊断留在结构化结果中，避免刷屏。"""
    return {key: value for key, value in result.items()
            if key not in ("quality_scopes", "diagnostics")}
