"""Published limit-ladder snapshot query, filtering and CSV read model."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Literal

import pandas as pd

from backend.common.logging import get_logger
from backend.services.limit_ladder_calculator import SUPPORTED_WINDOWS
from backend.services.limit_ladder_snapshot import RULE_VERSION, LimitLadderSnapshotService
from backend.services.limit_ladder_task_coordinator import LimitLadderTaskCoordinator
from backend.services.stock_board_correlation import StockBoardCorrelationService
from backend.storage.duckdb_client import DuckDBClient, get_client

log = get_logger("services.limit_ladder_query")

BOARD_ALIASES = {
    "main": "主板",
    "主板": "主板",
    "star": "科创板",
    "科创板": "科创板",
    "gem": "创业板",
    "chinext": "创业板",
    "创业板": "创业板",
}
SUPPORTED_BOARDS = frozenset(BOARD_ALIASES)
SUPPORTED_HOTSPOT_TYPES = frozenset({"industry", "concept"})


@dataclass(frozen=True, slots=True)
class LimitLadderFilters:
    """Normalized filters shared by JSON queries and CSV export."""

    window: int = 31
    boards: tuple[str, ...] = ()
    ignore_st: bool = True
    one_word_only: bool = False
    keyword: str | None = None
    hotspot_type: Literal["industry", "concept"] | None = None
    hotspot_key: str | None = None

    def validate(self) -> None:
        if self.window not in SUPPORTED_WINDOWS:
            raise ValueError(f"window must be one of {sorted(SUPPORTED_WINDOWS)}")
        invalid = sorted(set(self.boards) - SUPPORTED_BOARDS)
        if invalid:
            raise ValueError(f"unsupported boards: {','.join(invalid)}")
        if (self.hotspot_type is None) != (self.hotspot_key is None):
            raise ValueError("hotspot_type and hotspot_key must be provided together")
        if self.hotspot_type is not None and self.hotspot_type not in SUPPORTED_HOTSPOT_TYPES:
            raise ValueError("hotspot_type must be industry or concept")


class LimitLadderQueryService:
    """Read immutable snapshot facts and enrich only explicitly dynamic fields."""

    def __init__(
        self,
        client: DuckDBClient | None = None,
        *,
        coordinator: LimitLadderTaskCoordinator | None = None,
    ):
        self.c = client or get_client()
        self._coordinator = coordinator

    @property
    def coordinator(self) -> LimitLadderTaskCoordinator:
        if self._coordinator is None:
            self._coordinator = LimitLadderTaskCoordinator()
        return self._coordinator

    def trade_dates(self, *, limit: int = 250) -> dict[str, Any]:
        """Return selectable market dates and an explicit latest-readiness result."""
        rows = self.c.query_df(
            """
            SELECT c.trade_date
            FROM trade_calendar c
            WHERE c.is_open
              AND c.trade_date<=(SELECT max(trade_date) FROM daily_bar)
            ORDER BY c.trade_date DESC LIMIT ?
            """,
            [limit],
        )
        dates = [self._date(value) for value in rows.get("trade_date", []).tolist()]
        dates = [value for value in dates if value is not None]
        candidate = dates[0] if dates else None
        coverage = None
        if candidate is not None:
            coverage = LimitLadderSnapshotService(self.c).check_coverage(candidate).to_dict()
        latest_valid = self.c.query_df(
            "SELECT max(trade_date) AS trade_date FROM limit_ladder_snapshot_state "
            "WHERE status='valid' AND current_snapshot_id IS NOT NULL"
        )
        valid_date = None if latest_valid.empty else self._date(latest_valid.iloc[0]["trade_date"])
        latest_complete = candidate if coverage and not coverage["reason_codes"] else valid_date
        return {
            "dates": [value.isoformat() for value in dates],
            "latest_candidate_date": self._iso(candidate),
            "latest_complete_date": self._iso(latest_complete),
            "latest_candidate_coverage": coverage,
            "latest_candidate_ready": bool(coverage and not coverage["reason_codes"]),
        }

    def status(self, trade_date: date) -> dict[str, Any]:
        """Expose snapshot and task states without creating a new task."""
        LimitLadderSnapshotService(self.c).process_pending_invalidations()
        if not self._is_open_date(trade_date):
            return self._not_trading_day(trade_date)
        row = self._current_rule_state(trade_date)
        task = self._active_task(trade_date)
        if row is None:
            return {
                "trade_date": trade_date.isoformat(),
                "business_code": "SNAPSHOT_PENDING" if task else "SNAPSHOT_MISSING",
                "snapshot_status": "calculating" if task else "missing",
                "stored_snapshot_status": "missing",
                "has_snapshot": False,
                "task": task,
            }
        has_snapshot = bool(row.get("current_snapshot_id"))
        stored_status = str(row["status"])
        public_status = (
            "recalculating" if task and has_snapshot else ("calculating" if task else stored_status)
        )
        return {
            "trade_date": trade_date.isoformat(),
            "business_code": self._state_business_code(public_status, has_snapshot),
            "snapshot_status": public_status,
            "stored_snapshot_status": stored_status,
            "has_snapshot": has_snapshot,
            "current_snapshot_id": self._nullable_text(row.get("current_snapshot_id")),
            "last_success_at": self._iso(row.get("last_success_at")),
            "failure_summary": self._nullable_text(row.get("failure_summary")),
            "invalid_reason": self._nullable_text(row.get("invalid_reason")),
            "updated_at": self._iso(row.get("updated_at")),
            "task": task,
        }

    def query(
        self,
        trade_date: date,
        filters: LimitLadderFilters,
        *,
        auth_context=None,
        request=None,
        trigger_missing: bool = True,
    ) -> dict[str, Any]:
        filters.validate()
        if not self._is_open_date(trade_date):
            return self._not_trading_day(trade_date)

        LimitLadderSnapshotService(self.c).process_pending_invalidations()
        state = self._current_rule_state(trade_date)
        task_error = None
        ensured_task = None
        stored_status = None if state is None else str(state.get("status"))
        coverage_gate = None
        orphaned_processing = bool(
            state is not None
            and stored_status in {"calculating", "recalculating"}
            and self._active_task(trade_date) is None
        )
        if trigger_missing and stored_status == "invalid":
            coverage_gate = LimitLadderSnapshotService(self.c).check_coverage(trade_date)
        should_trigger = trigger_missing and (
            state is None
            or (stored_status == "invalid" and coverage_gate is not None and coverage_gate.ready)
            or orphaned_processing
        )
        if should_trigger:
            source = (
                "auto_invalid_refresh"
                if state is not None
                and (
                    str(state.get("status")) == "invalid"
                    or state.get("current_snapshot_id") is not None
                )
                else "auto_first_load"
            )
            try:
                ensured_task = self.coordinator.ensure_date_task(
                    trade_date,
                    source=source,
                    auth_context=auth_context,
                    request=request,
                )
            except Exception as exc:  # noqa: BLE001 -- old snapshot must survive task failures
                task_error = "任务创建失败，请稍后重试"
                log.warning("天梯日期任务创建失败 date=%s: %s", trade_date, exc)
            state = self._state_row(trade_date)

        status = self.status(trade_date)
        if coverage_gate is not None and not coverage_gate.ready:
            status["coverage"] = coverage_gate.to_dict()
        if ensured_task is not None and status.get("task") is None:
            has_snapshot = bool(state and state.get("current_snapshot_id"))
            status["task"] = {
                "command_id": ensured_task.command_id,
                "task_id": ensured_task.task_id,
                "status": ensured_task.status,
                "source": source,
                "progress": None,
                "message": None,
            }
            status["stored_snapshot_status"] = status["snapshot_status"]
            status["snapshot_status"] = "recalculating" if has_snapshot else "calculating"
            status["business_code"] = "SNAPSHOT_STALE" if has_snapshot else "SNAPSHOT_PENDING"
        if task_error:
            status["task_error"] = task_error
        snapshot_id = (
            None if state is None else self._nullable_text(state.get("current_snapshot_id"))
        )
        if snapshot_id is None:
            return {
                **status,
                "filters": asdict(filters),
                "snapshot": None,
                "requested_window_start_date": None,
                "requested_window_trade_days": 0,
                "dynamic_window_status": "unavailable",
                "summary": {"stock_count": 0, "highest_board": None, "first_board_count": 0},
                "hotspots": {"industry": [], "concept": []},
                "layers": [],
            }

        snapshot, stocks = self._load_snapshot(snapshot_id)
        requested_start, requested_days, metrics, dynamic_status = self._window_metrics(
            snapshot_id, filters.window, snapshot
        )
        concepts = self._snapshot_concepts(snapshot_id)
        related, related_status = self._related_boards_for_date(
            [str(row["code"]) for row in stocks], trade_date
        )
        enriched = []
        for stock in stocks:
            code = str(stock["code"])
            metric = metrics.get(code, {})
            enriched.append(
                {
                    **self._json_row(stock),
                    "window_limit_up_days": metric.get("window_limit_up_days"),
                    "window_return_pct": metric.get("window_return_pct"),
                    "window_start_date": metric.get("window_start_date"),
                    "actual_trade_days": metric.get("actual_trade_days"),
                    "snapshot_concepts": concepts.get(code, []),
                    "latest_related_industry": related.get(code, {}).get("industry"),
                    "latest_related_concept": related.get(code, {}).get("concept"),
                }
            )
        visible = self._filter(enriched, filters)
        visible.sort(
            key=lambda stock: (
                -int(stock["consecutive_days"]),
                -(
                    int(stock["window_limit_up_days"])
                    if stock["window_limit_up_days"] is not None
                    else -1
                ),
                -float(stock["amount"]),
                str(stock["code"]),
            )
        )
        summary = self._summary(visible)
        business_code = status["business_code"]
        if snapshot["stock_count"] == 0:
            business_code = "EMPTY_SNAPSHOT"
        elif not visible:
            business_code = "FILTER_EMPTY"
        return {
            **status,
            "business_code": business_code,
            "filters": asdict(filters),
            "snapshot": snapshot,
            "coverage": snapshot["coverage"],
            "requested_window_start_date": requested_start,
            "requested_window_trade_days": requested_days,
            "dynamic_window_status": dynamic_status,
            "related_board_status": related_status,
            "related_concept_status": related_status,
            "summary": summary,
            "hotspots": self._hotspots(visible),
            "layers": self._layers(visible),
        }

    def _current_rule_state(self, trade_date: date):
        row = self._state_row(trade_date)
        if (
            row is not None
            and row.get("current_snapshot_id")
            and str(row.get("rule_version")) != RULE_VERSION
            and str(row.get("status")) not in {"calculating", "recalculating"}
        ):
            LimitLadderSnapshotService(self.c).mark_invalid(
                trade_date, reason="rule_version_changed"
            )
            row = self._state_row(trade_date)
        return row

    def export_csv(self, trade_date: date, filters: LimitLadderFilters) -> tuple[str, bytes]:
        """Export exactly the same normalized, filtered stock collection as query()."""
        data = self.query(trade_date, filters, trigger_missing=False)
        if data.get("snapshot") is None:
            raise ValueError(str(data.get("business_code") or "SNAPSHOT_NOT_AVAILABLE"))
        stocks = [stock for layer in data["layers"] for stock in layer["stocks"]]
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "交易日",
                "代码",
                "名称",
                "板块",
                "连续板",
                "窗口涨停次数",
                "窗口累计涨幅",
                "窗口起始日",
                "实际交易日",
                "涨跌停比例",
                "ST",
                "ST质量",
                "一字板",
                "成交额",
                "快照行业",
                "快照概念",
                "最新相关概念",
                "相关概念代码",
                "相关概念截止日",
                "快照状态",
                "快照计算时间",
            ]
        )
        for stock in stocks:
            related = stock.get("latest_related_concept") or {}
            writer.writerow(
                [
                    self._csv_cell(value)
                    for value in [
                        trade_date.isoformat(),
                        stock["code"],
                        stock["name"],
                        stock["board"],
                        stock["consecutive_days"],
                        stock["window_limit_up_days"],
                        stock["window_return_pct"],
                        stock["window_start_date"],
                        stock["actual_trade_days"],
                        stock["price_limit_pct"],
                        "是" if stock["is_st"] else "否",
                        stock["st_quality"],
                        "是" if stock["is_one_word"] else "否",
                        stock["amount"],
                        stock["industry_name"],
                        "、".join(item["board_name"] for item in stock["snapshot_concepts"]),
                        related.get("board_name", ""),
                        related.get("board_code", ""),
                        related.get("as_of_date", ""),
                        data["snapshot_status"],
                        data["snapshot"]["computed_at"],
                    ]
                ]
            )
        filename = f"limit-ladder-{trade_date.isoformat()}-{filters.window}d.csv"
        return filename, output.getvalue().encode("utf-8-sig")

    def _window_metrics(self, snapshot_id: str, window: int, snapshot: dict[str, Any]):
        metadata = snapshot.get("window_metadata", {}).get(str(window), {})
        rows = self.c.query_df(
            "SELECT code,window_limit_up_days,window_return_pct,window_start_date,"
            "actual_trade_days FROM limit_ladder_snapshot_window_metric "
            "WHERE snapshot_id=? AND window_days=? ORDER BY code",
            [snapshot_id, window],
        )
        if rows.empty:
            status = (
                "ready"
                if int(snapshot.get("stock_count") or 0) == 0 and metadata
                else ("unavailable")
            )
            return (
                metadata.get("requested_window_start_date"),
                int(metadata.get("requested_window_trade_days") or 0),
                {},
                status,
            )
        metrics = {
            str(row["code"]): {
                "window_limit_up_days": int(row["window_limit_up_days"]),
                "window_return_pct": (
                    None
                    if pd.isna(row.get("window_return_pct"))
                    else float(row["window_return_pct"])
                ),
                "window_start_date": self._date(row["window_start_date"]).isoformat(),
                "actual_trade_days": int(row["actual_trade_days"]),
            }
            for row in rows.to_dict("records")
        }
        return (
            metadata.get("requested_window_start_date"),
            int(metadata.get("requested_window_trade_days") or 0),
            metrics,
            "ready",
        )

    def _load_snapshot(self, snapshot_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        meta = self.c.query_df(
            "SELECT * FROM limit_ladder_snapshot WHERE snapshot_id=?", [snapshot_id]
        )
        if meta.empty:
            raise RuntimeError("snapshot state points to a missing version")
        snapshot = self._json_row(meta.iloc[0].to_dict())
        raw_coverage = snapshot.pop("coverage_json", None)
        snapshot["coverage"] = self._parse_json(raw_coverage)
        raw_window_metadata = snapshot.pop("window_metadata_json", None)
        snapshot["window_metadata"] = self._parse_json(raw_window_metadata)
        rows = self.c.query_df(
            "SELECT * EXCLUDE (snapshot_id) FROM limit_ladder_snapshot_stock "
            "WHERE snapshot_id=? ORDER BY consecutive_days DESC,amount DESC,code",
            [snapshot_id],
        )
        return snapshot, rows.to_dict("records")

    def _snapshot_concepts(self, snapshot_id: str) -> dict[str, list[dict[str, str]]]:
        rows = self.c.query_df(
            "SELECT code,board_code,board_name FROM limit_ladder_snapshot_concept "
            "WHERE snapshot_id=? ORDER BY code,board_name,board_code",
            [snapshot_id],
        )
        result: dict[str, list[dict[str, str]]] = {}
        for row in rows.to_dict("records"):
            result.setdefault(str(row["code"]), []).append(
                {"board_code": str(row["board_code"]), "board_name": str(row["board_name"])}
            )
        return result

    def _related_boards_for_date(self, codes: list[str], trade_date: date):
        """读取天梯业务日的同日快照；缺档时只排队首次任务，不在请求内同步计算。"""
        if not codes:
            return {}, "ready"
        try:
            summaries = StockBoardCorrelationService(self.c).get_related_boards(codes, trade_date)
            result: dict[str, dict[str, dict[str, str]]] = {}
            missing = False
            pending = False
            for code, summary in summaries.items():
                if not summary:
                    missing = True
                    continue
                unavailable_reason = summary.get("unavailable_reason")
                if unavailable_reason:
                    pending = pending or unavailable_reason == "first_load_pending"
                    missing = True
                    continue
                as_of_date = str(summary["as_of_date"])
                for board_type in ("industry", "concept"):
                    winner = summary.get(board_type)
                    if winner is None:
                        continue
                    result.setdefault(code, {})[board_type] = {
                        "board_code": str(winner["board_code"]),
                        "board_name": str(winner["name"]),
                        "as_of_date": as_of_date,
                    }
            if pending:
                return result, "calculating"
            return result, "partial" if missing else "ready"
        except Exception as exc:  # noqa: BLE001 -- correlation is optional enrichment
            log.warning("天梯业务日相关行业/概念查询降级 date=%s: %s", trade_date, exc)
            return {}, "degraded"

    @staticmethod
    def _filter(stocks: list[dict[str, Any]], filters: LimitLadderFilters) -> list[dict[str, Any]]:
        keyword = (filters.keyword or "").strip().casefold()
        boards = {BOARD_ALIASES[board] for board in filters.boards}
        result = []
        for stock in stocks:
            if boards and stock["board"] not in boards:
                continue
            if filters.ignore_st and stock["is_st"]:
                continue
            if filters.one_word_only and not stock["is_one_word"]:
                continue
            if (
                keyword
                and keyword not in str(stock["code"]).casefold()
                and keyword not in str(stock["name"]).casefold()
            ):
                continue
            if filters.hotspot_type == "industry":
                related = stock.get("latest_related_industry")
                key = related.get("board_code") if related else "__unclassified__"
                if key != filters.hotspot_key:
                    continue
            if filters.hotspot_type == "concept":
                related = stock.get("latest_related_concept")
                concept_key = related.get("board_code") if related else "__unclassified__"
                if concept_key != filters.hotspot_key:
                    continue
            result.append(stock)
        return result

    @staticmethod
    def _summary(stocks: list[dict[str, Any]]) -> dict[str, int | None]:
        heights = [int(stock["consecutive_days"]) for stock in stocks]
        return {
            "stock_count": len(stocks),
            "highest_board": max(heights) if heights else None,
            "first_board_count": sum(height == 1 for height in heights),
        }

    @staticmethod
    def _layers(stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        layers: dict[int, list[dict[str, Any]]] = {}
        for stock in stocks:
            layers.setdefault(int(stock["consecutive_days"]), []).append(stock)
        return [
            {"consecutive_days": height, "stock_count": len(values), "stocks": values}
            for height, values in sorted(layers.items(), reverse=True)
        ]

    @staticmethod
    def _hotspots(stocks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        counts: dict[tuple[str, str, str], int] = {}
        for stock in stocks:
            # 顶部两类热点都使用天梯业务日的同日走势相关冠军；快照归属事实不参与热点聚合。
            for kind in ("industry", "concept"):
                related = stock.get(f"latest_related_{kind}") or {
                    "board_code": "__unclassified__",
                    "board_name": "未分类",
                }
                key = (kind, str(related["board_code"]), str(related["board_name"]))
                counts[key] = counts.get(key, 0) + 1
        result = {"industry": [], "concept": []}
        for (kind, key, name), count in sorted(
            counts.items(), key=lambda item: (item[0][0], -item[1], item[0][2], item[0][1])
        ):
            result[kind].append({"group_key": key, "group_name": name, "stock_count": count})
        return result

    def _active_task(self, trade_date: date) -> dict[str, Any] | None:
        try:
            command = self.coordinator.repository.get_active_for_date(trade_date)
            if command is None:
                return None
            task_id = self._nullable_text(command.get("task_id"))
            runtime = self.coordinator.tasks.get(task_id) if task_id else None
            if runtime is not None and str(runtime.get("status")) not in {"pending", "running"}:
                return None
            return {
                "command_id": str(command["command_id"]),
                "task_id": task_id,
                "status": str(command["status"]),
                "source": str(command["source"]),
                "progress": None if runtime is None else runtime.get("progress"),
                "message": None if runtime is None else runtime.get("message"),
            }
        except Exception as exc:  # noqa: BLE001 -- task status is optional enrichment
            log.warning("天梯活动任务状态查询降级 date=%s: %s", trade_date, exc)
            return None

    def _state_row(self, trade_date: date) -> dict[str, Any] | None:
        rows = self.c.query_df(
            "SELECT * FROM limit_ladder_snapshot_state WHERE trade_date=?", [trade_date]
        )
        if rows.empty:
            return None
        row = rows.iloc[0].to_dict()
        return {key: (None if pd.isna(value) else value) for key, value in row.items()}

    def _is_open_date(self, trade_date: date) -> bool:
        rows = self.c.query_df(
            "SELECT count(*) AS n FROM trade_calendar WHERE trade_date=? AND is_open", [trade_date]
        )
        return bool(int(rows.iloc[0]["n"]))

    def _not_trading_day(self, trade_date: date) -> dict[str, Any]:
        nearest = self.c.query_df(
            "SELECT max(trade_date) AS trade_date FROM trade_calendar WHERE is_open AND trade_date<?",
            [trade_date],
        )
        nearest_date = self._date(nearest.iloc[0]["trade_date"])
        return {
            "trade_date": trade_date.isoformat(),
            "business_code": "NOT_TRADING_DAY",
            "snapshot_status": "not_trading_day",
            "has_snapshot": False,
            "nearest_previous_trade_date": (
                nearest_date.isoformat() if nearest_date is not None else None
            ),
            "coverage": {"reason_codes": ["NOT_TRADING_DAY"]},
            "task": None,
        }

    @staticmethod
    def _state_business_code(status: str, has_snapshot: bool) -> str:
        if status == "valid":
            return "READY"
        if status in {"calculating", "recalculating"}:
            return "SNAPSHOT_STALE" if has_snapshot else "SNAPSHOT_PENDING"
        if status == "invalid":
            return "SNAPSHOT_STALE" if has_snapshot else "SNAPSHOT_NOT_READY"
        if status == "failed":
            return "SNAPSHOT_STALE" if has_snapshot else "SNAPSHOT_FAILED"
        return "SNAPSHOT_MISSING"

    @classmethod
    def _json_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        return {key: cls._json_value(value) for key, value in row.items()}

    @classmethod
    def _json_value(cls, value: Any) -> Any:
        if value is None or (not isinstance(value, (list, dict, tuple)) and pd.isna(value)):
            return None
        if isinstance(value, (date, datetime, pd.Timestamp)):
            return value.isoformat()
        if hasattr(value, "item"):
            return value.item()
        return value

    @staticmethod
    def _parse_json(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(str(value))
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _date(value: Any) -> date | None:
        return None if value is None or pd.isna(value) else pd.Timestamp(value).date()

    @classmethod
    def _iso(cls, value: Any) -> str | None:
        parsed = cls._date(value) if not isinstance(value, datetime) else value
        return None if parsed is None else parsed.isoformat()

    @staticmethod
    def _nullable_text(value: Any) -> str | None:
        return None if value is None or pd.isna(value) else str(value)

    @staticmethod
    def _csv_cell(value: Any) -> Any:
        """Prevent spreadsheet formula execution for externally sourced text cells."""
        if not isinstance(value, str):
            return value
        if value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value
