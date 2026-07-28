"""回测 API（T-M5-8，SDD §12）。

- POST /api/backtest/run     运行回测（kind=signal 信号质量 / strategy 完整策略），同步返回结果并落库。
- GET  /api/backtest/runs    历史回测任务列表。
- GET  /api/backtest/runs/{id}  某次回测详情（绩效+分层+资金曲线+逐笔）。

MVP 说明：本地单用户、DuckDB 单写锁，回测同步执行（区间数月约 10 秒级）；
异步提交+进度轮询规划 M7（与数据更新端点一致），届时前端切轮询。
"""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from backend.api.response import ApiResponse, err, ok
from backend.auth.context import get_current_context
from backend.auth.deps import require_perm, require_visibility_perm
from backend.services.asset_audit import record_asset_visibility_audit
from backend.services.asset_visibility import normalize_visibility
from backend.services.backtest_service import BacktestService

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


def _d(v) -> str | None:
    """日期字段统一格式化为 YYYY-MM-DD（去掉 DB Timestamp 的 00:00:00 时间部分）。"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return pd.Timestamp(v).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return str(v)


class BacktestRunIn(BaseModel):
    kind: str = "strategy"               # strategy（完整策略）/ score_check（评分验证）；旧值 signal 兼容
    date_start: str
    date_end: str
    profile_id: str | None = None        # 选股=筛选方案（strategy 候选池）
    score_profile_id: str | None = None  # 评分规则方案（strategy 排序 / score_check 验证）
    trade_profile_id: str | None = None  # 买卖指标方案（strategy 的买/卖/兜底）
    top_n: int | None = None
    initial_capital: float | None = None
    sell_ma_period: int | None = None    # 兜底：无 trade_profile 时的旧式跌破MA卖出
    max_hold_days: int | None = None
    take_profit: float | None = None
    stop_loss: float | None = None
    rebalance_days: int | None = None
    industry_max_pct: float | None = None
    benchmark: str | None = None
    horizons: list[int] | None = None
    thresholds: list[float] | None = None
    source_run_ref: str | None = None      # 复用公开历史参数重跑，仅用于留痕/审计，不参与回测撮合


class RunVisibilityBody(BaseModel):
    visibility: str

    @field_validator("visibility", mode="before")
    @classmethod
    def _normalize_visibility(cls, value):
        if value is None:
            raise ValueError("visibility 必须是 private、tenant 或 public")
        return normalize_visibility(str(value))


def _has_perm(code: str) -> bool:
    ctx = get_current_context()
    if ctx is None:
        return False
    return ctx.is_system or code in ctx.resources


@router.post("/run", response_model=ApiResponse,
             dependencies=[Depends(require_perm("backtest:run"))])
def run_backtest(body: BacktestRunIn) -> ApiResponse:
    params = {k: v for k, v in body.model_dump().items() if v is not None and k != "kind"}
    svc = BacktestService()
    try:
        if body.kind in ("signal", "score_check"):
            return ok(svc.run_signal(params))  # 落库进历史（同条件覆盖，唯一）
        return ok(svc.run_strategy(params))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/prepare", response_model=ApiResponse,
             dependencies=[Depends(require_perm("backtest:run"))])
def prepare_backtest(body: BacktestRunIn) -> ApiResponse:
    """运行前查重：返回签名 + 同条件已完成历史（前端据此弹框：加载历史 / 重新回测覆盖）。"""
    params = {k: v for k, v in body.model_dump().items() if v is not None and k != "kind"}
    kind = "score_check" if body.kind in ("signal", "score_check") else "strategy"
    try:
        return ok(BacktestService().prepare(kind, params))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e)) from e


_ROBUST_PARAMS = {"top_n", "stop_loss", "take_profit", "max_hold_days", "rebalance_days", "industry_max_pct"}


class RobustIn(BaseModel):
    mode: str = "param_sweep"            # param_sweep（参数敏感性）/ in_out_sample（样本内外）
    params: dict                          # 基准策略回测参数（同 /run，含 date_start/date_end/方案 id 等）
    param: str | None = None              # param_sweep：要扫的参数名
    values: list | None = None            # param_sweep：取值列表
    split_date: str | None = None         # in_out_sample：切分日


@router.post("/robust", response_model=ApiResponse,
             dependencies=[Depends(require_perm("backtest:robust"))])
def robust(body: RobustIn) -> ApiResponse:
    """稳健性测试（即跑即看，不落历史）：参数敏感性扫描 / 样本内外切分。"""
    from backend.backtest.robustness import RobustnessAnalyzer
    ra = RobustnessAnalyzer()
    try:
        if body.mode == "in_out_sample":
            if not body.split_date:
                raise ValueError("样本内外需提供 split_date")
            return ok(ra.in_out_sample(body.params, body.split_date))
        if body.param not in _ROBUST_PARAMS:
            raise ValueError(f"不支持扫描的参数: {body.param}（可选 {sorted(_ROBUST_PARAMS)}）")
        if not body.values:
            raise ValueError("param_sweep 需提供 values")
        return ok(ra.param_sweep(body.params, body.param, body.values))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/runs", response_model=ApiResponse,
            dependencies=[Depends(require_perm("backtest:view"))])
def list_runs(
    limit: int | None = Query(None, ge=1),   # 有 q 时 Python 切片、无 q 时 SQL LIMIT，负值/0 两路语义不一致，统一 ge=1
    kind: str | None = None,
    source: str | None = None,
    q: str | None = None,
) -> ApiResponse:
    if source not in (None, "mine", "tenant", "public"):
        return err(400, "source 必须是 mine、tenant 或 public")
    # 回测无系统内置段（无 is_preset）：搜索弹窗仅 tenant/public；q 按三类引用方案名 + kind 过滤
    runs = BacktestService().list_runs(limit, kind=kind, source=source, q=q)

    def _nan_none(v):
        return None if v is None or (isinstance(v, float) and pd.isna(v)) else v

    for r in runs:
        r["date_start"] = _d(r.get("date_start"))
        r["date_end"] = _d(r.get("date_end"))
        if r.get("created_at") is not None:
            r["created_at"] = str(r["created_at"])
        if r.get("published_at") is not None:
            r["published_at"] = str(r["published_at"])
        tr = _nan_none(r.get("total_return"))
        r["total_return"] = float(tr) if tr is not None else None
        for k in ("profile_name", "trade_profile_name", "score_profile_name"):
            r[k] = _nan_none(r.get(k))
        for k in ("profile_version", "trade_profile_version", "score_profile_version"):
            v = _nan_none(r.get(k))
            r[k] = int(v) if v is not None else None
    return ok({"runs": runs})


@router.post("/runs/{run_id}/visibility", response_model=ApiResponse,
             dependencies=[Depends(require_visibility_perm(
                 "backtest:view",
                 "backtest:publish-tenant",
                 "backtest:publish-public",
             ))])
def set_run_visibility(run_id: str, body: RunVisibilityBody) -> ApiResponse:
    visibility = body.visibility
    if visibility == "tenant" and not _has_perm("backtest:publish-tenant"):
        return err(403, "无权公开到租户")
    if visibility == "public" and not _has_perm("backtest:publish-public"):
        return err(403, "无权公开到全体用户")
    svc = BacktestService()
    before = svc._visible_run_row(run_id, include_owner=True)
    if not before:
        return err(404, "回测任务不存在")
    ctx = get_current_context()
    try:
        after = svc.set_run_visibility(
            run_id,
            visibility,
            published_by=ctx.user_id if ctx is not None else None,
        )
    except ValueError as e:
        return err(400, str(e))
    except PermissionError as e:
        return err(403, str(e))
    if not after:
        return err(404, "回测任务不存在")
    record_asset_visibility_audit(
        before,
        after,
        action="backtest_run_visibility",
        target_type="backtest_run",
        ref_key="run_ref",
        fallback_resource_prefix="backtest",
    )
    return ok(after)


@router.get("/runs/{run_id}", response_model=ApiResponse,
            dependencies=[Depends(require_perm("backtest:view"))])
def get_run(run_id: str) -> ApiResponse:
    res = BacktestService().get_run(run_id)
    if res is None:
        raise HTTPException(status_code=404, detail="回测任务不存在")
    # 序列化日期/时间（date 字段统一 YYYY-MM-DD，避免前端日期匹配失败）
    run = res["run"]
    run["date_start"] = _d(run.get("date_start"))
    run["date_end"] = _d(run.get("date_end"))
    for k in ("created_at", "finished_at"):
        if run.get(k) is not None:
            run[k] = str(run[k])
    if run.get("published_at") is not None:
        run["published_at"] = str(run["published_at"])
    for row in res["equity"]:
        row["trade_date"] = _d(row.get("trade_date"))
    for t in res["trades"]:
        t["entry_date"] = _d(t.get("entry_date"))
        t["exit_date"] = _d(t.get("exit_date"))
    return ok(res)


@router.delete("/runs/{run_id}", response_model=ApiResponse,
               dependencies=[Depends(require_perm("backtest:delete"))])
def delete_run(run_id: str) -> ApiResponse:
    try:
        found = BacktestService().delete_run(run_id)
    except PermissionError as e:
        return err(403, str(e))
    if not found:
        raise HTTPException(status_code=404, detail="回测任务不存在")
    return ok({"deleted": run_id})
