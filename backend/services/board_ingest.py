"""板块概念数据采集服务（板块概念需求 R1-R4，agent-works/concept-industry-board/）。

编排逻辑（承接 plan §6.4 T4）：
1. 字典两阶段：概念/行业字典 upsert（阶段一）→ 资金流并集补充 + has_fund_flow（阶段二）
   → 能力字段与 last_seen_at 收口。
2. 成分快照（只进不出）：逐板块 `ThsBoardSource.get_board_members` → 完整性判定（完整才落库）
   → 完整快照 INSERT ON CONFLICT DO NOTHING（(board_code, code) 单行累积，不删除不 diff）
   + 刷新 member_count/member_history_start_date；不完整快照整趟不落库、
   data_update_log 记 failed + 写 board_member_incomplete issue（供质量页逐板块重采）。
3. 指数：board_bar 幂等 upsert 原值。
4. 资金流：board_fund_flow 全周期 upsert + 名称匹配映射、未匹配写质检不伪造代码。

关键语义：
- 快照日期 = Asia/Shanghai 实际成功采集日期（需求 R2）。
- 成分股代码补交易所后缀对齐 stock_basic.code（复用 akshare_source.to_full_code）。
- member_count 每板块完整快照落库时刷新（只进不出模型当前成分数）。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from backend.common.exceptions import DataSourceError
from backend.common.logging import get_logger
from backend.datasource.akshare_source import to_full_code
from backend.datasource.ths_board import ThsBoardSource
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient, get_client

log = get_logger("services.board_ingest")


def _asia_date() -> date:
    """Asia/Shanghai 当前日期（快照日期语义）。"""
    return datetime.now(timezone.utc).astimezone(tz=timezone(timedelta(hours=8))).date()


def _in_placeholders(n: int) -> str:
    """DuckDB `IN (?,?,...)` 占位符串（DuckDB 对 `IN (?)` 传 list 会 Conversion Error，须展开）。"""
    return ",".join(["?"] * n)


class BoardIngestService:
    """板块数据采集编排（R1-R4，只进不出模型）。"""

    def __init__(self, client: DuckDBClient | None = None, source: ThsBoardSource | None = None):
        self.c = client or get_client()
        init_db(self.c)
        self.src = source or ThsBoardSource()

    def _log_update(self, table_name: str, date_start: date | None, date_end: date | None,
                    row_count: int, status: str, detail: str = "") -> None:
        """写 data_update_log（对齐现有采集的更新留痕，供数据概览/运维查看板块采集进度）。"""
        from datetime import datetime
        self.c.execute(
            "INSERT INTO data_update_log "
            "(id, table_name, source, date_start, date_end, row_count, status, detail, updated_at) "
            "VALUES (nextval('seq_update_log'), ?, 'ths_board', ?, ?, ?, ?, ?, ?)",
            [table_name, date_start, date_end, row_count, status, detail, datetime.now()])

    # ── 1. 字典两阶段 ─────────────────────────────────────────

    def ingest_board_dict(self, snapshot_date: date | None = None,
                          ctx: object | None = None) -> dict:
        """字典两阶段：概念/行业字典 upsert → 资金流并集补充 + 能力字段收口。

        阶段一（本方法）：概念 + 行业字典全量 upsert 进 board_dict（能力字段按各自接口初判，
        has_fund_flow 暂 false）；阶段二由 ingest_board_fund_flow 补充资金流独有板块与 has_fund_flow。
        返回 {"concept": n, "industry": n, "total": n}。ctx：任务上下文，按类型打实时日志。
        """
        sdate = snapshot_date or _asia_date()
        result = {"concept": 0, "industry": 0, "total": 0}
        for board_type in ("concept", "industry"):
            df = self.src.get_board_dict(board_type)
            if df.empty:
                log.warning("字典 %s 为空，跳过", board_type)
                if ctx:
                    ctx.log(f"字典 {board_type}：为空，跳过", "warn")
                continue
            rows = []
            for _, r in df.iterrows():
                rows.append({
                    "board_code": str(r["board_code"]),
                    "name": str(r["name"]),
                    "board_type": board_type,
                    "source": "ths",
                    "has_members": True,       # 字典板块均有成分股接口（能力字段收口见阶段二后）
                    "has_bar": True,
                    "has_fund_flow": False,
                    "last_seen_at": sdate,
                })
            self._upsert_board_dict(rows)
            result[board_type] = len(rows)
            if ctx:
                ctx.log(f"字典 {board_type}：{len(rows)} 个板块")
            # 更新留痕（对齐现有采集）
            self._log_update("board_dict", sdate, sdate, len(rows),
                             "success" if len(rows) else "failed",
                             f"{board_type} 字典")
        result["total"] = result["concept"] + result["industry"]
        log.info("板块字典入库 %d 个（概念 %d + 行业 %d）", result["total"], result["concept"], result["industry"])
        return result

    def _upsert_board_dict(self, rows: list[dict]) -> None:
        if not rows:
            return
        df = pd.DataFrame(rows)
        with self.c.temp_view(df, "bdict") as v:
            self.c.execute(
                f"""INSERT INTO board_dict
                    (board_code, name, board_type, source, has_members, has_bar,
                     has_fund_flow, last_seen_at)
                    SELECT board_code, name, board_type, source, has_members, has_bar,
                           has_fund_flow, last_seen_at
                    FROM {v}
                    ON CONFLICT (board_code) DO UPDATE SET
                      name=EXCLUDED.name, board_type=EXCLUDED.board_type, source=EXCLUDED.source,
                      has_members=EXCLUDED.has_members, has_bar=EXCLUDED.has_bar,
                      has_fund_flow=EXCLUDED.has_fund_flow, last_seen_at=EXCLUDED.last_seen_at,
                      updated_at=now()""")

    # ── 2. 成分快照（只进不出：完整快照落库）───────────────

    def ingest_board_members(self, snapshot_date: date | None = None,
                             board_codes: list[str] | None = None,
                             ctx: object | None = None) -> dict:
        """逐板块成分快照：完整快照 INSERT ON CONFLICT DO NOTHING 落库（只进不出）。

        board_codes=None → 全量（从 board_dict 读取有成分数据的板块）。单板块失败记日志不中断，
        返回 {board_code: {"total"/"added"/"error"...}}。
        ctx：任务上下文（TaskContext/CliTaskContext 鸭子类型），逐板块打实时日志。
        """
        sdate = snapshot_date or _asia_date()
        # 读取板块清单
        if board_codes:
            df_boards = self.c.query_df(
                f"SELECT board_code, board_type FROM board_dict "
                f"WHERE board_code IN ({_in_placeholders(len(board_codes))})",
                board_codes)
        else:
            df_boards = self.c.query_df(
                "SELECT board_code, board_type FROM board_dict WHERE has_members")
        results: dict[str, dict] = {}
        n_err = 0
        n_total = len(df_boards)
        for i, (_, b) in enumerate(df_boards.iterrows(), 1):
            code, board_type = str(b["board_code"]), str(b["board_type"])
            try:
                results[code] = self._ingest_one_member(code, board_type, sdate)
                r = results[code]
                if ctx:
                    ctx.log(f"成分 {i}/{n_total} {code}：完整 {r.get('total', 0)} 只落库")
            except Exception as e:  # noqa: BLE001 —— 单板块失败跳过不中断，记 data_update_log failed
                log.warning("板块 %s 成分快照失败: %s", code, e)
                results[code] = {"error": str(e)}
                n_err += 1
                self._log_update("board_member", sdate, sdate, 0, "failed", f"{code} {e}")
                self._write_incomplete_quality(code, sdate, str(e))
                if ctx:
                    ctx.log(f"成分 {i}/{n_total} {code}：失败 {e}", "error")
        # 更新留痕（聚合：一次运行一条日志，避免逐板块刷屏）
        self._log_update("board_member", sdate, sdate, len(results), "success" if not n_err else "partial",
                         f"{len(results)} 个板块成分快照（失败 {n_err}）")
        log.info("板块成分快照 %d 个板块（失败 %d）", len(results), n_err)
        return results

    def _ingest_one_member(self, code: str, board_type: str, sdate: date) -> dict:
        """单板块成分快照（只进不出模型）：完整快照 INSERT ON CONFLICT DO NOTHING，不 diff 不删除。

        - complete=True → 快照内每个 code `INSERT ... ON CONFLICT (board_code, code) DO NOTHING`
          （已在表的不动、新出现的插入），同步刷新 board_dict.member_count（当前成分数）。
        - complete=False（分页不完整/登录墙/401/异常）→ 抛 DataSourceError，整趟不落库，
          上层 ingest_board_members 记失败、data_update_log 记 failed 待重采；已采旧数据原样保留。
        """
        m = self.src.get_board_members(code, board_type)
        codes_full = [to_full_code(c) for c in m["codes"]]
        cur_set = set(codes_full)
        if not m["complete"]:
            # 完整性即闸门：不完整快照整趟不落库（含完全没取到的空快照），抛错走失败留痕
            raise DataSourceError(
                f"板块 {code} 成分快照不完整（complete=False，取到 {len(cur_set)} 只），不落库待重采")
        if not cur_set:
            # 完整但空快照：源端返回空成分（罕见，如板块成分为空），记失败
            raise DataSourceError(f"板块 {code} 成分快照完整但为空，记失败待重采")
        # 完整快照 → 只进不出落库（已有不动、新增插入），同事务刷新 member_count
        with self.c.transaction():
            ph = _in_placeholders(len(cur_set))
            self.c.execute(
                f"INSERT INTO board_member (board_code, code) "
                f"SELECT ?, code FROM (VALUES {','.join(f'(?)' for _ in cur_set)}) t(code) "
                f"ON CONFLICT (board_code, code) DO NOTHING",
                [code, *sorted(cur_set)])
            self.c.execute(
                "UPDATE board_dict SET member_count=?, updated_at=now() WHERE board_code=?",
                [len(cur_set), code])
            self.c.execute(
                "UPDATE board_dict SET member_history_start_date=COALESCE(member_history_start_date, ?), "
                "updated_at=now() WHERE board_code=?",
                [sdate, code])
        return {"total": len(cur_set), "added": len(cur_set)}

    # ── 3. 指数 ──────────────────────────────────────────────

    def ingest_board_bar(self, start: date, end: date | None = None,
                         board_codes: list[str] | None = None,
                         ctx: object | None = None) -> dict:
        """板块指数日线：幂等 upsert 原值。end 缺省=今天。返回 {"rows": n, "boards": n}。
        ctx：任务上下文，逐板块打实时日志（对齐现有采集「指数 X 完成」模式）。"""
        end = end or _asia_date()
        if board_codes:
            df_boards = self.c.query_df(
                f"SELECT board_code, board_type FROM board_dict "
                f"WHERE board_code IN ({_in_placeholders(len(board_codes))})",
                board_codes)
        else:
            df_boards = self.c.query_df(
                "SELECT board_code, board_type FROM board_dict WHERE has_bar")
        total_rows = 0
        boards = 0
        n_total = len(df_boards)
        for i, (_, b) in enumerate(df_boards.iterrows(), 1):
            code, board_type = str(b["board_code"]), str(b["board_type"])
            try:
                df = self.src.get_board_bar(code, board_type, start, end)
                if df.empty:
                    if ctx:
                        ctx.log(f"指数 {i}/{n_total} {code}：无数据")
                    continue
                df["board_code"] = code
                self._upsert_board_bar(df)
                total_rows += len(df)
                boards += 1
                if ctx:
                    ctx.log(f"指数 {i}/{n_total} {code}：{len(df)} 行")
            except Exception as e:  # noqa: BLE001
                log.warning("板块 %s 指数取数失败: %s", code, e)
                if ctx:
                    ctx.log(f"指数 {i}/{n_total} {code}：失败 {e}", "warn")
        self._log_update("board_bar", start, end, total_rows, "success", f"{boards} 个板块")
        log.info("板块指数入库 %d 行 / %d 个板块（%s ~ %s）", total_rows, boards, start, end)
        return {"rows": total_rows, "boards": boards}

    def _upsert_board_bar(self, df: pd.DataFrame) -> None:
        cols = ["board_code", "trade_date", "open", "high", "low", "close", "volume", "amount"]
        df = df[cols].copy()
        with self.c.temp_view(df, "bbar") as v:
            self.c.execute(
                f"""INSERT INTO board_bar
                    (board_code, trade_date, open, high, low, close, volume, amount)
                    SELECT board_code, trade_date, open, high, low, close, volume, amount FROM {v}
                    ON CONFLICT (board_code, trade_date) DO UPDATE SET
                      open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                      close=EXCLUDED.close,
                      volume=EXCLUDED.volume, amount=EXCLUDED.amount""")

    # ── 4. 资金流（并集映射）─────────────────────────────────

    def ingest_board_fund_flow(self, snapshot_date: date | None = None,
                               periods: tuple[str, ...] | None = None,
                               ctx: object | None = None) -> dict:
        """资金流 upsert + 名称匹配映射；未匹配写质检不伪造代码（R4）。

        periods=None → 全周期（"即时","3日","5日","10日","20日"）；update 模式只传 ("即时",)。
        ctx：任务上下文，按类型×周期打实时日志。
        """
        sdate = snapshot_date or _asia_date()
        periods = periods or ("即时", "3日", "5日", "10日", "20日")
        # 字典 code→name 映射
        d = self.c.query_df("SELECT board_code, name, board_type FROM board_dict")
        name_to_code: dict[tuple[str, str], str] = {}
        for _, r in d.iterrows():
            name_to_code[(str(r["board_type"]), str(r["name"]))] = str(r["board_code"])
        rows = 0
        unmatched: list[str] = []
        for board_type in ("concept", "industry"):
            for period in periods:
                try:
                    df = self.src.get_board_fund_flow(board_type, period)
                except Exception as e:  # noqa: BLE001
                    log.warning("资金流 %s/%s 取数失败: %s", board_type, period, e)
                    if ctx:
                        ctx.log(f"资金流 {board_type}/{period}：失败 {e}", "warn")
                    continue
                if df.empty:
                    if ctx:
                        ctx.log(f"资金流 {board_type}/{period}：无数据")
                    continue
                # 名称匹配映射到 board_code；未匹配记录（写质检）
                matched = []
                for _, r in df.iterrows():
                    name = str(r["name"])
                    code = name_to_code.get((board_type, name))
                    if not code:
                        unmatched.append(name)
                        continue
                    matched.append({
                        "board_code": code, "snapshot_date": sdate, "period": period,
                        "inflow": r["inflow"], "outflow": r["outflow"],
                        "net_inflow": r["net_inflow"], "net_ratio": r["net_ratio"],
                        "leader_stock": r["leader_stock"], "leader_pct": r["leader_pct"],
                    })
                if matched:
                    self._upsert_board_fund_flow(matched)
                    rows += len(matched)
                if ctx:
                    ctx.log(f"资金流 {board_type}/{period}：匹配 {len(matched)} 行"
                            f"（未匹配 {len(unmatched)}）")
                # 阶段二：资金流独有板块补充进字典（has_fund_flow=true，has_members/bar=false）
                self._fund_flow_union_supplement(board_type, df, sdate, name_to_code)
        # 未匹配写质检（不伪造代码）
        self._write_unmatched_quality(unmatched, sdate)
        # 能力字段收口：有资金流数据的板块 has_fund_flow=true
        self.c.execute(
            "UPDATE board_dict SET has_fund_flow=true, updated_at=now() "
            "WHERE board_code IN (SELECT DISTINCT board_code FROM board_fund_flow)")
        self._log_update("board_fund_flow", sdate, sdate, rows, "success",
                         f"未匹配 {len(unmatched)}")
        log.info("板块资金流入库 %d 行（未匹配 %d）", rows, len(unmatched))
        return {"rows": rows, "unmatched": len(unmatched)}

    def _upsert_board_fund_flow(self, rows: list[dict]) -> None:
        """资金流批量 upsert（temp_view 单条 INSERT SELECT，替代逐条写入）。"""
        if not rows:
            return
        df = pd.DataFrame(rows)
        with self.c.temp_view(df, "bflow") as v:
            self.c.execute(
                f"""INSERT INTO board_fund_flow
                    (board_code, snapshot_date, period, inflow, outflow,
                     net_inflow, net_ratio, leader_stock, leader_pct)
                    SELECT board_code, snapshot_date, period, inflow, outflow,
                           net_inflow, net_ratio, leader_stock, leader_pct FROM {v}
                    ON CONFLICT (board_code, snapshot_date, period) DO UPDATE SET
                      inflow=EXCLUDED.inflow, outflow=EXCLUDED.outflow,
                      net_inflow=EXCLUDED.net_inflow,
                      net_ratio=EXCLUDED.net_ratio, leader_stock=EXCLUDED.leader_stock,
                      leader_pct=EXCLUDED.leader_pct""")

    def _fund_flow_union_supplement(self, board_type: str, df: pd.DataFrame,
                                    sdate: date, name_to_code: dict) -> None:
        """资金流独有板块（字典无）补充进 board_dict：has_fund_flow=true 其余能力 false。

        资金流源无稳定代码、仅名称 → 无法生成路径 code 主键，**不能伪造代码**；
        按 R4「未匹配写质检」语义，独有板块不新增字典行，仅由 _write_unmatched_quality 记录质检
        （需求 §2.5「可进入 board_dict」依赖资金流源提供稳定代码，当前源无此能力，见 §10 待确认）。
        """
        for _, r in df.iterrows():
            name = str(r["name"])
            if (board_type, name) in name_to_code:
                continue
            # 无稳定代码 → 不新增（避免无主键板块）；未匹配由 _write_unmatched_quality 写质检。
            pass

    def _write_unmatched_quality(self, names: list[str], sdate: date) -> None:
        """未匹配资金流板块写质检（name 记录，无伪造代码）。"""
        if not names:
            return
        seen: dict[str, None] = {}
        for n in names:
            seen.setdefault(n, None)
        for name in seen:
            issue_id = int(self.c.query_df(
                "SELECT nextval('seq_quality_issue') AS v").iloc[0]["v"])
            self.c.execute(
                "INSERT INTO data_quality_issue "
                "(id, code, trade_date, issue_type, severity, status, "
                "detail, detected_at, fix_task_id) "
                "VALUES (?, ?, ?, 'board_fund_unmatched', 'mid', "
                "'open', ?, now(), NULL)",
                [issue_id, None, sdate, json.dumps({"name": name}, ensure_ascii=False)])

    def _write_incomplete_quality(self, code: str, sdate: date, reason: str) -> None:
        """成分快照采集不完整/失败写质检（board_member_incomplete），供数据质量页逐板块重采。

        幂等：同板块未解决（open）的 board_member_incomplete 不重复建（采集失败会反复触发，
        避免刷屏；重采成功/复检通过后 resolved 收敛）。
        """
        existing = self.c.query_df(
            "SELECT count(*) AS n FROM data_quality_issue "
            "WHERE issue_type='board_member_incomplete' AND code=? AND status='open'",
            [code])
        if int(existing.iloc[0]["n"]) > 0:
            return
        issue_id = int(self.c.query_df(
            "SELECT nextval('seq_quality_issue') AS v").iloc[0]["v"])
        self.c.execute(
            "INSERT INTO data_quality_issue "
            "(id, code, trade_date, issue_type, severity, status, "
            "detail, detected_at, fix_task_id) "
            "VALUES (?, ?, ?, 'board_member_incomplete', 'mid', "
            "'open', ?, now(), NULL)",
            [issue_id, code, sdate, json.dumps({"reason": reason, "snapshot_date": sdate.isoformat()},
                                               ensure_ascii=False)])
