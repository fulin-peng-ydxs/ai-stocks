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
import uuid
from contextlib import contextmanager, nullcontext
from datetime import date, datetime
from typing import Iterator

import pandas as pd
import psycopg

from backend.auth.context import get_current_owner
from backend.backtest.engine import BacktestEngine
from backend.backtest.metrics import compute_metrics
from backend.backtest.signal import SignalAnalyzer
from backend.common.logging import get_logger
from backend.services.asset_audit import record_backtest_reuse_audit
from backend.services.asset_visibility import (
    ASSET_BACKTEST_RUN,
    ASSET_SCORE_PROFILE,
    ASSET_SCREEN_PROFILE,
    ASSET_TRADE_PROFILE,
    BACKTEST_SIGNATURE_KEYS,
    VISIBILITY_PRIVATE,
    VISIBILITY_PUBLIC,
    VISIBILITY_TENANT,
    AssetRef,
    asset_visibility_locks,
    backtest_signature,
    decorate_asset_row,
    is_asset_visible,
    normalize_visibility,
    parse_asset_ref,
    resolve_asset_ref_or_legacy_id,
    restore_backtest_private_dependencies,
    visible_params,
    visible_sql,
)
from backend.storage.asset_repository import AssetRepository
from backend.storage.duckdb_client import get_client
from backend.storage.pg_client import get_pg_client

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
        # 秒级时间戳 + 短 UUID：同一用户并发/多标签/重试同秒启动会得到不同 id，避免互相覆盖（P1-5）。
        return f"bt_{kind}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    def _persist_run(self, run_id: str, kind: str, params: dict, status: str,
                     detail: str = "", finished: bool = False,
                     versions: dict | None = None, signature: str | None = None) -> None:
        v = versions or {}
        stored_params = {**params, "_data_versions": v}
        # 状态转换用 UPDATE（同一条 run：running → done/failed），不再「先 DELETE 再 INSERT」。
        # 唯一性由 _new_id 保证；同条件去重由 _purge_signature 负责，不靠删除承担 ID 生成。
        updated = self.pg.execute(
            "UPDATE backtest_run SET status=%s, detail=%s, finished_at=%s, params=%s, "
            "score_profile_version=%s, profile_version=%s, trade_profile_version=%s, signature=%s "
            "WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
            [status, detail, datetime.now() if finished else None,
             json.dumps(stored_params, ensure_ascii=False, default=str),
             v.get("score_profile_version"), v.get("profile_version"), v.get("trade_profile_version"), signature,
             run_id, *self._op])
        if updated:
            return
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
             json.dumps(stored_params, ensure_ascii=False, default=str), status, detail,
             datetime.now(), datetime.now() if finished else None],
        )

    # ── 版本解析 + 去重签名（全条件一致则同一记录，唯一）──
    _SIG_KEYS = list(BACKTEST_SIGNATURE_KEYS)

    def _visible_score_profile(self, profile_ref_or_id: str | None) -> dict | None:
        if not profile_ref_or_id:
            return None
        from backend.scoring.score_profile import ScoreProfileRepo

        return ScoreProfileRepo(market=self.c, pg=self.pg, tenant_id=self.tenant_id,
                                owner_user_id=self.owner_user_id).get_visible(
                                    profile_ref_or_id,
                                    include_owner=True,
                                )

    def _visible_trade_profile(self, profile_ref_or_id: str | None) -> dict | None:
        if not profile_ref_or_id:
            return None
        from backend.signals.trade_profile import TradeProfileRepo

        return TradeProfileRepo(market=self.c, pg=self.pg, tenant_id=self.tenant_id,
                                owner_user_id=self.owner_user_id).get_visible(
                                    profile_ref_or_id,
                                    include_owner=True,
                                )

    def _visible_screen_profile(self, profile_ref_or_id: str | None) -> dict | None:
        if not profile_ref_or_id:
            return None
        from backend.screening.profile import ProfileRepo

        return ProfileRepo(market=self.c, pg=self.pg, tenant_id=self.tenant_id,
                           owner_user_id=self.owner_user_id).get_visible(
                               profile_ref_or_id,
                               include_owner=True,
                           )

    def _batch_profile_labels(
        self,
        refs: list[str],
        *,
        table: str,
        ref_type: str,
    ) -> dict[str, dict]:
        parsed: list[tuple[str, str, str, str]] = []
        for ref in refs:
            try:
                asset_ref = parse_asset_ref(ref, expected_type=ref_type)
            except ValueError:
                continue
            parsed.append((ref, asset_ref.tenant_id, asset_ref.owner_user_id, asset_ref.asset_id))
        return self._query_profile_labels(table, parsed)

    def _batch_score_profile_labels(self, refs: list[str]) -> dict[str, dict]:
        from backend.scoring.score_profile import ScoreProfileRepo

        parsed: list[tuple[str, str, str, str]] = []
        for ref in refs:
            try:
                tenant_id, owner_user_id, profile_id = ScoreProfileRepo.parse_ref(ref)
            except ValueError:
                continue
            parsed.append((ref, tenant_id, owner_user_id, profile_id))
        return self._query_profile_labels("score_profile", parsed)

    def _query_profile_labels(
        self,
        table: str,
        parsed: list[tuple[str, str, str, str]],
    ) -> dict[str, dict]:
        if not parsed:
            return {}
        if table not in {"screen_profile", "score_profile", "trade_profile"}:
            raise ValueError("不支持的方案表")
        clauses: list[str] = []
        args: list[str] = []
        ref_by_key: dict[tuple[str, str, str], str] = {}
        for ref, tenant_id, owner_user_id, profile_id in parsed:
            clauses.append("(tenant_id=%s AND owner_user_id=%s AND id=%s)")
            args.extend([tenant_id, owner_user_id, profile_id])
            ref_by_key[(tenant_id, owner_user_id, profile_id)] = ref
        df = self.pg.query_df(
            f"SELECT tenant_id, owner_user_id, id, name, version FROM {table} "
            f"WHERE ({' OR '.join(clauses)}) AND {visible_sql()}",
            [
                *args,
                *visible_params(tenant_id=self.tenant_id, owner_user_id=self.owner_user_id),
            ],
        )
        out: dict[str, dict] = {}
        for row in df.to_dict("records"):
            key = (row["tenant_id"], row["owner_user_id"], row["id"])
            ref = ref_by_key.get(key)
            if ref:
                out[ref] = {"name": row["name"], "version": int(row["version"])}
        return out

    def _resolve_versions(self, params: dict) -> dict:
        """运行时解析各引用方案的当前版本（命名展示 + 签名用）。方案在 PG。"""
        out: dict = {}
        score_profile = self._visible_score_profile(params.get("score_profile_id"))
        if score_profile:
            out["score_profile_version"] = int(score_profile["version"])
        elif params.get("score_profile_id"):
            out["score_profile_version"] = None
        trade_profile = self._visible_trade_profile(params.get("trade_profile_id"))
        if trade_profile:
            out["trade_profile_version"] = int(trade_profile["version"])
        elif params.get("trade_profile_id"):
            out["trade_profile_version"] = None
        screen_profile = self._visible_screen_profile(params.get("profile_id"))
        if screen_profile:
            out["profile_version"] = int(screen_profile["version"])
        elif params.get("profile_id"):
            out["profile_version"] = None
        from backend.services.stock_st_status import StockSTStatusService

        start = params.get("date_start")
        end = params.get("date_end")
        start_date = pd.Timestamp(start).date() if start else None
        end_date = pd.Timestamp(end).date() if end else None
        out["st_data_version"] = StockSTStatusService(self.c).dataset_version(
            start_date, end_date
        )
        return out

    def _signature(self, kind: str, params: dict, versions: dict) -> str:
        return backtest_signature(kind, params, versions)

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

    def _ensure_explicit_deps_visible(self, params: dict) -> dict | None:
        """显式依赖 fail-closed（P1-4）：请求提供了 ref 而当前用户不可见/不存在即拒绝，
        禁止持久化和审计（防止方案失效/下架/跨租户竞态时静默改用默认评分/方案重跑）。
        任一显式 ref 解析不到 → ValueError（API 转 400）。"""
        checks = [
            ("profile_id", "选股方案", self._visible_screen_profile),
            ("score_profile_id", "评分方案", self._visible_score_profile),
            ("trade_profile_id", "买卖方案", self._visible_trade_profile),
        ]
        for field, label, resolver in checks:
            ref = params.get(field)
            if ref and not resolver(ref):
                raise ValueError(f"{label}不存在或不可见: {ref}")
        source_run_ref = params.get("source_run_ref")
        if not source_run_ref:
            return None
        source_run = self._visible_run_row(str(source_run_ref), include_owner=True)
        # source_run_ref 只表达“复用外部公开回测”：本人的私有/公开记录应走普通再次运行，
        # 不能伪装成跨资产复用；来源在运行前失效时也不得静默落一条无审计的新记录。
        if (
            source_run is None
            or not source_run.get("readonly")
            or source_run.get("visibility") not in {VISIBILITY_TENANT, VISIBILITY_PUBLIC}
            or source_run.get("status") != "done"
        ):
            raise ValueError(f"来源回测不存在、不可复用或不可见: {source_run_ref}")
        return source_run

    def prepare(self, kind: str, params: dict) -> dict:
        """运行前预备：解析版本 + 算签名 + 查同条件历史（供前端弹框询问加载/重跑）。"""
        self._ensure_explicit_deps_visible(params)
        versions = self._resolve_versions(params)
        sig = self._signature(kind, params, versions)
        return {"signature": sig, "versions": versions, "duplicate": self.find_duplicate(sig)}

    @contextmanager
    def _signature_run_lock(self, signature: str) -> Iterator[None]:
        """互斥保护同 owner、同签名的完整运行生命周期。

        锁必须覆盖“清旧记录 → running → 计算 → done/failed”全过程；若只保护清理和插入，
        后来的同签名请求仍能在前一请求计算期间删除其 running 行，最终被前一请求复活成重复记录。
        使用会话级 try-lock 让重复请求快速失败；等待式事务锁会让大量同步长请求占满连接池，
        导致持锁请求反而借不到连接写入结果。
        """
        scope = f"backtest:{self.tenant_id}:{self.owner_user_id}"
        # 锁连接不能占用业务连接池：运行过程中 _persist_run/_persist/审计还需从该池借连接；
        # 若每个长运行都先占一条池连接，并发数达到 pool_max 时会集体等待第二条连接而自锁。
        # 独立 autocommit 会话只持 advisory lock，不开启长事务，退出时连接关闭也会兜底释放锁。
        try:
            conn = psycopg.connect(
                self.pg.conninfo,
                autocommit=True,
                connect_timeout=10,
            )
        except psycopg.Error as exc:
            raise RuntimeError("回测并发锁连接失败，请稍后重试") from exc
        try:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "SELECT pg_try_advisory_lock(hashtext(%s), hashtext(%s))",
                        [scope, signature],
                    )
                    locked = bool(cur.fetchone()[0])
                except psycopg.Error as exc:
                    raise RuntimeError("回测并发锁获取失败，请稍后重试") from exc
                if not locked:
                    raise ValueError("相同条件的回测正在运行，请稍后重试")
                try:
                    yield
                finally:
                    try:
                        cur.execute(
                            "SELECT pg_advisory_unlock(hashtext(%s), hashtext(%s))",
                            [scope, signature],
                        )
                    except psycopg.Error as exc:
                        # 会话关闭仍会释放 advisory lock；此处不覆盖原业务异常。
                        log.warning("回测并发锁显式释放失败，将随会话关闭释放: %s", exc)
        finally:
            conn.close()

    def _purge_signature(self, signature: str | None) -> None:
        """覆盖语义：删除同签名旧记录（含曲线/逐笔/绩效），保证每个条件组合历史唯一。"""
        if not signature:
            return
        old = self.pg.query_df(
            "SELECT id FROM backtest_run WHERE signature=%s AND tenant_id=%s AND owner_user_id=%s",
            [signature, *self._op])
        for rid in old["id"].tolist():
            self.delete_run(rid)

    def _purge_signature_except(self, signature: str | None, keep_run_id: str) -> None:
        """发布规范化可能刷新签名；保留当前 run，清理等价旧记录。"""
        if not signature:
            return
        old = self.pg.query_df(
            "SELECT id FROM backtest_run "
            "WHERE signature=%s AND tenant_id=%s AND owner_user_id=%s AND id<>%s",
            [signature, *self._op, keep_run_id],
        )
        for rid in old["id"].tolist():
            self.delete_run(rid)

    def _load_score_profile(self, params: dict) -> dict | None:
        if not params.get("score_profile_id"):
            return None
        return self._visible_score_profile(params["score_profile_id"])

    def _decorate_run_row(self, row: dict, *, include_owner: bool = False) -> dict:
        out = decorate_asset_row(
            row,
            asset_type=ASSET_BACKTEST_RUN,
            tenant_id=self.tenant_id,
            owner_user_id=self.owner_user_id,
            include_owner=include_owner,
        )
        out["run_ref"] = out["asset_ref"]
        return out

    def _visible_run_row(self, run_ref_or_id: str, *, include_owner: bool = False) -> dict | None:
        try:
            ref = resolve_asset_ref_or_legacy_id(
                run_ref_or_id,
                asset_type=ASSET_BACKTEST_RUN,
                tenant_id=self.tenant_id,
                owner_user_id=self.owner_user_id,
            )
        except ValueError:
            return None
        df = self.pg.query_df(
            "SELECT * FROM backtest_run WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
            [ref.asset_id, ref.tenant_id, ref.owner_user_id],
        )
        if df.empty:
            return None
        row = df.iloc[0].to_dict()
        if not is_asset_visible(row, tenant_id=self.tenant_id, owner_user_id=self.owner_user_id):
            return None
        return self._decorate_run_row(row, include_owner=include_owner)

    # ── 评分验证（信号质量分析）──
    def run_signal(self, params: dict, persist: bool = True) -> dict:
        source_run = self._ensure_explicit_deps_visible(params)  # fail-closed：显式失效引用拒绝
        run_id = self._new_id("score_check")
        versions = self._resolve_versions(params)
        sig = self._signature("score_check", params, versions)
        guard = self._signature_run_lock(sig) if persist else nullcontext()
        with guard:
            if persist:
                self._purge_signature(sig)  # 锁内覆盖同条件旧记录（唯一）
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
                    self._record_reuse_if_needed(params, run_id, source_run)
                return res
            except Exception as e:  # noqa: BLE001
                if persist:
                    self._delete_run_results(run_id)
                    self._persist_run(run_id, "score_check", params, "failed", detail=str(e), finished=True,
                                      versions=versions, signature=sig)
                raise

    # ── 完整策略回测 ──
    def run_strategy(self, params: dict, persist: bool = True) -> dict:
        source_run = self._ensure_explicit_deps_visible(params)  # fail-closed：显式失效引用拒绝
        run_id = self._new_id("strategy")
        versions = self._resolve_versions(params)
        sig = self._signature("strategy", params, versions)
        guard = self._signature_run_lock(sig) if persist else nullcontext()
        with guard:
            if persist:
                self._purge_signature(sig)  # 锁内覆盖同条件旧记录（唯一）
                self._persist_run(run_id, "strategy", params, "running", versions=versions, signature=sig)
            try:
                # 共享一个 IndicatorEngine：策略回测与分层分析复用同一区间快照缓存（性能：避免重算）
                from backend.indicators.engine import IndicatorEngine
                shared_ind = IndicatorEngine(self.c)
                out = BacktestEngine(
                    self.c,
                    ind=shared_ind,
                    tenant_id=self.tenant_id,
                    owner_user_id=self.owner_user_id,
                ).run(params)
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
                    self._record_reuse_if_needed(params, run_id, source_run)
                return result
            except Exception as e:  # noqa: BLE001
                if persist:
                    self._delete_run_results(run_id)
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

    def _delete_run_results(self, run_id: str) -> None:
        """失败补偿：清理可能已写入的结果子表，保留 run 失败记录与错误详情。"""
        for table in ("backtest_trade", "backtest_equity", "backtest_metrics"):
            self.pg.execute(
                f"DELETE FROM {table} WHERE run_id=%s AND tenant_id=%s AND owner_user_id=%s",
                [run_id, *self._op],
            )

    def delete_run(self, run_id: str) -> bool:
        """删除某次回测的全部数据（run + equity + trade + metrics）。"""
        run = self._visible_run_row(run_id, include_owner=True)
        if run is None:
            return False
        if run.get("readonly"):
            raise PermissionError("只能删除自己的回测记录")
        for t in ("backtest_trade", "backtest_equity", "backtest_metrics", "backtest_run"):
            self.pg.execute(
                f"DELETE FROM {t} WHERE run_id=%s AND tenant_id=%s AND owner_user_id=%s"
                if t != "backtest_run" else
                f"DELETE FROM {t} WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
                [run["id"], run["tenant_id"], run["owner_user_id"]])
        return True

    def set_run_visibility(
        self,
        run_ref_or_id: str,
        visibility: str,
        published_by: str | None = None,
    ) -> dict | None:
        visibility = normalize_visibility(visibility)
        run = self._visible_run_row(run_ref_or_id, include_owner=True)
        if run is None:
            return None
        if run.get("readonly"):
            raise PermissionError("只能修改自己的回测记录可见性")
        if run.get("status") != "done" and visibility != VISIBILITY_PRIVATE:
            raise ValueError("仅已完成回测记录可公开")
        lock_refs = (
            self._run_profile_refs(run) if visibility != VISIBILITY_PRIVATE else []
        )
        with asset_visibility_locks(self.pg, lock_refs):
            # 等锁期间方案可能已收回，必须重新读取回测并在锁内重做依赖可见性校验。
            run = self._visible_run_row(run_ref_or_id, include_owner=True)
            if run is None:
                return None
            if run.get("readonly"):
                raise PermissionError("只能修改自己的回测记录可见性")
            if run.get("status") != "done" and visibility != VISIBILITY_PRIVATE:
                raise ValueError("仅已完成回测记录可公开")
            normalized = self._normalize_run_dependencies_for_visibility(run, visibility)
            now = datetime.now() if visibility != VISIBILITY_PRIVATE else None
            params = normalized["params"] if normalized else run.get("params")
            params_json = (
                json.dumps(params, ensure_ascii=False, default=str)
                if isinstance(params, dict)
                else params
            )
            affected = self.pg.execute(
                "UPDATE backtest_run SET visibility=%s, published_at=%s, published_by=%s, "
                "params=%s, profile_id=%s, score_profile_id=%s, trade_profile_id=%s, "
                "profile_version=%s, score_profile_version=%s, trade_profile_version=%s, "
                "signature=%s "
                "WHERE id=%s AND tenant_id=%s AND owner_user_id=%s",
                [
                    visibility,
                    now,
                    published_by if visibility != VISIBILITY_PRIVATE else None,
                    params_json,
                    normalized["profile_id"] if normalized else run.get("profile_id"),
                    normalized["score_profile_id"] if normalized else run.get("score_profile_id"),
                    normalized["trade_profile_id"] if normalized else run.get("trade_profile_id"),
                    normalized["profile_version"] if normalized else run.get("profile_version"),
                    normalized["score_profile_version"] if normalized else run.get("score_profile_version"),
                    normalized["trade_profile_version"] if normalized else run.get("trade_profile_version"),
                    normalized["signature"] if normalized else run.get("signature"),
                    run["id"],
                    run["tenant_id"],
                    run["owner_user_id"],
                ],
            )
        if affected == 0:
            return None
        # 仅发布时按新签名清理等价旧记录;收回 private 不清理,避免误删同签名的另一条私有回测
        if normalized and visibility != VISIBILITY_PRIVATE:
            self._purge_signature_except(normalized.get("signature"), run["id"])
        return self._visible_run_row(run["run_ref"])

    def _run_profile_refs(self, run: dict) -> list[AssetRef]:
        """提取回测依赖的真实方案归属，供发布与方案收回共享同一并发锁。"""
        raw_params = run.get("params") or "{}"
        if isinstance(raw_params, dict):
            params = raw_params
        else:
            try:
                params = json.loads(raw_params)
            except (TypeError, ValueError):
                params = {}
        specs = (
            ("profile_id", ASSET_SCREEN_PROFILE),
            ("score_profile_id", ASSET_SCORE_PROFILE),
            ("trade_profile_id", ASSET_TRADE_PROFILE),
        )
        refs = []
        for key, asset_type in specs:
            value = params.get(key) or run.get(key)
            if not value:
                continue
            try:
                refs.append(resolve_asset_ref_or_legacy_id(
                    str(value),
                    asset_type=asset_type,
                    tenant_id=run["tenant_id"],
                    owner_user_id=run["owner_user_id"],
                ))
            except ValueError:
                # 无效引用由锁内的标准依赖校验返回既有业务错误；这里没有可锁定的真实资产。
                continue
        return refs

    # ── 读取 ──
    def _runs_where(self, kind: str | None, source: str | None) -> tuple[str, list]:
        """list_runs / count_runs 共用的 WHERE 构建（可见性 + kind + source 过滤）。"""
        where = f"WHERE {visible_sql('r')} "
        args: list = visible_params(tenant_id=self.tenant_id, owner_user_id=self.owner_user_id)
        if kind == "score_check":
            where += "AND r.kind IN ('score_check','signal') "  # 兼容旧 signal 值
        elif kind == "strategy":
            where += "AND r.kind = 'strategy' "
        if source == "mine":
            where += "AND r.tenant_id=%s AND r.owner_user_id=%s "
            args += [self.tenant_id, self.owner_user_id]
        elif source == "tenant":
            where += "AND r.visibility='tenant' AND NOT (r.tenant_id=%s AND r.owner_user_id=%s) "
            args += [self.tenant_id, self.owner_user_id]
        elif source == "public":
            where += "AND r.visibility='public' AND NOT (r.tenant_id=%s AND r.owner_user_id=%s) "
            args += [self.tenant_id, self.owner_user_id]
        return where, args

    @staticmethod
    def _runs_q_filter(q_norm: str):
        """q 名称过滤：发布态回测的方案引用列已被改写成 opaque ref，SQL JOIN 裸 id 取不到方案名，
        只能在解析 ref、补全方案名之后于 Python 侧按三类引用方案名 + kind 过滤。"""
        def _hit(row: dict) -> bool:
            for key in ("profile_name", "score_profile_name", "trade_profile_name"):
                val = row.get(key)
                if val and q_norm in str(val).lower():
                    return True
            kind = str(row.get("kind") or "").lower()
            aliases = {
                "strategy": ("strategy", "策略", "策略回测"),
                "score_check": ("score_check", "signal", "评分", "评分验证"),
                "signal": ("score_check", "signal", "评分", "评分验证"),
            }.get(kind, (kind,))
            if any(q_norm in alias for alias in aliases):
                return True
            return False
        return _hit

    def list_runs_page(
        self,
        *,
        limit: int,
        offset: int = 0,
        kind: str | None = None,
        source: str | None = None,
        q: str | None = None,
    ) -> tuple[list[dict], int]:
        """返回分页记录与同口径 total；带 q 时只做一次全量解析和装饰。"""
        limit = max(1, limit)
        offset = max(0, offset)
        q_norm = q.strip().lower() if q and q.strip() else None
        if q_norm is None:
            return (
                self.list_runs(limit, kind=kind, source=source, offset=offset),
                self.count_runs(kind=kind, source=source),
            )
        where, args = self._runs_where(kind, source)
        order_by, owner_args = self._runs_order()
        rows = self._query_runs_decorated(where, order_by, "", [*args, *owner_args])
        hit = self._runs_q_filter(q_norm)
        matched = [row for row in rows if hit(row)]
        return matched[offset:offset + limit], len(matched)

    def _runs_order(self) -> tuple[str, list]:
        # 「我的」置顶,与方案 list_visible 口径一致;末位补**完整主键** (tenant_id, owner_user_id, id)
        # 作稳定唯一键——回测主键是三元组且 created_at 仅秒级精度、跨 owner 可同 id，只补 r.id 仍可能抖动。
        # 排序参数必须在 LIMIT 之前。
        order_by = (
            "ORDER BY (CASE WHEN r.tenant_id=%s AND r.owner_user_id=%s THEN 0 ELSE 1 END), "
            "r.created_at DESC, r.tenant_id, r.owner_user_id, r.id "
        )
        return order_by, [self.tenant_id, self.owner_user_id]

    def count_runs(
        self,
        kind: str | None = None,
        source: str | None = None,
        q: str | None = None,
    ) -> int:
        """list_runs 的真 total（分页契约）。无 q 走 SQL COUNT（where 只涉 backtest_run 列，无需 JOIN）；
        q 路径因需 Python 侧按方案名过滤，取全量装饰行后按 len(matched) 计数（与 list_runs 同口径）。"""
        where, args = self._runs_where(kind, source)
        q_norm = q.strip().lower() if q and q.strip() else None
        if q_norm is None:
            df = self.pg.query_df(f"SELECT COUNT(*) AS c FROM backtest_run r {where}", args)
            return int(df.iloc[0]["c"]) if len(df) else 0
        order_by, owner_args = self._runs_order()
        rows = self._query_runs_decorated(where, order_by, "", [*args, *owner_args])
        hit = self._runs_q_filter(q_norm)
        return sum(1 for r in rows if hit(r))

    def list_runs(
        self,
        limit: int | None = None,
        kind: str | None = None,
        source: str | None = None,
        q: str | None = None,
        offset: int = 0,
    ) -> list[dict]:
        """历史记录。kind 给定则只列该类（strategy / score_check），策略与评分验证不混展；
        limit=None 则全列（不截断），同签名因覆盖语义本就只留一条。run⋈三方案⋈metrics 全在 PG。
        offset 用于分页（搜索抽屉）；total 由 count_runs 提供（同 where/q 口径）。

        q（搜索弹窗浏览）：回测自身无 name，按三类引用方案名（筛选/评分/买卖）+ kind 关键字过滤。"""
        # 防御：非正 limit 归一为「不截断」，避免无 q 时 SQL LIMIT 负值报错、有 q 时 Python 切片语义反常
        if limit is not None and limit < 1:
            limit = None
        if offset < 0:
            offset = 0
        where, args = self._runs_where(kind, source)
        q_norm = q.strip().lower() if q and q.strip() else None
        order_by, owner_args = self._runs_order()

        if q_norm is None:
            tail = ""
            tail_args: list = []
            if limit is not None:
                tail = "LIMIT %s OFFSET %s"
                tail_args = [limit, offset]
            elif offset:
                # 无 limit 但有 offset：LIMIT ALL 在 PostgreSQL 与 DuckDB 均合法，占位保证 OFFSET 生效（语义仍为「不截断上限」）
                tail = "LIMIT ALL OFFSET %s"
                tail_args = [offset]
            return self._query_runs_decorated(where, order_by, tail, [*args, *owner_args, *tail_args])

        # q：取全部可见行（不截断），解析 opaque ref、补全方案名后于 Python 侧按名 + kind 过滤，
        # 再按 offset/limit 切片。**correctness 优先**：不设扫描上限，避免匹配项靠后被静默漏掉、
        # 也不破坏 limit=None「全列」契约。发布态回测规模化后的成本优化（keyset/冗余搜索列）
        # 留后续按分页 UX 统一设计（见 plan §8 备注 / 跟踪任务）。
        hit = self._runs_q_filter(q_norm)
        rows = self._query_runs_decorated(where, order_by, "", [*args, *owner_args])
        matched = [r for r in rows if hit(r)]
        sliced = matched[offset:]
        return sliced[:limit] if limit is not None else sliced

    def _query_runs_decorated(self, where: str, order_by: str, tail: str, args: list) -> list[dict]:
        """执行 run⋈三方案⋈metrics 查询 + 脱敏装饰 + 发布态 opaque ref 方案名补全，返回装饰后行。"""
        df = self.pg.query_df(
            "SELECT r.id, r.tenant_id, r.owner_user_id, r.kind, r.profile_id, "
            "       p.name AS profile_name, r.profile_version, "
            "       r.trade_profile_id, tp.name AS trade_profile_name, r.trade_profile_version, "
            "       r.score_profile_id, sp.name AS score_profile_name, r.score_profile_version, "
            "       r.date_start, r.date_end, r.status, r.visibility, r.published_at, r.published_by, "
            "       r.created_at, m.total_return "
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
            f"{order_by}{tail}", args)
        rows = [self._decorate_run_row(r) for r in df.to_dict("records")]
        screen_labels = self._batch_profile_labels(
            [str(r["profile_id"]) for r in rows
             if r.get("profile_id") and not r.get("profile_name")],
            table="screen_profile",
            ref_type=ASSET_SCREEN_PROFILE,
        )
        score_labels = self._batch_score_profile_labels(
            [str(r["score_profile_id"]) for r in rows
             if r.get("score_profile_id") and not r.get("score_profile_name")],
        )
        trade_labels = self._batch_profile_labels(
            [str(r["trade_profile_id"]) for r in rows
             if r.get("trade_profile_id") and not r.get("trade_profile_name")],
            table="trade_profile",
            ref_type=ASSET_TRADE_PROFILE,
        )
        for row in rows:
            if row.get("profile_id") and not row.get("profile_name"):
                prof = screen_labels.get(str(row["profile_id"]))
                if prof:
                    row["profile_name"] = prof["name"]
                    row["profile_version"] = prof["version"]
            if row.get("score_profile_id") and not row.get("score_profile_name"):
                prof = score_labels.get(str(row["score_profile_id"]))
                if prof:
                    row["score_profile_name"] = prof["name"]
                    row["score_profile_version"] = prof["version"]
            if row.get("trade_profile_id") and not row.get("trade_profile_name"):
                prof = trade_labels.get(str(row["trade_profile_id"]))
                if prof:
                    row["trade_profile_name"] = prof["name"]
                    row["trade_profile_version"] = prof["version"]
        return rows

    def _record_reuse_if_needed(
        self,
        params: dict,
        run_id: str,
        source_run: dict | None = None,
    ) -> None:
        source_run_ref = params.get("source_run_ref")
        if not source_run_ref:
            return
        # 运行前已 fail-closed 校验并冻结来源；此处不二次查询，避免长回测期间来源撤回导致审计静默丢失。
        if source_run is None:
            raise ValueError(f"来源回测不存在、不可复用或不可见: {source_run_ref}")
        if not record_backtest_reuse_audit(source_run, run_id):
            raise RuntimeError("回测复用审计写入失败")

    def _normalize_run_dependencies_for_visibility(
        self,
        run: dict,
        visibility: str,
    ) -> dict | None:
        if visibility == VISIBILITY_PRIVATE:
            # 收回为私有:把发布时改写成 opaque ref 的方案引用列还原为原始裸 id
            return self._restore_run_dependencies(run)
        raw_params = run.get("params") or "{}"
        if isinstance(raw_params, dict):
            params = dict(raw_params)
        else:
            try:
                params = json.loads(raw_params)
            except (TypeError, ValueError):
                raise ValueError("回测参数不可解析，不能公开") from None
        params.pop("source_run_ref", None)
        dependencies = [
            ("profile_id", "profile_version", "筛选方案", self._run_owner_screen_profile),
            ("score_profile_id", "score_profile_version", "评分方案", self._run_owner_score_profile),
            ("trade_profile_id", "trade_profile_version", "买卖方案", self._run_owner_trade_profile),
        ]
        normalized = {
            "params": params,
            "profile_id": run.get("profile_id"),
            "score_profile_id": run.get("score_profile_id"),
            "trade_profile_id": run.get("trade_profile_id"),
            "profile_version": run.get("profile_version"),
            "score_profile_version": run.get("score_profile_version"),
            "trade_profile_version": run.get("trade_profile_version"),
            "signature": run.get("signature"),
        }
        for key, version_key, label, resolver in dependencies:
            ref_or_id = params.get(key) or run.get(key)
            if not ref_or_id:
                continue
            dep = resolver(run, str(ref_or_id))
            if dep is None:
                raise ValueError(f"回测引用的{label}不可见，不能公开回测记录")
            dep_visibility = normalize_visibility(dep.get("visibility"))
            if visibility == VISIBILITY_TENANT:
                allowed = dep_visibility == VISIBILITY_PUBLIC or (
                    dep_visibility == VISIBILITY_TENANT
                    and dep.get("tenant_id") == run.get("tenant_id")
                )
                if not allowed:
                    raise ValueError(f"请先将回测引用的{label}公开到租户或全体")
            elif visibility == VISIBILITY_PUBLIC and dep_visibility != VISIBILITY_PUBLIC:
                raise ValueError(f"请先将回测引用的{label}公开到全体")
            profile_ref = dep.get("profile_ref") or dep.get("asset_ref")
            if not profile_ref:
                raise ValueError(f"回测引用的{label}缺少公开引用，不能公开回测记录")
            normalized["params"][key] = profile_ref
            normalized[key] = profile_ref
            if dep.get("version") is not None:
                normalized[version_key] = int(dep["version"])
        normalized["signature"] = self._signature(
            str(run.get("kind") or "strategy"),
            normalized["params"],
            {
                "profile_version": normalized["profile_version"],
                "score_profile_version": normalized["score_profile_version"],
                "trade_profile_version": normalized["trade_profile_version"],
            },
        )
        return normalized

    def _bare_asset_id(self, ref_or_id: str) -> str:
        """opaque ref → 原始裸 id;非 ref 原样返回。"""
        try:
            return parse_asset_ref(ref_or_id).asset_id
        except ValueError:
            return ref_or_id

    def _restore_run_dependencies(self, run: dict) -> dict | None:
        """收回为 private 时还原方案引用列 + 重算 signature,消除发布态列语义污染(P4)。

        返回 None 表示无 ref 需还原(走原值写回);否则返回与发布路径同构的 normalized。
        """
        return restore_backtest_private_dependencies(run)

    def _run_owner_screen_profile(self, run: dict, profile_ref_or_id: str) -> dict | None:
        from backend.screening.profile import ProfileRepo

        return ProfileRepo(
            market=self.c,
            pg=self.pg,
            tenant_id=run["tenant_id"],
            owner_user_id=run["owner_user_id"],
        ).get_visible(
            profile_ref_or_id,
            include_owner=True,
        )

    def _run_owner_score_profile(self, run: dict, profile_ref_or_id: str) -> dict | None:
        from backend.scoring.score_profile import ScoreProfileRepo

        return ScoreProfileRepo(
            market=self.c,
            pg=self.pg,
            tenant_id=run["tenant_id"],
            owner_user_id=run["owner_user_id"],
        ).get_visible(
            profile_ref_or_id,
            include_owner=True,
        )

    def _run_owner_trade_profile(self, run: dict, profile_ref_or_id: str) -> dict | None:
        from backend.signals.trade_profile import TradeProfileRepo

        return TradeProfileRepo(
            market=self.c,
            pg=self.pg,
            tenant_id=run["tenant_id"],
            owner_user_id=run["owner_user_id"],
        ).get_visible(
            profile_ref_or_id,
            include_owner=True,
        )

    def get_run(self, run_id: str) -> dict | None:
        run_d = self._visible_run_row(run_id, include_owner=True)
        if run_d is None:
            return None
        run_owner = [run_d["tenant_id"], run_d["owner_user_id"]]
        m = self.pg.query_df(
            "SELECT * FROM backtest_metrics WHERE run_id=%s AND tenant_id=%s AND owner_user_id=%s",
            [run_d["id"], *run_owner])
        eq = self.pg.query_df(
            "SELECT * FROM backtest_equity WHERE run_id=%s AND tenant_id=%s AND owner_user_id=%s "
            "ORDER BY trade_date", [run_d["id"], *run_owner])
        td = self.pg.query_df(
            "SELECT * FROM backtest_trade WHERE run_id=%s AND tenant_id=%s AND owner_user_id=%s "
            "ORDER BY seq", [run_d["id"], *run_owner])
        metrics = m.iloc[0].to_dict() if not m.empty else {}
        for _k in ("tenant_id", "owner_user_id"):
            metrics.pop(_k, None)
        layers = json.loads(metrics.pop("hit_rate_by_grade")) if metrics.get("hit_rate_by_grade") else None
        for _k in ("tenant_id", "owner_user_id"):
            run_d.pop(_k, None)
        return {"run": run_d, "metrics": metrics, "layers": layers,
                "equity": eq.to_dict("records"), "trades": td.to_dict("records")}
