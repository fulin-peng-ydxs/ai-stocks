"""板块概念数据采集服务（板块概念需求 R1-R4，agent-works/concept-industry-board/）。

编排逻辑（承接 plan §6.4 T4）：
1. 字典：概念/行业字典 upsert，补齐路径 code 与 App clid 双代码映射，能力字段收口。
2. 成分快照（只进不出）：逐板块 `ThsBoardSource.get_board_members` → 完整性判定（完整才落库）
   → 完整快照 INSERT ON CONFLICT DO NOTHING（(board_code, code) 单行累积，不删除不 diff）
   + 刷新 member_count/member_snapshot_at/member_history_start_date；不完整快照整趟不落库、
   data_update_log 记 failed + 写 board_member_incomplete issue（供质量页逐板块重采）。
3. 指数：board_bar 幂等 upsert 原值。
4. 资金流：board_fund_flow 全周期 upsert + 名称匹配映射、未匹配写质检不伪造代码。

关键语义：
- 快照日期 = Asia/Shanghai 实际成功采集日期（需求 R2）。
- 成分股代码补交易所后缀对齐 stock_basic.code（复用 akshare_source.to_full_code）。
- member_count 记录最近一次完整源快照的成分数；board_member 本身保留累计出现过的关系。
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


def _board_types(board_type: str | None) -> tuple[str, ...]:
    if board_type is None:
        return ("concept", "industry")
    if board_type not in ("concept", "industry"):
        raise ValueError("板块类型仅支持 concept/industry")
    return (board_type,)


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

    # ── 1. 板块字典 ───────────────────────────────────────────

    def ingest_board_dict(self, snapshot_date: date | None = None,
                          board_type: str | None = None,
                          ctx: object | None = None) -> dict:
        """概念/行业字典全量 upsert，并为尚无 app_code 的板块补取 clid。"""
        sdate = snapshot_date or _asia_date()
        result = {"concept": 0, "industry": 0, "total": 0, "failed": []}
        done_types = set(getattr(ctx, "checkpoint", {}).get("dict_done_types") or []) if ctx else set()
        types = _board_types(board_type)
        for current_type in types:
            if current_type in done_types:
                continue
            if ctx:
                ctx.check_cancel()
                done_in_scope = len(done_types.intersection(types))
                ctx.set_phase("board_dict", done=done_in_scope, total=len(types),
                              phase_total=len(types), phase_done=done_in_scope,
                              current_item=current_type,
                              dict_done_types=sorted(done_types))
            try:
                df = self.src.get_board_dict(current_type)
            except Exception as e:  # noqa: BLE001 -- 两类字典独立失败，保留另一类成功结果
                result["failed"].append(f"{current_type}: {e}")
                self._log_update("board_dict", sdate, sdate, 0, "failed", f"{current_type} 字典：{e}")
                if ctx:
                    ctx.log(f"字典 {current_type}：失败 {e}", "error")
                continue
            if df.empty:
                log.warning("字典 %s 为空，跳过", current_type)
                result["failed"].append(f"{current_type}: empty")
                self._log_update("board_dict", sdate, sdate, 0, "failed", f"{current_type} 字典为空")
                if ctx:
                    ctx.log(f"字典 {current_type}：为空，跳过", "warn")
                continue
            existing = self.c.query_df(
                "SELECT board_code, app_code FROM board_dict WHERE board_type=?", [current_type])
            known_app_codes = {
                str(r["board_code"]): str(r["app_code"])
                for _, r in existing.iterrows()
                if r["app_code"] is not None and str(r["app_code"]) != "nan"
            }
            app_failures_before = len(result["failed"])
            rows = []
            for _, r in df.iterrows():
                code = str(r["board_code"])
                raw_app_code = r.get("app_code") if "app_code" in df.columns else None
                app_code = (str(raw_app_code) if raw_app_code is not None and str(raw_app_code) != "nan"
                            else known_app_codes.get(code))
                if not app_code:
                    try:
                        getter = getattr(self.src, "get_board_app_code", None)
                        app_code = getter(code, current_type) if getter else (code if current_type == "industry" else None)
                    except Exception as e:  # noqa: BLE001 -- 主字典仍入库，后续采集重试补齐 clid
                        result["failed"].append(f"app_code:{code}: {e}")
                        if ctx:
                            ctx.log(f"字典 {current_type} {code}：App clid 获取失败 {e}", "error")
                rows.append({
                    "board_code": code,
                    "app_code": app_code,
                    "name": str(r["name"]),
                    "board_type": current_type,
                    "source": "ths",
                    "has_members": True,       # 字典板块均有成分股接口（能力字段收口见阶段二后）
                    "has_bar": True,
                    "has_fund_flow": False,
                    "last_seen_at": sdate,
                })
            self._upsert_board_dict(rows)
            result[current_type] = len(rows)
            if ctx:
                ctx.log(f"字典 {current_type}：{len(rows)} 个板块")
            # 更新留痕（对齐现有采集）
            self._log_update("board_dict", sdate, sdate, len(rows),
                             "partial" if len(result["failed"]) > app_failures_before else "success",
                             f"{current_type} 字典")
            if len(result["failed"]) == app_failures_before:
                done_types.add(current_type)
            if ctx and current_type in done_types:
                done_in_scope = len(done_types.intersection(types))
                ctx.set_phase("board_dict", done=done_in_scope, total=len(types),
                              phase_total=len(types), phase_done=done_in_scope,
                              current_item=current_type,
                              dict_done_types=sorted(done_types))
        result["total"] = result["concept"] + result["industry"]
        log.info("板块字典入库 %d 个（概念 %d + 行业 %d）", result["total"], result["concept"], result["industry"])
        return result

    def _upsert_fund_only_boards(self, items: list[tuple[str, str, str]], sdate: date) -> None:
        """资金流独有板块补进字典：链接带真实路径 code（稳定主键），has_fund_flow=true。

        与 _fund_flow_union_supplement（旧 no-op）不同：当时假设资金流源无稳定代码，
        实测链接里带 code，故这些板块可安全入库（has_members/bar=false，列表页不展示，
        仅 has_fund_flow=true 供资金流数据关联展示）。
        """
        if not items:
            return
        rows = [{"board_code": c, "app_code": None, "name": n, "board_type": t,
                 "source": "ths", "has_members": False, "has_bar": False,
                 "has_fund_flow": True, "last_seen_at": sdate}
                for c, n, t in items]
        df = pd.DataFrame(rows)
        with self.c.temp_view(df, "bfund_dict") as v:
            self.c.execute(
                f"""INSERT INTO board_dict
                    (board_code, app_code, name, board_type, source, has_members, has_bar,
                     has_fund_flow, last_seen_at)
                    SELECT board_code, app_code, name, board_type, source, has_members, has_bar,
                           has_fund_flow, last_seen_at FROM {v}
                    ON CONFLICT (board_code) DO UPDATE SET
                      name=EXCLUDED.name, has_fund_flow=TRUE,
                      last_seen_at=EXCLUDED.last_seen_at, updated_at=now()""")

    def _upsert_board_dict(self, rows: list[dict]) -> None:
        if not rows:
            return
        df = pd.DataFrame(rows)
        with self.c.temp_view(df, "bdict") as v:
            self.c.execute(
                f"""INSERT INTO board_dict
                    (board_code, app_code, name, board_type, source, has_members, has_bar,
                     has_fund_flow, last_seen_at)
                    SELECT board_code, app_code, name, board_type, source, has_members, has_bar,
                           has_fund_flow, last_seen_at
                    FROM {v}
                    ON CONFLICT (board_code) DO UPDATE SET
                      app_code=COALESCE(EXCLUDED.app_code, board_dict.app_code),
                      name=EXCLUDED.name, board_type=EXCLUDED.board_type, source=EXCLUDED.source,
                      has_members=EXCLUDED.has_members, has_bar=EXCLUDED.has_bar,
                      has_fund_flow=board_dict.has_fund_flow OR EXCLUDED.has_fund_flow,
                      last_seen_at=EXCLUDED.last_seen_at,
                      updated_at=now()""")

    # ── 2. 成分快照（只进不出：完整快照落库）───────────────

    def ingest_board_members(self, snapshot_date: date | None = None,
                             board_codes: list[str] | None = None,
                             board_type: str | None = None,
                             ctx: object | None = None) -> dict:
        """逐板块成分快照：完整快照 INSERT ON CONFLICT DO NOTHING 落库（只进不出）。

        board_codes=None → 全量（从 board_dict 读取有成分数据的板块）。单板块失败记日志不中断，
        返回 {board_code: {"total"/"added"/"error"...}}。
        ctx：任务上下文（TaskContext/CliTaskContext 鸭子类型），逐板块打实时日志。
        """
        sdate = snapshot_date or _asia_date()
        # 读取板块清单
        types = _board_types(board_type)
        if board_codes is not None:
            if not board_codes:
                return {}
            type_clause = " AND board_type=?" if board_type else ""
            df_boards = self.c.query_df(
                f"SELECT board_code, board_type FROM board_dict "
                f"WHERE board_code IN ({_in_placeholders(len(board_codes))}){type_clause} "
                "ORDER BY board_code",
                [*board_codes, *types] if board_type else board_codes)
        else:
            type_clause = " AND board_type=?" if board_type else ""
            df_boards = self.c.query_df(
                f"SELECT board_code, board_type FROM board_dict "
                f"WHERE has_members{type_clause} ORDER BY board_code",
                list(types) if board_type else [])
        results: dict[str, dict] = {}
        done_codes = set(getattr(ctx, "checkpoint", {}).get("member_done_codes") or []) if ctx else set()
        done_codes.intersection_update({str(x) for x in df_boards["board_code"].tolist()})
        if done_codes:
            df_boards = df_boards[~df_boards["board_code"].astype(str).isin(done_codes)]
        n_err = 0
        n_total = len(df_boards)
        phase_total = len(done_codes) + n_total
        for i, (_, b) in enumerate(df_boards.iterrows(), 1):
            code, board_type = str(b["board_code"]), str(b["board_type"])
            if ctx:
                ctx.check_cancel()
                ctx.set_phase("board_members", done=len(done_codes), total=phase_total,
                              phase_total=phase_total, phase_done=len(done_codes),
                              current_item=code, member_done_codes=sorted(done_codes))
            try:
                results[code] = self._ingest_one_member(code, board_type, sdate)
                r = results[code]
                done_codes.add(code)
                if ctx:
                    ctx.set_phase("board_members", done=len(done_codes), total=phase_total,
                                  phase_total=phase_total,
                                  phase_done=len(done_codes), current_item=code,
                                  member_done_codes=sorted(done_codes))
                if ctx:
                    ctx.log(f"成分 {i}/{n_total} {code}：完整 {r.get('total', 0)} 只，"
                            f"新增 {r.get('added', 0)} 只")
            except Exception as e:  # noqa: BLE001 —— 单板块失败跳过不中断，记 data_update_log failed
                log.warning("板块 %s 成分快照失败: %s", code, e)
                results[code] = {"error": str(e)}
                n_err += 1
                self._log_update("board_member", sdate, sdate, 0, "failed", f"{code} {e}")
                self._write_incomplete_quality(code, sdate, str(e))
                if ctx:
                    ctx.log(f"成分 {i}/{n_total} {code}：失败 {e}", "error")
        # 更新留痕（聚合：一次运行一条日志，避免逐板块刷屏）
        written = sum(int(r.get("added", 0)) for r in results.values() if "error" not in r)
        self._log_update("board_member", sdate, sdate, written,
                         "success" if not n_err else "partial",
                         f"处理 {len(results)} 个板块，新增 {written} 条成员关系（失败 {n_err}）")
        log.info("板块成分快照 %d 个板块（失败 %d）", len(results), n_err)
        return results

    def _ingest_one_member(self, code: str, board_type: str, sdate: date) -> dict:
        """单板块成分快照（只进不出模型）：完整快照 INSERT ON CONFLICT DO NOTHING，不 diff 不删除。

        - complete=True → 快照内每个 code `INSERT ... ON CONFLICT (board_code, code) DO NOTHING`
          （已在表的不动、新出现的插入），同步刷新 board_dict.member_count（最近完整快照成分数）。
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
            existing = int(self.c.query_df(
                f"SELECT count(*) AS n FROM board_member WHERE board_code=? AND code IN ({ph})",
                [code, *sorted(cur_set)]).iloc[0]["n"])
            self.c.execute(
                f"INSERT INTO board_member (board_code, code) "
                f"SELECT ?, code FROM (VALUES {','.join(f'(?)' for _ in cur_set)}) t(code) "
                f"ON CONFLICT (board_code, code) DO NOTHING",
                [code, *sorted(cur_set)])
            self.c.execute(
                "UPDATE board_dict SET member_count=?, member_snapshot_at=now(), updated_at=now() "
                "WHERE board_code=?",
                [len(cur_set), code])
            self.c.execute(
                "UPDATE board_dict SET member_history_start_date=COALESCE(member_history_start_date, ?), "
                "updated_at=now() WHERE board_code=?",
                [sdate, code])
            # 普通采集和质量修复共用同一闭环：新的完整快照成功后，旧的不完整问题即已消失。
            self.c.execute(
                "UPDATE data_quality_issue SET status='resolved', resolved_at=now(), fix_task_id=NULL "
                "WHERE issue_type='board_member_incomplete' AND code=? "
                "AND status IN ('open','fixing')", [code])
        return {"total": len(cur_set), "added": len(cur_set) - existing}

    # ── 3. 指数 ──────────────────────────────────────────────

    def ingest_board_bar(self, start: date, end: date | None = None,
                         board_codes: list[str] | None = None,
                         board_type: str | None = None,
                         ctx: object | None = None) -> dict:
        """板块指数日线：幂等 upsert 原值。end 缺省=今天。返回 {"rows": n, "boards": n}。
        ctx：任务上下文，逐板块打实时日志（对齐现有采集「指数 X 完成」模式）。"""
        end = end or _asia_date()
        types = _board_types(board_type)
        if board_codes is not None:
            if not board_codes:
                return {"rows": 0, "boards": 0, "failed": []}
            type_clause = " AND board_type=?" if board_type else ""
            df_boards = self.c.query_df(
                f"SELECT board_code, board_type FROM board_dict "
                f"WHERE board_code IN ({_in_placeholders(len(board_codes))}){type_clause} "
                "ORDER BY board_code",
                [*board_codes, *types] if board_type else board_codes)
        else:
            type_clause = " AND board_type=?" if board_type else ""
            df_boards = self.c.query_df(
                f"SELECT board_code, board_type FROM board_dict "
                f"WHERE has_bar{type_clause} ORDER BY board_code",
                list(types) if board_type else [])
        total_rows = 0
        boards = 0
        failed: list[str] = []
        done_codes = set(getattr(ctx, "checkpoint", {}).get("bar_done_codes") or []) if ctx else set()
        done_codes.intersection_update({str(x) for x in df_boards["board_code"].tolist()})
        if done_codes:
            df_boards = df_boards[~df_boards["board_code"].astype(str).isin(done_codes)]
        n_total = len(df_boards)
        phase_total = len(done_codes) + n_total
        for i, (_, b) in enumerate(df_boards.iterrows(), 1):
            code, board_type = str(b["board_code"]), str(b["board_type"])
            if ctx:
                ctx.check_cancel()
                ctx.set_phase("board_bar", done=len(done_codes), total=phase_total,
                              phase_total=phase_total, phase_done=len(done_codes),
                              current_item=code, bar_done_codes=sorted(done_codes))
            try:
                df = self.src.get_board_bar(code, board_type, start, end)
                failed_years = list(df.attrs.get("failed_years") or [])
                if df.empty:
                    if ctx:
                        ctx.log(f"指数 {i}/{n_total} {code}：无数据")
                else:
                    df["board_code"] = code
                    self._upsert_board_bar(df)
                    total_rows += len(df)
                    boards += 1
                if failed_years:
                    failed.append(f"{code}: years {failed_years}")
                    self._log_update("board_bar", start, end, len(df), "partial",
                                     f"{code} 失败年份 {failed_years}")
                if not failed_years:
                    done_codes.add(code)
                if ctx and not failed_years:
                    ctx.set_phase("board_bar", done=len(done_codes), total=phase_total,
                                  phase_total=phase_total,
                                  phase_done=len(done_codes), current_item=code,
                                  bar_done_codes=sorted(done_codes))
                if ctx:
                    ctx.log(f"指数 {i}/{n_total} {code}：{len(df)} 行")
            except Exception as e:  # noqa: BLE001
                log.warning("板块 %s 指数取数失败: %s", code, e)
                failed.append(f"{code}: {e}")
                self._log_update("board_bar", start, end, 0, "failed", f"{code} {e}")
                if ctx:
                    ctx.log(f"指数 {i}/{n_total} {code}：失败 {e}", "error")
        status = "partial" if failed else "success"
        self._log_update("board_bar", start, end, total_rows, status,
                         f"{boards} 个板块（失败 {len(failed)}）")
        log.info("板块指数入库 %d 行 / %d 个板块（失败 %d，%s ~ %s）",
                 total_rows, boards, len(failed), start, end)
        return {"rows": total_rows, "boards": boards, "failed": failed}

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
                               board_codes: list[str] | None = None,
                               board_type: str | None = None,
                               ctx: object | None = None) -> dict:
        """资金流 upsert + 名称匹配映射；未匹配写质检不伪造代码（R4）。

        periods=None → 全周期（"即时","3日","5日","10日","20日"）；update 模式只传 ("即时",)。
        ctx：任务上下文，按类型×周期打实时日志。
        """
        sdate = snapshot_date or _asia_date()
        periods = periods or ("即时", "3日", "5日", "10日", "20日")
        requested_types = set(_board_types(board_type))
        if board_codes is not None and not board_codes:
            return {"rows": 0, "unmatched": 0, "failed": []}
        # 字典 code→name 映射（code 反向表供「优先 code 匹配」用）
        d = self.c.query_df("SELECT board_code, name, board_type FROM board_dict")
        code_to_meta: dict[str, tuple[str, str]] = {}
        for _, r in d.iterrows():
            code_to_meta[str(r["board_code"])] = (str(r["board_type"]), str(r["name"]))
        target_codes = ({str(x) for x in board_codes}
                        if board_codes is not None else None)
        target_types = requested_types
        if target_codes is not None:
            target_types = {
                str(r["board_type"]) for _, r in d.iterrows()
                if str(r["board_code"]) in target_codes and str(r["board_type"]) in requested_types
            }
        rows = 0
        unmatched: list[dict[str, str]] = []
        failed: list[str] = []
        newly_added_codes: list[tuple[str, str, str]] = []  # 资金流独有板块 (code, name, board_type)
        done_keys = set(getattr(ctx, "checkpoint", {}).get("fund_done_keys") or []) if ctx else set()
        valid_keys = {f"{bt}:{period}" for bt in target_types for period in periods}
        done_keys.intersection_update(valid_keys)
        total_groups = len(target_types) * len(periods)
        for board_type in ("concept", "industry"):
            if board_type not in target_types:
                continue
            for period in periods:
                group_key = f"{board_type}:{period}"
                if group_key in done_keys:
                    continue
                if ctx:
                    ctx.check_cancel()
                    ctx.set_phase("board_fund_flow", done=len(done_keys), total=total_groups,
                                  phase_total=total_groups, phase_done=len(done_keys),
                                  current_item=group_key, fund_done_keys=sorted(done_keys))
                try:
                    df = self.src.get_board_fund_flow(board_type, period)
                except Exception as e:  # noqa: BLE001
                    log.warning("资金流 %s/%s 取数失败: %s", board_type, period, e)
                    failed.append(f"{group_key}: {e}")
                    self._log_update("board_fund_flow", sdate, sdate, 0, "failed",
                                     f"{group_key} {e}")
                    if ctx:
                        ctx.log(f"资金流 {board_type}/{period}：失败 {e}", "error")
                    continue
                if df.empty:
                    failed.append(f"{group_key}: empty")
                    self._log_update("board_fund_flow", sdate, sdate, 0, "failed",
                                     f"{group_key} 资金流为空")
                    if ctx:
                        ctx.log(f"资金流 {board_type}/{period}：无数据，记失败", "error")
                    continue
                # 优先用资金流链接里抓到的路径 code 匹配；其次名称匹配。
                # 资金流源板块单元格带链接（/gn/detail/code/308734/），code 真实存在。
                matched = []
                for _, r in df.iterrows():
                    name = str(r["name"])
                    raw_code = str(r.get("board_code") or "").strip()
                    code = ""
                    bt = board_type
                    if raw_code:
                        meta = code_to_meta.get(raw_code)
                        if meta:
                            code, bt = raw_code, meta[0]
                        elif target_codes is None:
                            # 资金流独有板块但链接里有真实路径 code → 补进字典（有稳定主键，非伪造）
                            code = raw_code
                    if not code:
                        # 无链接 code 回落名称匹配（行业资金流可能无链接）
                        for existing_code, (ebt, ename) in code_to_meta.items():
                            if ebt == board_type and ename == name:
                                code = existing_code
                                bt = ebt
                                break
                    if not code:
                        if target_codes is None:
                            unmatched.append({"name": name, "board_type": board_type})
                        continue
                    if target_codes is not None and code not in target_codes:
                        continue
                    if raw_code and raw_code not in code_to_meta and target_codes is None:
                        newly_added_codes.append((raw_code, name, bt))
                    inflow, outflow, net = r["inflow"], r["outflow"], r["net_inflow"]
                    if not pd.isna(inflow) and not pd.isna(outflow):
                        expected = float(inflow) - float(outflow)
                        if pd.isna(net):
                            net = expected
                        elif abs(float(net) - expected) > 0.05:
                            failed.append(
                                f"{group_key}:{name}: net_inflow={net} != inflow-outflow={expected:.4f}")
                            continue
                    matched.append({
                        "board_code": code, "snapshot_date": sdate, "period": period,
                        "inflow": inflow, "outflow": outflow,
                        "net_inflow": net, "net_ratio": r["net_ratio"],
                        "leader_stock": r["leader_stock"], "leader_pct": r["leader_pct"],
                    })
                if matched:
                    self._upsert_board_fund_flow(matched)
                    rows += len(matched)
                if ctx:
                    ctx.log(f"资金流 {board_type}/{period}：匹配 {len(matched)} 行"
                            f"（未匹配 {len(unmatched)}）")
                if not any(x.startswith(group_key + ":") for x in failed):
                    done_keys.add(group_key)
                    if ctx:
                        ctx.set_phase("board_fund_flow", done=len(done_keys), total=total_groups,
                                      phase_total=total_groups, phase_done=len(done_keys),
                                      current_item=group_key, fund_done_keys=sorted(done_keys))
        # 资金流独有板块（链接带真实路径 code 但字典缺）补进 board_dict：有稳定主键，非伪造。
        # 能力字段 has_fund_flow=true、has_members/bar=false；列表页只展示有核心数据的板块，故不影响展示。
        if target_codes is None and newly_added_codes:
            self._upsert_fund_only_boards(newly_added_codes, sdate)
        # 未匹配写质检（无链接也无名称映射的板块——真无稳定代码才记）
        if target_codes is None:
            self._write_unmatched_quality(unmatched, sdate)
        # 能力字段收口：有资金流数据的板块 has_fund_flow=true
        self.c.execute(
            "UPDATE board_dict SET has_fund_flow=true, updated_at=now() "
            "WHERE board_code IN (SELECT DISTINCT board_code FROM board_fund_flow)")
        status = "partial" if failed else "success"
        self._log_update("board_fund_flow", sdate, sdate, rows, status,
                         f"未匹配 {len(unmatched)}，失败 {len(failed)}")
        log.info("板块资金流入库 %d 行（未匹配 %d，失败 %d）",
                 rows, len(unmatched), len(failed))
        return {"rows": rows, "unmatched": len(unmatched), "failed": failed}

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

    def _write_unmatched_quality(self, items: list[dict[str, str]], sdate: date) -> None:
        """未匹配资金流板块写质检（name 记录，无伪造代码）。

        收敛语义：写入前**解决历史误报**——已能匹配字典的旧 open `board_fund_unmatched`
        （板块名现已存在 board_dict，说明上次采集时字典不完整/匹配失败，本次已可匹配，
        不应再作为未匹配）。随后只对当次仍无法匹配的板块名幂等建 issue（去重 name）。
        """
        # 已能匹配字典的历史问题保留审计记录并置 resolved，不直接删除。
        self.c.execute(
            "UPDATE data_quality_issue SET status='resolved', resolved_at=now(), fix_task_id=NULL "
            "WHERE issue_type='board_fund_unmatched' AND status IN ('open','fixing') "
            "AND EXISTS (SELECT 1 FROM board_dict b "
            "WHERE b.name=json_extract_string(try_cast(data_quality_issue.detail AS JSON), '$.name') "
            "AND (json_extract_string(try_cast(data_quality_issue.detail AS JSON), '$.board_type') IS NULL "
            "OR b.board_type=json_extract_string(try_cast(data_quality_issue.detail AS JSON), "
            "'$.board_type')))")
        seen = {(x["board_type"], x["name"]) for x in items}
        for board_type, name in seen:
            existing = int(self.c.query_df(
                "SELECT count(*) AS n FROM data_quality_issue "
                "WHERE issue_type='board_fund_unmatched' AND status IN ('open','fixing') "
                "AND json_extract_string(try_cast(detail AS JSON), '$.name')=? "
                "AND COALESCE(json_extract_string(try_cast(detail AS JSON), '$.board_type'), ?)=?",
                [name, board_type, board_type]).iloc[0]["n"])
            if existing:
                continue
            issue_id = int(self.c.query_df(
                "SELECT nextval('seq_quality_issue') AS v").iloc[0]["v"])
            self.c.execute(
                "INSERT INTO data_quality_issue "
                "(id, code, trade_date, issue_type, severity, status, "
                "detail, detected_at, fix_task_id) "
                "VALUES (?, ?, ?, 'board_fund_unmatched', 'mid', "
                "'open', ?, now(), NULL)",
                [issue_id, None, sdate,
                 json.dumps({"name": name, "board_type": board_type}, ensure_ascii=False)])

    def _write_incomplete_quality(self, code: str, sdate: date, reason: str) -> None:
        """成分快照采集不完整/失败写质检（board_member_incomplete），供数据质量页逐板块重采。

        幂等：同板块未解决（open）的 board_member_incomplete 不重复建（采集失败会反复触发，
        避免刷屏；重采成功/复检通过后 resolved 收敛）。
        """
        existing = self.c.query_df(
            "SELECT count(*) AS n FROM data_quality_issue "
            "WHERE issue_type='board_member_incomplete' AND code=? AND status IN ('open','fixing')",
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
