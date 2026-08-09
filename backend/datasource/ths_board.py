"""同花顺板块数据源适配器（板块概念需求 R1-R4）。

独立普通类（不继承 `DataSource`、不进 `_source_for` 选源链）——同花顺板块取数是关系型数据
（板块字典/成分股多对多/板块指数/资金流），与 `DataSource` 的「个股时间序列」抽象职责不同，
此口径承接 research.md 附录《同花顺板块适配器封装决策》与 requirement-closure.md §189 已确认决策。

直连同花顺 `q.10jqka.com.cn` / `data.10jqka.com.cn` / `d.10jqka.com.cn`，不调用 akshare 板块公开函数；
仅复用 akshare 打包的 `ths.js`（反爬 v cookie 生成脚本，经 `py_mini_racer` 执行）与其 URL/参数形态。

取数要点（research.md §2/§5.4 实测）：
- 请求必须带 v cookie（概念/行业详情页 AJAX），否则 401；`data.*` 资金流用 `hexin-v` 头。
- 翻页是路径参数 `page/N/ajax/1/`，不是 URL query；每页行数不固定（概念 10/行业 20），
  用「该页无行」终止翻页，并做页码上限护栏。
- 排序参数敏感：部分板块带 `field/199112/order/desc` 才能取全，部分不带反而更多；
  鲁棒策略是两种请求都试、取代码集合的并集。
- 板块指数历史：先取详情页 `clid`（概念 88xxxx / 行业=路径 code），再按年请求
  `https://d.10jqka.com.cn/v4/line/bk_{clid}/01/{year}.js`（quotebridge 包裹的 JSON 文本）。
- 资金流：`data.10jqka.com.cn/funds/gnzjl`（概念）/`hyzjl`（行业），周期走 `board/N` 参数，
  表格 `pd.read_html` 解析（列名带单位括号与 % 后缀，入库前清洗）。
"""

from __future__ import annotations

import json
import re
import time
from datetime import date
from io import StringIO

import pandas as pd
import requests
from importlib import resources

from backend.common.exceptions import DataSourceError
from backend.common.logging import get_logger
from backend.datasource.base import rate_limited, with_retry

log = get_logger("datasource.ths_board")

# ── 常量 ─────────────────────────────────────────────────────

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/90.0.4430.85 Safari/537.36"
)
# 板块详情页（概念/行业）基础 URL；成分股 AJAX 翻页与排序参数拼在其后
_DETAIL_URLS = {
    "concept": "https://q.10jqka.com.cn/gn/detail/code/{code}",
    "industry": "https://q.10jqka.com.cn/thshy/detail/code/{code}",
}
# 概念全量索引分页（分类页 cate_inner 仅折叠展示 58 条，此处按概念时间表分页取全量）
_CONCEPT_INDEX_PAGE = "http://q.10jqka.com.cn/gn/index/field/addtime/order/desc/page/{page}/ajax/1/"
# 资金流排行基础 URL（概念 gnzjl / 行业 hyzjl）
_FUND_FLOW_URLS = {
    "concept": "http://data.10jqka.com.cn/funds/gnzjl",
    "industry": "http://data.10jqka.com.cn/funds/hyzjl",
}
# 资金流周期 → 是否带 board/N 段（即时无 board 段）
_FUND_FLOW_PERIODS = {
    "即时": "", "3日": "board/3/", "5日": "board/5/", "10日": "board/10/", "20日": "board/20/",
}
# 指数日线 JS 模板（{clid}/{yyyy}）
_BAR_LINE_URL = "https://d.10jqka.com.cn/v4/line/bk_{clid}/01/{year}.js"
# 分页终止护栏（登录墙截断下的兜底；实测第 6 页起必登录墙，护栏远大于实际可达页数）
_MAX_PAGES = 50


def _ths_js_path() -> "str":
    """akshare 打包的同花顺 v cookie 脚本路径（akshare.data/ths.js，走 importlib.resources）。"""
    return str(resources.files("akshare.data").joinpath("ths.js"))


def _login_cookie_from_env() -> str | None:
    """从环境变量读取登录态 cookie（浏览器同花顺登录后复制，非硬编码、不入库）。

    `AI_STOCKS_THS_COOKIE` 为完整 Cookie 头字符串；也可指向存有 cookie 的文件路径
    （`AI_STOCKS_THS_COOKIE_FILE`）。登录态可解除详情页翻页的登录墙（第 6 页起无登录
    必返回登录墙，登录后正常翻页，见 get_board_members docstring）。
    """
    import os

    raw = os.environ.get("AI_STOCKS_THS_COOKIE", "")
    if not raw:
        f = os.environ.get("AI_STOCKS_THS_COOKIE_FILE", "")
        if f:
            try:
                with open(f, encoding="utf-8") as fh:
                    raw = fh.read().strip()
            except OSError:
                return None
    return raw or None


