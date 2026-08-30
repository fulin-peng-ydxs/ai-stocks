"""Pure DuckDB read model for limit-up ladder domain calculation."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date

import pandas as pd

from backend.limit_ladder.rules import (
    PointInTimeSTStatus,
    STStatusQuality,
    resolve_point_in_time_st,
)
from backend.market_rules import (
    CloseLimitStatus,
    PriceLimitApplicability,
    evaluate_close_limit_up,
    ipo_price_limit_applicability,
    listing_board_for,
)
from backend.storage.duckdb_client import DuckDBClient, get_client

SUPPORTED_WINDOWS = frozenset({10, 20, 31, 60})
HISTORY_BATCH_SIZE = 60
UNCLASSIFIED_KEY = "__unclassified__"
UNCLASSIFIED_NAME = "未分类"


@dataclass(frozen=True, slots=True)
class LadderCoverageIssue:
    code: str
    trade_date: date
    reason: str


@dataclass(frozen=True, slots=True)
class LadderConcept:
    board_code: str
    board_name: str


@dataclass(frozen=True, slots=True)
class LadderStock:
    code: str
    name: str
    board: str
    price_limit_pct: float
    is_st: bool
    st_quality: str
    st_source: str
    is_one_word: bool
    consecutive_days: int
    window_limit_up_days: int
    window_start_date: date
    actual_trade_days: int
    amount: float
    industry_name: str
    industry_board_code: str | None
    concepts: tuple[LadderConcept, ...]


@dataclass(frozen=True, slots=True)
class LadderAggregate:
    group_type: str
    group_key: str
    group_name: str
    stock_count: int


@dataclass(frozen=True, slots=True)
class LimitLadderCalculation:
    trade_date: date
    requested_window: int
    requested_window_start_date: date
    requested_window_trade_days: int
    stocks: tuple[LadderStock, ...]
    aggregates: tuple[LadderAggregate, ...]
    coverage_issues: tuple[LadderCoverageIssue, ...]
    batch_query_count: int

    @property
    def summary(self) -> dict[str, int | None]:
        heights = [stock.consecutive_days for stock in self.stocks]
        return {
            "stock_count": len(self.stocks),
            "highest_board": max(heights) if heights else None,
            "first_board_count": sum(height == 1 for height in heights),
        }


class LimitLadderCalculator:
    """Calculate one date in bounded batches without per-stock history queries."""

    def __init__(self, client: DuckDBClient | None = None):
        self.c = client or get_client()
        self._batch_query_count = 0

    def calculate(self, trade_date: date, *, window: int = 31) -> LimitLadderCalculation:
        if window not in SUPPORTED_WINDOWS:
            raise ValueError(f"window must be one of {sorted(SUPPORTED_WINDOWS)}")
        calendar = self._calendar_through(trade_date)
        if not calendar or calendar[-1] != trade_date:
            raise ValueError(f"not an open trade date: {trade_date}")
        window_dates = calendar[-window:]
        self._batch_query_count = 0

        basics = self._point_in_time_basics(trade_date)
        basic_by_code = {str(row["code"]): row for _, row in basics.iterrows()}
        issues: dict[tuple[str, date, str], LadderCoverageIssue] = {}
        pool_codes: list[str] = []
        for code, row in basic_by_code.items():
            if listing_board_for(board=self._text(row.get("board")), code=code) is None:
                continue
            if pd.isna(row.get("list_date")):
                self._add_issue(issues, code, trade_date, "LIST_DATE_UNKNOWN")
            pool_codes.append(code)

        selected_facts = self._load_daily_facts(pool_codes, [trade_date])
        candidates: dict[str, dict] = {}
        for code in pool_codes:
            row = basic_by_code[code]
            fact = selected_facts.get((code, trade_date))
            if fact is None:
                self._add_issue(issues, code, trade_date, "MISSING_BAR_OR_SUSPENSION")
                continue
            if self._bool_value(fact.get("confirmed_suspension")) or self._bool_value(
                fact.get("is_suspended")
            ):
                continue
            result, st_status = self._evaluate_fact(
                code=code,
                basic=row,
                fact=fact,
                calendar=calendar,
            )
            self._record_rule_issue(issues, code, trade_date, result.status)
            if result.status is not CloseLimitStatus.LIMIT_UP:
                continue
            candidates[code] = {
                "selected": fact,
                "st_status": st_status,
                "limit_pct": float(result.limit_pct),
            }

        counts = {code: 0 for code in candidates}
        streaks = {code: 0 for code in candidates}
        active = set(candidates)
        calendar_desc = list(reversed(calendar))
        window_set = set(window_dates)
        for offset in range(0, len(calendar_desc), HISTORY_BATCH_SIZE):
            batch_dates = calendar_desc[offset : offset + HISTORY_BATCH_SIZE]
            query_codes = set(candidates) if offset == 0 else set(active)
            if not query_codes:
                break
            facts = self._load_daily_facts(sorted(query_codes), batch_dates)
            for code in sorted(query_codes):
                basic = basic_by_code[code]
                list_date = self._date_value(basic.get("list_date"))
                for day in batch_dates:
                    if list_date is not None and day < list_date:
                        active.discard(code)
                        break
                    fact = facts.get((code, day))
                    result = None
                    if fact is not None and not self._bool_value(
                        fact.get("confirmed_suspension")
                    ):
                        result, _ = self._evaluate_fact(
                            code=code,
                            basic=basic,
                            fact=fact,
                            calendar=calendar,
                        )
                        self._record_rule_issue(issues, code, day, result.status)
                    elif day in window_set and list_date is not None and day >= list_date:
                        self._add_issue(issues, code, day, "MISSING_BAR_OR_SUSPENSION")

                    if day in window_set and result is not None and result.is_limit_up:
                        counts[code] += 1

                    if code in active:
                        if result is not None and result.is_limit_up:
                            streaks[code] += 1
                        else:
                            active.remove(code)
                    if offset > 0 and code not in active:
                        break
            if not active and offset >= HISTORY_BATCH_SIZE:
                break

        concepts_by_code = self._concepts_for(sorted(candidates))
        industry_codes = self._unique_industry_codes()
        stocks: list[LadderStock] = []
        for code, candidate in candidates.items():
            basic = basic_by_code[code]
            list_date = self._date_value(basic.get("list_date"))
            actual_dates = [day for day in window_dates if list_date is None or day >= list_date]
            if not actual_dates:
                self._add_issue(issues, code, trade_date, "WINDOW_HISTORY_UNAVAILABLE")
                continue
            industry_name = self._text(basic.get("industry")) or UNCLASSIFIED_NAME
            selected = candidate["selected"]
            st_status: PointInTimeSTStatus = candidate["st_status"]
            stocks.append(
                LadderStock(
                    code=code,
                    name=self._text(basic.get("name")) or code,
                    board=listing_board_for(
                        board=self._text(basic.get("board")), code=code
                    ).value,
                    price_limit_pct=candidate["limit_pct"],
                    is_st=st_status.is_st,
                    st_quality=st_status.quality.value,
                    st_source=st_status.source,
                    is_one_word=self._bool_value(selected.get("is_one_word")),
                    consecutive_days=streaks[code],
                    window_limit_up_days=counts[code],
                    window_start_date=actual_dates[0],
                    actual_trade_days=len(actual_dates),
                    amount=float(selected.get("amount") or 0),
                    industry_name=industry_name,
                    industry_board_code=industry_codes.get(industry_name),
                    concepts=tuple(concepts_by_code.get(code, ())),
                )
            )
        stocks.sort(
            key=lambda stock: (
                -stock.consecutive_days,
                -stock.window_limit_up_days,
                -stock.amount,
                stock.code,
            )
        )
        aggregates = self._aggregates(stocks)
        return LimitLadderCalculation(
            trade_date=trade_date,
            requested_window=window,
            requested_window_start_date=window_dates[0],
            requested_window_trade_days=len(window_dates),
            stocks=tuple(stocks),
            aggregates=tuple(aggregates),
            coverage_issues=tuple(
                sorted(issues.values(), key=lambda issue: (issue.trade_date, issue.code, issue.reason))
            ),
            batch_query_count=self._batch_query_count,
        )

    def _calendar_through(self, trade_date: date) -> list[date]:
        rows = self.c.query_df(
            "SELECT trade_date FROM trade_calendar "
            "WHERE is_open AND trade_date<=? ORDER BY trade_date",
            [trade_date],
        )
        return [pd.Timestamp(value).date() for value in rows["trade_date"].tolist()]

    def _point_in_time_basics(self, trade_date: date) -> pd.DataFrame:
        return self.c.query_df(
            """
            SELECT code,name,board,list_date,delist_date,industry,price_limit_pct
            FROM stock_basic
            WHERE (list_date IS NULL OR list_date<=?)
              AND (delist_date IS NULL OR delist_date>=?)
            ORDER BY code
            """,
            [trade_date, trade_date],
        )

    def _load_daily_facts(self, codes: list[str], dates: list[date]) -> dict[tuple[str, date], dict]:
        if not codes or not dates:
            return {}
        code_frame = pd.DataFrame({"code": codes})
        date_frame = pd.DataFrame({"trade_date": dates})
        with (
            self.c.temp_view(code_frame, "ladder_codes") as code_view,
            self.c.temp_view(date_frame, "ladder_dates") as date_view,
        ):
            rows = self.c.query_df(
                f"""
                SELECT b.code,b.trade_date,b.open,b.high,b.low,b.close,b.pre_close,
                       b.amount,b.is_suspended,b.is_one_word,
                       st.is_st AS point_is_st,st.source AS st_source,
                       st.source_ref AS st_source_ref,st.quality AS st_quality,
                       (s.trade_date IS NOT NULL) AS confirmed_suspension
                FROM daily_bar b
                JOIN {code_view} codes ON codes.code=b.code
                JOIN {date_view} dates ON dates.trade_date=b.trade_date
                LEFT JOIN stock_st_status_daily st
                  ON st.code=b.code AND st.trade_date=b.trade_date
                LEFT JOIN stock_suspension s
                  ON s.code=b.code AND s.trade_date=b.trade_date
                UNION ALL
                SELECT s.code,s.trade_date,NULL,NULL,NULL,NULL,NULL,NULL,TRUE,FALSE,
                       st.is_st,st.source,st.source_ref,st.quality,TRUE
                FROM stock_suspension s
                JOIN {code_view} codes ON codes.code=s.code
                JOIN {date_view} dates ON dates.trade_date=s.trade_date
                LEFT JOIN stock_st_status_daily st
                  ON st.code=s.code AND st.trade_date=s.trade_date
                WHERE NOT EXISTS (
                    SELECT 1 FROM daily_bar b
                    WHERE b.code=s.code AND b.trade_date=s.trade_date
                )
                """
            )
        self._batch_query_count += 1
        return {
            (str(row["code"]), pd.Timestamp(row["trade_date"]).date()): row.to_dict()
            for _, row in rows.iterrows()
        }

    def _evaluate_fact(self, *, code: str, basic, fact: dict, calendar: list[date]):
        st_status = self._st_status(basic, fact)
        board = listing_board_for(board=self._text(basic.get("board")), code=code)
        list_date = self._date_value(basic.get("list_date"))
        applicability = PriceLimitApplicability.UNKNOWN
        if board is not None and list_date is not None:
            day = self._date_value(fact.get("trade_date"))
            first_index = bisect_left(calendar, list_date)
            if day is not None:
                current_index = bisect_left(calendar, day)
                applicability = ipo_price_limit_applicability(
                    board=board,
                    list_date=list_date,
                    listing_session_number=current_index - first_index + 1,
                )
        board_pct = None if pd.isna(basic.get("price_limit_pct")) else float(
            basic.get("price_limit_pct")
        )
        result = evaluate_close_limit_up(
            close=fact.get("close"),
            pre_close=fact.get("pre_close"),
            board_limit_pct=board_pct,
            is_st=st_status.is_st,
            trade_date=fact.get("trade_date"),
            applicability=applicability,
            is_suspended=self._bool_value(fact.get("is_suspended")),
        )
        return result, st_status

    @staticmethod
    def _st_status(basic, fact: dict) -> PointInTimeSTStatus:
        if not pd.isna(fact.get("st_source")):
            source_ref = fact.get("st_source_ref")
            return PointInTimeSTStatus(
                is_st=LimitLadderCalculator._bool_value(fact.get("point_is_st")),
                source=str(fact.get("st_source")),
                source_ref=None if pd.isna(source_ref) else str(source_ref),
                quality=STStatusQuality(str(fact.get("st_quality"))),
            )
        return resolve_point_in_time_st(name=LimitLadderCalculator._text(basic.get("name")))

    def _concepts_for(self, codes: list[str]) -> dict[str, tuple[LadderConcept, ...]]:
        if not codes:
            return {}
        code_frame = pd.DataFrame({"code": codes})
        with self.c.temp_view(code_frame, "concept_codes") as code_view:
            rows = self.c.query_df(
                f"""
                SELECT bm.code,bd.board_code,bd.name
                FROM board_member bm
                JOIN {code_view} codes ON codes.code=bm.code
                JOIN board_dict bd ON bd.board_code=bm.board_code
                WHERE bd.board_type='concept'
                ORDER BY bm.code,bd.name,bd.board_code
                """
            )
        result: dict[str, list[LadderConcept]] = {}
        for _, row in rows.iterrows():
            result.setdefault(str(row["code"]), []).append(
                LadderConcept(board_code=str(row["board_code"]), board_name=str(row["name"]))
            )
        return {code: tuple(values) for code, values in result.items()}

    def _unique_industry_codes(self) -> dict[str, str]:
        rows = self.c.query_df(
            """
            SELECT name,min(board_code) AS board_code,count(*) AS n
            FROM board_dict WHERE board_type='industry'
            GROUP BY name HAVING count(*)=1
            """
        )
        return {str(row["name"]): str(row["board_code"]) for _, row in rows.iterrows()}

    @staticmethod
    def _aggregates(stocks: list[LadderStock]) -> list[LadderAggregate]:
        counts: dict[tuple[str, str, str], int] = {}
        for stock in stocks:
            industry_key = stock.industry_board_code or (
                UNCLASSIFIED_KEY
                if stock.industry_name == UNCLASSIFIED_NAME
                else f"name:{stock.industry_name}"
            )
            industry = ("industry", industry_key, stock.industry_name)
            counts[industry] = counts.get(industry, 0) + 1
            concepts = stock.concepts or (LadderConcept(UNCLASSIFIED_KEY, UNCLASSIFIED_NAME),)
            for concept in concepts:
                key = ("concept", concept.board_code, concept.board_name)
                counts[key] = counts.get(key, 0) + 1
        return [
            LadderAggregate(group_type=kind, group_key=key, group_name=name, stock_count=count)
            for (kind, key, name), count in sorted(
                counts.items(), key=lambda item: (item[0][0], -item[1], item[0][2], item[0][1])
            )
        ]

    @staticmethod
    def _record_rule_issue(issues, code: str, trade_date: date, status: CloseLimitStatus) -> None:
        if status is CloseLimitStatus.INVALID_PRICE:
            LimitLadderCalculator._add_issue(issues, code, trade_date, "INVALID_DAILY_BAR")
        elif status is CloseLimitStatus.UNSUPPORTED_RULE:
            LimitLadderCalculator._add_issue(issues, code, trade_date, "UNSUPPORTED_LIMIT_RULE")

    @staticmethod
    def _add_issue(issues, code: str, trade_date: date, reason: str) -> None:
        issues[(code, trade_date, reason)] = LadderCoverageIssue(code, trade_date, reason)

    @staticmethod
    def _date_value(value) -> date | None:
        return None if value is None or pd.isna(value) else pd.Timestamp(value).date()

    @staticmethod
    def _text(value) -> str | None:
        return None if value is None or pd.isna(value) else str(value).strip() or None

    @staticmethod
    def _bool_value(value) -> bool:
        """DuckDB/pandas nullable booleans must not turn NaN into truthy values."""
        return False if value is None or pd.isna(value) else bool(value)
