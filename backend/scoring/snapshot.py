"""评分快照层（SDD §10.1，M2.6）——按 日期+方案+版本 惰性物化全市场评分榜。

统一各入口（生产任务 / 试运行 / 回测排名 / 评分验证）的打分口径，避免重复实时计算。
- 惰性物化：首次请求某 (日期, 方案, 版本) → 整天打分一次落 score_snapshot + 写 meta(stale=false)。
- 显式失效（关键）：结果维护任务把 score_snapshot_meta 标 stale=true（便宜），**不立即重算**；
  下次 get 时若 meta 缺失或 stale → 当场重算覆盖、meta 置 false 再返回，否则直接用缓存。
- 只读入口可调用 get_board_cached：只读 fresh 快照，缺失/失效返回空表，不触发物化。
- fresh 同时要求命中当日 ST 输入版本；ST 批次未发布时拒绝把旧缓存当成有效结果。
- 口径与回测 `_decision_data` 一致：wide_snapshot 单日 + 排除 ST + ScoreProfileModel（表达式型指标补列）。
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pandas as pd

from backend.auth.context import get_current_owner
from backend.common.logging import get_logger
from backend.storage.duckdb_client import get_client
from backend.storage.pg_client import get_pg_client

log = get_logger("scoring.snapshot")

_COLS = ["code", "total_score", "grade", "rank", "sub_scores"]


def _current_param_hash(market=None, profile: dict | None = None) -> str:
    """当前指标参数与评分方案所引用自定义定义的联合指纹。"""
    from backend.indicators.compute import build_params, param_hash

    params = build_params()
    client = market or get_client()
    data_revision = client.query_df(
        "SELECT max(id) AS revision FROM data_update_log "
        "WHERE table_name IN ('daily_bar','daily_metrics') AND status IN ('success','partial')"
    ).iloc[0]["revision"]
    if pd.notna(data_revision):
        # 正常行情/市值更新会留下日志；将版本并入指纹，让历史修订自动淘汰旧榜单。
        params["market_data_revision"] = int(data_revision)
    custom_keys = sorted({
        str(item.get("indicator"))
        for item in (profile or {}).get("items", [])
        if item.get("indicator")
    })
    if custom_keys:
        placeholders = ",".join("?" * len(custom_keys))
        definitions = client.query_df(
            "SELECT key,dtype,kind,expression,params FROM indicator_def "
            f"WHERE key IN ({placeholders}) ORDER BY key",
            custom_keys,
        )
        if not definitions.empty:
            semantic_definitions = []
            for row in definitions.fillna("").to_dict("records"):
                raw_params = json.loads(row["params"]) if row.get("params") else []
                row["params"] = [
                    {key: param.get(key) for key in ("name", "type", "default", "min", "max")}
                    for param in raw_params
                ]
                semantic_definitions.append(row)
            params["indicator_definitions"] = semantic_definitions
    return param_hash(params)


def score_day(c, run_date: date, profile: dict) -> pd.DataFrame:
    """对某交易日全市场（排除 ST）按评分方案打分 → DataFrame[code,total_score,grade,rank,sub_scores]（降序）。

    与回测 `_decision_data` / `/board/compute` 同口径；纯计算，不落库。sub_scores=各指标项达标分 JSON。
    """
    from backend.indicators.engine import IndicatorEngine
    from backend.scoring.score_profile import ScoreProfileModel

    eng = IndicatorEngine(c)
    snap = eng.wide_snapshot(run_date, run_date)
    if snap.empty:
        return pd.DataFrame(columns=_COLS)
    snap = snap.set_index("code")
    from backend.services.stock_st_status import StockSTStatusService

    statuses = StockSTStatusService(c).status_map(run_date, snap.index.astype(str).tolist())
    st = {code for code, is_st in statuses.items() if is_st}
    snap = snap[~snap.index.isin(st)]
    if snap.empty:
        return pd.DataFrame(columns=_COLS)
    eng.attach_columns(snap, profile.get("items", []), run_date)
    scored = ScoreProfileModel(profile).score(snap).sort_values("total_score", ascending=False)
    item_keys = [it["indicator"] for it in profile.get("items", []) if it.get("indicator") in scored.columns]
    subs = [json.dumps({k: round(float(r[k]), 2) for k in item_keys}, ensure_ascii=False)
            for _, r in scored.iterrows()] if item_keys else [None] * len(scored)
    out = pd.DataFrame({
        "code": scored.index,
        "total_score": scored["total_score"].astype(float).round(2).values,
        "grade": scored["grade"].astype(str).values,
    })
    out["rank"] = range(1, len(out) + 1)
    out["sub_scores"] = subs
    return out


class ScoreSnapshotRepo:
    """评分快照惰性物化（用户资产→PG；计算读行情→DuckDB）。

    - 快照明细/元数据走 PG（self.pg，%s + 归属过滤），批量写用 AssetRepository。
    - score_day 计算读行情/指标走 DuckDB（self.mkt）。
    - 失效标记（mark_stale_*）是**全局**的：显式维护时按选定日期
      影响所有归属者，不按当前请求归属过滤。
    第一位保留为 market 以兼容历史 ScoreSnapshotRepo(c) 调用。
    """

    def __init__(self, market=None, pg=None, *, tenant_id: str | None = None,
                 owner_user_id: str | None = None):
        self.mkt = market or get_client()
        self.pg = pg or get_pg_client()
        _ctx_t, _ctx_o = get_current_owner()
        self.tenant_id = tenant_id or _ctx_t
        self.owner_user_id = owner_user_id or _ctx_o

    @property
    def _op(self) -> list:
        return [self.tenant_id, self.owner_user_id]

    def _profile(self, profile_id: str) -> dict | None:
        from backend.scoring.score_profile import ScoreProfileRepo
        return ScoreProfileRepo(market=self.mkt, pg=self.pg, tenant_id=self.tenant_id,
                                owner_user_id=self.owner_user_id).get(profile_id)

    def get_board(self, run_date: date, profile_id: str, top: int | None = None,
                  profile: dict | None = None) -> pd.DataFrame:
        """惰性取某日某方案评分榜（降序）。命中且未失效→用缓存；否则重算并落库。

        profile 可注入以省一次查询（须含 version/items）；否则按 profile_id 现查当前版本。
        """
        prof = profile or self._profile(profile_id)
        if not prof:
            return pd.DataFrame(columns=_COLS)
        version = int(prof.get("version") or 1)
        ph = _current_param_hash(self.mkt, prof)
        st_version = self._st_input_version(run_date)
        if self._fresh(run_date, profile_id, version, ph, st_version):
            rows = self._read_board(run_date, profile_id, version)
            # PG 元数据和 DuckDB 事实不能跨库做原子读；返回缓存前再验一次，收窄
            # “刚判定 fresh、ST 随即变化”的双库竞态窗口。
            if self._st_input_version(run_date) != st_version:
                rows = self._materialize_locked(run_date, profile_id, version, prof, ph)
        else:
            rows = self._materialize_locked(run_date, profile_id, version, prof, ph)
        return rows.head(top) if top else rows

    def get_board_cached(self, run_date: date, profile_id: str, top: int | None = None,
                         profile: dict | None = None) -> pd.DataFrame:
        """只读取已物化且未失效的评分榜；缺失/失效时返回空表，不触发重算写库。"""
        prof = profile or self._profile(profile_id)
        if not prof:
            return pd.DataFrame(columns=_COLS)
        version = int(prof.get("version") or 1)
        st_version = self._st_input_version(run_date)
        if not self._fresh(
            run_date, profile_id, version, _current_param_hash(self.mkt, prof), st_version
        ):
            return pd.DataFrame(columns=_COLS)
        rows = self.pg.query_df(
            "SELECT code, total_score, grade, rank, sub_scores FROM score_snapshot "
            "WHERE trade_date=%s AND profile_id=%s AND profile_version=%s "
            "AND tenant_id=%s AND owner_user_id=%s ORDER BY rank",
            [run_date, profile_id, version, *self._op])
        if self._st_input_version(run_date) != st_version:
            return pd.DataFrame(columns=_COLS)
        return rows.head(top) if top else rows

    def _read_board(self, run_date: date, profile_id: str, version: int) -> pd.DataFrame:
        return self.pg.query_df(
            "SELECT code, total_score, grade, rank, sub_scores FROM score_snapshot "
            "WHERE trade_date=%s AND profile_id=%s AND profile_version=%s "
            "AND tenant_id=%s AND owner_user_id=%s ORDER BY rank",
            [run_date, profile_id, version, *self._op])

    def _read_board_cur(self, cur, run_date: date, profile_id: str, version: int) -> pd.DataFrame:
        cur.execute(
            "SELECT code, total_score, grade, rank, sub_scores FROM score_snapshot "
            "WHERE trade_date=%s AND profile_id=%s AND profile_version=%s "
            "AND tenant_id=%s AND owner_user_id=%s ORDER BY rank",
            [run_date, profile_id, version, *self._op])
        cols = [d.name if hasattr(d, "name") else d[0] for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)

    def is_fresh(self, run_date: date, profile_id: str, version: int) -> bool:
        """Return whether the stored snapshot matches every current read-time input."""
        profile = self._profile(profile_id)
        return self._fresh(
            run_date,
            profile_id,
            version,
            _current_param_hash(self.mkt, profile),
            self._st_input_version(run_date),
        )

    def _st_input_version(self, run_date: date) -> str:
        from backend.services.stock_st_status import StockSTStatusService

        return StockSTStatusService(self.mkt).input_version_for_date(run_date)

    def _fresh(
        self,
        run_date: date,
        profile_id: str,
        version: int,
        ph: str,
        st_version: str,
    ) -> bool:
        m = self.pg.query_df(
            "SELECT stale,param_hash,st_input_version FROM score_snapshot_meta "
            "WHERE trade_date=%s AND profile_id=%s "
            "AND profile_version=%s AND tenant_id=%s AND owner_user_id=%s",
            [run_date, profile_id, version, *self._op])
        if m.empty or bool(m.iloc[0]["stale"]):
            return False
        # 历史 NULL 版本视为不匹配；首次读取沿用原物化入口完成一次自愈。
        return (
            m.iloc[0]["param_hash"] == ph
            and m.iloc[0]["st_input_version"] == st_version
        )

    def _fresh_cur(
        self,
        cur,
        run_date: date,
        profile_id: str,
        version: int,
        ph: str,
        st_version: str,
    ) -> bool:
        cur.execute(
            "SELECT stale,param_hash,st_input_version FROM score_snapshot_meta "
            "WHERE trade_date=%s AND profile_id=%s "
            "AND profile_version=%s AND tenant_id=%s AND owner_user_id=%s",
            [run_date, profile_id, version, *self._op])
        row = cur.fetchone()
        if row is None or bool(row[0]):
            return False
        return row[1] == ph and row[2] == st_version

    def _materialize_locked(self, run_date: date, profile_id: str, version: int, profile: dict,
                            ph: str) -> pd.DataFrame:
        """锁内用稳定 ST 版本重算，并原子覆盖明细和 PG 元数据。"""
        lock_scope = f"{self.tenant_id}:{self.owner_user_id}"
        lock_key = f"{run_date}:{profile_id}:{version}"
        with self.pg.transaction() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))", [lock_scope, lock_key])
            # 等锁后再查一次：其它请求可能已经完成同一快照物化。
            current_st_version = self._st_input_version(run_date)
            if self._fresh_cur(
                cur, run_date, profile_id, version, ph, current_st_version
            ):
                return self._read_board_cur(cur, run_date, profile_id, version)

            for attempt in range(2):
                before_st_version = self._st_input_version(run_date)
                df = score_day(self.mkt, run_date, profile)
                after_st_version = self._st_input_version(run_date)
                if before_st_version == after_st_version:
                    break
                log.warning(
                    "评分快照计算期间 ST 输入变化，准备重试 %s/%s v%d attempt=%d",
                    run_date,
                    profile_id,
                    version,
                    attempt + 1,
                )
            else:
                from backend.services.stock_st_status import STStatusNotReadyError

                raise STStatusNotReadyError(
                    "ST 输入在评分快照计算期间持续变化，请稍后重试"
                )

            self._replace_snapshot_cur(
                cur,
                run_date,
                profile_id,
                version,
                df,
                ph,
                before_st_version,
            )
            log.info("评分快照物化 %s/%s v%d → %d 只", run_date, profile_id, version, len(df))
            return df

    def _replace_snapshot_cur(self, cur, run_date: date, profile_id: str, version: int,
                              df: pd.DataFrame, ph: str, st_version: str) -> None:
        cur.execute(
            "DELETE FROM score_snapshot WHERE trade_date=%s AND profile_id=%s AND profile_version=%s "
            "AND tenant_id=%s AND owner_user_id=%s",
            [run_date, profile_id, version, *self._op])
        if not df.empty:
            rows = [
                (
                    run_date,
                    self.tenant_id,
                    self.owner_user_id,
                    profile_id,
                    version,
                    r.code,
                    float(r.total_score),
                    str(r.grade),
                    int(r.rank),
                    r.sub_scores,
                )
                for r in df.itertuples(index=False)
            ]
            cur.executemany(
                "INSERT INTO score_snapshot "
                "(trade_date, tenant_id, owner_user_id, profile_id, profile_version, code, "
                "total_score, grade, rank, sub_scores) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id, owner_user_id, trade_date, profile_id, profile_version, code) "
                "DO UPDATE SET total_score=EXCLUDED.total_score, grade=EXCLUDED.grade, "
                "rank=EXCLUDED.rank, sub_scores=EXCLUDED.sub_scores",
                rows,
            )
        cur.execute(
            "INSERT INTO score_snapshot_meta "
            "(trade_date,profile_id,profile_version,tenant_id,owner_user_id,computed_at,"
            "stale,n_codes,param_hash,st_input_version) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (tenant_id, owner_user_id, trade_date, profile_id, profile_version) "
            "DO UPDATE SET computed_at=EXCLUDED.computed_at, stale=EXCLUDED.stale, "
            "n_codes=EXCLUDED.n_codes,param_hash=EXCLUDED.param_hash,"
            "st_input_version=EXCLUDED.st_input_version",
            [run_date, profile_id, version, self.tenant_id, self.owner_user_id,
             datetime.now(UTC).replace(tzinfo=None), False, len(df), ph, st_version])

    # ── 显式结果维护（惰性标记，不重算）；共享行情口径 → 全局失效 ──
    def mark_stale_dates(self, trade_dates: list[date]) -> int:
        """按用户选定的交易日标记所有方案版本、所有归属者快照失效。"""
        dates = [d for d in trade_dates if d is not None]
        if not dates:
            return 0
        ph = ",".join(["%s"] * len(dates))
        before = self.pg.query_df(
            f"SELECT count(*) AS n FROM score_snapshot_meta WHERE trade_date IN ({ph}) AND stale=false", dates)
        self.pg.execute(
            f"UPDATE score_snapshot_meta SET stale=true WHERE trade_date IN ({ph})", dates)
        n = int(before.iloc[0]["n"]) if not before.empty else 0
        if n:
            log.info("评分快照标记失效：%d 个交易日×方案 → stale（待生产/读取重算）", n)
        return n

    def mark_stale_all(self) -> int:
        """按用户选定的“全部快照”范围标记失效，返回受影响行数。"""
        before = self.pg.query_df("SELECT count(*) AS n FROM score_snapshot_meta WHERE stale=false")
        self.pg.execute("UPDATE score_snapshot_meta SET stale=true")
        n = int(before.iloc[0]["n"]) if not before.empty else 0
        if n:
            log.info("评分快照全部标记失效：%d 个交易日×方案 → stale（待生产/读取重算）", n)
        return n

    def stats(self) -> dict:
        df = self.pg.query_df(
            "SELECT count(*) AS metas, sum(CASE WHEN stale THEN 1 ELSE 0 END) AS stale_n, "
            "sum(n_codes) AS rows FROM score_snapshot_meta")
        r = df.iloc[0]
        return {"materialized_day_profiles": int(r["metas"] or 0),
                "stale": int(r["stale_n"] or 0), "snapshot_rows": int(r["rows"] or 0)}