class ThsBoardSource:
    """同花顺板块数据适配器（独立普通类，见模块 docstring）。"""

    name = "ths_board"

    def __init__(
        self,
        session: requests.Session | None = None,
        min_interval_sec: float = 2.0,
        timeout: float = 10.0,
        max_retries: int = 3,
        retry_backoff_sec: float = 2.0,
        login_cookie: str | None = None,
    ):
        self._session = session or requests.Session()
        # 与 base.py 装饰器契约一致：实例属性优先级 > 装饰器入参（运行时可按生效配置注入）
        self._min_interval_sec = min_interval_sec
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_backoff_sec = retry_backoff_sec
        self._v_code: str | None = None
        # 可选登录态（环境变量注入，不硬编码）：解除详情页翻页登录墙
        self._login_cookie = login_cookie if login_cookie is not None else _login_cookie_from_env()

    # ── v cookie（反爬校验）──────────────────────────────────

    @with_retry()
    def _v_cookie(self) -> str:
        """经 py_mini_racer 执行 akshare 打包的 ths.js 生成 v cookie。"""
        if self._v_code:
            return self._v_code
        import py_mini_racer

        js_path = _ths_js_path()
        with open(js_path, encoding="utf-8") as f:
            js = f.read()
        ctx = py_mini_racer.MiniRacer()
        ctx.eval(js)
        self._v_code = str(ctx.call("v"))
        return self._v_code

    def _refresh_v_cookie(self) -> None:
        """401 时强制刷新 v cookie（置空后下次 _v_cookie 重新生成）。"""
        self._v_code = None

    def _headers(self, *, data_host: bool = False) -> dict:
        v = self._v_cookie()
        base = {"User-Agent": _UA}
        if data_host:
            base.update({
                "hexin-v": v,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "http://data.10jqka.com.cn/funds/gnzjl/",
            })
            if self._login_cookie:
                base["Cookie"] = self._login_cookie
        else:
            if self._login_cookie:
                # 登录态：用登录 cookie（含 user/ticket/sess_tk 等登录凭证 + 有效 v），
                # 解除详情页翻页登录墙；不再拼接独立 v（登录 cookie 已带 v）
                base["Cookie"] = self._login_cookie
            else:
                base["Cookie"] = f"v={v}"
        return base

    # ── 底层 HTTP ────────────────────────────────────────────

    @rate_limited(1.0)
    def _http_get(self, url: str, *, data_host: bool = False, referer: str | None = None) -> str:
        """GET 并返回文本（带限流 + 401 刷新单次重试 + 普通异常指数退避重试）。

        v cookie 失效（401）会触发同花顺频次反爬：刷新 cookie 后**只重试一次**，不经过
        with_retry 的指数退避（避免连续 401 时白等 2s+4s）；其余异常按 _max_retries 指数退避。
        """
        for attempt in range(1, self._max_retries + 1):
            try:
                headers = self._headers(data_host=data_host)
                if referer:
                    headers["Referer"] = referer
                resp = self._session.get(url, headers=headers, timeout=self._timeout)
                if resp.status_code == 401:
                    self._refresh_v_cookie()
                    # 刷新后重试一次
                    headers = self._headers(data_host=data_host)
                    if referer:
                        headers["Referer"] = referer
                    resp = self._session.get(url, headers=headers, timeout=self._timeout)
                    if resp.status_code == 401:
                        raise _VCookieInvalid("v cookie 刷新后仍 401")
                resp.raise_for_status()
                return resp.text
            except _VCookieInvalid as e:
                raise DataSourceError(f"{url} v cookie 失效且刷新后仍不可用: {e}") from e
            except Exception as e:  # noqa: BLE001
                if attempt < self._max_retries:
                    sleep = self._retry_backoff_sec * (2 ** (attempt - 1))
                    log.warning("%s 第%d次失败: %s，%.1fs 后重试", url, attempt, e, sleep)
                    time.sleep(sleep)
                else:
                    raise DataSourceError(f"{url} 重试 {self._max_retries} 次仍失败: {e}") from e

    # ── 公开取数方法 ─────────────────────────────────────────

    @rate_limited(1.0)
    def get_board_dict(self, board_type: str) -> pd.DataFrame:
        """板块字典：同花顺概念/行业全量板块（name, board_code 6 位路径 code）。

        概念 = 分类页全量（351，`/gn/detail/code/` 链接直接抓，不截断 cate_inner）∪
        `gn/index` 分页前几页净增（24 个新概念，实测 375 全量；`gn/index` 翻页到第 6 页起
        触发同花顺登录墙——HTTP 200 但返回登录跳转壳，此时应停止而非继续翻页）。
        行业：分类页 cate_inner 含全量 90 条。返回列：board_code, name。
        """
        _validate_board_type(board_type)
        if board_type == "industry":
            html = self._http_get(_DETAIL_URLS["industry"].format(code="881272"),
                                  referer="https://q.10jqka.com.cn/")
            pairs = _parse_board_links(html)
            df = pd.DataFrame({"board_code": [c for c, _ in pairs], "name": [n for _, n in pairs]})
            df = df.drop_duplicates(subset="board_code").reset_index(drop=True)
            return df
        # 概念：分类页全量 + gn/index 补充（遇到登录墙空页即停）
        seen: dict[str, str] = {}
        cate_html = self._http_get(_DETAIL_URLS["concept"].format(code="307822"),
                                   referer="https://q.10jqka.com.cn/")
        for code, name in _parse_board_links(cate_html):
            seen.setdefault(code, name)
        for page in range(1, 6):  # 实测前 3 页即净增完；护栏 5 页防无限
            html = self._http_get(_CONCEPT_INDEX_PAGE.format(page=page),
                                  referer="https://q.10jqka.com.cn/")
            if _is_login_wall(html):
                break  # 登录墙：后续页不再有新概念，停止
            pairs = _parse_board_links(html)
            if not pairs:
                break
            for code, name in pairs:
                seen.setdefault(code, name)
        df = pd.DataFrame({"board_code": list(seen), "name": [seen[c] for c in seen]})
        return df

    @rate_limited(1.0)
    def get_board_members(self, code: str, board_type: str = "concept") -> dict:
        """板块成分股：分页取详情页 AJAX 表格全部成分股。

        排序参数敏感（research.md §2）：无排序参数与 `field/199112/order/desc` 两种请求都试，
        取代码集合的并集（避免某一种被源端少返回）。
        **翻页限制（2026-08-09 实测，登录态可解除）**：无登录态时详情页翻页第 6 页起必返回登录墙
        （HTTP 200 但内容为 `upass...login` 跳转壳，单发第 6 页同样命中），单板块最多稳定取 5 页
        （概念 50 只/行业 100 只）；**提供登录 cookie（`login_cookie`/`AI_STOCKS_THS_COOKIE`）后
        登录墙解除**——第 6 页起正常返回数据、空页即真实尾页（实测半导体完整 120 只），`complete`
        判定回归正确。遇到登录墙时若此前已有数据，标记 `complete=False`（数据可能被截断），供
        采集层走 R2 不完整快照保护。返回：
        {"codes": [6 位代码...], "complete": bool, "pages": int}
        """
        _validate_board_type(board_type)
        base = _DETAIL_URLS[board_type].format(code=code)
        variants = [base, f"{base}/field/199112/order/desc"]
        seen: dict[str, None] = {}
        complete = True
        total_pages = 0
        for v in variants:
            page = 1
            got_any = False
            while page <= _MAX_PAGES:
                url = f"{v}/page/{page}/ajax/1/"
                try:
                    html = self._http_get(url, referer="https://q.10jqka.com.cn/")
                except Exception as e:  # noqa: BLE001 —— 单页失败标记不完整，不中断整体
                    log.warning("板块 %s 第 %d 页取数失败: %s", code, page, e)
                    complete = False
                    break
                if _is_login_wall(html):
                    # 登录墙仅无登录态出现：数据可能被截断（大板块取不全），保守标不完整
                    if got_any or page > 1:
                        complete = False
                    break
                codes = _extract_member_codes(html)
                if not codes:
                    break  # 正常空表格 = 真实尾页
                seen.update({c: None for c in codes})
                got_any = True
                total_pages = page
                page += 1
            if not got_any and complete:
                complete = False  # 整个 variant 一页都没取到 → 源端异常
        return {"codes": list(seen), "complete": complete, "pages": total_pages}

    @rate_limited(1.0)
    def get_board_bar(self, code: str, board_type: str, start: date, end: date) -> pd.DataFrame:
        """板块指数日线（原始连续指数，原值）。

        先取详情页 clid（概念 88xxxx / 行业=路径 code），再按年请求 quotebridge JS。
        返回列：trade_date, open, high, low, close, volume, amount。
        """
        _validate_board_type(board_type)
        clid = self._get_clid(code, board_type)
        rows: list[dict] = []
        for year in range(start.year, end.year + 1):
            url = _BAR_LINE_URL.format(clid=clid, year=year)
            try:
                text = self._http_get(url, referer="https://q.10jqka.com.cn/")
            except Exception as e:  # noqa: BLE001 —— 单年失败跳过（指数缺口由 T7 质检扫描发现）
                log.warning("板块 %s 指数 %d 年取数失败: %s", code, year, e)
                continue
            for row in _parse_bar_js(text, year):
                rows.append(row)
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        df = df[(df["trade_date"] >= start) & (df["trade_date"] <= end)]
        return df.reset_index(drop=True)

    @rate_limited(1.0)
    def get_board_fund_flow(self, board_type: str, period: str = "即时") -> pd.DataFrame:
        """板块资金流排行（概念/行业 × 周期），多页拼接。

        返回列（清洗后）：name, board_code(6 位路径 code), period, inflow, outflow,
        net_inflow, net_ratio, leader_stock, leader_pct。
        资金流源无稳定代码、只有名称时，board_code 由调用方按名称映射（未匹配写质检不伪造代码，见 R4）。
        """
        _validate_board_type(board_type)
        if period not in _FUND_FLOW_PERIODS:
            raise ValueError(f"非法资金流周期: {period}（可选 {list(_FUND_FLOW_PERIODS)}）")
        base = _FUND_FLOW_URLS[board_type]
        board_seg = _FUND_FLOW_PERIODS[period]
        # 先探首页拿总页数（page_info「1/N」）
        first_url = f"{base}/{board_seg}field/tradezdf/order/desc/page/1/ajax/1/free/1/"
        first = self._http_get(first_url, data_host=True)
        total_pages = _fund_flow_total_pages(first)
        frames: list[pd.DataFrame] = []
        for page in range(1, total_pages + 1):
            url = f"{base}/{board_seg}field/tradezdf/order/desc/page/{page}/ajax/1/free/1/"
            text = first if page == 1 else self._http_get(url, data_host=True)
            df = _parse_fund_flow(text, board_type=board_type, period=period)
            if df.empty:
                break
            frames.append(df)
        if not frames:
            return pd.DataFrame(columns=_FUND_FLOW_COLS)
        out = (pd.concat(frames, ignore_index=True)
               .drop_duplicates(subset="name")
               .reset_index(drop=True))
        return out

    def _get_clid(self, code: str, board_type: str) -> str:
        """详情页隐藏字段 clid：概念=App 内部码（88xxxx），行业=路径 code。"""
        if board_type == "industry":
            return code
        url = _DETAIL_URLS[board_type].format(code=code)
        html = self._http_get(url, referer="https://q.10jqka.com.cn/")
        m = re.search(r'<input[^>]+id="clid"[^>]+value=[\'"](\d+)[\'"]', html)
        if not m:
            raise ValueError(f"板块 {code} 详情页无 clid（疑似代码失效）")
        return m.group(1)


