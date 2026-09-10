"""Coverage gate, immutable publication and invalidation for limit-up ladder snapshots."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from uuid import uuid4

import pandas as pd

from backend.market_rules import CloseLimitStatus, listing_board_for
from backend.services.limit_ladder_calculator import (
    LimitLadderCalculation,
    LimitLadderCalculator,
)
from backend.storage.duckdb_client import DuckDBClient, get_client

RULE_VERSION = "limit-ladder-v2"
SOURCE_VERSION = "duckdb-eod-v1"
TERMINAL_STATUSES = frozenset({"success", "partial", "failed", "unknown"})


@dataclass(frozen=True, slots=True)
class LimitLadderCoverage:
    pool_count: int
    valid_bar_count: int
    confirmed_suspension_count: int
    missing_count: int
    invalid_bar_count: int
    unsupported_rule_count: int
    ingest_terminal_status: str
    ingest_run_id: str | None
    reason_codes: tuple[str, ...]
    sample_codes: tuple[str, ...]
    checked_at: str
    upstream_fingerprint: str
    st_input_version: str

    @property
    def ready(self) -> bool:
        closed = self.pool_count == (
            self.valid_bar_count
            + self.confirmed_suspension_count
            + self.missing_count
            + self.invalid_bar_count
            + self.unsupported_rule_count
        )
        return closed and not self.reason_codes

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        payload["sample_codes"] = list(self.sample_codes)
        return payload


@dataclass(frozen=True, slots=True)
class LimitLadderSnapshotOutcome:
    status: str
    snapshot_id: str | None
    coverage: LimitLadderCoverage


class LimitLadderSnapshotService:
    """Own the date-level gate and atomic pointer switch for ladder snapshots."""

    def __init__(self, client: DuckDBClient | None = None):
        self.c = client or get_client()

    def check_coverage(self, trade_date: date) -> LimitLadderCoverage:
        from backend.services.stock_st_status import StockSTStatusService

        st_service = StockSTStatusService(self.c)
        st_input_version = st_service.input_version_through(trade_date)
        checked_at = self._now().isoformat()
        calendar_rows = self.c.query_df(
            "SELECT trade_date FROM trade_calendar WHERE trade_date=? AND is_open",
            [trade_date],
        )
        if calendar_rows.empty:
            return LimitLadderCoverage(
                pool_count=0,
                valid_bar_count=0,
                confirmed_suspension_count=0,
                missing_count=0,
                invalid_bar_count=0,
                unsupported_rule_count=0,
                ingest_terminal_status="unknown",
                ingest_run_id=None,
                reason_codes=("NOT_TRADING_DAY",),
                sample_codes=(),
                checked_at=checked_at,
                upstream_fingerprint=self._fingerprint({"trade_date": str(trade_date)}),
                st_input_version=st_input_version,
            )

        calendar = self._calendar_through(trade_date)
        basics = self.c.query_df(
            """
            SELECT code,name,board,list_date,delist_date,industry,price_limit_pct
            FROM stock_basic
            WHERE list_date IS NOT NULL AND list_date<=?
              AND (delist_date IS NULL OR delist_date>=?)
            ORDER BY code
            """,
            [trade_date, trade_date],
        )
        basic_by_code = {
            str(row["code"]): row
            for _, row in basics.iterrows()
            if listing_board_for(
                board=LimitLadderCalculator._text(row.get("board")), code=str(row["code"])
            )
            is not None
        }
        codes = sorted(basic_by_code)
        facts = self._selected_facts(codes, trade_date)
        terminal_status, run_id = self._latest_terminal(trade_date)

        valid = suspended = missing = invalid = unsupported = 0
        st_not_ready = 0
        samples: list[str] = []
        fingerprint_rows: list[dict] = []
        calculator = LimitLadderCalculator(self.c)
        for code in codes:
            fact = facts.get(code)
            basic = basic_by_code[code]
            if fact is None:
                missing += 1
                self._sample(samples, code)
                fingerprint_rows.append({"code": code, "fact": "missing"})
                continue
            if calculator._bool_value(fact.get("confirmed_suspension")):
                suspended += 1
                fingerprint_rows.append({"code": code, "fact": "suspended"})
                continue
            if calculator._bool_value(fact.get("is_suspended")):
                missing += 1
                self._sample(samples, code)
                fingerprint_rows.append({"code": code, "fact": "unconfirmed_suspension"})
                continue
            if pd.isna(fact.get("st_source")) or fact.get("st_quality") != "accurate":
                st_not_ready += 1
                invalid += 1
                self._sample(samples, code)
                fingerprint_rows.append({"code": code, "fact": "st_status_not_ready"})
                continue
            if not self._valid_ohlc(fact):
                invalid += 1
                self._sample(samples, code)
                fingerprint_rows.append({"code": code, "fact": "invalid_ohlc"})
                continue
            result, st_status = calculator.evaluate_fact(
                code=code,
                basic=basic,
                fact=fact,
                calendar=calendar,
            )
            if result.status is CloseLimitStatus.INVALID_PRICE:
                invalid += 1
                self._sample(samples, code)
            elif result.status is CloseLimitStatus.UNSUPPORTED_RULE:
                unsupported += 1
                self._sample(samples, code)
            else:
                valid += 1
            fingerprint_rows.append(
                {
                    "code": code,
                    "name": LimitLadderCalculator._text(basic.get("name")),
                    "board": LimitLadderCalculator._text(basic.get("board")),
                    "list_date": str(LimitLadderCalculator._date_value(basic.get("list_date"))),
                    "industry": LimitLadderCalculator._text(basic.get("industry")),
                    "price_limit_pct": self._json_value(basic.get("price_limit_pct")),
                    "open": self._json_value(fact.get("open")),
                    "high": self._json_value(fact.get("high")),
                    "low": self._json_value(fact.get("low")),
                    "close": self._json_value(fact.get("close")),
                    "pre_close": self._json_value(fact.get("pre_close")),
                    "amount": self._json_value(fact.get("amount")),
                    "is_one_word": self._json_value(fact.get("is_one_word")),
                    "st": st_status.is_st,
                    "st_source": st_status.source,
                    "st_source_ref": st_status.source_ref,
                    "st_quality": st_status.quality.value,
                    "status": result.status.value,
                }
            )

        reasons: list[str] = []
        if not codes:
            reasons.append("POINT_IN_TIME_POOL_EMPTY")
        if terminal_status in {"partial", "failed"} and missing:
            reasons.append("INGEST_PARTIAL")
        if missing:
            reasons.append("MISSING_BAR_OR_SUSPENSION")
        if invalid:
            reasons.append("INVALID_DAILY_BAR")
        if unsupported:
            reasons.append("UNSUPPORTED_LIMIT_RULE")
        if st_not_ready:
            reasons.append("ST_STATUS_NOT_READY")
        concepts = self._concept_fingerprint(codes, trade_date)
        industries = self._industry_fingerprint()
        fingerprint = self._fingerprint(
            {
                "trade_date": str(trade_date),
                "terminal_status": terminal_status,
                "facts": fingerprint_rows,
                "concepts": concepts,
                "industries": industries,
            }
        )
        return LimitLadderCoverage(
            pool_count=len(codes),
            valid_bar_count=valid,
            confirmed_suspension_count=suspended,
            missing_count=missing,
            invalid_bar_count=invalid,
            unsupported_rule_count=unsupported,
            ingest_terminal_status=terminal_status,
            ingest_run_id=run_id,
            reason_codes=tuple(reasons),
            sample_codes=tuple(samples),
            checked_at=checked_at,
            upstream_fingerprint=fingerprint,
            st_input_version=st_input_version,
        )

    def materialize(
        self,
        trade_date: date,
        *,
        task_id: str | None = None,
        window: int = 31,
    ) -> LimitLadderSnapshotOutcome:
        self.begin(trade_date, task_id=task_id)
        coverage = self.check_coverage(trade_date)
        if not coverage.ready:
            self.mark_invalid(
                trade_date,
                reason=",".join(coverage.reason_codes) or "COVERAGE_NOT_READY",
                task_id=task_id,
                fingerprint=coverage.upstream_fingerprint,
            )
            return LimitLadderSnapshotOutcome("invalid", None, coverage)
        try:
            calculation = LimitLadderCalculator(self.c).calculate(trade_date, window=window)
            snapshot_id = self.publish(calculation, coverage=coverage, task_id=task_id)
            return LimitLadderSnapshotOutcome("valid", snapshot_id, coverage)
        except Exception as exc:
            self.mark_failed(trade_date, summary=str(exc), task_id=task_id)
            raise

    def begin(self, trade_date: date, *, task_id: str | None = None) -> str:
        current = self.c.query_df(
            "SELECT current_snapshot_id FROM limit_ladder_snapshot_state WHERE trade_date=?",
            [trade_date],
        )
        status = (
            "recalculating"
            if not current.empty and pd.notna(current.iloc[0]["current_snapshot_id"])
            else "calculating"
        )
        self.c.execute(
            """
            INSERT INTO limit_ladder_snapshot_state (
                trade_date,status,current_snapshot_id,last_success_at,task_id,rule_version,
                upstream_fingerprint,failure_summary,invalid_reason,updated_at
            ) VALUES (?, ?, NULL, NULL, ?, ?, NULL, NULL, NULL, ?)
            ON CONFLICT (trade_date) DO UPDATE SET
                status=EXCLUDED.status,task_id=EXCLUDED.task_id,
                rule_version=EXCLUDED.rule_version,failure_summary=NULL,
                invalid_reason=NULL,updated_at=EXCLUDED.updated_at
            """,
            [trade_date, status, task_id, RULE_VERSION, self._now()],
        )
        return status

    def publish(
        self,
        calculation: LimitLadderCalculation,
        *,
        coverage: LimitLadderCoverage,
        task_id: str | None = None,
    ) -> str:
        if not coverage.ready:
            raise ValueError("cannot publish an incomplete limit ladder coverage")
        snapshot_id = uuid4().hex
        now = self._now()
        stocks = pd.DataFrame(
            [
                {
                    "snapshot_id": snapshot_id,
                    "code": stock.code,
                    "name": stock.name,
                    "board": stock.board,
                    "price_limit_pct": stock.price_limit_pct,
                    "is_st": stock.is_st,
                    "st_quality": stock.st_quality,
                    "st_source": stock.st_source,
                    "is_one_word": stock.is_one_word,
                    "consecutive_days": stock.consecutive_days,
                    "amount": stock.amount,
                    "industry_name": stock.industry_name,
                    "industry_board_code": stock.industry_board_code,
                    "source_version": SOURCE_VERSION,
                }
                for stock in calculation.stocks
            ],
            columns=[
                "snapshot_id",
                "code",
                "name",
                "board",
                "price_limit_pct",
                "is_st",
                "st_quality",
                "st_source",
                "is_one_word",
                "consecutive_days",
                "amount",
                "industry_name",
                "industry_board_code",
                "source_version",
            ],
        )
        concepts = pd.DataFrame(
            [
                {
                    "snapshot_id": snapshot_id,
                    "code": stock.code,
                    "board_code": concept.board_code,
                    "board_name": concept.board_name,
                    "source_version": SOURCE_VERSION,
                }
                for stock in calculation.stocks
                for concept in stock.concepts
            ],
            columns=["snapshot_id", "code", "board_code", "board_name", "source_version"],
        )
        aggregates = pd.DataFrame(
            [
                {
                    "snapshot_id": snapshot_id,
                    "group_type": item.group_type,
                    "group_key": item.group_key,
                    "group_name": item.group_name,
                    "stock_count": item.stock_count,
                }
                for item in calculation.aggregates
            ],
            columns=["snapshot_id", "group_type", "group_key", "group_name", "stock_count"],
        )
        window_calculations = LimitLadderCalculator(self.c).calculate_all_window_metrics(
            calculation.trade_date, [stock.code for stock in calculation.stocks]
        )
        window_metrics = pd.DataFrame(
            [
                {
                    "snapshot_id": snapshot_id,
                    "code": metric.code,
                    "window_days": window,
                    "window_limit_up_days": metric.window_limit_up_days,
                    "window_return_pct": metric.window_return_pct,
                    "window_start_date": metric.window_start_date,
                    "actual_trade_days": metric.actual_trade_days,
                    "source_version": SOURCE_VERSION,
                }
                for window, window_calculation in window_calculations.items()
                for metric in window_calculation.stocks
            ],
            columns=[
                "snapshot_id",
                "code",
                "window_days",
                "window_limit_up_days",
                "window_return_pct",
                "window_start_date",
                "actual_trade_days",
                "source_version",
            ],
        )
        window_metadata_json = json.dumps(
            {
                str(window): {
                    "requested_window_start_date": (
                        window_calculation.requested_window_start_date.isoformat()
                    ),
                    "requested_window_trade_days": (window_calculation.requested_window_trade_days),
                }
                for window, window_calculation in window_calculations.items()
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        coverage_json = json.dumps(coverage.to_dict(), ensure_ascii=False, sort_keys=True)
        with self.c.transaction():
            latest_coverage = self.check_coverage(calculation.trade_date)
            if (
                not latest_coverage.ready
                or latest_coverage.upstream_fingerprint != coverage.upstream_fingerprint
                or latest_coverage.st_input_version != coverage.st_input_version
            ):
                raise RuntimeError("limit ladder upstream changed during calculation")
            self.c.execute(
                """
                INSERT INTO limit_ladder_snapshot (
                    snapshot_id,trade_date,rule_version,computed_at,stock_count,
                    has_approx_st,coverage_json,window_metadata_json,source_version,
                    st_input_version
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    snapshot_id,
                    calculation.trade_date,
                    RULE_VERSION,
                    now,
                    len(calculation.stocks),
                    any(stock.st_quality == "approximate" for stock in calculation.stocks),
                    coverage_json,
                    window_metadata_json,
                    SOURCE_VERSION,
                    coverage.st_input_version,
                ],
            )
            self._insert_frame("limit_ladder_snapshot_stock", stocks)
            self._insert_frame("limit_ladder_snapshot_concept", concepts)
            self._insert_frame("limit_ladder_snapshot_aggregate", aggregates)
            self._insert_frame("limit_ladder_snapshot_window_metric", window_metrics)
            self.c.execute(
                """
                INSERT INTO limit_ladder_snapshot_state (
                    trade_date,status,current_snapshot_id,last_success_at,task_id,rule_version,
                    upstream_fingerprint,st_input_version,failure_summary,invalid_reason,updated_at
                ) VALUES (?, 'valid', ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
                ON CONFLICT (trade_date) DO UPDATE SET
                    status='valid',current_snapshot_id=EXCLUDED.current_snapshot_id,
                    last_success_at=EXCLUDED.last_success_at,task_id=EXCLUDED.task_id,
                    rule_version=EXCLUDED.rule_version,
                    upstream_fingerprint=EXCLUDED.upstream_fingerprint,
                    st_input_version=EXCLUDED.st_input_version,
                    failure_summary=NULL,invalid_reason=NULL,updated_at=EXCLUDED.updated_at
                """,
                [
                    calculation.trade_date,
                    snapshot_id,
                    now,
                    task_id,
                    RULE_VERSION,
                    coverage.upstream_fingerprint,
                    coverage.st_input_version,
                    now,
                ],
            )
        return snapshot_id

    def invalidate_dates(self, trade_dates: list[date], *, reason: str) -> int:
        dates = sorted({self._date(value) for value in trade_dates if value is not None})
        if not dates:
            return 0
        affected_from = dates[0]
        with self.c.transaction():
            before = self.c.query_df(
                """
                SELECT count(*) AS n FROM limit_ladder_snapshot_state state
                WHERE state.trade_date>=? AND state.current_snapshot_id IS NOT NULL
                  AND state.status NOT IN ('calculating','recalculating','invalid')
                """,
                [affected_from],
            )
            self.c.execute(
                """
                UPDATE limit_ladder_snapshot_state AS state
                SET status='invalid',invalid_reason=?,failure_summary=NULL,updated_at=?
                WHERE state.trade_date>=? AND state.current_snapshot_id IS NOT NULL
                  AND state.status NOT IN ('calculating','recalculating')
                """,
                [reason, self._now(), affected_from],
            )
        return int(before.iloc[0]["n"])

    def invalidate_all(self, *, reason: str) -> int:
        rows = self.c.query_df(
            "SELECT trade_date FROM limit_ladder_snapshot_state WHERE current_snapshot_id IS NOT NULL"
        )
        return self.invalidate_dates(
            [
                self._date(value)
                for value in rows.get("trade_date", pd.Series(dtype=object)).tolist()
            ],
            reason=reason,
        )

    def request_invalidation(self, trade_dates: list[date] | None, *, reason: str) -> int:
        """Persist the intent first, then atomically invalidate and close the event."""
        dates = sorted({self._date(value) for value in (trade_dates or []) if value is not None})
        event_id = uuid4().hex
        now = self._now()
        self.c.execute(
            """
            INSERT INTO limit_ladder_invalidation_outbox (
                event_id,affected_from,reason,status,attempt_count,last_error,
                created_at,updated_at,completed_at
            ) VALUES (?,?,?,'pending',0,NULL,?,?,NULL)
            """,
            [event_id, dates[0] if dates else None, reason, now, now],
        )
        return self.process_pending_invalidations()

    def process_pending_invalidations(self) -> int:
        rows = self.c.query_df(
            "SELECT event_id,affected_from,reason FROM limit_ladder_invalidation_outbox "
            "WHERE status='pending' ORDER BY created_at,event_id"
        )
        total = 0
        for row in rows.to_dict("records"):
            try:
                with self.c.transaction():
                    affected_from = row.get("affected_from")
                    if affected_from is None or pd.isna(affected_from):
                        count_row = self.c.query_df(
                            "SELECT count(*) AS n FROM limit_ladder_snapshot_state "
                            "WHERE current_snapshot_id IS NOT NULL "
                            "AND status NOT IN ('calculating','recalculating','invalid')"
                        )
                        self.c.execute(
                            "UPDATE limit_ladder_snapshot_state SET status='invalid',"
                            "invalid_reason=?,failure_summary=NULL,updated_at=? "
                            "WHERE current_snapshot_id IS NOT NULL "
                            "AND status NOT IN ('calculating','recalculating')",
                            [row["reason"], self._now()],
                        )
                    else:
                        affected_from = self._date(affected_from)
                        count_row = self.c.query_df(
                            "SELECT count(*) AS n FROM limit_ladder_snapshot_state "
                            "WHERE trade_date>=? AND current_snapshot_id IS NOT NULL "
                            "AND status NOT IN ('calculating','recalculating','invalid')",
                            [affected_from],
                        )
                        self.c.execute(
                            "UPDATE limit_ladder_snapshot_state SET status='invalid',"
                            "invalid_reason=?,failure_summary=NULL,updated_at=? "
                            "WHERE trade_date>=? AND current_snapshot_id IS NOT NULL "
                            "AND status NOT IN ('calculating','recalculating')",
                            [row["reason"], self._now(), affected_from],
                        )
                    self.c.execute(
                        "UPDATE limit_ladder_invalidation_outbox SET status='completed',"
                        "attempt_count=attempt_count+1,last_error=NULL,updated_at=?,completed_at=? "
                        "WHERE event_id=?",
                        [self._now(), self._now(), row["event_id"]],
                    )
                    total += int(count_row.iloc[0]["n"])
            except Exception as exc:
                self.c.execute(
                    "UPDATE limit_ladder_invalidation_outbox SET attempt_count=attempt_count+1,"
                    "last_error=?,updated_at=? WHERE event_id=?",
                    [str(exc)[:1000], self._now(), row["event_id"]],
                )
                raise RuntimeError(f"limit ladder invalidation pending: {row['event_id']}") from exc
        return total

    def mark_invalid(
        self,
        trade_date: date,
        *,
        reason: str,
        task_id: str | None = None,
        fingerprint: str | None = None,
    ) -> None:
        self._set_terminal_state(
            trade_date,
            status="invalid",
            task_id=task_id,
            fingerprint=fingerprint,
            failure=None,
            invalid_reason=reason,
        )

    def mark_failed(self, trade_date: date, *, summary: str, task_id: str | None = None) -> None:
        self._set_terminal_state(
            trade_date,
            status="failed",
            task_id=task_id,
            fingerprint=None,
            failure=summary[:1000],
            invalid_reason=None,
        )

    def recover_processing_after_restart(self) -> int:
        """Close every in-memory processing state after process restart, preserving old snapshots."""
        return self._fail_processing_states(
            summary="服务重启中断，等待重新创建计算任务",
        )

    def recover_interrupted_task(self, task_id: str, *, summary: str) -> int:
        """Close a processing state when its persisted task has reached a failure terminal state."""
        if not task_id.strip():
            return 0
        return self._fail_processing_states(task_id=task_id, summary=summary)

    def _fail_processing_states(self, *, summary: str, task_id: str | None = None) -> int:
        where = "status IN ('calculating','recalculating')"
        params: list[object] = [summary[:1000], self._now()]
        if task_id is not None:
            where += " AND task_id=?"
            params.append(task_id)
        before = self.c.query_df(
            f"SELECT count(*) AS n FROM limit_ladder_snapshot_state WHERE {where}",
            ([] if task_id is None else [task_id]),
        )
        self.c.execute(
            f"""
            UPDATE limit_ladder_snapshot_state
            SET status='failed',failure_summary=?,invalid_reason=NULL,updated_at=?
            WHERE {where}
            """,
            params,
        )
        return int(before.iloc[0]["n"])

    def _set_terminal_state(
        self,
        trade_date: date,
        *,
        status: str,
        task_id: str | None,
        fingerprint: str | None,
        failure: str | None,
        invalid_reason: str | None,
    ) -> None:
        self.c.execute(
            """
            INSERT INTO limit_ladder_snapshot_state (
                trade_date,status,current_snapshot_id,last_success_at,task_id,rule_version,
                upstream_fingerprint,failure_summary,invalid_reason,updated_at
            ) VALUES (?,?,NULL,NULL,?,?,?, ?,?,?)
            ON CONFLICT (trade_date) DO UPDATE SET
                status=EXCLUDED.status,task_id=EXCLUDED.task_id,
                rule_version=EXCLUDED.rule_version,
                upstream_fingerprint=COALESCE(EXCLUDED.upstream_fingerprint,
                                              limit_ladder_snapshot_state.upstream_fingerprint),
                failure_summary=EXCLUDED.failure_summary,
                invalid_reason=EXCLUDED.invalid_reason,updated_at=EXCLUDED.updated_at
            """,
            [
                trade_date,
                status,
                task_id,
                RULE_VERSION,
                fingerprint,
                failure,
                invalid_reason,
                self._now(),
            ],
        )

    def _selected_facts(self, codes: list[str], trade_date: date) -> dict[str, dict]:
        if not codes:
            return {}
        frame = pd.DataFrame({"code": codes})
        with self.c.temp_view(frame, "ladder_gate_codes") as view:
            rows = self.c.query_df(
                f"""
                SELECT b.code,b.trade_date,b.open,b.high,b.low,b.close,b.pre_close,
                       b.amount,b.is_suspended,b.is_one_word,
                       st.is_st AS point_is_st,st.source AS st_source,
                       st.source_ref AS st_source_ref,st.quality AS st_quality,
                       (s.trade_date IS NOT NULL) AS confirmed_suspension
                FROM daily_bar b
                JOIN {view} codes ON codes.code=b.code
                LEFT JOIN stock_st_status_daily st
                  ON st.code=b.code AND st.trade_date=b.trade_date
                LEFT JOIN stock_suspension s
                  ON s.code=b.code AND s.trade_date=b.trade_date
                WHERE b.trade_date=?
                UNION ALL
                SELECT s.code,s.trade_date,NULL,NULL,NULL,NULL,NULL,NULL,TRUE,NULL,
                       st.is_st,st.source,st.source_ref,st.quality,TRUE
                FROM stock_suspension s
                JOIN {view} codes ON codes.code=s.code
                LEFT JOIN stock_st_status_daily st
                  ON st.code=s.code AND st.trade_date=s.trade_date
                WHERE s.trade_date=? AND NOT EXISTS (
                    SELECT 1 FROM daily_bar b
                    WHERE b.code=s.code AND b.trade_date=s.trade_date
                )
                """,
                [trade_date, trade_date],
            )
        return {str(row["code"]): row.to_dict() for _, row in rows.iterrows()}

    def _latest_terminal(self, trade_date: date) -> tuple[str, str | None]:
        rows = self.c.query_df(
            """
            SELECT status,detail FROM data_update_log
            WHERE table_name='daily_bar' AND source='pipeline'
              AND date_start=? AND date_end=?
            ORDER BY updated_at DESC,id DESC
            """,
            [trade_date, trade_date],
        )
        for _, row in rows.iterrows():
            try:
                detail = json.loads(str(row["detail"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(detail, dict) or detail.get("kind") != "market_day_terminal":
                continue
            status = str(detail.get("status") or row["status"])
            if status not in TERMINAL_STATUSES:
                continue
            try:
                expected = int(detail["expected"])
                successful = int(detail["successful"])
                failed = int(detail["failed"])
            except (KeyError, TypeError, ValueError):
                continue
            if expected < 0 or successful < 0 or failed < 0:
                continue
            if status == "success" and (successful < expected or failed > 0):
                status = "partial" if successful > 0 else "failed"
            run_id = detail.get("run_id")
            return status, None if run_id is None else str(run_id)
        return "unknown", None

    def _concept_fingerprint(
        self, codes: list[str], trade_date: date
    ) -> list[tuple[str, str, str]]:
        if not codes:
            return []
        frame = pd.DataFrame({"code": codes})
        with self.c.temp_view(frame, "ladder_concept_codes") as view:
            rows = self.c.query_df(
                f"""
                SELECT bm.code,bd.board_code,bd.name
                FROM board_member bm
                JOIN {view} codes ON codes.code=bm.code
                JOIN board_dict bd ON bd.board_code=bm.board_code
                WHERE bd.board_type='concept'
                  AND (bm.first_seen_date IS NULL OR bm.first_seen_date<=?)
                ORDER BY bm.code,bd.board_code,bd.name
                """,
                [trade_date],
            )
        return [
            (str(row["code"]), str(row["board_code"]), str(row["name"]))
            for _, row in rows.iterrows()
        ]

    def _industry_fingerprint(self) -> list[tuple[str, str]]:
        rows = self.c.query_df(
            "SELECT board_code,name FROM board_dict "
            "WHERE board_type='industry' ORDER BY board_code,name"
        )
        return [(str(row["board_code"]), str(row["name"])) for _, row in rows.iterrows()]

    def _insert_frame(self, table: str, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        with self.c.temp_view(frame, f"publish_{table}") as view:
            columns = ",".join(frame.columns)
            self.c.execute(f"INSERT INTO {table} ({columns}) SELECT {columns} FROM {view}")

    def _calendar_through(self, trade_date: date) -> list[date]:
        rows = self.c.query_df(
            "SELECT trade_date FROM trade_calendar WHERE is_open AND trade_date<=? ORDER BY trade_date",
            [trade_date],
        )
        return [self._date(value) for value in rows["trade_date"].tolist()]

    @staticmethod
    def _sample(samples: list[str], code: str) -> None:
        if len(samples) < 20 and code not in samples:
            samples.append(code)

    @staticmethod
    def _valid_ohlc(fact: dict) -> bool:
        try:
            open_price = float(fact.get("open"))
            high = float(fact.get("high"))
            low = float(fact.get("low"))
            close = float(fact.get("close"))
        except (TypeError, ValueError):
            return False
        # IPO 无涨跌幅限制期允许 pre_close 为空；是否必须有有效昨收由后续统一
        # 市场规则判定。这里仅校验当日本身的 OHLC，避免在识别 IPO 规则之前误拦截。
        values = (open_price, high, low, close)
        return (
            all(math.isfinite(value) and value > 0 for value in values)
            and high >= max(open_price, close, low)
            and low <= min(open_price, close, high)
        )

    @staticmethod
    def _fingerprint(payload: dict) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _json_value(value):
        if value is None or pd.isna(value):
            return None
        if hasattr(value, "item"):
            value = value.item()
        return value

    @staticmethod
    def _date(value) -> date:
        return pd.Timestamp(value).date()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
