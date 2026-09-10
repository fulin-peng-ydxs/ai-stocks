"""Point-in-time ST fact persistence and immutable change tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import uuid4

import pandas as pd

from backend.common.exceptions import DataQualityError
from backend.limit_ladder.rules import PointInTimeSTStatus, STStatusQuality
from backend.storage.duckdb_client import DuckDBClient, get_client


@dataclass(frozen=True, slots=True)
class StockSTStatusFact:
    """One stock's resolved ST status on one market date."""

    code: str
    trade_date: date
    status: PointInTimeSTStatus


class STStatusNotReadyError(DataQualityError):
    """Requested business scope has no complete, accurate point-in-time ST facts."""


class StockSTStatusService:
    """Batch-upsert current facts and append history only for real changes."""

    def __init__(self, client: DuckDBClient | None = None):
        self.c = client or get_client()

    def begin_refresh(
        self,
        *,
        task_id: str | None,
        target_count: int,
        start: date | None,
        end: date | None,
    ) -> None:
        """Close the publication gate while a batch refresh can expose mixed vintages."""
        self.c.execute(
            """
            INSERT INTO stock_st_status_refresh_state (
                scope_key,status,task_id,target_count,date_start,date_end,last_error,updated_at
            ) VALUES ('market','refreshing',?,?,?,?,NULL,?)
            ON CONFLICT (scope_key) DO UPDATE SET
                status='refreshing',task_id=EXCLUDED.task_id,
                target_count=EXCLUDED.target_count,date_start=EXCLUDED.date_start,
                date_end=EXCLUDED.date_end,last_error=NULL,updated_at=EXCLUDED.updated_at
            """,
            [task_id, target_count, start, end, datetime.now(UTC).replace(tzinfo=None)],
        )

    def finish_refresh(self, *, ready: bool, error: str | None = None) -> None:
        self.c.execute(
            """
            UPDATE stock_st_status_refresh_state
            SET status=?,last_error=?,updated_at=CURRENT_TIMESTAMP
            WHERE scope_key='market'
            """,
            ["ready" if ready else "failed", None if ready else (error or "ST 刷新未完整完成")[:500]],
        )

    def refresh_state(self) -> dict | None:
        rows = self.c.query_df(
            "SELECT status,task_id,target_count,date_start,date_end,last_error,updated_at "
            "FROM stock_st_status_refresh_state WHERE scope_key='market'"
        )
        if rows.empty:
            return None
        row = rows.iloc[0]
        return {
            "status": str(row["status"]),
            "task_id": None if pd.isna(row["task_id"]) else str(row["task_id"]),
            "target_count": int(row["target_count"]),
            "date_start": None if pd.isna(row["date_start"]) else str(row["date_start"])[:10],
            "date_end": None if pd.isna(row["date_end"]) else str(row["date_end"])[:10],
            "last_error": None if pd.isna(row["last_error"]) else str(row["last_error"]),
            "updated_at": None if pd.isna(row["updated_at"]) else str(row["updated_at"])[:19],
        }

    def assert_published(self) -> None:
        """Reject business reads while the latest refresh batch is not published."""
        state = self.refresh_state()
        if state and state["status"] != "ready":
            detail = f"：{state['last_error']}" if state.get("last_error") else ""
            raise STStatusNotReadyError(
                f"ST 点时事实批次状态为 {state['status']}{detail}；"
                "请等待或重新运行“ST状态刷新”"
            )

    @staticmethod
    def _normalized(fact: StockSTStatusFact) -> StockSTStatusFact:
        code = fact.code.strip()
        source = fact.status.source.strip()
        if not code or not source:
            raise ValueError("ST fact requires code and source")
        quality = STStatusQuality(fact.status.quality)
        return StockSTStatusFact(
            code=code,
            trade_date=fact.trade_date,
            status=PointInTimeSTStatus(
                is_st=bool(fact.status.is_st),
                source=source,
                source_ref=fact.status.source_ref,
                quality=quality,
            ),
        )

    @classmethod
    def _deduplicated(
        cls, facts: list[StockSTStatusFact]
    ) -> dict[tuple[str, date], StockSTStatusFact]:
        deduplicated: dict[tuple[str, date], StockSTStatusFact] = {}
        for raw in facts:
            fact = cls._normalized(raw)
            key = (fact.code, fact.trade_date)
            previous = deduplicated.get(key)
            if previous is not None and previous.status != fact.status:
                raise ValueError(f"conflicting ST facts in one batch: {fact.code} {fact.trade_date}")
            deduplicated[key] = fact
        return deduplicated

    def prefer_existing_accurate(
        self, facts: list[StockSTStatusFact]
    ) -> list[StockSTStatusFact]:
        """Keep authoritative stored facts when an ordinary approximate batch overlaps them."""
        deduplicated = self._deduplicated(facts)
        if not deduplicated:
            return []
        keys = pd.DataFrame(
            [
                {"code": code, "trade_date": trade_date}
                for code, trade_date in deduplicated
            ]
        )
        with self.c.temp_view(keys, "st_fact_keys") as view:
            existing = self.c.query_df(
                f"""
                SELECT current.code,current.trade_date,current.is_st,current.source,
                       current.source_ref,current.quality
                FROM stock_st_status_daily current
                JOIN {view} incoming
                  ON current.code=incoming.code AND current.trade_date=incoming.trade_date
                WHERE current.quality='accurate'
                """
            )
        for _, row in existing.iterrows():
            key = (str(row["code"]), pd.Timestamp(row["trade_date"]).date())
            incoming = deduplicated[key]
            if incoming.status.quality != STStatusQuality.APPROXIMATE:
                continue
            deduplicated[key] = StockSTStatusFact(
                code=key[0],
                trade_date=key[1],
                status=PointInTimeSTStatus(
                    is_st=bool(row["is_st"]),
                    source=str(row["source"]),
                    source_ref=(
                        None if pd.isna(row["source_ref"]) else str(row["source_ref"])
                    ),
                    quality=STStatusQuality.ACCURATE,
                ),
            )
        return list(deduplicated.values())

    def upsert_facts(
        self,
        facts: list[StockSTStatusFact],
        *,
        change_reason: str,
        task_id: str | None = None,
        captured_at: datetime | None = None,
    ) -> list[date]:
        """Persist a batch atomically and return dates whose effective fact changed."""
        if not facts:
            return []
        if not change_reason.strip():
            raise ValueError("change_reason is required")

        deduplicated = self._deduplicated(facts)

        now = captured_at or datetime.now(UTC).replace(tzinfo=None)
        rows = [
            {
                "code": fact.code,
                "trade_date": fact.trade_date,
                "is_st": fact.status.is_st,
                "source": fact.status.source,
                "source_ref": fact.status.source_ref,
                "quality": fact.status.quality.value,
                "captured_at": now,
                "updated_at": now,
            }
            for fact in deduplicated.values()
        ]
        incoming = pd.DataFrame(rows)

        with self.c.transaction(), self.c.temp_view(incoming, "st_status") as view:
            existing = self.c.query_df(
                f"""
                SELECT incoming.code, incoming.trade_date,
                       current.is_st AS old_is_st,
                       current.source AS old_source,
                       current.source_ref AS old_source_ref,
                       current.quality AS old_quality
                FROM {view} incoming
                LEFT JOIN stock_st_status_daily current
                  ON current.code=incoming.code AND current.trade_date=incoming.trade_date
                """
            )
            changed_keys: set[tuple[str, date]] = set()
            history_rows: list[dict] = []
            for _, old in existing.iterrows():
                key = (str(old["code"]), pd.Timestamp(old["trade_date"]).date())
                new = deduplicated[key]
                is_new = pd.isna(old["old_source"])
                # 质量只能由 approximate 升为 accurate。普通采集无权把已存在的
                # 权威事实降级；显式降级若未来确有业务需求，必须另建带审计的管理入口。
                if (
                    not is_new
                    and str(old["old_quality"]) == STStatusQuality.ACCURATE.value
                    and new.status.quality == STStatusQuality.APPROXIMATE
                ):
                    continue
                old_ref = None if pd.isna(old["old_source_ref"]) else str(old["old_source_ref"])
                changed = is_new or (
                    bool(old["old_is_st"]) != new.status.is_st
                    or str(old["old_source"]) != new.status.source
                    or old_ref != new.status.source_ref
                    or str(old["old_quality"]) != new.status.quality.value
                )
                if not changed:
                    continue
                changed_keys.add(key)
                if not is_new:
                    history_rows.append(
                        {
                            "version_id": uuid4().hex,
                            "code": new.code,
                            "trade_date": new.trade_date,
                            "old_is_st": bool(old["old_is_st"]),
                            "new_is_st": new.status.is_st,
                            "old_source": str(old["old_source"]),
                            "new_source": new.status.source,
                            "old_source_ref": old_ref,
                            "new_source_ref": new.status.source_ref,
                            "old_quality": str(old["old_quality"]),
                            "new_quality": new.status.quality.value,
                            "change_reason": change_reason,
                            "changed_at": now,
                            "task_id": task_id,
                        }
                    )

            if changed_keys:
                changed_df = incoming[
                    incoming.apply(
                        lambda row: (str(row["code"]), pd.Timestamp(row["trade_date"]).date())
                        in changed_keys,
                        axis=1,
                    )
                ]
                with self.c.temp_view(changed_df, "changed_st_status") as changed_view:
                    self.c.execute(
                        f"""
                        INSERT INTO stock_st_status_daily (
                            code, trade_date, is_st, source, source_ref, quality,
                            captured_at, updated_at
                        )
                        SELECT code, trade_date, is_st, source, source_ref, quality,
                               captured_at, updated_at
                        FROM {changed_view}
                        ON CONFLICT (code, trade_date) DO UPDATE SET
                            is_st=EXCLUDED.is_st,
                            source=EXCLUDED.source,
                            source_ref=EXCLUDED.source_ref,
                            quality=EXCLUDED.quality,
                            updated_at=EXCLUDED.updated_at
                        """
                    )
            if history_rows:
                history = pd.DataFrame(history_rows)
                with self.c.temp_view(history, "st_history") as history_view:
                    self.c.execute(
                        f"""
                        INSERT INTO stock_st_status_history (
                            version_id, code, trade_date, old_is_st, new_is_st,
                            old_source, new_source, old_source_ref, new_source_ref,
                            old_quality, new_quality, change_reason, changed_at, task_id
                        )
                        SELECT version_id, code, trade_date, old_is_st, new_is_st,
                               old_source, new_source, old_source_ref, new_source_ref,
                               old_quality, new_quality, change_reason, changed_at, task_id
                        FROM {history_view}
                        """
                    )
        return sorted({trade_date for _, trade_date in changed_keys})

    def status_map(
        self,
        trade_date: date,
        codes: list[str],
        *,
        require_accurate: bool = True,
    ) -> dict[str, bool]:
        """Return point-in-time ST flags and fail closed on missing/degraded facts.

        Business consumers must call this instead of inferring historical status from the
        current security name.  A partial map is never returned because silently treating
        a missing row as non-ST changes both the universe and the legal price-limit band.
        """
        normalized = sorted({str(code).strip() for code in codes if str(code).strip()})
        if not normalized:
            return {}
        self.assert_published()
        frame = pd.DataFrame({"code": normalized})
        with self.c.temp_view(frame, "st_read_codes") as view:
            rows = self.c.query_df(
                f"""
                SELECT wanted.code,current.is_st,current.quality,current.source
                FROM {view} wanted
                LEFT JOIN stock_st_status_daily current
                  ON current.code=wanted.code AND current.trade_date=?
                ORDER BY wanted.code
                """,
                [trade_date],
            )
        missing = rows[rows["source"].isna()]["code"].astype(str).tolist()
        approximate = rows[
            rows["source"].notna() & (rows["quality"] != STStatusQuality.ACCURATE.value)
        ]["code"].astype(str).tolist()
        if missing or (require_accurate and approximate):
            details = []
            if missing:
                details.append(f"缺失 {len(missing)}（示例 {','.join(missing[:5])}）")
            if require_accurate and approximate:
                details.append(f"非权威 {len(approximate)}（示例 {','.join(approximate[:5])}）")
            raise STStatusNotReadyError(
                f"{trade_date} ST 点时事实未就绪：{'；'.join(details)}；"
                "请运行个股采集中的“ST状态刷新”后重试"
            )
        return {
            str(row["code"]): bool(row["is_st"])
            for _, row in rows.iterrows()
            if not pd.isna(row["source"])
        }

    def coverage(self, start: date | None = None, end: date | None = None) -> dict:
        """Summarize canonical ST coverage against stored daily bars."""
        where = []
        params: list = []
        if start is not None:
            where.append("b.trade_date>=?")
            params.append(start)
        if end is not None:
            where.append("b.trade_date<=?")
            params.append(end)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        row = self.c.query_df(
            f"""
            SELECT count(*) AS expected,
                   count(st.code) AS present,
                   count(*) FILTER (WHERE st.quality='accurate') AS accurate,
                   count(*) FILTER (WHERE st.quality='approximate') AS approximate,
                   min(st.trade_date) AS first_date,max(st.trade_date) AS latest_date,
                   max(st.updated_at) AS updated_at
            FROM daily_bar b
            LEFT JOIN stock_st_status_daily st
              ON st.code=b.code AND st.trade_date=b.trade_date
            {clause}
            """,
            params,
        ).iloc[0]
        expected = int(row["expected"])
        accurate = int(row["accurate"])
        refresh_state = self.refresh_state()
        published = refresh_state is None or refresh_state["status"] == "ready"
        return {
            "expected": expected,
            "present": int(row["present"]),
            "accurate": accurate,
            "approximate": int(row["approximate"]),
            "missing": expected - int(row["present"]),
            "coverage_rate": round(accurate / expected * 100, 2) if expected else 100.0,
            "ready": expected == accurate and published,
            "first_date": None if pd.isna(row["first_date"]) else str(row["first_date"])[:10],
            "latest_date": None if pd.isna(row["latest_date"]) else str(row["latest_date"])[:10],
            "updated_at": None if pd.isna(row["updated_at"]) else str(row["updated_at"])[:19],
            "refresh_state": refresh_state,
        }

    def sync_daily_bar_projection(self, dates: list[date] | None = None) -> int:
        """Synchronize the transitional daily_bar.is_st projection from the canonical table."""
        if dates:
            frame = pd.DataFrame({"trade_date": sorted(set(dates))})
            with self.c.temp_view(frame, "st_sync_dates") as view:
                changed = self.c.query_df(
                    f"""
                    SELECT count(*) AS n FROM daily_bar b
                    JOIN stock_st_status_daily st
                      ON st.code=b.code AND st.trade_date=b.trade_date
                    JOIN {view} d ON d.trade_date=b.trade_date
                    WHERE b.is_st IS DISTINCT FROM st.is_st
                    """
                ).iloc[0]["n"]
                self.c.execute(
                    f"""
                    UPDATE daily_bar AS b SET is_st=st.is_st
                    FROM stock_st_status_daily st,{view} d
                    WHERE st.code=b.code AND st.trade_date=b.trade_date
                      AND d.trade_date=b.trade_date
                      AND b.is_st IS DISTINCT FROM st.is_st
                    """
                )
                return int(changed)
        changed = self.c.query_df(
            """
            SELECT count(*) AS n FROM daily_bar b
            JOIN stock_st_status_daily st
              ON st.code=b.code AND st.trade_date=b.trade_date
            WHERE b.is_st IS DISTINCT FROM st.is_st
            """
        ).iloc[0]["n"]
        self.c.execute(
            """
            UPDATE daily_bar AS b SET is_st=st.is_st
            FROM stock_st_status_daily st
            WHERE st.code=b.code AND st.trade_date=b.trade_date
              AND b.is_st IS DISTINCT FROM st.is_st
            """
        )
        return int(changed)

    def rebuild_daily_bar_markers(
        self,
        *,
        codes: list[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> int:
        """Rebuild every ST-dependent daily marker in one set-based operation.

        A global refresh keeps the publication gate closed until this statement completes,
        so consumers can never observe a partially rebuilt marker set. The price-limit SQL
        comes from the same module as Python matching and quality checks.
        """
        from backend.market_rules import price_limit_pct_sql

        pct = price_limit_pct_sql("sb.price_limit_pct", "st.is_st", "b.trade_date")
        up = f"floor((b.pre_close*(1+({pct})))*100+0.5)/100"
        down = f"floor((b.pre_close*(1-({pct})))*100+0.5)/100"
        status = (
            f"CASE WHEN b.close>=({up})-0.0001 THEN 1 "
            f"WHEN b.close<=({down})+0.0001 THEN -1 ELSE 0 END"
        )
        where = [
            "st.code=b.code",
            "st.trade_date=b.trade_date",
            "st.quality='accurate'",
            "sb.code=b.code",
        ]
        params: list = []
        if start is not None:
            where.append("b.trade_date>=?")
            params.append(start)
        if end is not None:
            where.append("b.trade_date<=?")
            params.append(end)

        normalized_codes = sorted(
            {str(code).strip() for code in (codes or []) if str(code).strip()}
        )
        code_frame = pd.DataFrame({"code": normalized_codes}) if normalized_codes else None

        def run(code_view: str | None = None) -> int:
            scoped_where = list(where)
            if code_view:
                scoped_where.append(f"EXISTS (SELECT 1 FROM {code_view} wanted WHERE wanted.code=b.code)")
            clause = " AND ".join(scoped_where)
            count = int(
                self.c.query_df(
                    "SELECT count(*) AS n FROM daily_bar b,stock_st_status_daily st,"
                    f"stock_basic sb WHERE {clause}",
                    params,
                ).iloc[0]["n"]
            )
            self.c.execute(
                f"""
                UPDATE daily_bar AS b SET
                    is_st=st.is_st,
                    is_suspended=FALSE,
                    limit_status={status},
                    is_one_word=COALESCE(
                        b.open=b.high AND b.high=b.low AND b.low=b.close
                        AND ({status})<>0,
                        FALSE
                    )
                FROM stock_st_status_daily st,stock_basic sb
                WHERE {clause}
                """,
                params,
            )
            return count

        if code_frame is not None:
            with self.c.temp_view(code_frame, "st_marker_codes") as view:
                return run(view)
        return run()

    def dataset_version(self, start: date | None = None, end: date | None = None) -> str:
        """Stable signature material for reproducible backtests."""
        coverage = self.coverage(start, end)
        return ":".join(
            [
                str(coverage["updated_at"] or "none"),
                str(coverage["expected"]),
                str(coverage["accurate"]),
                str(coverage["missing"]),
            ]
        )
