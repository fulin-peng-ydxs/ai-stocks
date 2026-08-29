"""个股走势关联板块确定性性能入口的轻量契约测试。"""

from backend.devtools.benchmark_stock_board_correlation import build_fixture, run_benchmark


def test_benchmark_fixture_is_reproducible_for_fixed_seed():
    first = build_fixture(stock_count=3, candidate_count=4, seed=20260829)
    second = build_fixture(stock_count=3, candidate_count=4, seed=20260829)

    assert first == second
    assert len(first.stocks) == 3
    assert len(first.candidates) == 4


def test_small_benchmark_entry_reports_requested_scale():
    result = run_benchmark(stock_count=4, candidate_count=3, seed=20260829)

    assert result.stocks == 4
    assert result.candidates_per_stock == 3
    assert result.candidate_relations == 12
    assert result.elapsed_seconds > 0
    assert result.candidate_throughput_per_second > 0
    assert result.peak_python_alloc_mib > 0
