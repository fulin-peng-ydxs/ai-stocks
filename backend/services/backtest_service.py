"""回测编排服务（T-M5-8，SDD §10.6）——跑回测、算绩效+分层、落库。

两种 kind：
  - signal  ：信号质量分析（SignalAnalyzer）——分档命中率 vs base rate（核心概率口径）。
  - strategy：完整事件驱动策略回测（BacktestEngine）——资金曲线+绩效，并附带同区间分层分析。

落库：backtest_run（任务）/backtest_equity（曲线）/backtest_trade（逐笔）/backtest_metrics（绩效+分层JSON）。

混合持久层（stage1·T2）：
- 回测结果四表 + 方案三表均为**用户资产**，全部在 PG（self.pg，%s + 归属过滤；批量写 self.assets）。
  list_runs 的「run⋈三方案⋈metrics」JOIN 全在 PG 内，无跨库。
- 计算引擎（BacktestEngine/SignalAnalyzer/IndicatorEngine）读行情走 DuckDB（self.c）。
- 归属：auth 未落地前默认 default/admin；第一位参保留为 market(DuckDB) 兼容历史调用。
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pandas as pd

from backend.backtest.engine import BacktestEngine
from backend.backtest.metrics import compute_metrics
from backend.backtest.signal import SignalAnalyzer
from backend.common.logging import get_logger
from backend.storage.asset_repository import AssetRepository
from backend.storage.duckdb_client import get_client
from backend.storage.pg_client import get_pg_client
from backend.auth.context import get_current_owner

log = get_logger("services.backtest")


class BacktestService:
    def __init__(self, client=None, *, tenant_id: str | None = None,
                 owner_user_id: str | None = None):
        self.c = client or get_client()                  # 行情库（DuckDB），喂计算引擎
        from backend.storage.ddl import init_db
        init_db(self.c)
        _ctx_t, _ctx_o = get_current_owner()
        self.tenant_id = tenant_id or _ctx_t
        self.owner_user_id = owner_user_id or _ctx_o
        self.pg = get_pg_client()                        # 资产库（PG）
        self.assets = AssetRepository(self.pg, tenant_id=self.tenant_id,
                                      owner_user_id=self.owner_user_id)

    @property
    def _op(self) -> list:
        return [self.tenant_id, self.owner_user_id]

    def _new_id(self, kind: str) -> str:
        return f"bt_{kind}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    def _persist_run(self, run_id: str, kind: str, params: dict, status: str,
                     detail: str = "", finished: bool = False,
                     versions: dict | None = None, signature: str | None = None) -> None:
        v = versions or {}
        self.pg.execute(
            "DELETE FROM backtest_run WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
            [run_id, *self._op])
        self.pg.execute(
            "INSERT INTO backtest_run (id, tenant_id, owner_user_id, kind, profile_id, model_id, "
            "score_profile_id, trade_profile_id, score_profile_version, profile_version, "
            "trade_profile_version, signature, date_start, date_end, params, status, detail, "
            "created_at, finished_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [run_id, self.tenant_id, self.owner_user_id, kind, params.get("profile_id"),
             params.get("model_id", "default"),
             params.get("score_profile_id"), params.get("trade_profile_id"),
             v.get("score_profile_version"), v.get("profile_version"), v.get("trade_profile_version"), signature,
             date.fromisoformat(params["date_start"]) if isinstance(params["date_start"], str) else params["date_start"],
             date.fromisoformat(params["date_end"]) if isinstance(params["date_end"], str) else params["date_end"],
             json.dumps(params, ensure_ascii=False, default=str), status, detail,
             datetime.now(), datetime.now() if finished else None],
        )

    # ── 版本解析 + 去重签名（全条件一致则同一记录，唯一）──
    _SIG_KEYS = ["date_start", "date_end", "profile_id", "score_profile_id", "trade_profile_id",
                 "top_n", "initial_capital", "sell_ma_period", "max_hold_days", "take_profit",
                 "stop_loss", "rebalance_days", "industry_max_pct", "benchmark", "horizons", "thresholds"]

    def _visible_score_profile(self, profile_ref_or_id: str | None) -> dict | None:
        if not profile_ref_or_id:
            return None
        from backend.scoring.score_profile import ScoreProfileRepo

        return ScoreProfileRepo(market=self.c, pg=self.pg, tenant_id=self.tenant_id,
                                owner_user_id=self.owner_user_id).get_visible(
                                    profile_ref_or_id,
                                    include_owner=True,
                                )

    def _resolve_versions(self, params: dict) -> dict:
        """运行时解析各引用方案的当前版本（命名展示 + 签名用）。方案在 PG。"""
        out: dict = {}
        score_profile = self._visible_score_profile(params.get("score_profile_id"))
        if score_profile:
            out["score_profile_version"] = int(score_profile["version"])
        elif params.get("score_profile_id"):
            out["score_profile_version"] = None
        for pid_key, tbl, vk in (("profile_id", "screen_profile", "profile_version"),
                                 ("trade_profile_id", "trade_profile", "trade_profile_version")):
            if params.get(pid_key):
                df = self.pg.query_df(
                    f"SELECT version FROM {tbl} WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
                    [params[pid_key], *self._op])
                out[vk] = int(df.iloc[0]["version"]) if not df.empty else None
        return out

    def _signature(self, kind: str, params: dict, versions: dict) -> str:
        import hashlib
        payload: dict = {"kind": "strategy" if kind == "strategy" else "score_check"}
        for k in self._SIG_KEYS:
            val = params.get(k)
            if val is not None:
                payload[k] = str(val) if k in ("date_start", "date_end") else val
        payload.update({k: versions.get(k) for k in sorted(versions)})
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()

    def find_duplicate(self, signature: str) -> dict | None:
        """同签名且已完成的历史记录（覆盖语义下至多一条）。"""
        df = self.pg.query_df(
            "SELECT id, kind, date_start, date_end, created_at FROM backtest_run "
            "WHERE signature=%s AND status='done' AND tenant_id=%s AND owner_user_id=%s "
            "ORDER BY created_at DESC LIMIT 1", [signature, *self._op])
        if df.empty:
            return None
        r = df.iloc[0]
        return {"run_id": r["id"], "kind": r["kind"],
                "date_start": str(r["date_start"])[:10], "date_end": str(r["date_end"])[:10],
                "created_at": str(r["created_at"])}

    def prepare(self, kind: str, params: dict) -> dict:
        """运行前预备：解析版本 + 算签名 + 查同条件历史（供前端弹框询问加载/重跑）。"""
        versions = self._resolve_versions(params)
        sig = self._signature(kind, params, versions)
        return {"signature": sig, "versions": versions, "duplicate": self.find_duplicate(sig)}

    def _purge_signature(self, signature: str | None) -> None:
        """覆盖语义：删除同签名旧记录（含曲线/逐笔/绩效），保证每个条件组合历史唯一。"""
        if not signature:
            return
        old = self.pg.query_df(
            "SELECT id FROM backtest_run WHERE signature=%s AND tenant_id=%s AND owner_user_id=%s",
            [signature, *self._op])
        for rid in old["id"].tolist():
            self.delete_run(rid)

    def _load_score_profile(self, params: dict) -> dict | None:
        if not params.get("score_profile_id"):
            return None
        return self._visible_score_profile(params["score_profile_id"])

    # ── 评分验证（信号质量分析）──
    def run_signal(self, params: dict, persist: bool = True) -> dict:
        run_id = self._new_id("score_check")
        versions = self._resolve_versions(params)
        sig = self._signature("score_check", params, versions)
        if persist:
            self._purge_signature(sig)  # 覆盖同条件旧记录（唯一）
            self._persist_run(run_id, "score_check", params, "running", versions=versions, signature=sig)
        try:
            res = SignalAnalyzer(self.c).analyze(
                date.fromisoformat(params["date_start"]) if isinstance(params["date_start"], str) else params["date_start"],
                date.fromisoformat(params["date_end"]) if isinstance(params["date_end"], str) else params["date_end"],
                horizons=params.get("horizons"), thresholds=params.get("thresholds"),
                min_samples=params.get("min_samples", 30),
                score_profile=self._load_score_profile(params),
            )
            res["run_id"] = run_id
            if persist:
                self.assets.upsert("backtest_metrics", pd.DataFrame([{
                    "run_id": run_id, "hit_rate_by_grade": json.dumps(res, ensure_ascii=False),
                }]))
                self._persist_run(run_id, "score_check", params, "done", finished=True,
                                  versions=versions, signature=sig)
            return res
        except Exception as e:  # noqa: BLE001
            if persist:
                self._persist_run(run_id, "score_check", params, "failed", detail=str(e), finished=True,
                                  versions=versions, signature=sig)
            raise

    # ── 完整策略回测 ──
    def run_strategy(self, params: dict, persist: bool = True) -> dict:
        run_id = self._new_id("strategy")
        versions = self._resolve_versions(params)
        sig = self._signature("strategy", params, versions)
        if persist:
            self._purge_signature(sig)  # 覆盖同条件旧记录（唯一）
            self._persist_run(run_id, "strategy", params, "running", versions=versions, signature=sig)
        try:
            # 共享一个 IndicatorEngine：策略回测与分层分析复用同一区间快照缓存（性能：避免重算）
            from backend.indicators.engine import IndicatorEngine
            shared_ind = IndicatorEngine(self.c)
            out = BacktestEngine(self.c, ind=shared_ind).run(params)
            if "error" in out:
                if persist:
                    self._persist_run(run_id, "strategy", params, "failed", detail=out["error"], finished=True,
                                      versions=versions, signature=sig)
                return {"run_id": run_id, **out}
            eq = out["equity"]
            metrics = compute_metrics(
                eq.set_index("trade_date")["equity"],
                eq.set_index("trade_date")["benchmark_equity"] if "benchmark_equity" in eq else None,
                out["trades"],
            )
            # 分层（同区间信号质量），附在 metrics 里
            layers = SignalAnalyzer(self.c, ind=shared_ind).analyze(
                date.fromisoformat(params["date_start"]) if isinstance(params["date_start"], str) else params["date_start"],
                date.fromisoformat(params["date_end"]) if isinstance(params["date_end"], str) else params["date_end"],
                horizons=params.get("horizons"), thresholds=params.get("thresholds"),
                score_profile=self._load_score_profile(params),
            )
            result = {"run_id": run_id, "metrics": metrics, "layers": layers,
                      "trades": out["trades"], "equity": eq.to_dict("records"),
                      "benchmark_code": out["benchmark_code"], "initial_capital": out["initial_capital"]}
            if persist:
                self._persist(run_id, eq, out["trades"], metrics, layers)
                self._persist_run(run_id, "strategy", params, "done", finished=True,
                                  versions=versions, signature=sig)
            return result
        except Exception as e:  # noqa: BLE001
            if persist:
                self._persist_run(run_id, "strategy", params, "failed", detail=str(e), finished=True,
                                  versions=versions, signature=sig)
            raise

    def _persist(self, run_id: str, eq: pd.DataFrame, trades: list[dict],
                 metrics: dict, layers: dict) -> None:
        self.pg.execute(
            "DELETE FROM backtest_equity WHERE run_id=%s AND tenant_id=%s AND owner_user_id=%s",
            [run_id, *self._op])
        self.pg.execute(
            "DELETE FROM backtest_trade WHERE run_id=%s AND tenant_id=%s AND owner_user_id=%s",
            [run_id, *self._op])
        eq2 = eq.copy()
        eq2.insert(0, "run_id", run_id)
        self.assets.upsert("backtest_equity", eq2)
        if trades:
            td = pd.DataFrame(trades)
            td.insert(0, "run_id", run_id)
            self.assets.upsert("backtest_trade", td)
        row = {"run_id": run_id, **{k: v for k, v in metrics.items()},
               "hit_rate_by_grade": json.dumps(layers, ensure_ascii=False), "extra": None}
        self.assets.upsert("backtest_metrics", pd.DataFrame([row]))

    def delete_run(self, run_id: str) -> bool:
        """删除某次回测的全部数据（run + equity + trade + metrics）。"""
        exists = self.pg.query_df(
            "SELECT 1 FROM backtest_run WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
            [run_id, *self._op])
        for t in ("backtest_trade", "backtest_equity", "backtest_metrics", "backtest_run"):
            self.pg.execute(
                f"DELETE FROM {t} WHERE run_id=%s AND tenant_id=%s AND owner_user_id=%s"
                if t != "backtest_run" else
                f"DELETE FROM {t} WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
                [run_id, *self._op])
        return not exists.empty

    # ── 读取 ──
    def list_runs(self, limit: int | None = None, kind: str | None = None) -> list[dict]:
        """历史记录。kind 给定则只列该类（strategy / score_check），策略与评分验证不混展；
        limit=None 则全列（不截断），同签名因覆盖语义本就只留一条。run⋈三方案⋈metrics 全在 PG。"""
        where = "WHERE r.tenant_id=%s AND r.owner_user_id=%s "
        args: list = [*self._op]
        if kind == "score_check":
            where += "AND r.kind IN ('score_check','signal') "  # 兼容旧 signal 值
        elif kind == "strategy":
            where += "AND r.kind = 'strategy' "
        tail = ""
        if limit is not None:
            tail = "LIMIT %s"
            args = [*args, limit]
        df = self.pg.query_df(
            "SELECT r.id, r.kind, r.profile_id, p.name AS profile_name, r.profile_version, "
            "       r.trade_profile_id, tp.name AS trade_profile_name, r.trade_profile_version, "
            "       r.score_profile_id, sp.name AS score_profile_name, r.score_profile_version, "
            "       r.date_start, r.date_end, r.status, r.created_at, m.total_return "
            # JOIN 必须带归属：复合主键下同一业务 id 可属不同 owner，只按 id JOIN 会串其他 owner 的行
            "FROM backtest_run r "
            "LEFT JOIN screen_profile p ON p.id = r.profile_id "
            "  AND p.tenant_id = r.tenant_id AND p.owner_user_id = r.owner_user_id "
            "LEFT JOIN trade_profile tp ON tp.id = r.trade_profile_id "
            "  AND tp.tenant_id = r.tenant_id AND tp.owner_user_id = r.owner_user_id "
            "LEFT JOIN score_profile sp ON sp.id = r.score_profile_id "
            "  AND sp.tenant_id = r.tenant_id AND sp.owner_user_id = r.owner_user_id "
            "LEFT JOIN backtest_metrics m ON m.run_id = r.id "
            "  AND m.tenant_id = r.tenant_id AND m.owner_user_id = r.owner_user_id "
            f"{where}"
            f"ORDER BY r.created_at DESC {tail}", args)
        rows = df.to_dict("records")
        for row in rows:
            if row.get("score_profile_id") and not row.get("score_profile_name"):
                prof = self._visible_score_profile(row["score_profile_id"])
                if prof:
                    row["score_profile_name"] = prof["name"]
                    row["score_profile_version"] = int(prof["version"])
        return rows

    def get_run(self, run_id: str) -> dict | None:
        run = self.pg.query_df(
            "SELECT * FROM backtest_run WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
            [run_id, *self._op])
        if run.empty:
            return None
        m = self.pg.query_df(
            "SELECT * FROM backtest_metrics WHERE run_id=%s AND tenant_id=%s AND owner_user_id=%s",
            [run_id, *self._op])
        eq = self.pg.query_df(
            "SELECT * FROM backtest_equity WHERE run_id=%s AND tenant_id=%s AND owner_user_id=%s "
            "ORDER BY trade_date", [run_id, *self._op])
        td = self.pg.query_df(
            "SELECT * FROM backtest_trade WHERE run_id=%s AND tenant_id=%s AND owner_user_id=%s "
            "ORDER BY seq", [run_id, *self._op])
        metrics = m.iloc[0].to_dict() if not m.empty else {}
        for _k in ("tenant_id", "owner_user_id"):
            metrics.pop(_k, None)
        layers = json.loads(metrics.pop("hit_rate_by_grade")) if metrics.get("hit_rate_by_grade") else None
        run_d = run.iloc[0].to_dict()
        for _k in ("tenant_id", "owner_user_id"):
            run_d.pop(_k, None)
        return {"run": run_d, "metrics": metrics, "layers": layers,
                "equity": eq.to_dict("records"), "trades": td.to_dict("records")}
