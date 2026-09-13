"""个股走势关联板块 T3：固定日历、市场中性相关算法与批量输入。"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from backend.indicators.stock_board_correlation import (
    ALGORITHM_VERSION,
    BenchmarkDataError,
    CandidateRef,
    CorrelationInputError,
    CorrelationWinner,
    build_market_returns,
    calculate_stock_correlations,
    classify_confidence,
    normalize_calendar,
    pick_correlation_winner,
    precompute_market_returns,
    resolve_benchmark_code,
    winsorized_pearson,
)
from backend.services.stock_board_correlation import StockBoardCorrelationService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


def _calendar() -> tuple[date, ...]:
    start = date(2026, 1, 1)
    return tuple(start + timedelta(days=index) for index in range(61))


def _closes(dates: tuple[date, ...], returns: list[float]) -> dict[date, float]:
    assert len(returns) == len(dates) - 1
    result = {dates[0]: 100.0}
    for index, value in enumerate(returns, start=1):
        result[dates[index]] = result[dates[index - 1]] * (1.0 + value)
    return result


def _series_fixture():
    dates = _calendar()
    benchmark_returns = [0.0005 * ((index % 5) - 2) for index in range(60)]
    signal = [0.001 * ((index % 7) - 3) for index in range(60)]
    stock = _closes(
        dates,
        [benchmark_returns[index] + signal[index] for index in range(60)],
    )
    industry = _closes(
        dates,
        [benchmark_returns[index] + 2 * signal[index] for index in range(60)],
    )
    concept = _closes(
        dates,
        [benchmark_returns[index] - signal[index] for index in range(60)],
    )
    benchmark = _closes(dates, benchmark_returns)
    return dates, stock, industry, concept, benchmark


@pytest.mark.parametrize(
    ("board", "code", "expected"),
    [
        ("主板", "600000.SH", ("000001.SH", False)),
        ("主板", "000001.SZ", ("399001.SZ", False)),
        ("创业板", "300001.SZ", ("399006.SZ", False)),
        ("科创板", "688001.SH", ("000688.SH", False)),
        (None, "600000.SH", ("000001.SH", True)),
        ("未知板", "000001.SZ", ("000001.SH", True)),
    ],
)
def test_benchmark_mapping_covers_four_boards_and_unknown(board, code, expected):
    assert resolve_benchmark_code(board, code) == expected


def test_market_returns_use_exact_61_points_and_do_not_bridge_gap():
    dates = _calendar()
    closes = _closes(dates, [0.01] * 60)
    closes.pop(dates[30])

    returns = build_market_returns(closes, dates)

    assert len(returns) == 58
    assert dates[30] not in returns
    assert dates[31] not in returns
    assert returns[dates[29]] == pytest.approx(0.01)
    assert returns[dates[32]] == pytest.approx(0.01)
    with pytest.raises(CorrelationInputError):
        normalize_calendar(dates[:60])


def test_market_neutral_winsor_score_type_isolation_and_stable_tie_break():
    dates, stock, industry, concept, benchmark = _series_fixture()
    result = calculate_stock_correlations(
        code="600000.SH",
        board="主板",
        calendar_dates=dates,
        stock_closes=stock,
        candidates=[
            CandidateRef("881002", "industry"),
            CandidateRef("881001", "industry"),
            CandidateRef("301001", "concept"),
        ],
        board_closes={"881001": industry, "881002": industry, "301001": concept},
        benchmark_closes={"000001.SH": benchmark},
    )

    assert result.algorithm_version == ALGORITHM_VERSION
    assert result.benchmark_code == "000001.SH"
    assert result.benchmark_fallback is False
    assert result.industry is not None
    assert result.industry.board_code == "881001"
    assert result.industry.score == pytest.approx(1.0)
    assert result.industry.corr_20 == pytest.approx(1.0)
    assert result.industry.corr_60 == pytest.approx(1.0)
    assert (result.industry.sample_20, result.industry.sample_60) == (20, 60)
    assert result.industry.confidence == "high"
    assert result.concept is not None
    assert result.concept.score == pytest.approx(-1.0)
    assert result.concept.confidence == "low"


def test_mapped_benchmark_shortage_falls_back_for_whole_stock():
    dates, stock, industry, _, fallback_benchmark = _series_fixture()
    result = calculate_stock_correlations(
        code="000001.SZ",
        board="主板",
        calendar_dates=dates,
        stock_closes=stock,
        candidates=[CandidateRef("881001", "industry")],
        board_closes={"881001": industry},
        benchmark_closes={
            "399001.SZ": {},
            "000001.SH": fallback_benchmark,
        },
    )

    assert result.benchmark_code == "000001.SH"
    assert result.benchmark_fallback is True
    assert result.industry is not None


def test_mapped_benchmark_missing_as_of_close_falls_back_for_whole_stock():
    dates, stock, industry, _, benchmark = _series_fixture()
    mapped = dict(benchmark)
    mapped.pop(dates[-1])

    result = calculate_stock_correlations(
        code="000001.SZ",
        board="主板",
        calendar_dates=dates,
        stock_closes=stock,
        candidates=[CandidateRef("881001", "industry")],
        board_closes={"881001": industry},
        benchmark_closes={"399001.SZ": mapped, "000001.SH": benchmark},
    )

    assert result.benchmark_code == "000001.SH"
    assert result.benchmark_fallback is True
    assert result.industry is not None


def test_shanghai_benchmark_missing_as_of_close_fails_even_when_samples_are_sufficient():
    dates, stock, industry, _, benchmark = _series_fixture()
    benchmark.pop(dates[-1])

    with pytest.raises(BenchmarkDataError, match="目标日收盘缺失"):
        calculate_stock_correlations(
            code="600000.SH",
            board="主板",
            calendar_dates=dates,
            stock_closes=stock,
            candidates=[CandidateRef("881001", "industry")],
            board_closes={"881001": industry},
            benchmark_closes={"000001.SH": benchmark},
        )


def test_benchmark_middle_gap_keeps_mapping_when_both_sample_thresholds_hold():
    dates, stock, industry, _, benchmark = _series_fixture()
    benchmark.pop(dates[10])

    result = calculate_stock_correlations(
        code="000001.SZ",
        board="主板",
        calendar_dates=dates,
        stock_closes=stock,
        candidates=[CandidateRef("881001", "industry")],
        board_closes={"881001": industry},
        benchmark_closes={"399001.SZ": benchmark, "000001.SH": {}},
    )

    assert result.benchmark_code == "399001.SZ"
    assert result.benchmark_fallback is False
    assert result.industry is not None


def test_precomputed_returns_match_direct_construction():
    dates, _, industry, concept, benchmark = _series_fixture()
    closes = {"881001": industry, "301001": concept, "000001.SH": benchmark}

    prepared = precompute_market_returns(closes, dates)

    assert prepared == {
        code: build_market_returns(series, dates) for code, series in closes.items()
    }


def test_shanghai_fallback_shortage_fails_instead_of_mixing_benchmarks():
    dates, stock, industry, _, _ = _series_fixture()
    with pytest.raises(BenchmarkDataError, match="上证指数"):
        calculate_stock_correlations(
            code="000001.SZ",
            board="主板",
            calendar_dates=dates,
            stock_closes=stock,
            candidates=[CandidateRef("881001", "industry")],
            board_closes={"881001": industry},
            benchmark_closes={"399001.SZ": {}, "000001.SH": {}},
        )


def test_stock_or_candidate_shortage_does_not_trigger_benchmark_fallback_or_expand_window():
    dates, stock, industry, _, benchmark = _series_fixture()
    for shortage in (stock, industry):
        shortened = dict(shortage)
        for missing_index in (45, 50, 55):
            shortened.pop(dates[missing_index])
        result = calculate_stock_correlations(
            code="000001.SZ",
            board="主板",
            calendar_dates=dates,
            stock_closes=shortened if shortage is stock else stock,
            candidates=[CandidateRef("881001", "industry")],
            board_closes={"881001": shortened if shortage is industry else industry},
            benchmark_closes={"399001.SZ": benchmark, "000001.SH": benchmark},
        )

        assert result.benchmark_code == "399001.SZ"
        assert result.benchmark_fallback is False
        assert result.industry is None
        assert result.industry_empty_reason is not None
        assert result.industry_empty_reason.code == "insufficient_samples"
        assert result.industry_empty_reason.max_sample_20 == 14
        assert result.industry_empty_reason.max_sample_60 == 54


def test_constant_neutral_series_is_invalid_and_confidence_boundaries_are_fixed():
    dates, stock, _, _, benchmark = _series_fixture()
    result = calculate_stock_correlations(
        code="600000.SH",
        board="主板",
        calendar_dates=dates,
        stock_closes=stock,
        candidates=[CandidateRef("881001", "industry")],
        board_closes={"881001": benchmark},
        benchmark_closes={"000001.SH": benchmark},
    )

    assert result.industry is None
    assert result.industry_empty_reason is not None
    assert result.industry_empty_reason.code == "invalid_correlation"
    nonfinite = calculate_stock_correlations(
        code="600000.SH",
        board="主板",
        calendar_dates=dates,
        stock_closes=stock,
        candidates=[CandidateRef("881001", "industry")],
        board_closes={"881001": {day: float("inf") for day in dates}},
        benchmark_closes={"000001.SH": benchmark},
    )
    assert nonfinite.industry is None
    empty = calculate_stock_correlations(
        code="600000.SH",
        board="主板",
        calendar_dates=dates,
        stock_closes=stock,
        candidates=[],
        board_closes={},
        benchmark_closes={"000001.SH": benchmark},
    )
    assert empty.industry is None and empty.concept is None
    assert empty.industry_empty_reason is not None
    assert empty.industry_empty_reason.code == "no_candidates"
    assert empty.concept_empty_reason is not None
    assert empty.concept_empty_reason.code == "no_candidates"
    assert winsorized_pearson([1.0] * 15, list(range(15))) is None
    assert classify_confidence(50, 0.70, 0.8, 0.7) == "high"
    assert classify_confidence(49, 0.70, 0.8, 0.7) == "medium"
    assert classify_confidence(40, 0.49, 0.8, 0.7) == "low"


def test_winsorization_and_all_stable_tie_break_levels_are_explicit():
    correlation = winsorized_pearson(list(range(20)), [*range(19), 100])
    assert correlation == pytest.approx(0.990393821210588)

    def winner(code, score, corr_60, sample_60):
        return CorrelationWinner(
            board_code=code,
            board_type="industry",
            score=score,
            corr_20=score,
            corr_60=corr_60,
            sample_20=20,
            sample_60=sample_60,
            confidence="low",
        )

    selected = pick_correlation_winner([
        winner("881004", 0.6, 0.7, 60),
        winner("881003", 0.7, 0.6, 60),
        winner("881002", 0.7, 0.7, 50),
        winner("881001", 0.7, 0.7, 60),
        winner("881000", 0.7, 0.7, 60),
    ])
    assert selected is not None
    assert selected.board_code == "881000"


class _CountingClient:
    def __init__(self, delegate: DuckDBClient):
        self.delegate = delegate
        self.queries = 0

    def query_df(self, sql, params=None):
        self.queries += 1
        return self.delegate.query_df(sql, params)


def _insert_frame(client: DuckDBClient, frame: pd.DataFrame, table: str, columns: str) -> None:
    with client.temp_view(frame, "correlation_input") as view:
        client.execute(f"INSERT INTO {table} ({columns}) SELECT {columns} FROM {view}")


def test_input_loader_batches_hfq_stock_and_raw_board_benchmark_prices():
    dates = _calendar()
    future = dates[-1] + timedelta(days=1)
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _insert_frame(
            market,
            pd.DataFrame({"trade_date": [*dates, future], "is_open": [True] * 62}),
            "trade_calendar",
            "trade_date,is_open",
        )
        market.execute(
            "INSERT INTO stock_basic (code,name,board) VALUES ('600000.SH','浦发银行','主板')"
        )
        market.execute(
            "INSERT INTO board_dict (board_code,name,board_type) "
            "VALUES ('881001','银行','industry')"
        )
        market.execute(
            "INSERT INTO board_member (board_code,code) VALUES ('881001','600000.SH')"
        )
        _insert_frame(
            market,
            pd.DataFrame({
                "code": ["600000.SH"] * 62,
                "trade_date": [*dates, future],
                "close": [10.0] * 62,
                "adj_factor": [3.0] * 62,
                "adj_factor_clean": [2.0] * 62,
            }),
            "daily_bar",
            "code,trade_date,close,adj_factor,adj_factor_clean",
        )
        _insert_frame(
            market,
            pd.DataFrame({
                "board_code": ["881001"] * 62,
                "trade_date": [*dates, future],
                "close": [100.0] * 62,
            }),
            "board_bar",
            "board_code,trade_date,close",
        )
        benchmark_codes = ["000001.SH", "000688.SH", "399001.SZ", "399006.SZ"]
        _insert_frame(
            market,
            pd.DataFrame([
                {"index_code": code, "trade_date": trade_date, "close": 1000.0}
                for code in benchmark_codes
                for trade_date in [*dates, future]
            ]),
            "index_bar",
            "index_code,trade_date,close",
        )
        counting = _CountingClient(market)
        bundle = StockBoardCorrelationService(counting).load_correlation_inputs(  # type: ignore[arg-type]
            ["600000.sh"],
            dates[-1],
        )

        assert counting.queries == 6
        assert bundle.as_of_date == dates[-1]
        assert bundle.calendar_dates == dates
        assert bundle.stock_boards == {"600000.SH": "主板"}
        assert bundle.stock_closes["600000.SH"][dates[0]] == 20.0
        assert future not in bundle.stock_closes["600000.SH"]
        assert bundle.candidates["600000.SH"] == (CandidateRef("881001", "industry"),)
        assert bundle.board_closes["881001"][dates[0]] == 100.0
        assert set(bundle.benchmark_closes) == set(benchmark_codes)


def test_empty_input_loader_does_not_query():
    counting = _CountingClient(DuckDBClient(db_path=":memory:"))
    bundle = StockBoardCorrelationService(counting).load_correlation_inputs(  # type: ignore[arg-type]
        [],
        date(2026, 1, 1),
    )
    assert counting.queries == 0
    assert bundle.calendar_dates == ()
