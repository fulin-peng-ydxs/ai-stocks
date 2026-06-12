"""回测编排服务（T-M5-8，SDD §10.6）——跑回测、算绩效+分层、落库。

两种 kind：
  - signal  ：信号质量分析（SignalAnalyzer）——分档命中率 vs base rate（核心概率口径）。
  - strategy：完整事件驱动策略回测（BacktestEngine）——资金曲线+绩效，并附带同区间分层分析。

落库：backtest_run（任务）/backtest_equity（曲线）/backtest_trade（逐笔）/backtest_metrics（绩效+分层JSON）。
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pandas as pd

from backend.backtest.engine import BacktestEngine
from backend.backtest.metrics import compute_metrics
from backend.backtest.signal import SignalAnalyzer
from backend.common.logging import get_logger
from backend.storage.duckdb_client import get_client
from backend.storage.repository import MarketRepository

log = get_logger("services.backtest")


class BacktestService:
    def __init__(self, client=None):
        self.c = client or get_client()
        from backend.storage.ddl import init_db
        init_db(self.c)
        self.repo = MarketRepository(self.c)

    def _new_id(self, kind: str) -> str:
        return f"bt_{kind}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    def _persist_run(self, run_id: str, kind: str, params: dict, status: str,
                     detail: str = "", finished: bool = False,
                     versions: dict | None = None, signature: str | None = None) -> None:
        v = versions or {}
        self.c.execute("DELETE FROM backtest_run WHERE id = ?", [run_id])
        self.c.execute(
            "INSERT INTO backtest_run (id, kind, profile_id, model_id, score_profile_id, trade_profile_id, "
            "score_profile_version, profile_version, trade_profile_version, signature, "
            "date_start, date_end, params, status, detail, created_at, finished_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [run_id, kind, params.get("profile_id"), params.get("model_id", "default"),
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

    def _resolve_versions(self, params: dict) -> dict:
        """运行时解析各引用方案的当前版本（命名展示 + 签名用）。"""
        out: dict = {}
        for pid_key, tbl, vk in (("score_profile_id", "score_profile", "score_profile_version"),
                                 ("profile_id", "screen_profile", "profile_version"),
                                 ("trade_profile_id", "trade_profile", "trade_profile_version")):
            if params.get(pid_key):
                df = self.c.query_df(f"SELECT version FROM {tbl} WHERE id=?", [params[pid_key]])
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
        df = self.c.query_df(
            "SELECT id, kind, date_start, date_end, created_at FROM backtest_run "
            "WHERE signature = ? AND status = 'done' ORDER BY created_at DESC LIMIT 1", [signature])
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
        old = self.c.query_df("SELECT id FROM backtest_run WHERE signature = ?", [signature])
        for rid in old["id"].tolist():
            self.delete_run(rid)

    def _load_score_profile(self, params: dict) -> dict | None:
        if not params.get("score_profile_id"):
            return None
        from backend.scoring.score_profile import ScoreProfileRepo
        return ScoreProfileRepo(self.c).get(params["score_profile_id"])

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
                self.repo.upsert("backtest_metrics", pd.DataFrame([{
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
        self.c.execute("DELETE FROM backtest_equity WHERE run_id = ?", [run_id])
        self.c.execute("DELETE FROM backtest_trade WHERE run_id = ?", [run_id])
        eq2 = eq.copy()
        eq2.insert(0, "run_id", run_id)
        self.repo.upsert("backtest_equity", eq2)
        if trades:
            td = pd.DataFrame(trades)
            td.insert(0, "run_id", run_id)
            self.repo.upsert("backtest_trade", td)
        row = {"run_id": run_id, **{k: v for k, v in metrics.items()},
               "hit_rate_by_grade": json.dumps(layers, ensure_ascii=False), "extra": None}
        self.repo.upsert("backtest_metrics", pd.DataFrame([row]))

    def delete_run(self, run_id: str) -> bool:
        """删除某次回测的全部数据（run + equity + trade + metrics）。"""
        exists = self.c.query_df("SELECT 1 FROM backtest_run WHERE id = ?", [run_id])
        self.c.execute("DELETE FROM backtest_trade WHERE run_id = ?", [run_id])
        self.c.execute("DELETE FROM backtest_equity WHERE run_id = ?", [run_id])
        self.c.execute("DELETE FROM backtest_metrics WHERE run_id = ?", [run_id])
        self.c.execute("DELETE FROM backtest_run WHERE id = ?", [run_id])
        return not exists.empty

    # ── 读取 ──
    def list_runs(self, limit: int = 50, kind: str | None = None) -> list[dict]:
        """历史记录。kind 给定则只列该类（strategy / score_check），策略与评分验证不混展。"""
        where, args = "", []
        if kind == "score_check":
            where = "WHERE r.kind IN ('score_check','signal') "  # 兼容旧 signal 值
        elif kind == "strategy":
            where = "WHERE r.kind = 'strategy' "
        df = self.c.query_df(
            "SELECT r.id, r.kind, r.profile_id, p.name AS profile_name, r.profile_version, "
            "       r.trade_profile_id, tp.name AS trade_profile_name, r.trade_profile_version, "
            "       r.score_profile_id, sp.name AS score_profile_name, r.score_profile_version, "
            "       r.date_start, r.date_end, r.status, r.created_at, m.total_return "
            "FROM backtest_run r "
            "LEFT JOIN screen_profile p ON p.id = r.profile_id "
            "LEFT JOIN trade_profile tp ON tp.id = r.trade_profile_id "
            "LEFT JOIN score_profile sp ON sp.id = r.score_profile_id "
            "LEFT JOIN backtest_metrics m ON m.run_id = r.id "
            f"{where}"
            "ORDER BY r.created_at DESC LIMIT ?", [*args, limit])
        return df.to_dict("records")

    def get_run(self, run_id: str) -> dict | None:
        run = self.c.query_df("SELECT * FROM backtest_run WHERE id = ?", [run_id])
        if run.empty:
            return None
        m = self.c.query_df("SELECT * FROM backtest_metrics WHERE run_id = ?", [run_id])
        eq = self.c.query_df("SELECT * FROM backtest_equity WHERE run_id = ? ORDER BY trade_date", [run_id])
        td = self.c.query_df("SELECT * FROM backtest_trade WHERE run_id = ? ORDER BY seq", [run_id])
        metrics = m.iloc[0].to_dict() if not m.empty else {}
        layers = json.loads(metrics.pop("hit_rate_by_grade")) if metrics.get("hit_rate_by_grade") else None
        return {"run": run.iloc[0].to_dict(), "metrics": metrics, "layers": layers,
                "equity": eq.to_dict("records"), "trades": td.to_dict("records")}
