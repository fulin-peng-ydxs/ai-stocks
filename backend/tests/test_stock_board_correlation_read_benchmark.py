"""T10：批量冠军摘要读取基准入口契约。"""

from backend.devtools.benchmark_stock_board_correlation_read import run_read_benchmark


def test_read_benchmark_reports_fixed_scales_and_one_sql_per_round():
    report = run_read_benchmark(stock_count=220, rounds=3, warmups=1)

    assert report.fixture_stocks == 220
    assert report.fixture_champions == 440
    assert [item.codes for item in report.results] == [1, 50, 200]
    assert all(item.rounds == 3 for item in report.results)
    assert all(item.p50_ms > 0 and item.p95_ms > 0 for item in report.results)
    assert all(item.sql_queries_per_round == 1 for item in report.results)
