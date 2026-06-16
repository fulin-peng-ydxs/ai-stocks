"""一键日常流程编排（T-M7-1，SDD §13/§14）。

把全链路串成一条命令：更新行情（含补市值）→ 数据质检 →（可选）结构体检。
每步留痕：名称 / 状态 / 耗时 / 摘要；关键链路任一步失败即中止并返回已完成部分（可观测、可断点续跑）。

M2.9（DM-D14）：每日自动任务默认含"数据质检"步（quality=True，扫 abnormal_change/adj_jump 写台账），
使数据质量随每日流程自动监控，不再只靠手动体检。verify 仍为可选的结构/契约交叉校验。

v2.0 精简：评分榜单/预设筛选改为运行时按需计算 + 快照惰性物化（访问即算并缓存），不再在本流程
预跑落库（移除原步骤4打分榜单、步骤5预设筛选）；补市值并入 update()，不再单列步骤。

用法：DailyPipeline().run(skip_update=False, quality=True, verify=False)
CLI： python -m backend.cli daily [--skip-update] [--verify]
"""

from __future__ import annotations

import time
from datetime import date

import pandas as pd

from backend.common.logging import get_logger
from backend.storage.duckdb_client import get_client

log = get_logger("services.pipeline")


class DailyPipeline:
    def __init__(self, client=None):
        self.c = client or get_client()

    def _latest_date(self) -> date | None:
        d = self.c.query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]
        return None if pd.isna(d) else pd.Timestamp(d).date()

    def run(self, skip_update: bool = False, verify: bool = False, quality: bool = True,
            codes: list[str] | None = None, ctx=None) -> dict:
        """每日流程（v2.0 精简版）：更新行情（含补市值）→ 数据质检 →（可选）数据体检。

        评分榜单/预设筛选已改为运行时按需计算 + 快照惰性物化（榜单页/筛选页访问即算并缓存），
        不再在本流程预跑落库——故移除原步骤4（打分榜单）、步骤5（预设筛选）。
        补市值已并入 IngestionService.update()，不再单列步骤。
        """
        steps: list[dict] = []
        # 已知总步数（更新/质检），用于实时日志的"步骤 i/N"分段。
        total_steps = (1 if not skip_update else 0) + (1 if quality else 0) + (1 if verify else 0)
        idx = {"n": 0}

        def step(name: str, fn) -> bool:
            idx["n"] += 1
            if ctx:
                ctx.check_cancel()   # 步骤间响应终止
                ctx.log(f"━━━━ 步骤 {idx['n']}/{total_steps}：{name} ━━━━")
                ctx.progress(round(0.05 + 0.9 * (idx["n"] - 1) / max(total_steps, 1), 3), name)
            t0 = time.time()
            try:
                detail = fn()
                secs = round(time.time() - t0, 1)
                steps.append({"step": name, "status": "ok", "secs": secs, "detail": detail})
                log.info("[daily] %s ✓ %.1fs %s", name, secs, detail)
                if ctx:
                    ctx.log(f"步骤「{name}」完成（{secs}s）：{detail}")
                return True
            except Exception as e:  # noqa: BLE001
                secs = round(time.time() - t0, 1)
                steps.append({"step": name, "status": "failed", "secs": secs, "detail": str(e)})
                log.error("[daily] %s ✗ %s", name, e)
                if ctx:
                    ctx.log(f"步骤「{name}」失败：{e}", "error")
                return False

        # 1. 增量更新（最慢，可跳过：数据已最新时）
        if not skip_update:
            from backend.services import IngestionService
            if not step("更新数据", lambda: IngestionService().update(codes=codes, ctx=ctx)):
                return {"ok": False, "steps": steps}

        run_date = self._latest_date()
        if run_date is None:
            steps.append({"step": "定位最新交易日", "status": "failed", "secs": 0, "detail": "无行情数据"})
            return {"ok": False, "steps": steps}

        # 2. 数据质检（M2.9 DM-D14）：扫异常涨跌/复权跳变写 data_quality_issue（幂等，每日自动监控）。
        if quality:
            def _quality():
                from backend.services.data_report import DataIntegrityReport
                return DataIntegrityReport(self.c).scan_quality_issues()
            step("数据质检", _quality)

        # 评分榜单 / 预设筛选已改为运行时按需计算（快照惰性物化），不再在此预跑——见类 docstring。

        # 3. 可选：数据体检（不联网交叉验证）
        if verify:
            def _verify():
                from backend.services.data_verify import DataVerifier
                return {"passed": DataVerifier(self.c).run(cross=False)}
            step("数据体检", _verify)

        ok = all(s["status"] == "ok" for s in steps)
        log.info("[daily] 流程完成 run_date=%s ok=%s", run_date, ok)
        return {"ok": ok, "run_date": str(run_date), "steps": steps}
