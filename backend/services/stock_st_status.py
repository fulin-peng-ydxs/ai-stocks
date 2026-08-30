"""Point-in-time ST fact persistence and immutable change tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import uuid4

import pandas as pd

from backend.limit_ladder.rules import PointInTimeSTStatus, STStatusQuality
from backend.storage.duckdb_client import DuckDBClient, get_client


@dataclass(frozen=True, slots=True)
class StockSTStatusFact:
    """One stock's resolved ST status on one market date."""

    code: str
    trade_date: date
    status: PointInTimeSTStatus


class StockSTStatusService:
    """Batch-upsert current facts and append history only for real changes."""

    def __init__(self, client: DuckDBClient | None = None):
        self.c = client or get_client()

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

        deduplicated: dict[tuple[str, date], StockSTStatusFact] = {}
        for raw in facts:
            fact = self._normalized(raw)
            key = (fact.code, fact.trade_date)
            previous = deduplicated.get(key)
            if previous is not None and previous.status != fact.status:
                raise ValueError(f"conflicting ST facts in one batch: {fact.code} {fact.trade_date}")
            deduplicated[key] = fact

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
            if changed_keys:
                affected_dates = pd.DataFrame(
                    {"trade_date": sorted({trade_date for _, trade_date in changed_keys})}
                )
                with self.c.temp_view(affected_dates, "st_changed_dates") as affected_view:
                    self.c.execute(
                        f"""
                        UPDATE limit_ladder_snapshot_state AS state
                        SET status='invalid',invalid_reason='st_status_changed',
                            failure_summary=NULL,updated_at=?
                        FROM {affected_view} affected
                        WHERE state.trade_date=affected.trade_date
                          AND state.current_snapshot_id IS NOT NULL
                          AND state.status NOT IN ('calculating','recalculating')
                        """,
                        [now],
                    )
        return sorted({trade_date for _, trade_date in changed_keys})