# ── 解析工具 ─────────────────────────────────────────────────

_FUND_FLOW_COLS = [
    "name", "board_code", "period", "inflow", "outflow",
    "net_inflow", "net_ratio", "leader_stock", "leader_pct",
]


class _VCookieInvalid(Exception):
    """v cookie 失效（401）——内部信号，由 with_retry 重试刷新后的请求。"""


def _validate_board_type(board_type: str) -> None:
    if board_type not in ("concept", "industry"):
        raise ValueError(f"非法板块类型: {board_type}（concept|industry）")


def _extract_member_codes(html: str) -> list[str]:
    """成分股 AJAX 页：抽取行内 `stockpage.10jqka.com.cn/{code}/` 链接的 6 位代码（去重保序）。"""
    codes = re.findall(r"stockpage\.10jqka\.com\.cn/(\d{6})/", html)
    return list(dict.fromkeys(codes))


def _parse_board_links(html: str) -> list[tuple[str, str]]:
    """提取页面内全部板块链接 (code, name)：`/gn/detail/code/{code}/` 或 `/thshy/detail/code/{code}/`。

    直接全页正则（不依赖 cate_inner 块边界——该块含多个 cate_group，非贪婪截断会丢概念）。
    """
    return [
        (code, name.strip())
        for code, name in re.findall(r'/code/(\d+)/"[^>]*>([^<]+)</a>', html)
        if name.strip()
    ]


