"""ThsBoardSource 数据源适配器单测（mock HTTP，不触网、不碰 DuckDB）。

覆盖计划 T2 验收场景：v cookie 生成 / 401 刷新 / 翻页 / 两种排序策略取多者 /
不完整快照标记（登录墙截断与请求失败）/ 字典全量合并 / 指数解析 / 资金流解析。
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.datasource import ths_board as tb
from backend.datasource.ths_board import ThsBoardSource


# ── 测试页夹具 ────────────────────────────────────────────────

_LOGIN_WALL = '<script>location.href="//upass.10jqka.com.cn/login?redir=..."</script>'


def _member_page(codes: list[str], rows_per_page: int = 20) -> str:
    """构造成分股 AJAX 页 HTML（行内 stockpage 链接）。"""
    rows = []
    for c in codes:
        rows.append(
            f'<tr><td>1</td>'
            f'<td><a href="http://stockpage.10jqka.com.cn/{c}/" target="_blank">{c}</a></td>'
            f'<td><a href="http://stockpage.10jqka.com.cn/{c}" target="_blank">股{c}</a></td>'
            f'<td class="c-rise">10.0</td></tr>'
        )
    return '<table class="m-table"><tbody>' + "".join(rows) + "</tbody></table>"


def _cate_page(codes_names: list[tuple[str, str]]) -> str:
    """构造分类页（行业全量/概念分类页）HTML。"""
    links = "".join(
        f'<a href="https://q.10jqka.com.cn/gn/detail/code/{c}/" target="_blank">{n}</a>'
        for c, n in codes_names
    )
    return f'<div class="cate_inner">{links}</div>'


def _index_page_html(codes_names: list[tuple[str, str]]) -> str:
    """构造 gn/index 分页 HTML（概念补充）。"""
    links = "".join(
        f'<a href="/gn/detail/code/{c}/" target="_blank">{n}</a>' for c, n in codes_names
    )
    return f'<span class="page_info">1/39</span><tbody>{links}</tbody>'


class _FakeResp:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")


# ── 工具函数单测 ──────────────────────────────────────────────


def test_extract_member_codes():
    html = _member_page(["300476", "603936", "300476"])  # 含重复
    assert tb._extract_member_codes(html) == ["300476", "603936"]


def test_is_login_wall():
    assert tb._is_login_wall(_LOGIN_WALL) is True
    assert tb._is_login_wall(_member_page(["300476"])) is False


def test_parse_bar_js():
    js = ('quotebridge_v4_line_bk_886071_01_2026({"data":"'
          '20260105,10,11,9,10.5,1000,2000.5,1,2,3;'
          '20260106,10.5,12,10,11.5,1200,2500.5"}')
    rows = tb._parse_bar_js(js, 2026)
    assert len(rows) == 2
    assert rows[0]["trade_date"] == "2026-01-05"
    assert rows[0]["close"] == 10.5
    assert rows[0]["amount"] == 2000.5


def test_parse_fund_flow_immediate():
    html = (
        '<table><thead><tr><th>序号</th><th>行业</th><th>行业指数</th><th>涨跌幅</th>'
        '<th>流入资金(亿)</th><th>流出资金(亿)</th><th>净额(亿)</th><th>公司家数</th>'
        '<th>领涨股</th><th>涨跌幅.1</th><th>当前价(元)</th></tr></thead><tbody>'
        '<tr><td>1</td><td><a href="http://q.10jqka.com.cn/gn/detail/code/308734/" target="_blank">CRO概念</a></td>'
        '<td>970.0</td><td>8.05%</td><td>227.07</td>'
        '<td>170.78</td><td>56.29</td><td>76</td><td>博腾股份</td><td>20.02%</td><td>20.44</td></tr>'
        '</tbody></table>'
    )
    df = tb._parse_fund_flow(html, board_type="concept", period="即时")
    assert len(df) == 1
    r = df.iloc[0]
    assert r["name"] == "CRO概念"
    assert r["board_code"] == "308734"   # 板块单元格链接里的路径 code 被抓到
    assert r["inflow"] == 227.07
    assert r["net_inflow"] == 56.29
    assert r["net_ratio"] == 8.05
    assert r["leader_stock"] == "博腾股份"
    assert r["leader_pct"] == 20.02


def test_parse_fund_flow_3day_no_leader():
    html = (
        '<table><thead><tr><th>序号</th><th>行业</th><th>公司家数</th><th>行业指数</th>'
        '<th>阶段涨跌幅</th><th>流入资金</th><th>流出资金</th><th>净额</th></tr></thead><tbody>'
        '<tr><td>1</td><td>CRO概念</td><td>76</td><td>970.0</td><td>5.0%</td>'
        '<td>100</td><td>80</td><td>20</td></tr></tbody></table>'
    )
    df = tb._parse_fund_flow(html, board_type="concept", period="3日")
    assert len(df) == 1
    r = df.iloc[0]
    assert r["name"] == "CRO概念"
    assert r["net_ratio"] == 5.0
    assert r["leader_stock"] is None  # 3日周期无领涨股列


def test_num_pct():
    assert tb._num("227.07亿") == 227.07
    assert tb._num("8,123.5") == 8123.5
    assert tb._num("--") is None
    assert tb._num("nan") is None
    assert tb._pct("8.05%") == 8.05
    assert tb._pct("-1.2%") == -1.2


# ── 适配器单测（mock HTTP）────────────────────────────────────


def _make_source(responses: dict[str, object], max_retries: int = 1) -> ThsBoardSource:
    """构造 ThsBoardSource，session.get 返回预置 responses（URL 子串 → 文本/异常）。"""

    class _FakeSession:
        def __init__(self):
            self.calls: list[str] = []

        def get(self, url: str, headers=None, timeout=None):
            self.calls.append(url)
            for key, val in responses.items():
                if key in url:
                    if isinstance(val, Exception):
                        raise val
                    return _FakeResp(val)
            return _FakeResp("", status=404)

    s = ThsBoardSource(min_interval_sec=0.0, timeout=1.0, max_retries=max_retries,
                       retry_backoff_sec=0.0)
    s._session = _FakeSession()  # type: ignore[assignment]
    # 不真正执行 JS：直接注入假 v cookie
    s._v_code = "fake-v-cookie"
    return s


def test_get_board_dict_concept_merges_full():
    """概念字典 = 分类页全量 ∪ gn/index 补充，去重且含登录墙截断保护。"""
    cate = _cate_page([("309121", "AI PC"), ("302035", "人工智能")])
    idx1 = _index_page_html([("309121", "AI PC"), ("309999", "新概念A")])
    idx2 = _index_page_html([("309998", "新概念B")])
    idx3 = _LOGIN_WALL
    s = _make_source({
        "/gn/detail/code/307822": cate,
        "/gn/index/field/addtime/order/desc/page/1": idx1,
        "/gn/index/field/addtime/order/desc/page/2": idx2,
        "/gn/index/field/addtime/order/desc/page/3": idx3,
    })
    df = s.get_board_dict("concept")
    codes = set(df["board_code"])
    assert codes == {"309121", "302035", "309999", "309998"}
    assert len(df) == 4


def test_get_board_dict_industry_cate_full():
    """行业字典 = 分类页全量（90 条无需 gn/index 补充）。"""
    s = _make_source({
        "/thshy/detail/code/881272": _cate_page([("881121", "半导体"), ("881155", "银行")])
    })
    df = s.get_board_dict("industry")
    assert set(df["board_code"]) == {"881121", "881155"}


def test_get_board_members_pagination_and_union():
    """成分股：翻页拼接 + 两种排序策略取并集（field/199112 变体）。"""
    p1 = _member_page(["300476", "603936"])
    p2 = _member_page(["002913"])
    sorted_p1 = _member_page(["300476", "688449"])  # 排序变体含第 1 页无的 688449
    s = _make_source({
        "/field/199112/order/desc/page/1/ajax/1/": sorted_p1,  # 排序变体 key 放前（URL 同时含通用 page key）
        "/page/1/ajax/1/": p1,
        "/page/2/ajax/1/": p2,
        "/page/3/ajax/1/": _LOGIN_WALL,  # 登录墙 → 标记不完整
    })
    m = s.get_board_members("309121", "concept")
    assert set(m["codes"]) == {"300476", "603936", "002913", "688449"}  # 并集含排序变体独有
    assert m["complete"] is False  # 登录墙截断
    assert m["pages"] == 2


def test_get_board_members_request_failure_marks_incomplete():
    """翻页请求失败 → complete=False。"""
    import requests
    p1 = _member_page(["300476"])
    s = _make_source({
        "/field/199112/order/desc/page/1/ajax/1/": p1,
        "/field/199112/order/desc/page/2/ajax/1/": requests.ConnectionError("connection reset"),
        "/page/1/ajax/1/": p1,
        "/page/2/ajax/1/": requests.ConnectionError("connection reset"),
    })
    m = s.get_board_members("309121", "concept")
    assert m["complete"] is False


def test_get_board_members_small_board_complete_through_empty():
    """小板块：真实空表格尾页（非登录墙）→ complete=True。"""
    p1 = _member_page(["300476"])
    s = _make_source({
        "/field/199112/order/desc/page/1/ajax/1/": p1,
        "/field/199112/order/desc/page/2/ajax/1/": "<table class='m-table'></table>",
        "/page/1/ajax/1/": p1,
        "/page/2/ajax/1/": "<table class='m-table'></table>",  # 真实空尾页
    })
    m = s.get_board_members("309121", "concept")
    assert set(m["codes"]) == {"300476"}
    assert m["complete"] is True


def test_401_refresh_and_retry():
    """401 → 刷新 v cookie 后重试成功。"""
    p1 = _member_page(["300476"])
    calls: list[str] = []

    class _FakeSession:
        def get(self, url, headers=None, timeout=None):
            calls.append(url)
            # 第 1 次 401，之后 200
            if calls.count(url) == 1 and "page/1" in url:
                return _FakeResp("", status=401)
            return _FakeResp(p1)

    s = _make_source({})
    s._session = _FakeSession()  # type: ignore[assignment]
    s._v_code = "v1"
    m = s.get_board_members("309121", "concept")
    assert "300476" in m["codes"]
    # 401 后 v cookie 被刷新（置空再生成，mock 下 _v_cookie 仍返回注入值）
    assert any("/page/1/ajax/1/" in u for u in calls)
    assert len(calls) >= 2


def test_get_board_bar():
    """指数：先取 clid 再按年请求 quotebridge JS。"""
    detail = '<input type="hidden" id="clid" value="886071">'
    bar_js = ('quotebridge_v4_line_bk_886071_01_2026({"data":"'
              '20260105,10,11,9,10.5,1000,2000.5;'
              '20260106,10.5,12,10,11.5,1200,2500.5"}')
    s = _make_source({"/gn/detail/code/309121": detail, "/v4/line/bk_886071/01/2026.js": bar_js})
    df = s.get_board_bar("309121", "concept", date(2026, 1, 1), date(2026, 1, 31))
    assert len(df) == 2
    assert df["close"].tolist() == [10.5, 11.5]
    assert df["trade_date"].iloc[0] == date(2026, 1, 5)


def test_get_board_bar_industry_uses_code_as_clid():
    """行业指数：clid = 路径 code，不额外请求详情页。"""
    bar_js = ('quotebridge_v4_line_bk_881121_01_2026({"data":"20260105,10,11,9,10.5,1000,2000.5"})')
    s = _make_source({"/v4/line/bk_881121/01/2026.js": bar_js})
    df = s.get_board_bar("881121", "industry", date(2026, 1, 1), date(2026, 1, 31))
    assert len(df) == 1


def test_get_board_fund_flow_paged():
    """资金流：首页探总数 + 多页拼接 + 领涨股清洗。"""
    p1 = (
        '<span class="page_info">1/2</span>'
        '<table><thead><tr><th>序号</th><th>行业</th><th>涨跌幅</th><th>流入资金(亿)</th>'
        '<th>流出资金(亿)</th><th>净额(亿)</th><th>领涨股</th><th>涨跌幅.1</th></tr></thead><tbody>'
        '<tr><td>1</td><td>CRO概念</td><td>8.05%</td><td>227.07</td><td>170.78</td><td>56.29</td>'
        '<td>博腾股份</td><td>20.02%</td></tr>'
        '</tbody></table>'
    )
    p2 = (
        '<table><thead><tr><th>序号</th><th>行业</th><th>涨跌幅</th><th>流入资金(亿)</th>'
        '<th>流出资金(亿)</th><th>净额(亿)</th><th>领涨股</th><th>涨跌幅.1</th></tr></thead><tbody>'
        '<tr><td>2</td><td>减肥药</td><td>6.62%</td><td>174.41</td><td>121.83</td><td>52.58</td>'
        '<td>博腾股份</td><td>20.02%</td></tr>'
        '</tbody></table>'
    )
    s = _make_source({
        "/page/2/ajax/1/free/1/": p2,  # 先匹配分页（更具体）
        "/funds/gnzjl/": p1,  # 首页（含 page_info）
    })
    df = s.get_board_fund_flow("concept", "即时")
    assert len(df) == 2
    assert set(df["name"]) == {"CRO概念", "减肥药"}
    assert df["leader_stock"].tolist() == ["博腾股份", "博腾股份"]
    assert df["net_inflow"].tolist() == [56.29, 52.58]


def test_get_board_fund_flow_empty_shell_retried_then_success():
    """资金流：第 2 页偶发空壳（200-无行）重试后成功，不截断后续页。"""
    p1 = (
        '<span class="page_info">1/3</span>'
        '<table><thead><tr><th>序号</th><th>行业</th><th>涨跌幅</th><th>流入资金(亿)</th>'
        '<th>流出资金(亿)</th><th>净额(亿)</th><th>领涨股</th><th>涨跌幅.1</th></tr></thead><tbody>'
        '<tr><td>1</td><td>CRO概念</td><td>8.05%</td><td>227.07</td><td>170.78</td><td>56.29</td>'
        '<td>博腾股份</td><td>20.02%</td></tr>'
        '</tbody></table>'
    )
    p2 = (
        '<table><thead><tr><th>序号</th><th>行业</th><th>涨跌幅</th><th>流入资金(亿)</th>'
        '<th>流出资金(亿)</th><th>净额(亿)</th><th>领涨股</th><th>涨跌幅.1</th></tr></thead><tbody>'
        '<tr><td>2</td><td>减肥药</td><td>6.62%</td><td>174.41</td><td>121.83</td><td>52.58</td>'
        '<td>博腾股份</td><td>20.02%</td></tr>'
        '</tbody></table>'
    )
    p3 = (
        '<table><thead><tr><th>序号</th><th>行业</th><th>涨跌幅</th><th>流入资金(亿)</th>'
        '<th>流出资金(亿)</th><th>净额(亿)</th><th>领涨股</th><th>涨跌幅.1</th></tr></thead><tbody>'
        '<tr><td>3</td><td>猴痘概念</td><td>5.1%</td><td>100.0</td><td>80.0</td><td>20.0</td>'
        '<td>博腾股份</td><td>20.02%</td></tr>'
        '</tbody></table>'
    )
    # 用计数器模拟：第 2 页第 1 次空壳（空 tbody），重试返回数据
    class _FlakySession:
        def __init__(self):
            self.page2_hits = 0

        def get(self, url, headers=None, timeout=None):
            if "/page/2/ajax/1/free/1/" in url:
                self.page2_hits += 1
                if self.page2_hits == 1:
                    return _FakeResp('<table class="m-table"><tbody></tbody></table>')
                return _FakeResp(p2)
            if "/page/3/ajax/1/free/1/" in url:
                return _FakeResp(p3)
            if "/funds/gnzjl/" in url:
                return _FakeResp(p1)
            return _FakeResp("", status=404)

    s = _make_source({})
    s._session = _FlakySession()  # type: ignore[assignment]
    df = s.get_board_fund_flow("concept", "即时")
    assert len(df) == 3
    assert set(df["name"]) == {"CRO概念", "减肥药", "猴痘概念"}


def test_get_board_fund_flow_persistent_empty_mid_page_skipped():
    """资金流：中间页持续空壳（重试仍空）只跳过该页，不截断后续页。"""
    p1 = (
        '<span class="page_info">1/3</span>'
        '<table><thead><tr><th>序号</th><th>行业</th><th>涨跌幅</th><th>流入资金(亿)</th>'
        '<th>流出资金(亿)</th><th>净额(亿)</th><th>领涨股</th><th>涨跌幅.1</th></tr></thead><tbody>'
        '<tr><td>1</td><td>CRO概念</td><td>8.05%</td><td>227.07</td><td>170.78</td><td>56.29</td>'
        '<td>博腾股份</td><td>20.02%</td></tr>'
        '</tbody></table>'
    )
    p3 = (
        '<table><thead><tr><th>序号</th><th>行业</th><th>涨跌幅</th><th>流入资金(亿)</th>'
        '<th>流出资金(亿)</th><th>净额(亿)</th><th>领涨股</th><th>涨跌幅.1</th></tr></thead><tbody>'
        '<tr><td>3</td><td>猴痘概念</td><td>5.1%</td><td>100.0</td><td>80.0</td><td>20.0</td>'
        '<td>博腾股份</td><td>20.02%</td></tr>'
        '</tbody></table>'
    )
    s = _make_source({
        "/page/2/ajax/1/free/1/": '<table class="m-table"><tbody></tbody></table>',  # 第 2 页持续空壳
        "/page/3/ajax/1/free/1/": p3,  # 更具体，先匹配
        "/funds/gnzjl/": p1,
    })
    df = s.get_board_fund_flow("concept", "即时")
    assert len(df) == 2
    assert set(df["name"]) == {"CRO概念", "猴痘概念"}


def test_validate_board_type():
    with pytest.raises(ValueError):
        _make_source({}).get_board_dict("bad_type")
    with pytest.raises(ValueError):
        _make_source({}).get_board_fund_flow("concept", "7日")


# ── 登录态（解除翻页登录墙）──────────────────────────────────


def test_login_cookie_from_env(monkeypatch):
    monkeypatch.delenv("AI_STOCKS_THS_COOKIE", raising=False)
    monkeypatch.delenv("AI_STOCKS_THS_COOKIE_FILE", raising=False)
    # 环境变量与配置兜底都为空 → None
    monkeypatch.setattr("backend.datasource.ths_board.get_effective_settings",
                        lambda: _NoCookieSettings())
    assert tb._login_cookie_from_env() is None

    monkeypatch.setenv("AI_STOCKS_THS_COOKIE", "user=1; ticket=abc")
    assert tb._login_cookie_from_env() == "user=1; ticket=abc"

    # FILE 优先于空 COOKIE
    monkeypatch.delenv("AI_STOCKS_THS_COOKIE")
    import tempfile
    import os
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("file-cookie=xyz")
        p = f.name
    monkeypatch.setenv("AI_STOCKS_THS_COOKIE_FILE", p)
    try:
        assert tb._login_cookie_from_env() == "file-cookie=xyz"
    finally:
        os.unlink(p)


class _NoCookieSettings:
    class ths_board:
        login_cookie = ""


def test_login_cookie_config_fallback(monkeypatch):
    """环境变量为空时回落数据治理页面配置的登录 Cookie。"""
    monkeypatch.delenv("AI_STOCKS_THS_COOKIE", raising=False)
    monkeypatch.delenv("AI_STOCKS_THS_COOKIE_FILE", raising=False)

    class _Cfg:
        class ths_board:
            login_cookie = "cfg-cookie=abc"
    monkeypatch.setattr("backend.datasource.ths_board.get_effective_settings", lambda: _Cfg())
    assert tb._login_cookie_from_env() == "cfg-cookie=abc"

    # 环境变量存在时优先（覆盖配置）
    monkeypatch.setenv("AI_STOCKS_THS_COOKIE", "env-cookie=123")
    assert tb._login_cookie_from_env() == "env-cookie=123"


def test_headers_login_cookie_uses_login_v():
    """登录态：保留登录凭证，但必须用本机生成的动态 v 替换复制来的旧 v。"""
    s = _make_source({})
    s._login_cookie = "user=1; ticket=abc; v=loginv"
    h = s._headers()
    assert h["Cookie"] == "user=1; ticket=abc; v=fake-v-cookie"

    # 无登录态：拼接独立生成的 v
    s2 = _make_source({})
    s2._v_code = "genv"
    h2 = s2._headers()
    assert h2["Cookie"] == "v=genv"


def test_get_board_app_code_uses_clid_and_cache():
    """双代码：概念从详情页取 clid，重复读取命中缓存；行业直接使用路径 code。"""
    s = _make_source({"/gn/detail/code/309121": '<input id="clid" value="886071">'})
    assert s.get_board_app_code("309121", "concept") == "886071"
    assert s.get_board_app_code("309121", "concept") == "886071"
    assert s.get_board_app_code("881121", "industry") == "881121"
    assert sum("/gn/detail/code/309121" in x for x in s._session.calls) == 1


def test_get_board_members_login_breaks_wall():
    """登录态下：第 6 页返回真实数据（非登录墙）→ 正常拼接，空尾页才终止。"""
    p1 = _member_page(["300476", "603936"])
    p2 = _member_page(["002913", "688449"])
    p3 = _LOGIN_WALL  # 登录态下若仍出现登录墙（极端），仍应标不完整
    s = _make_source({
        "/field/199112/order/desc/page/1/ajax/1/": p1,
        "/field/199112/order/desc/page/2/ajax/1/": p2,
        "/page/1/ajax/1/": p1,
        "/page/2/ajax/1/": p2,
        "/page/3/ajax/1/": p3,
    })
    s._login_cookie = "user=1; ticket=abc"  # 模拟登录态
    m = s.get_board_members("309121", "concept")
    # 两页并集全拿到；第 3 页登录墙（极端情形）→ 不完整兜底
    assert set(m["codes"]) == {"300476", "603936", "002913", "688449"}
    assert m["complete"] is False  # 登录墙兜底仍生效


def test_get_board_members_login_true_end():
    """登录态下：正常空表格=真实尾页，complete=True。"""
    p1 = _member_page(["300476"])
    s = _make_source({
        "/field/199112/order/desc/page/1/ajax/1/": p1,
        "/field/199112/order/desc/page/2/ajax/1/": "<table class='m-table'></table>",
        "/page/1/ajax/1/": p1,
        "/page/2/ajax/1/": "<table class='m-table'></table>",
    })
    s._login_cookie = "user=1; ticket=abc"
    m = s.get_board_members("309121", "concept")
    assert set(m["codes"]) == {"300476"}
    assert m["complete"] is True
