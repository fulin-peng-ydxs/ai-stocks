"""采集批次收尾：合并嵌套阶段的对象范围，复用质检台账规则。"""

from __future__ import annotations

from functools import wraps
from inspect import signature

from backend.common.logging import get_logger

log = get_logger("services.collection_quality")


class CollectionQualityBatch:
    """只在编排线程登记范围；拉取线程和逐股写入不启动全套质检。"""

    def __init__(self):
        self.scopes: dict[str, set[str] | None] = {}

    def include(self, domain: str, codes) -> None:
        if codes is None:
            self.scopes[domain] = None
        elif codes:
            if domain not in self.scopes:
                self.scopes[domain] = set(codes)
            elif self.scopes[domain] is not None:
                self.scopes[domain].update(codes)

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
            if domain == "stock":
                result[domain] = report.scan_quality_issues(codes=codes, include_intraday=False)
            elif domain == "market_index":
                result[domain] = report.scan_market_index_quality(codes=codes)
            elif domain == "board":
                result[domain] = report.scan_board_quality(codes=codes)
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
        batch = CollectionQualityBatch()
        self._collection_quality_batch = batch
        try:
            result = method(self, *args, **kwargs)
            ctx = sig.bind(self, *args, **kwargs).arguments.get("ctx")
            # 质检异常直接传播：采集写入保留，异步任务失败并保留断点，不误报整个流程成功。
            quality = batch.finish(self.c, ctx)
            if isinstance(result, dict):
                result["quality"] = quality
                result["quality_scopes"] = {
                    domain: None if codes is None else sorted(codes)
                    for domain, codes in batch.scopes.items()
                }
            elif quality:
                log.info("采集收尾质检完成: %s", quality)
            return result
        finally:
            self._collection_quality_batch = None

    return run


def collection_summary(result: dict) -> dict:
    """任务提示保留计数，完整对象及逐股诊断留在结构化结果中，避免刷屏。"""
    return {key: value for key, value in result.items()
            if key not in ("quality_scopes", "diagnostics")}
