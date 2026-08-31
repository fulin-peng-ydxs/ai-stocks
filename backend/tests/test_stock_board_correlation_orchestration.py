"""个股走势关联板块 T4：目标范围、完整性校验与原子替换。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

import backend.services.stock_board_correlation as correlation_service_module
from backend.common.exceptions import StorageError
from backend.indicators.stock_board_correlation import (
    ALGORITHM_VERSION,
    BenchmarkDataError,
    CorrelationInputError,
)
from backend.services.stock_board_correlation import StockBoardCorrelationService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


def _insert_frame(client: DuckDBClient, frame: pd.DataFrame, table: str) -> None:
    columns = ",".join(frame.columns)
    with client.temp_view(frame, "correlation_t4") as view:
        client.execute(f"INSERT INTO {table} ({columns}) SELECT {columns} FROM {view}")


def _closes(returns: list[float]) -> list[float]:
    values = [100.0]
    for value in returns:
        values.append(values[-1] * (1.0 + value))
    return values


def _computed_at(hour: int) -> datetime:
    """测试库列为无时区 TIMESTAMP，与生产存储契约一致。"""
    return datetime(2026, 3, 2, hour, 0)  # noqa: DTZ001


def _seed_market(client: DuckDBClient) -> tuple[date, ...]:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(61))
    _insert_frame(
        client,
        pd.DataFrame({"trade_date": dates, "is_open": [True] * len(dates)}),
        "trade_calendar",
    )
    client.execute(
        "INSERT INTO stock_basic (code,name,exchange,board,list_date,delist_date) VALUES "
        "('600000.SH','甲','SH','主板','2020-01-01',NULL),"
        "('000001.SZ','乙','SZ','主板','2020-01-01',NULL),"
        "('300999.SZ','未来','SZ','创业板','2030-01-01',NULL),"
        "('600999.SH','退市','SH','主板','2020-01-01','2025-01-01'),"
        "('830001.BJ','北交','BJ','北交所','2020-01-01',NULL)"
    )
    client.execute(
        "INSERT INTO board_dict (board_code,name,board_type) VALUES "
        "('881001','行业甲','industry'),('301001','概念甲','concept')"
    )
    client.execute(
        "INSERT INTO board_member (board_code,code) VALUES "
        "('881001','600000.SH'),('301001','600000.SH'),('881001','000001.SZ')"
    )
    benchmark_returns = [0.0004 * ((index % 5) - 2) for index in range(60)]
    signal = [0.001 * ((index % 7) - 3) for index in range(60)]
    stock_closes = _closes([benchmark_returns[index] + signal[index] for index in range(60)])
    industry_closes = _closes([benchmark_returns[index] + 2 * signal[index] for index in range(60)])
    concept_closes = _closes([benchmark_returns[index] - signal[index] for index in range(60)])
    benchmark_closes = _closes(benchmark_returns)
    _insert_frame(
        client,
        pd.DataFrame(
            [
                {
                    "code": code,
                    "trade_date": trade_date,
                    "close": stock_closes[index],
                    "adj_factor": 1.0,
                    "adj_factor_clean": 1.0,
                }
                for code in ("600000.SH", "000001.SZ")
                for index, trade_date in enumerate(dates)
            ]
        ),
        "daily_bar",
    )
    _insert_frame(
        client,
        pd.DataFrame(
            [
                {
                    "board_code": board_code,
                    "trade_date": trade_date,
                    "close": closes[index],
                }
                for board_code, closes in (
                    ("881001", industry_closes),
                    ("301001", concept_closes),
                )
                for index, trade_date in enumerate(dates)
            ]
        ),
        "board_bar",
    )
    _insert_frame(
        client,
        pd.DataFrame(
            [
                {
                    "index_code": index_code,
                    "trade_date": trade_date,
                    "close": benchmark_closes[index],
                }
                for index_code in ("000001.SH", "399001.SZ", "399006.SZ", "000688.SH")
                for index, trade_date in enumerate(dates)
            ]
        ),
        "index_bar",
    )
    return dates


@pytest.fixture
def market(tmp_path):
    with DuckDBClient(db_path=tmp_path / "market.duckdb") as client:
        init_db(client)
        dates = _seed_market(client)
        yield client, dates


def _snapshot(client: DuckDBClient) -> tuple[list[tuple], list[tuple]]:
    states = client.conn.execute(
        "SELECT * FROM stock_board_correlation_state ORDER BY code"
    ).fetchall()
    champions = client.conn.execute(
        "SELECT * FROM stock_board_correlation ORDER BY code,board_type"
    ).fetchall()
    return states, champions


def test_full_run_skip_partial_stale_version_change_and_forced_idempotence(market):
    client, dates = market
    service = StockBoardCorrelationService(client)
    first_time = _computed_at(8)
    first = service.compute_and_replace(force=True, computed_at=first_time)

    assert first.target_date == dates[-1]
    assert first.target_count == 2
    assert (first.industry_champion_count, first.concept_champion_count) == (2, 1)
    assert first.switched is True
    assert client.query_df("SELECT count(*) n FROM stock_board_correlation_state").iloc[0]["n"] == 2
    assert client.query_df("SELECT count(*) n FROM stock_board_correlation").iloc[0]["n"] == 3

    skipped = service.compute_and_replace()
    assert skipped.switched is False and skipped.skipped_count == 2
    assert skipped.candidate_count == 3
    assert (skipped.industry_champion_count, skipped.concept_champion_count) == (2, 1)
    assert skipped.empty_result_count == 0
    assert skipped.benchmark_counts == {"000001.SH": 1, "399001.SZ": 1}

    client.execute(
        "UPDATE stock_board_correlation_state "
        "SET algorithm_version='stock-board-correlation-v1' WHERE code='600000.SH'"
    )
    second_time = _computed_at(9)
    refreshed = service.compute_and_replace(computed_at=second_time)
    assert refreshed.switched is True
    refreshed_times = client.query_df(
        "SELECT DISTINCT computed_at FROM stock_board_correlation_state"
    )["computed_at"].tolist()
    assert refreshed_times == [pd.Timestamp(second_time)]

    before = _snapshot(client)
    service.compute_and_replace(force=True, computed_at=second_time)
    assert _snapshot(client) == before
    assert set(
        client.query_df("SELECT DISTINCT algorithm_version FROM stock_board_correlation_state")[
            "algorithm_version"
        ]
    ) == {ALGORITHM_VERSION}


def test_range_replacement_keeps_other_stock_and_legal_empty_clears_old_winners(market):
    client, _ = market
    service = StockBoardCorrelationService(client)
    service.compute_and_replace(force=True)
    other_before = client.conn.execute(
        "SELECT * FROM stock_board_correlation WHERE code='000001.SZ'"
    ).fetchall()
    client.execute("DELETE FROM board_member WHERE code='600000.SH'")

    result = service.compute_and_replace(["600000.sh"], force=True)

    assert result.target_count == 1 and result.empty_result_count == 1
    assert (
        client.conn.execute(
            "SELECT count(*) FROM stock_board_correlation WHERE code='600000.SH'"
        ).fetchone()[0]
        == 0
    )
    state = client.conn.execute(
        "SELECT has_industry_champion,has_concept_champion "
        "FROM stock_board_correlation_state WHERE code='600000.SH'"
    ).fetchone()
    assert state == (False, False)
    assert (
        client.conn.execute(
            "SELECT * FROM stock_board_correlation WHERE code='000001.SZ'"
        ).fetchall()
        == other_before
    )


@pytest.mark.parametrize(
    ("codes", "reason"),
    [
        (["600404.SH"], "未知股票"),
        (["300999.SZ"], "尚未上市"),
        (["600999.SH"], "已退市"),
        (["830001.BJ"], "股票代码格式非法"),
    ],
)
def test_explicit_invalid_scope_is_rejected_before_writes(market, codes, reason):
    client, _ = market
    service = StockBoardCorrelationService(client)
    service.compute_and_replace(force=True)
    before = _snapshot(client)

    with pytest.raises((CorrelationInputError, ValueError), match=reason):
        service.compute_and_replace(codes, force=True)

    assert _snapshot(client) == before


@pytest.mark.parametrize(
    ("corruption", "reason"),
    [
        ("date", "结果日期或算法版本不一致"),
        ("version", "结果日期或算法版本不一致"),
        ("benchmark", "实际基准与回退标记不一致"),
        ("dictionary", "冠军板块字典引用失效"),
        ("type", "industry冠军类型错位"),
    ],
)
def test_integrity_failure_is_rejected_before_writes(market, monkeypatch, corruption, reason):
    client, _ = market
    service = StockBoardCorrelationService(client)
    service.compute_and_replace(force=True)
    before = _snapshot(client)
    original = correlation_service_module.calculate_stock_correlations

    def corrupt_result(**kwargs):
        result = original(**kwargs)
        if corruption == "date":
            return replace(result, as_of_date=result.as_of_date - timedelta(days=1))
        if corruption == "version":
            return replace(result, algorithm_version="old")
        if corruption == "benchmark":
            return replace(result, benchmark_fallback=not result.benchmark_fallback)
        assert result.industry is not None
        if corruption == "dictionary":
            return replace(
                result,
                industry=replace(result.industry, board_code="missing-board"),
            )
        return replace(
            result,
            industry=replace(result.industry, board_type="concept"),
        )

    monkeypatch.setattr(correlation_service_module, "calculate_stock_correlations", corrupt_result)
    with pytest.raises(CorrelationInputError, match=reason):
        service.compute_and_replace(force=True)

    assert _snapshot(client) == before


def test_batch_orchestration_builds_board_and_benchmark_returns_once_per_unique_code(
    market,
    monkeypatch,
):
    client, _ = market
    service = StockBoardCorrelationService(client)
    calls: list[set[str]] = []
    original = correlation_service_module.precompute_market_returns

    def track_precompute(closes_by_code, calendar_dates):
        calls.append(set(closes_by_code))
        return original(closes_by_code, calendar_dates)

    monkeypatch.setattr(
        correlation_service_module,
        "precompute_market_returns",
        track_precompute,
    )

    result = service.compute_and_replace(force=True)

    assert result.target_count == 2
    assert calls == [{"301001", "881001"}, {"000001.SH", "000688.SH", "399001.SZ", "399006.SZ"}]


def test_target_day_benchmark_fallback_is_persisted_and_missing_shanghai_keeps_old_rows(market):
    client, dates = market
    service = StockBoardCorrelationService(client)
    service.compute_and_replace(force=True, computed_at=_computed_at(8))

    client.execute(
        "DELETE FROM index_bar WHERE index_code='399001.SZ' AND trade_date=?",
        [dates[-1]],
    )
    fallback_result = service.compute_and_replace(force=True, computed_at=_computed_at(9))
    fallback_state = client.query_df(
        "SELECT benchmark_code,benchmark_fallback "
        "FROM stock_board_correlation_state WHERE code='000001.SZ'"
    ).iloc[0]
    assert fallback_result.fallback_count == 1
    assert fallback_state.to_dict() == {
        "benchmark_code": "000001.SH",
        "benchmark_fallback": True,
    }

    before = _snapshot(client)
    client.execute(
        "DELETE FROM index_bar WHERE index_code='000001.SH' AND trade_date=?",
        [dates[-1]],
    )
    with pytest.raises(BenchmarkDataError, match="目标日收盘缺失"):
        service.compute_and_replace(force=True, computed_at=_computed_at(10))

    assert _snapshot(client) == before


@pytest.mark.parametrize("failure_step", [1, 3, 4])
def test_replace_statement_failures_rollback_exact_previous_rows(market, monkeypatch, failure_step):
    client, _ = market
    service = StockBoardCorrelationService(client)
    service.compute_and_replace(force=True, computed_at=_computed_at(8))
    before = _snapshot(client)
    calls = 0
    original = service._run_replace_statement

    def fail_at_step(sql, params=None):
        nonlocal calls
        calls += 1
        if calls == failure_step:
            raise RuntimeError(f"fault at statement {failure_step}")
        original(sql, params)

    monkeypatch.setattr(service, "_run_replace_statement", fail_at_step)
    with pytest.raises(StorageError, match="已回滚"):
        service.compute_and_replace(force=True, computed_at=_computed_at(9))

    assert _snapshot(client) == before


class _CommitFailureClient(DuckDBClient):
    fail_before_commit = False

    @contextmanager
    def transaction(self):
        with super().transaction():
            yield self
            if self.fail_before_commit:
                raise RuntimeError("fault before commit")


def test_commit_failure_rolls_back_exact_previous_rows(tmp_path):
    with _CommitFailureClient(db_path=tmp_path / "commit-failure.duckdb") as client:
        init_db(client)
        _seed_market(client)
        service = StockBoardCorrelationService(client)
        service.compute_and_replace(force=True, computed_at=_computed_at(8))
        before = _snapshot(client)
        client.fail_before_commit = True

        with pytest.raises(StorageError, match="已回滚"):
            service.compute_and_replace(force=True, computed_at=_computed_at(9))

        assert _snapshot(client) == before


def test_full_scope_does_not_skip_when_out_of_pool_stale_rows_exist(market):
    client, dates = market
    service = StockBoardCorrelationService(client)
    service.compute_and_replace(force=True)
    client.execute(
        "INSERT INTO stock_board_correlation_state VALUES ('600999.SH',?,?,?,?,?,?,?)",
        [dates[-1], _computed_at(10), ALGORITHM_VERSION, "000001.SH", False, False, False],
    )

    result = service.compute_and_replace()

    # 每日快照语义下，池外股票（600999.SH）的历史快照保留（不随全量删除）；它只在
    # "按最新交易日读取"时被排除，并触发全量不跳过（_target_is_current 的 outside_winners 按日判定）。
    assert result.switched is True
    assert (
        client.conn.execute(
            "SELECT count(*) FROM stock_board_correlation_state WHERE code='600999.SH'"
        ).fetchone()[0]
        == 1
    )


def test_phase_callbacks_cancel_immediately_before_switch_without_changing_rows(market):
    client, _ = market
    service = StockBoardCorrelationService(client)
    service.compute_and_replace(force=True, computed_at=_computed_at(8))
    before = _snapshot(client)
    phases = []

    def phase_callback(phase):
        phases.append(phase)

    def cancel_check():
        if phases[-1] == "switch":
            raise RuntimeError("cancel before atomic switch")

    with pytest.raises(RuntimeError, match="cancel before atomic switch"):
        service.compute_and_replace(
            force=True,
            computed_at=_computed_at(9),
            phase_callback=phase_callback,
            cancel_check=cancel_check,
        )

    assert phases == [
        "read_candidates",
        "load_prices",
        "calculate",
        "validate",
        "switch",
    ]
    assert _snapshot(client) == before