def _is_login_wall(html: str) -> bool:
    """同花顺登录墙识别：HTTP 200 但返回登录跳转壳（`location.href="//upass.10jqka.com.cn/login"`）。"""
    return "upass.10jqka.com.cn/login" in html


def _paged_total(html: str) -> int:
    """`span.page_info` 的「1/N」取总页数（列表/资金流通用）；缺省 1。"""
    m = re.search(r'page_info[^>]*>([^<]+)<', html)
    if not m:
        return 1
    parts = m.group(1).split("/")
    try:
        return max(1, int(parts[-1].strip()))
    except (ValueError, IndexError):
        return 1


def _parse_bar_js(text: str, year: int) -> list[dict]:
    """解析 quotebridge 指数 JS：`quotebridge_...(json)` 包裹，data 为分号分隔行。

    行字段：date,open,high,low,close,volume,amount,后续未知列忽略。
    返回 trade_date(ISO 字符串), open/high/low/close(float), volume/amount(int)。
    """
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return []
    try:
        payload = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    data = payload.get("data", "")
    rows: list[dict] = []
    for line in str(data).split(";"):
        parts = line.split(",")
        if len(parts) < 7 or not parts[0].strip():
            continue
        try:
            rows.append({
                "trade_date": (f"{parts[0].strip()[:4]}-{parts[0].strip()[4:6]}"
                               f"-{parts[0].strip()[6:8]}"),
                "open": float(parts[1]),
                "high": float(parts[2]),
                "low": float(parts[3]),
                "close": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]),
            })
        except ValueError:
            continue
    return rows


