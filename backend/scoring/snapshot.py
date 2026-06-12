"""评分快照层（SDD §10.1，M2.6）——按 日期+方案+版本 惰性物化全市场评分榜。

统一各入口（每日榜单 / 试运行 / 回测排名 / 评分验证）的打分口径，避免重复实时计算。
- 惰性物化：首次请求某 (日期, 方案, 版本) → 整天打分一次落 score_snapshot + 写 meta(stale=false)。
- 惰性失效（关键）：行情数据变更只把 score_snapshot_meta 标 stale=true（便宜），**不立即重算**；
  下次 get 时若 meta 缺失或 stale → 当场重算覆盖、meta 置 false 再返回，否则直接用缓存。
- 口径与回测 `_decision_data` 一致：wide_snapshot 单日 + 排除 ST + ScoreProfileModel（表达式型指标补列）。
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pandas as pd

from backend.common.logging import get_logger
from backend.storage.duckdb_client import get_client

log = get_logger("scoring.snapshot")

_COLS = ["code", "total_score", "grade", "rank", "sub_scores"]


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
    st = set(c.query_df("SELECT code FROM stock_basic WHERE name LIKE '%ST%'")["code"])
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
    def __init__(self, client=None):
        self.c = client or get_client()
        from backend.storage.ddl import init_db
        init_db(self.c)

    def _profile(self, profile_id: str) -> dict | None:
        from backend.scoring.score_profile import ScoreProfileRepo
        return ScoreProfileRepo(self.c).get(profile_id)

    def get_board(self, run_date: date, profile_id: str, top: int | None = None,
                  profile: dict | None = None) -> pd.DataFrame:
        """惰性取某日某方案评分榜（降序）。命中且未失效→用缓存；否则重算并落库。

        profile 可注入以省一次查询（须含 version/items）；否则按 profile_id 现查当前版本。
        """
        prof = profile or self._profile(profile_id)
        if not prof:
            return pd.DataFrame(columns=_COLS)
        version = int(prof.get("version") or 1)
        if self._fresh(run_date, profile_id, version):
            rows = self.c.query_df(
                "SELECT code, total_score, grade, rank, sub_scores FROM score_snapshot "
                "WHERE trade_date=? AND profile_id=? AND profile_version=? ORDER BY rank",
                [run_date, profile_id, version])
        else:
            rows = self._materialize(run_date, profile_id, version, prof)
        return rows.head(top) if top else rows

    def _fresh(self, run_date: date, profile_id: str, version: int) -> bool:
        m = self.c.query_df(
            "SELECT stale FROM score_snapshot_meta WHERE trade_date=? AND profile_id=? AND profile_version=?",
            [run_date, profile_id, version])
        return (not m.empty) and (not bool(m.iloc[0]["stale"]))

    def _materialize(self, run_date: date, profile_id: str, version: int, profile: dict) -> pd.DataFrame:
        """重算该日该方案 → 覆盖 score_snapshot 明细 + 刷新 meta(stale=false)。"""
        from backend.storage.repository import MarketRepository
        df = score_day(self.c, run_date, profile)
        self.c.execute(
            "DELETE FROM score_snapshot WHERE trade_date=? AND profile_id=? AND profile_version=?",
            [run_date, profile_id, version])
        if not df.empty:
            rows = df.copy()
            rows.insert(0, "trade_date", run_date)
            rows.insert(1, "profile_id", profile_id)
            rows.insert(2, "profile_version", version)
            MarketRepository(self.c).upsert("score_snapshot", rows)
        self.c.execute(
            "DELETE FROM score_snapshot_meta WHERE trade_date=? AND profile_id=? AND profile_version=?",
            [run_date, profile_id, version])
        self.c.execute(
            "INSERT INTO score_snapshot_meta (trade_date, profile_id, profile_version, computed_at, stale, n_codes) "
            "VALUES (?,?,?,?,?,?)",
            [run_date, profile_id, version, datetime.now(), False, int(len(df))])
        log.info("评分快照物化 %s/%s v%d → %d 只", run_date, profile_id, version, len(df))
        return df

    # ── 失效（惰性标记，不重算）──
    def mark_stale_dates(self, trade_dates: list[date]) -> int:
        """触发器1：行情数据变更后，把这些交易日的**所有方案版本**快照标记失效。返回受影响行数。"""
        dates = [d for d in trade_dates if d is not None]
        if not dates:
            return 0
        ph = ",".join("?" * len(dates))
        before = self.c.query_df(
            f"SELECT count(*) n FROM score_snapshot_meta WHERE trade_date IN ({ph}) AND stale=false", dates)
        self.c.execute(
            f"UPDATE score_snapshot_meta SET stale=true WHERE trade_date IN ({ph})", dates)
        n = int(before.iloc[0]["n"]) if not before.empty else 0
        if n:
            log.info("评分快照标记失效：%d 个交易日×方案 → stale（待下次读取重算）", n)
        return n

    def mark_stale_all(self) -> int:
        """触发器1（粗粒度）：数据全量变更（补数/重算）后标记全部快照失效。返回受影响行数。"""
        before = self.c.query_df("SELECT count(*) n FROM score_snapshot_meta WHERE stale=false")
        self.c.execute("UPDATE score_snapshot_meta SET stale=true")
        n = int(before.iloc[0]["n"]) if not before.empty else 0
        if n:
            log.info("评分快照全部标记失效：%d 个交易日×方案 → stale", n)
        return n

    def stats(self) -> dict:
        df = self.c.query_df(
            "SELECT count(*) AS metas, sum(CASE WHEN stale THEN 1 ELSE 0 END) AS stale_n, "
            "sum(n_codes) AS rows FROM score_snapshot_meta")
        r = df.iloc[0]
        return {"materialized_day_profiles": int(r["metas"] or 0),
                "stale": int(r["stale_n"] or 0), "snapshot_rows": int(r["rows"] or 0)}
