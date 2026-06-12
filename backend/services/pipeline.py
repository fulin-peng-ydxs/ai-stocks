"""一键日常流程编排（T-M7-1，SDD §13/§14）。

把全链路串成一条命令：增量更新 → 指标计算 → 打分榜单 → 预设筛选 →（可选）数据体检。
每步留痕：名称 / 状态 / 耗时 / 摘要；关键链路任一步失败即中止并返回已完成部分（可观测、可断点续跑）。

用法：DailyPipeline().run(skip_update=False, presets=True, verify=False)
CLI： python -m backend.cli daily [--skip-update] [--no-presets] [--verify]
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

    def run(self, skip_update: bool = False, presets: bool = True,
            verify: bool = False, codes: list[str] | None = None,
            top_n: int | None = None) -> dict:
        steps: list[dict] = []

        def step(name: str, fn) -> bool:
            t0 = time.time()
            try:
                detail = fn()
                steps.append({"step": name, "status": "ok",
                              "secs": round(time.time() - t0, 1), "detail": detail})
                log.info("[daily] %s ✓ %.1fs %s", name, time.time() - t0, detail)
                return True
            except Exception as e:  # noqa: BLE001
                steps.append({"step": name, "status": "failed",
                              "secs": round(time.time() - t0, 1), "detail": str(e)})
                log.error("[daily] %s ✗ %s", name, e)
                return False

        # 1. 增量更新（最慢，可跳过：数据已最新时）
        if not skip_update:
            from backend.services import IngestionService
            if not step("更新数据", lambda: IngestionService().update(codes=codes)):
                return {"ok": False, "steps": steps}

        run_date = self._latest_date()
        if run_date is None:
            steps.append({"step": "定位最新交易日", "status": "failed", "secs": 0, "detail": "无行情数据"})
            return {"ok": False, "steps": steps}

        # 2. （v2.0）指标动态实时计算，无预计算落库步骤——榜单/筛选运行时按需计算。

        from backend.services.screen_score import ScreenScoreService
        svc = ScreenScoreService(self.c)

        # 3. 打分榜单（含买点/风险信号）
        if not step("打分榜单+买点风险",
                    lambda: {"board": len(svc.rank_board(run_date, top_n=top_n,
                                                          with_signals=True, persist=True))}):
            return {"ok": False, "steps": steps}

        # 4. 预设筛选（pre-populate screen_result，供筛选页按日回看）
        if presets:
            def _run_presets():
                from backend.screening.profile import ProfileRepo
                profs = [p for p in ProfileRepo(self.c).list() if p.get("is_preset")]
                hit = {}
                for p in profs:
                    hit[p["name"]] = len(svc.run_profile(p["id"], run_date))
                return hit
            step("预设筛选", _run_presets)

        # 6. 可选：数据体检（不联网交叉验证）
        if verify:
            def _verify():
                from backend.services.data_verify import DataVerifier
                return {"passed": DataVerifier(self.c).run(cross=False)}
            step("数据体检", _verify)

        ok = all(s["status"] == "ok" for s in steps)
        log.info("[daily] 流程完成 run_date=%s ok=%s", run_date, ok)
        return {"ok": ok, "run_date": str(run_date), "steps": steps}