def _fund_flow_total_pages(html: str) -> int:
    """资金流首页 `span.page_info` 取总页数（复用通用 _paged_total）。"""
    return _paged_total(html)


def _parse_fund_flow(html: str, *, board_type: str, period: str) -> pd.DataFrame:
    """资金流 HTML 表格 → 清洗后 DataFrame。

    即时周期列：行业/行业指数/涨跌幅/流入资金(亿)/流出资金(亿)/净额(亿)/公司家数/领涨股/涨跌幅/当前价；
    3/5/10/20 日周期列：行业/公司家数/行业指数/阶段涨跌幅/流入/流出/净额（无领涨股）。
    """
    try:
        table = pd.read_html(StringIO(html))[0]
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=_FUND_FLOW_COLS)
    if table.empty:
        return pd.DataFrame(columns=_FUND_FLOW_COLS)
    cols = [str(c) for c in table.columns]
    name_col = next((c for c in cols if c in ("行业", "板块")), None)
    if name_col is None:
        return pd.DataFrame(columns=_FUND_FLOW_COLS)

    # 列定位：按列名子串匹配（同花顺列名带单位括号/序号，跨版本有差异）
    def col(substr: str) -> str | None:
        for c in cols:
            if substr in c:
                return c
        return None

    inflow_c = col("流入资金")
    outflow_c = col("流出资金")
    net_c = col("净额")
    ratio_c = col("涨跌幅") or col("阶段涨跌幅")
    leader_c = col("领涨股")
    leader_pct_c = None
    if leader_c is not None:
        # 领涨股涨幅列：'涨跌幅.1' 或紧随领涨股的 '涨跌幅'（同名第二列）
        for c in cols:
            if "涨跌幅" in c and c != ratio_c:
                leader_pct_c = c
                break
    rows: list[dict] = []
    for _, r in table.iterrows():
        row: dict = {"name": str(r[name_col]).strip(), "board_code": "",
                     "period": period, "inflow": None, "outflow": None,
                     "net_inflow": None, "net_ratio": None,
                     "leader_stock": None, "leader_pct": None}
        row["inflow"] = _num(r[inflow_c]) if inflow_c else None
        row["outflow"] = _num(r[outflow_c]) if outflow_c else None
        row["net_inflow"] = _num(r[net_c]) if net_c else None
        row["net_ratio"] = _pct(r[ratio_c]) if ratio_c else None
        if leader_c is not None:
            row["leader_stock"] = str(r[leader_c]).strip()
            if leader_pct_c is not None:
                row["leader_pct"] = _pct(r[leader_pct_c])
        rows.append(row)
    return pd.DataFrame(rows)


def _num(value) -> float | None:
    """'227.07'/'227.07亿'/NaN → float（去除单位后缀与逗号）。"""
    try:
        s = str(value).replace(",", "").strip()
        if s in ("", "--", "nan", "None"):
            return None
        s = re.sub(r"[亿万元%]+", "", s)
        return float(s)
    except (ValueError, TypeError):
        return None


def _pct(value) -> float | None:
    """'8.05%'/'-1.2%' → float（百分数值，不带 %）。"""
    v = _num(value)
    return v
