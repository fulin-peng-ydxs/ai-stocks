"""T-M1-8 数据质检测试：涨跌停标记、一字板、ST 限制、异常检测。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from backend.dataquality.checker import QualityChecker, add_markers, limit_pct_for
from backend.market_rules import price_limit_pct_for, round_price_to_cent
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


def _bar(open_, high, low, close, pre_close):
    return pd.DataFrame(
        [{"open": open_, "high": high, "low": low, "close": close, "pre_close": pre_close}]
    )


def test_limit_pct_st_override():
    assert limit_pct_for(0.10, is_st=False) == 0.10
    assert limit_pct_for(0.20, is_st=False) == 0.20
    assert price_limit_pct_for(0.10, is_st=True, trade_date="2026-07-03") == 0.05
    assert price_limit_pct_for(0.10, is_st=True, trade_date="2026-07-06") == 0.10
    assert price_limit_pct_for(0.20, is_st=True, trade_date="2026-07-06") == 0.20


def test_round_price_to_cent_uses_half_up():
    assert round_price_to_cent(1.005) == 1.01


def test_limit_up_main_board():
    # 主板 10%：pre_close 10.00 -> 涨停 11.00
    df = add_markers(_bar(10.5, 11.0, 10.4, 11.0, 10.0), 0.10, False)
    assert df["limit_status"].iloc[0] == 1
    assert not df["is_one_word"].iloc[0]  # 非一字（开!=收）


def test_one_word_limit():
    # 一字涨停：开=高=低=收=11.00，pre=10.00
    df = add_markers(_bar(11.0, 11.0, 11.0, 11.0, 10.0), 0.10, False)
    assert df["limit_status"].iloc[0] == 1
    assert df["is_one_word"].iloc[0]


def test_limit_down_star_board():
    # 科创 20%：pre 10.00 -> 跌停 8.00
    df = add_markers(_bar(8.5, 8.6, 8.0, 8.0, 10.0), 0.20, False)
    assert df["limit_status"].iloc[0] == -1


def test_no_limit_normal_day():
    df = add_markers(_bar(10.0, 10.3, 9.9, 10.2, 10.0), 0.10, False)
    assert df["limit_status"].iloc[0] == 0
    assert not df["is_one_word"].iloc[0]


def test_first_day_no_pre_close():
    df = add_markers(_bar(10.0, 10.3, 9.9, 10.2, None), 0.10, False)
    assert df["limit_status"].iloc[0] == 0  # pre_close 缺失不判涨跌停


def test_abnormal_change_detection():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        c.execute(
            "INSERT INTO daily_bar (code, trade_date, close, pre_close) VALUES "
            "('600000.SH', DATE '2024-01-02', 13.0, 10.0)"  # +30% 远超主板 10%
        )
        qc = QualityChecker(c)
        n = qc.check_abnormal_change("600000.SH", 0.10)
        assert n == 1
        issues = c.query_df("SELECT issue_type FROM data_quality_issue")
        assert issues.iloc[0]["issue_type"] == "abnormal_change"


def test_compute_pre_close_exrights():
    """除权日前收盘按复权因子调整（修复 001332 类高送转误判）。"""
    import pandas as pd

    from backend.datasource.akshare_source import compute_pre_close

    # 普通日因子不变 → pre_close = 上一日收盘
    close = pd.Series([10.0, 10.5, 11.0])
    factor = pd.Series([2.0, 2.0, 2.0])
    pc = compute_pre_close(close, factor)
    assert pd.isna(pc.iloc[0])
    assert abs(pc.iloc[1] - 10.0) < 1e-9
    assert abs(pc.iloc[2] - 10.5) < 1e-9

    # 除权日：因子从 1.5 跳到 2.12（类 001332），前收盘应被调小
    close2 = pd.Series([63.97, 46.45])
    factor2 = pd.Series([1.503674, 2.121851])
    pc2 = compute_pre_close(close2, factor2)
    # 63.97 × 1.503674/2.121851 ≈ 45.33（而非原始 63.97）
    assert abs(pc2.iloc[1] - 45.33) < 0.1


def test_ingest_calibrates_limit_changing_corporate_action_pre_close(monkeypatch):
    """除息参考价一分钱误差改变涨停结论时，使用备用源官方 preclose。"""
    from datetime import date

    import pandas as pd

    from backend.services.ingest import IngestionService

    primary = pd.DataFrame(
        [{
            "code": "603759.SH",
            "trade_date": date(2026, 7, 2),
            "close": 7.65,
            "pre_close": 6.94,
            "_pre_close_factor_event": True,
        }]
    )
    backup = type("Backup", (), {
        "name": "baostock",
        "get_daily_bar": lambda self, code, start, end: pd.DataFrame(
            [{"trade_date": date(2026, 7, 2), "pre_close": 6.95}]
        ),
    })()
    service = object.__new__(IngestionService)
    monkeypatch.setattr(service, "_bao_source", lambda: backup)

    calibrated, source = service._calibrate_corporate_action_pre_close(
        primary, "603759.SH", 0.10, "akshare"
    )

    assert calibrated.iloc[0]["pre_close"] == 6.95
    assert source == "akshare+baostock:preclose"


def test_factor_rebuild_preserves_calibrated_corporate_action_pre_close():
    """后续干净因子重算不能把官方6.95再次覆盖成反推6.94。"""
    from backend.services.ingest import IngestionService
    from backend.storage.repository import MarketRepository

    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        client.execute(
            "INSERT INTO stock_basic (code,name,price_limit_pct) "
            "VALUES ('603759.SH','海天股份',0.10)"
        )
        client.execute(
            """
            INSERT INTO daily_bar
              (code,trade_date,open,high,low,close,pre_close,adj_factor)
            VALUES
              ('603759.SH',DATE '2026-07-01',6.94,7.15,6.80,7.06,6.88,
               1.5722379603399435),
              ('603759.SH',DATE '2026-07-02',6.96,7.65,6.94,7.65,6.95,
               1.5986928104575162)
            """
        )
        service = object.__new__(IngestionService)
        service.c = client
        service.repo = MarketRepository(client)

        service._recompute_clean_one("603759.SH", 0.10, False, full=True)

        row = client.query_df(
            "SELECT pre_close FROM daily_bar "
            "WHERE code='603759.SH' AND trade_date=DATE '2026-07-02'"
        ).iloc[0]
        assert row["pre_close"] == 6.95


def test_sina_js_runtime_initializes_once_under_concurrency(monkeypatch):
    """续跑跳过串行前置时，多工作线程不得并发首次初始化 MiniRacer。"""
    from backend.datasource import akshare_source

    created = 0

    class FakeMiniRacer:
        def __init__(self):
            nonlocal created
            created += 1

        def eval(self, expression):
            assert expression == "1 + 1"

    monkeypatch.setattr(akshare_source, "_SINA_JS_RUNTIME_CONTEXT", None)
    monkeypatch.setattr(akshare_source.py_mini_racer, "MiniRacer", FakeMiniRacer)

    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(lambda _: akshare_source.ensure_sina_js_runtime_ready(), range(24)))

    assert created == 1
    assert akshare_source._SINA_JS_RUNTIME_CONTEXT is not None


def test_sina_daily_prepares_js_runtime_before_fetch(monkeypatch):
    """日线真实入口必须在调用 AKShare 前完成进程运行时预热。"""
    from datetime import date

    from backend.datasource import akshare_source

    calls = []
    monkeypatch.setattr(
        akshare_source,
        "ensure_sina_js_runtime_ready",
        lambda: calls.append("runtime"),
    )
    monkeypatch.setattr(
        akshare_source.ak,
        "stock_zh_a_daily",
        lambda **_kwargs: calls.append("fetch") or pd.DataFrame(),
    )

    source = akshare_source.AKShareSource()
    source._sina_daily("600000", date(2026, 8, 24), date(2026, 8, 24), "")

    assert calls == ["runtime", "fetch"]


def test_dejitter_adj_factor():
    """复权因子去抖：消非除权日噪声、保真实除权跳变。"""
    import pandas as pd

    from backend.datasource.akshare_source import compute_pre_close, dejitter_adj_factor

    # 非除权日带四舍五入噪声（两个 2 位小数价相除）→ 去抖后恒定为首值
    noisy = pd.Series([8.677146, 8.677145, 8.677148, 8.677142])
    close = pd.Series([1309.6, 1307.22, 1281.91, 1268.0])
    clean = dejitter_adj_factor(noisy, close)
    assert (clean == clean.iloc[0]).all()
    # 去抖后非除权日 pre_close 恰为上一日收盘（消除 1309.5998 vs 1309.6 误差）
    pc = compute_pre_close(close, clean)
    assert abs(pc.iloc[1] - 1309.6) < 1e-9
    assert abs(pc.iloc[2] - 1307.22) < 1e-9

    # 真实除权保留，新段内再恒定
    jump = pd.Series([2.2956, 2.2955, 3.4415, 3.4416])  # 第3日除权
    jump_close = pd.Series([10.0, 10.5, 8.0, 8.4])
    cj = dejitter_adj_factor(jump, jump_close)
    assert cj.iloc[1] == cj.iloc[0]            # 第2日沿用
    assert cj.iloc[2] != cj.iloc[1]            # 除权日开启新段
    assert cj.iloc[3] == cj.iloc[2]            # 除权后再恒定
    pc_jump = compute_pre_close(jump_close, cj)
    assert abs(pc_jump.iloc[2] - round(10.5 * 2.2955 / 3.4415, 2)) < 1e-9


def test_dejitter_keeps_small_cash_dividend_and_ignores_next_day_noise():
    """福达合金样本：小额分红日保留，次日因子回摆忽略。"""
    import pandas as pd

    from backend.datasource.akshare_source import compute_pre_close, dejitter_adj_factor

    close = pd.Series([89.20, 80.28, 76.01, 72.86])
    raw_factor = pd.Series([1.448655, 1.448680, 1.451388, 1.451276])
    clean = dejitter_adj_factor(raw_factor, close)
    pc = compute_pre_close(close, clean)
    pct = (close / pc - 1) * 100

    # 2026-06-11：真实小额分红，参考价约 80.13，涨跌幅约 -5.14%
    assert abs(pc.iloc[2] - 80.13) < 0.01
    assert round(float(pct.iloc[2]), 2) == -5.14
    # 2026-06-12：非除权日，回到上一日收盘 76.01，涨跌幅约 -4.14%
    assert abs(pc.iloc[3] - 76.01) < 1e-9
    assert round(float(pct.iloc[3]), 2) == -4.14


def test_dejitter_keeps_debang_exright_reference_price():
    """得邦照明样本：2026-06-12 真实除权参考价应保留。"""
    import pandas as pd

    from backend.datasource.akshare_source import compute_pre_close, dejitter_adj_factor

    close = pd.Series([30.02, 32.30, 32.70])
    raw_factor = pd.Series([2.648901, 2.648916, 2.674006])
    clean = dejitter_adj_factor(raw_factor, close)
    pc = compute_pre_close(close, clean)
    pct = (close / pc - 1) * 100

    assert abs(pc.iloc[2] - 32.00) < 1e-9
    assert round(float(pct.iloc[2]), 2) == 2.19


def test_dejitter_fills_missing_factor_and_keeps_real_reference_change():
    """源端单日因子缺失时沿用上一段；下一日真实参考价变化仍可识别。"""
    import pandas as pd

    from backend.datasource.akshare_source import compute_pre_close, dejitter_adj_factor

    close = pd.Series([69.78, 69.78, 51.25, 56.38])
    raw_factor = pd.Series([2.399828, float("nan"), 3.482732, 3.482618])
    clean = dejitter_adj_factor(raw_factor, close)
    pc = compute_pre_close(close, clean)

    assert abs(clean.iloc[1] - clean.iloc[0]) < 1e-9
    assert clean.iloc[2] != clean.iloc[1]
    assert abs(pc.iloc[1] - 69.78) < 1e-9
    assert abs(pc.iloc[2] - 48.08) < 0.01


def test_dejitter_ignores_source_factor_reset_when_raw_price_continuous():
    """源端后复权因子突然重置为 1，但原始价连续时，不应误判为除权。"""
    import pandas as pd

    from backend.datasource.akshare_source import compute_pre_close, dejitter_adj_factor

    close = pd.Series([7.59, 7.44, 7.67])
    raw_factor = pd.Series([2.578393, 1.0, 1.0])
    clean = dejitter_adj_factor(raw_factor, close)
    pc = compute_pre_close(close, clean)

    assert abs(clean.iloc[1] - clean.iloc[0]) < 1e-9
    assert abs(clean.iloc[2] - clean.iloc[0]) < 1e-9
    assert abs(pc.iloc[1] - 7.59) < 1e-9
    assert abs(pc.iloc[2] - 7.44) < 1e-9


def test_get_daily_bar_anchors_window_first_day():
    """窗口首日 pre_close 修复：向前多取交易日锚定，区间首日不再丢 pre_close。"""
    import datetime as dt

    import pandas as pd

    from backend.datasource.akshare_source import AKShareSource

    # 模拟新浪返回：含请求区间前的锚定日（05-29），区间首日 06-01
    def fake_sina(self, code6, start, end, adjust):
        dates = ["2026-05-28", "2026-05-29", "2026-06-01", "2026-06-02"]
        closes = [33.22, 33.33, 34.70, 34.50]
        return pd.DataFrame({
            "date": pd.to_datetime(dates),
            "open": closes, "high": closes, "low": closes, "close": closes,
            "volume": [1000] * 4, "amount": [value * 1000 for value in closes],
            "turnover": [0.01] * 4, "outstanding_share": [10000] * 4,
        })

    src = AKShareSource()
    src._sina_daily = fake_sina.__get__(src, AKShareSource)
    df = src.get_daily_bar("600000.SH", dt.date(2026, 6, 1), dt.date(2026, 6, 2))
    # 已裁掉锚定日，仅留请求区间
    assert df["trade_date"].min() == dt.date(2026, 6, 1)
    # 区间首日 06-01 的 pre_close = 上一交易日 05-29 收盘（不再为 NaN）
    first = df[df["trade_date"] == dt.date(2026, 6, 1)].iloc[0]
    assert abs(first["pre_close"] - 33.33) < 1e-6


def test_get_daily_bar_keeps_source_adj_factor_for_qfq_prices():
    """福达样本：pre_close 用清洗因子，adj_factor 保留源因子给前复权价。"""
    import datetime as dt

    import pandas as pd

    from backend.datasource.akshare_source import AKShareSource

    dates = ["2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"]
    raw_close = [89.20, 80.28, 76.01, 72.86]
    hfq_close = [129.22, 116.30, 110.32, 105.74]

    def fake_sina(self, code6, start, end, adjust):
        closes = hfq_close if adjust == "hfq" else raw_close
        return pd.DataFrame({
            "date": pd.to_datetime(dates),
            "open": closes, "high": closes, "low": closes, "close": closes,
            "volume": [1000] * 4, "amount": [value * 1000 for value in raw_close],
            "turnover": [0.01] * 4, "outstanding_share": [10000] * 4,
        })

    src = AKShareSource()
    src._sina_daily = fake_sina.__get__(src, AKShareSource)
    df = src.get_daily_bar("603045.SH", dt.date(2026, 6, 10), dt.date(2026, 6, 12))
    row_0611 = df[df["trade_date"] == dt.date(2026, 6, 11)].iloc[0]

    assert abs(row_0611["pre_close"] - 80.13) < 0.01
    assert abs(row_0611["adj_factor"] - (110.32 / 76.01)) < 1e-12


def test_get_daily_bar_retries_crossed_raw_and_hfq_responses():
    """不复权/后复权成交指纹不一致时必须整对重试，不能把串票行情补上请求代码。"""
    import datetime as dt

    import pandas as pd

    from backend.datasource.akshare_source import AKShareSource

    calls = []

    def frame(close, volume, amount):
        return pd.DataFrame({
            "date": pd.to_datetime(["2026-09-08", "2026-09-09"]),
            "open": close, "high": close, "low": close, "close": close,
            "volume": volume, "amount": amount,
            "turnover": [0.01, 0.01], "outstanding_share": [10000, 10000],
        })

    def fake_sina(self, code6, start, end, adjust):
        calls.append(adjust)
        attempt = (len(calls) - 1) // 2
        if attempt == 0:
            return frame([16.0, 16.14], [1000, 1000], [16000, 16140]) if not adjust else frame(
                [39.5, 39.9], [2000, 2000], [32000, 32280]
            )
        return frame([16.0, 16.14], [1000, 1000], [16000, 16140]) if not adjust else frame(
            [39.5, 39.9], [1000, 1000], [16000, 16140]
        )

    src = AKShareSource()
    src._max_retries = 2
    src._retry_backoff_sec = 0
    src._sina_daily = fake_sina.__get__(src, AKShareSource)

    result = src.get_daily_bar("601919.SH", dt.date(2026, 9, 9), dt.date(2026, 9, 9))

    assert calls == ["", "hfq", "", "hfq"]
    assert result.iloc[0]["close"] == 16.14
    assert result.iloc[0]["code"] == "601919.SH"


def test_sanitize_bars():
    """入库自清洗：丢弃坏close、回填零OHL、零成交填0。"""
    import pandas as pd

    from backend.dataquality.checker import sanitize_bars

    df = pd.DataFrame([
        {"close": 10.0, "open": 0.0, "high": 0.0, "low": 0.0, "volume": 100, "amount": 1000.0, "turnover_rate": 1.0},  # OHL=0→回填
        {"close": 0.0, "open": 5.0, "high": 5.0, "low": 5.0, "volume": 0, "amount": None, "turnover_rate": None},      # close=0→丢弃
        {"close": 8.0, "open": 8.0, "high": 8.0, "low": 8.0, "volume": 0, "amount": None, "turnover_rate": None},      # 零成交→填0
    ])
    out, stats = sanitize_bars(df)
    assert stats["dropped"] == 1          # 丢了 close=0 那行
    assert len(out) == 2
    row0 = out.iloc[0]
    assert row0["open"] == 10.0 and row0["high"] == 10.0  # OHL 用 close 回填
    zero = out[out["volume"] == 0].iloc[0]
    assert zero["amount"] == 0.0 and zero["turnover_rate"] == 0.0
