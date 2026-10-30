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
- 成分快照日期 = Asia/Shanghai 实际成功采集日期；资金流快照日期由主编排
  传入当前目标交易日，供页面与行情截面严格同日匹配。
- 成分股代码补交易所后缀对齐 stock_basic.code（复用 akshare_source.to_full_code）。
- member_count 记录最近一次完整源快照返回的成员数量；board_member 本身保留累计出现过的关系。
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta

import pandas as pd

from backend.common.exceptions import DataSourceError
from backend.common.logging import get_logger
from backend.config import get_effective_settings
from backend.dataquality.checker import severity_for
from backend.datasource.akshare_source import classify_board, to_full_code
from backend.datasource.ths_board import FUND_FLOW_PERIODS, ThsBoardSource
from backend.services import eod_dates
from backend.services.async_task import TaskCancelled
from backend.services.bounded_parallel import run_bounded_parallel
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient, get_client

log = get_logger("services.board_ingest")

BOARD_INGEST_STAGES: tuple[str, ...] = ("dict", "members", "bar", "fund")

# 源端当日就绪探测（对齐行情 update 的 _UPDATE_READY_* 就绪门）：板块指数源端分板块陆续发布，
# 采早了会落一批"停在昨天"的半成品还报成功（实测 2026-08-18 晚 480 板块仅 27 个已出当日）。
# 增量且截止日=今天时先抽样探测，未达阈值回退到上一交易日继续采集。
_BAR_READY_SAMPLE = 10
_BAR_READY_RATIO = 0.5


def normalize_board_stages(value) -> list[str] | None:
    """规范化板块采集阶段；None 表示默认全阶段，显式空数组属于非法配置。"""
    if value is None:
        return None
    try:
        raw = value.split(",") if isinstance(value, str) else list(value)
    except TypeError as exc:
        raise ValueError("板块采集内容必须是数组或逗号分隔字符串") from exc
    stages = list(dict.fromkeys(str(x).strip() for x in raw if str(x).strip()))
    if not stages:
        raise ValueError("板块采集内容至少选择一项")
    unknown = sorted(set(stages) - set(BOARD_INGEST_STAGES))
    if unknown:
        raise ValueError(f"未知板块采集步骤: {unknown}")
    return stages


def normalize_board_force_current_day(mode: str, value) -> bool:
    """校验板块当日退级参数；仅增量模式允许显式绕过。"""
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ValueError("板块强制采集当日必须是布尔值")
    if mode != "update" and value:
        raise ValueError("只有板块增量采集支持强制采集当日")
    return value


def normalize_board_date_range(
    mode: str, date_start: date | str | None, date_end: date | str | None,
    force_current_day: bool = False,
) -> tuple[date | None, date | None]:
    """规范化手动指数区间；留空表示按板块最新水位自动增量。"""
    def parse(value, label: str) -> date | None:
        if value in (None, ""):
            return None
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value))
        except ValueError as exc:
            raise ValueError(f"板块{label}必须是 YYYY-MM-DD") from exc

    start = parse(date_start, "起始日期")
    end = parse(date_end, "结束日期")
    if end and not start:
        raise ValueError("指定板块指数结束日期时必须同时指定起始日期")
    if start and not end:
        end = start
    if start and end and start > end:
        raise ValueError("板块指数起始日期不能晚于结束日期")
    if start and mode != "update":
        raise ValueError("显式板块指数区间仅支持增量模式")
    if start and force_current_day:
        raise ValueError("显式板块指数区间不能与强制采集当日同时使用")
    return start, end


def _asia_now() -> datetime:
    """统一采集时钟，避免编排目标日与资金流门禁使用不同的时区。"""
    return eod_dates.shanghai_now()


def _asia_date() -> date:
    """Asia/Shanghai 当前日期（快照日期语义）。"""
    return _asia_now().date()


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

    def __init__(self, client: DuckDBClient | None = None, source: ThsBoardSource | None = None,
                 member_interval_days: int | None = None,
                 source_factory: Callable[[], ThsBoardSource] | None = None):
        self.c = client or get_client()
        init_db(self.c)
        self.src = source or ThsBoardSource()
        self._source_factory = source_factory
        # 成分快照更新间隔（天，周频控制）：显式入参优先；未传读生效配置；配置异常回落 7 天。
        # 对齐 ThsBoardSource 同款「显式入参 → 生效配置 → 参数默认」模式，便于测试注入与 Web 配置生效。
        if member_interval_days is None:
            try:
                from backend.config.settings import get_effective_settings
                self._member_interval_days = int(
                    get_effective_settings().ths_board.member_update_interval_days)
            except Exception:  # noqa: BLE001 —— 配置/DB 异常回落默认
                self._member_interval_days = 7
        else:
            self._member_interval_days = member_interval_days

    def _work_concurrency(self, stage: str, concurrency: int | None, ctx) -> int:
        """成分与指数共用并发校验和观测；任务覆盖优先，阶段默认值彼此独立。"""
        default = getattr(get_effective_settings().ths_board, f"{stage}_concurrency")
        requested = default if concurrency is None else concurrency
        if isinstance(requested, bool) or not isinstance(requested, int) or not 1 <= requested <= 16:
            label = {"member": "成分", "bar": "指数"}[stage]
            raise ValueError(f"板块{label}采集并发数必须为1~16的整数")
        tracker = getattr(ctx, "request_tracker", None)
        if tracker and not getattr(self.src, "is_prefetched", False):
            tracker.meta.update(
                configured_work_concurrency=requested, default_concurrency=default,
                concurrency_origin="task" if concurrency is not None else "default",
            )
        return requested

    def _run_board_units(self, items, fetch, complete, *, concurrency: int, ctx, label: str):
        """共享有界取源入口：每线程独立会话，主线程收口，取消后等待在途退出再释放。"""
        workers = min(concurrency, max(1, len(items)))
        material_only = getattr(self.src, "is_prefetched", False)
        tracker = getattr(ctx, "request_tracker", None)
        if tracker and not material_only:
            tracker.meta.update(work_concurrency=workers)
        local = threading.local()
        sources: list[ThsBoardSource] = []
        source_lock = threading.Lock()

        def worker(item):
            if workers == 1:
                source = self.src
            else:
                if not hasattr(local, "source"):
                    factory = self._source_factory or self.src.fork
                    local.source = factory()
                    with source_lock:
                        sources.append(local.source)
                source = local.source
            return fetch(source, item)

        if ctx and material_only:
            ctx.log(f"{label}：复用已取源材料，由编排线程校验落库")
        elif ctx:
            ctx.log(f"{label}：待采 {len(items)} 个板块，工作并发 {workers}；"
                    "来源总频率、在途上限与冷却共享，主线程统一落库")
        try:
            run_bounded_parallel(
                items, worker, concurrency=workers, ctx=ctx,
                wait_label=label, on_complete=complete,
            )
        finally:
            for source in sources:
                source.close()

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
        fetched = False  # 本次是否真实拉取过字典（区分全新入库与 checkpoint 跳过）
        def report(processed, current_type):
            if ctx:
                ctx.set_phase("board_dict", done=len(done_types.intersection(types)), total=len(types),
                              phase_total=len(types), phase_done=processed, current_item=current_type,
                              dict_done_types=sorted(done_types))

        for type_index, current_type in enumerate(types, 1):
            if current_type in done_types:
                # 续跑命中 checkpoint：本次不拉取，回查库内数量回填，避免日志误报「概念 0 / 行业 0」
                existing = self.c.query_df(
                    "SELECT count(*) AS n FROM board_dict WHERE board_type=?", [current_type])
                result[current_type] = int(existing["n"].iloc[0]) if not existing.empty else 0
                if ctx:
                    report(type_index, current_type)
                    ctx.log(f"字典 {current_type}：上次已完成，本次跳过（库内 {result[current_type]} 个）")
                continue
            if ctx:
                ctx.check_cancel()
                report(type_index - 1, current_type)
            try:
                df = self.src.get_board_dict(current_type)
            except Exception as e:  # noqa: BLE001 -- 两类字典独立失败，保留另一类成功结果
                result["failed"].append(f"{current_type}: {e}")
                self._log_update("board_dict", sdate, sdate, 0, "failed", f"{current_type} 字典：{e}")
                if ctx:
                    ctx.log(f"字典 {current_type}：失败 {e}", "error")
                report(type_index, current_type)
                continue
            if df.empty:
                log.warning("字典 %s 为空，跳过", current_type)
                result["failed"].append(f"{current_type}: empty")
                self._log_update("board_dict", sdate, sdate, 0, "failed", f"{current_type} 字典为空")
                if ctx:
                    ctx.log(f"字典 {current_type}：为空，跳过", "warn")
                report(type_index, current_type)
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
            fetched = True
            if ctx:
                ctx.log(f"字典 {current_type}：{len(rows)} 个板块")
            # 更新留痕（对齐现有采集）
            self._log_update("board_dict", sdate, sdate, len(rows),
                             "partial" if len(result["failed"]) > app_failures_before else "success",
                             f"{current_type} 字典")
            if len(result["failed"]) == app_failures_before:
                done_types.add(current_type)
            report(type_index, current_type)
        result["total"] = result["concept"] + result["industry"]
        if not fetched and done_types.issuperset(types):
            log.info("板块字典本次跳过（checkpoint 已完成）：概念 %d + 行业 %d（库内现有）",
                     result["concept"], result["industry"])
        else:
            log.info("板块字典入库 %d 个（概念 %d + 行业 %d）",
                     result["total"], result["concept"], result["industry"])
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
                             ctx: object | None = None,
                             force: bool = False,
                             concurrency: int | None = None) -> dict:
        """逐板块成分快照：完整快照 INSERT ON CONFLICT DO NOTHING 落库（只进不出）。

        board_codes=None → 全量（从 board_dict 读取有成分数据的板块）。单板块失败记日志不中断，
        返回 {board_code: {"total"/"added"/"error"/"skipped"...}}。
        ctx：任务上下文（TaskContext/CliTaskContext 鸭子类型），逐板块打实时日志。

        周频更新（板块概念 R 深化）：成分股不随每日增量更新。默认模式只重拉「上次完整快照
        距今 >= member_update_interval_days 天」或「从未完整落库（member_snapshot_at IS NULL）」
        的板块，未达间隔的记 skipped 跳过（不计失败、不打日志 failed、不写 incomplete issue）。
        force=True 绕过间隔直接全量（质量页修复重采 / backfill 初始化 / CLI --force-members 用）。
        并发数缺省读取 ths_board.member_concurrency；工作线程只取源，主线程落库并维护断点。
        每线程独立来源会话，同一板块仍顺序执行双排序分页，来源总频率和冷却继续共享。
        """
        requested_concurrency = self._work_concurrency("member", concurrency, ctx)
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
        # 周频跳过（force 时不过滤）：只拉「上次完整快照过久」或「从未完整落库」的板块。
        # 间隔比较与写入同源：member_snapshot_at 由 now() 写入 TIMESTAMP 列（DuckDB 会话时区
        # 默认为 Asia/Shanghai，读出 naive 墙钟）；cutoff 取 DB 会话 now() - 间隔折 naive 墙钟，
        # 不引入 Python 时区假设，任何会话时区下判定都与写入一致。
        skipped_codes: set[str] = set()
        if not force and len(df_boards):
            db_now = self.c.query_df("SELECT now() AS n").iloc[0]["n"]
            cutoff = (pd.Timestamp(db_now) - pd.Timedelta(days=self._member_interval_days)) \
                .tz_localize(None).to_pydatetime()
            snap = self.c.query_df(
                f"SELECT board_code, member_snapshot_at FROM board_dict "
                f"WHERE board_code IN ({_in_placeholders(len(df_boards))})",
                [str(x) for x in df_boards["board_code"].tolist()])
            snap_map = dict(zip(snap["board_code"].astype(str), snap["member_snapshot_at"]))
            keep: list[bool] = []
            for bc in df_boards["board_code"].astype(str):
                at = snap_map.get(bc)
                # member_snapshot_at 缺失/NaT（从未完整落库）→ 必须拉；存在且距今不足间隔 → 跳过。
                # TIMESTAMP 列读出为 naive 墙钟，与 naive cutoff 一致直接比较。
                if at is None or pd.isna(at):
                    keep.append(True)
                else:
                    keep.append(pd.Timestamp(at).to_pydatetime() < cutoff)
            skip_mask = pd.Series(keep, index=df_boards.index)
            skipped_codes = {str(x) for x in df_boards.loc[~skip_mask, "board_code"].tolist()}
            df_boards = df_boards[skip_mask]
            if skipped_codes:
                results.update({c: {"skipped": True, "interval_days": self._member_interval_days}
                                for c in skipped_codes})
        n_err = 0
        n_total = len(df_boards)
        phase_total = len(done_codes) + n_total + len(skipped_codes)
        resumed_members = len(done_codes) + len(skipped_codes)
        if ctx:
            ctx.set_phase("board_members", done=len(done_codes), total=phase_total,
                          phase_total=phase_total, phase_done=resumed_members,
                          current_item=None, member_done_codes=sorted(done_codes))
        items = [(str(b.board_code), str(b.board_type))
                 for b in df_boards.itertuples(index=False)]
        def fetch(source, item):
            code, current_type = item
            return source.get_board_members(code, current_type)

        def complete(i, item, material, error, pending):
            nonlocal n_err
            code, _ = item
            try:
                if error is not None:
                    raise error
                results[code] = self._store_member_snapshot(code, material, sdate)
                r = results[code]
                done_codes.add(code)
                if ctx:
                    ctx.set_phase("board_members", done=len(done_codes), total=phase_total,
                                  phase_total=phase_total,
                                  phase_done=resumed_members + i, current_item=code,
                                  member_done_codes=sorted(done_codes))
                if ctx:
                    ctx.log(
                        f"成分 {i}/{n_total} {code}：源端完整 {r.get('total', 0)} 只，"
                        f"项目内 {r.get('eligible_total', 0)} 只，"
                        f"排除范围外 {r.get('excluded_out_of_scope', 0)} 只，"
                        f"新增 {r.get('added', 0)} 只"
                    )
            except TaskCancelled:
                raise
            except Exception as e:  # noqa: BLE001 —— 单板块失败跳过不中断，记 data_update_log failed
                log.warning("板块 %s 成分快照失败: %s", code, e)
                results[code] = {"error": str(e)}
                n_err += 1
                self._log_update("board_member", sdate, sdate, 0, "failed", f"{code} {e}")
                self._write_incomplete_quality(code, sdate, str(e))
                if ctx:
                    ctx.log(f"成分 {i}/{n_total} {code}：失败 {e}", "error")
                    ctx.set_phase("board_members", done=len(done_codes), total=phase_total,
                                  phase_total=phase_total, phase_done=resumed_members + i,
                                  current_item=code, member_done_codes=sorted(done_codes))
        self._run_board_units(
            items, fetch, complete, concurrency=requested_concurrency, ctx=ctx, label="板块成分",
        )
        if skipped_codes and ctx:
            ctx.log(f"成分：{len(skipped_codes)} 个板块未达更新间隔（{self._member_interval_days} 天），跳过")
        # 更新留痕（聚合：一次运行一条日志，避免逐板块刷屏）
        written = sum(int(r.get("added", 0)) for r in results.values() if "error" not in r and not r.get("skipped"))
        excluded = sum(
            int(r.get("excluded_out_of_scope", 0))
            for r in results.values()
            if "error" not in r and not r.get("skipped")
        )
        skip_detail = f"，跳过 {len(skipped_codes)} 个未到期板块" if skipped_codes else ""
        self._log_update("board_member", sdate, sdate, written,
                         "success" if not n_err else "partial",
                         f"处理 {len(results) - len(skipped_codes)} 个板块，新增 {written} 条成员关系"
                         f"，排除范围外 {excluded} 条（失败 {n_err}）{skip_detail}")
        log.info("板块成分快照 %d 个板块（跳过 %d，失败 %d）",
                 len(results) - len(skipped_codes), len(skipped_codes), n_err)
        return results

    def _ingest_one_member(self, code: str, board_type: str, sdate: date) -> dict:
        """单板块成分快照（只进不出模型）：完整快照 INSERT ON CONFLICT DO NOTHING，不 diff 不删除。

        - complete=True → 快照内每个 code `INSERT ... ON CONFLICT (board_code, code) DO NOTHING`
          （已在表的不动、新出现的插入），同步刷新 board_dict.member_count（最近完整快照返回数）。
        - complete=False（分页不完整/登录墙/401/异常）→ 抛 DataSourceError，整趟不落库，
          上层 ingest_board_members 记失败、data_update_log 记 failed 待重采；已采旧数据原样保留。
        """
        m = self.src.get_board_members(code, board_type)
        return self._store_member_snapshot(code, m, sdate)

    def _store_member_snapshot(self, code: str, m: dict, sdate: date) -> dict:
        """在编排线程校验完整性并原子落库；串行、并发及质量修复共用同一口径。"""
        codes_full = [to_full_code(c) for c in m["codes"]]
        source_set = set(codes_full)
        cur_set = {
            member_code
            for member_code in source_set
            if classify_board(member_code.split(".", 1)[0])[1]
            in {"主板", "创业板", "科创板"}
        }
        excluded_count = len(source_set) - len(cur_set)
        if not m["complete"]:
            # 完整性即闸门：不完整快照整趟不落库（含完全没取到的空快照），抛错走失败留痕
            raise DataSourceError(
                f"板块 {code} 成分快照不完整（complete=False，取到 {len(source_set)} 只），不落库待重采")
        if not source_set:
            # 完整但空快照：源端返回空成分（罕见，如板块成分为空），记失败
            raise DataSourceError(f"板块 {code} 成分快照完整但为空，记失败待重采")
        # 完整快照 → 只进不出落库（已有不动、新增插入），同事务刷新 member_count
        with self.c.transaction():
            existing = 0
            if cur_set:
                ph = _in_placeholders(len(cur_set))
                existing = int(self.c.query_df(
                    f"SELECT count(*) AS n FROM board_member WHERE board_code=? AND code IN ({ph})",
                    [code, *sorted(cur_set)]).iloc[0]["n"])
                self.c.execute(
                    f"INSERT INTO board_member (board_code, code, first_seen_date) "
                    f"SELECT ?, code, ? FROM (VALUES {','.join('(?)' for _ in cur_set)}) t(code) "
                    f"ON CONFLICT (board_code, code) DO NOTHING",
                    [code, sdate, *sorted(cur_set)])
            self.c.execute(
                "UPDATE board_dict SET member_count=?, member_snapshot_at=now(), updated_at=now() "
                "WHERE board_code=?",
                [len(source_set), code])
            self.c.execute(
                "UPDATE board_dict SET member_history_start_date=COALESCE(member_history_start_date, ?), "
                "updated_at=now() WHERE board_code=?",
                [sdate, code])
            # 普通采集和质量修复共用同一闭环：新的完整快照成功后，旧的不完整问题即已消失。
            self.c.execute(
                "UPDATE data_quality_issue SET status='resolved', resolved_at=now(), fix_task_id=NULL "
                "WHERE issue_type='board_member_incomplete' AND code=? "
                "AND status IN ('open','fixing')", [code])
            from backend.dataquality.ignore_rules import deactivate_occurrence_ignores
            ignored_dates = self.c.query_df(
                "SELECT trade_date FROM data_quality_issue WHERE issue_type='board_member_incomplete' "
                "AND code=? AND status='ignored' AND ignore_active=true", [code])
            deactivate_occurrence_ignores(
                self.c, "board_member_incomplete", code, ignored_dates["trade_date"].tolist(),
            )
        return {
            "total": len(source_set),
            "eligible_total": len(cur_set),
            "excluded_out_of_scope": excluded_count,
            "added": len(cur_set) - existing,
        }

    # ── 3. 指数 ──────────────────────────────────────────────

    def ingest_board_bar(self, start: date | None, end: date | None = None,
                         board_codes: list[str] | None = None,
                         board_type: str | None = None,
                         probe_ready: bool = False,
                         resume_from_latest: bool = False,
                         ctx: object | None = None,
                         concurrency: int | None = None) -> dict:
        """板块指数日线：幂等 upsert 原值。end 缺省=今天。返回 {"rows": n, "boards": n}。

        ctx：任务上下文，逐板块打实时日志（对齐现有采集「指数 X 完成」模式）。
        resume_from_latest：自动增量按每个板块已落库最大交易日的下一自然日续采；从未落库的
        板块只尝试截止日，历史初始化由 backfill 负责。该模式下 start 必须为 None。
        probe_ready：仅每日增量（ingest_board update 分支）传 True——截止日=今天时
        先抽样探测源端当日数据是否就绪，未就绪回退到上一交易日继续采集；backfill/
        缺口重采不传，尊重调用方意图直接采。"""
        requested_concurrency = self._work_concurrency("bar", concurrency, ctx)
        if resume_from_latest and start is not None:
            raise ValueError("按板块最新日期续采时不得指定统一起始日期")
        if not resume_from_latest and start is None:
            raise ValueError("板块指数区间采集必须指定起始日期")
        end = end or _asia_date()
        if start is not None and start > end:
            raise ValueError("板块指数起始日期不能晚于结束日期")
        requested_end = end
        end = eod_dates.cap_range(start, end) if start else eod_dates.cap_end(end)
        fallback = end != requested_end
        types = _board_types(board_type)
        if board_codes is not None:
            if not board_codes:
                return {"rows": 0, "boards": 0, "failed": [],
                        "start": start.isoformat() if start else None,
                        "end": end.isoformat(),
                        "at_end": 0, "scope_total": 0}
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
        scope_codes = [str(x) for x in df_boards["board_code"].tolist()]  # 本轮全量范围（含续跑已完成）
        checkpoint = (getattr(ctx, 'checkpoint', {}) or {}) if ctx else {}
        scope = hashlib.md5(json.dumps({
            'codes': sorted(board_codes) if board_codes is not None else None,
            'type': board_type, 'start': start.isoformat() if start else None,
            'incremental': resume_from_latest,
        }, sort_keys=True).encode()).hexdigest()[:12]
        done_codes = (set(checkpoint.get('bar_done_codes') or [])
                      if (checkpoint.get('bar_target_end') == end.isoformat()
                          and checkpoint.get('bar_scope') == scope) else set())
        done_codes.intersection_update({str(x) for x in df_boards["board_code"].tolist()})
        resumed_done = len(done_codes)  # 续跑命中 checkpoint 的板块数（done_codes 循环中会继续增长）
        if done_codes:
            df_boards = df_boards[~df_boards["board_code"].astype(str).isin(done_codes)]
            if ctx:
                ctx.log(f"指数：{resumed_done} 个板块上次已完成，本次跳过")
        board_starts: dict[str, date] = {}
        missing_bar_codes: set[str] = set()
        if resume_from_latest and len(df_boards):
            pending_codes = [str(x) for x in df_boards["board_code"].tolist()]
            latest = self.c.query_df(
                f"SELECT board_code, max(trade_date) AS d FROM board_bar "
                f"WHERE board_code IN ({_in_placeholders(len(pending_codes))}) GROUP BY board_code",
                pending_codes,
            )
            latest_map = dict(zip(latest["board_code"].astype(str), latest["d"]))
            pending: list[bool] = []
            for code in df_boards["board_code"].astype(str):
                last = latest_map.get(code)
                if last is None or pd.isna(last):
                    missing_bar_codes.add(code)
                board_start = end if last is None or pd.isna(last) else pd.Timestamp(last).date() + timedelta(days=1)
                board_starts[code] = board_start
                pending.append(board_start <= end)
            pending_mask = pd.Series(pending, index=df_boards.index)
            current_codes = set(df_boards.loc[~pending_mask, "board_code"].astype(str))
            done_codes.update(current_codes)
            df_boards = df_boards[pending_mask]
            board_starts = {
                code: board_starts[code] for code in df_boards["board_code"].astype(str)
            }
            if current_codes and ctx:
                ctx.log(f"指数：{len(current_codes)} 个板块已到 {end}，无需请求")
        n_total = len(df_boards)
        phase_total = len(done_codes) + n_total
        if ctx and n_total:
            tail = f"（续跑跳过已完成 {resumed_done}）" if resumed_done else ""
            range_text = "逐板块水位续采" if resume_from_latest else f"{start} ~ {end}"
            ctx.log(f"板块指数采集区间 {range_text}，待采 {n_total} 个板块{tail}")
        if probe_ready and n_total and end >= _asia_date():
            # 就绪探测：仅「每日增量 + 截止日=今天」。backfill/缺口窄窗口重采不传
            # probe_ready；非交易日默认 end<今天，数据必已发布。
            ready, sampled = self._probe_bar_ready(df_boards, end)
            if ready / max(sampled, 1) < _BAR_READY_RATIO:
                fallback_end = self._previous_open_day(end)
                msg = (f"板块指数源端当日数据未就绪：抽样 {ready}/{sampled} 个板块已出 {end}，"
                       f"回退到上一交易日 {fallback_end} 继续采集；"
                       "下轮定时仍会重新目标当天")
                log.warning(msg)
                if ctx:
                    ctx.log(msg, "warn")
                end = fallback_end
                # 从未采到指数的板块只请求实际截止日；退级后不能沿用原目标日造成逆序空区间。
                for code in missing_bar_codes.intersection(board_starts):
                    board_starts[code] = end
                if start is not None:
                    start = min(start, end)
                fallback = True
        if ctx:
            ctx.set_phase('board_bar', bar_target_end=end.isoformat(),
                          bar_scope=scope, bar_done_codes=sorted(done_codes),
                          phase_total=phase_total, phase_done=len(done_codes), current_item=None)
        resumed_bars = len(done_codes)
        items = [(str(b.board_code), str(b.board_type))
                 for b in df_boards.itertuples(index=False)]

        def fetch(source, item):
            code, current_type = item
            board_start = board_starts.get(code, start)
            assert board_start is not None
            if board_start > end:
                return None
            # 单板块内仍顺序取年度数据；日期已在主线程统一收敛。
            return source.get_board_bar(code, current_type, board_start, end)

        def complete(i, item, material, error, pending):
            nonlocal total_rows, boards
            code, _ = item
            try:
                if error is not None:
                    raise error
                board_start = board_starts.get(code, start)
                assert board_start is not None
                if board_start > end:
                    done_codes.add(code)
                    if ctx:
                        ctx.set_phase("board_bar", done=len(done_codes), total=phase_total,
                                      phase_total=phase_total, phase_done=resumed_bars + i,
                                      current_item=code, bar_done_codes=sorted(done_codes))
                    return
                df = material
                failed_years = list(df.attrs.get("failed_years") or [])
                df = eod_dates.bound_bars(df, board_start, end)
                if df.empty:
                    if ctx:
                        ctx.log(f"指数 {i}/{n_total} {code}：无数据")
                else:
                    df = df.copy()
                    df["board_code"] = code
                    self._upsert_board_bar(df)
                    total_rows += len(df)
                    boards += 1
                if failed_years:
                    failed.append(f"{code}: years {failed_years}")
                    self._log_update("board_bar", board_start, end, len(df), "partial",
                                     f"{code} 失败年份 {failed_years}")
                if not failed_years:
                    done_codes.add(code)
                if ctx:
                    ctx.set_phase("board_bar", done=len(done_codes), total=phase_total,
                                  phase_total=phase_total,
                                  phase_done=resumed_bars + i, current_item=code,
                                  bar_done_codes=sorted(done_codes))
                if ctx:
                    ctx.log(f"指数 {i}/{n_total} {code}：{len(df)} 行")
            except TaskCancelled:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("板块 %s 指数取数失败: %s", code, e)
                failed.append(f"{code}: {e}")
                self._log_update("board_bar", board_starts.get(code, start), end, 0, "failed", f"{code} {e}")
                if ctx:
                    ctx.log(f"指数 {i}/{n_total} {code}：失败 {e}", "error")
                    ctx.set_phase("board_bar", done=len(done_codes), total=phase_total,
                                  phase_total=phase_total, phase_done=resumed_bars + i,
                                  current_item=code, bar_done_codes=sorted(done_codes))
        self._run_board_units(
            items, fetch, complete, concurrency=requested_concurrency, ctx=ctx, label="板块指数",
        )
        status = "partial" if failed else "success"
        # 新鲜度透出：成功不代表源端已发截止日（源端分板块陆续发布），汇总里给出已出截止日的覆盖数，
        # 避免「成功 480 板块」掩盖「大部分停在昨天」；缺口仍由质检扫描兜底发现。
        at_end = self._count_at_end(scope_codes, end) if scope_codes else 0
        fresh = f"，已出 {end}：{at_end}/{len(scope_codes)}"
        log_start = min(board_starts.values()) if board_starts else (end if resume_from_latest else start)
        self._log_update("board_bar", log_start, end, total_rows, status,
                         f"{boards} 个板块（失败 {len(failed)}{fresh}）")
        skip_detail = f"，续跑跳过已完成 {resumed_done}" if resumed_done else ""
        log.info("板块指数入库 %d 行 / %d 个板块（失败 %d%s，%s ~ %s%s）",
                 total_rows, boards, len(failed), skip_detail, log_start, end, fresh)
        return {"rows": total_rows, "boards": boards, "failed": failed,
                "start": log_start.isoformat() if log_start else None, "end": end.isoformat(),
                "resume_from_latest": resume_from_latest,
                "requested_end": requested_end.isoformat(), "fallback": fallback,
                "reason": ("not_closed" if requested_end > eod_dates.time_cutoff()
                           else "source_not_ready") if fallback else None,
                "at_end": at_end, "scope_total": len(scope_codes)}

    def _previous_open_day(self, day: date) -> date:
        """只按已入库事实回退，日历缺失时不能以自然日伪造交易日。"""
        return eod_dates.latest_open_day(self.c, day - timedelta(days=1))

    def _probe_bar_ready(self, df_boards: pd.DataFrame, end: date) -> tuple[int, int]:
        """抽样探测源端是否已发布 end 当日板块指数，返回 (已出数板块数, 抽样数)。

        均匀抽样（对齐行情 update 的就绪探测）；单点异常按未就绪计，整体由阈值兜底，
        探测本身不中断采集。
        """
        n = len(df_boards)
        step = max(n // _BAR_READY_SAMPLE, 1)
        sample = df_boards.iloc[::step].head(_BAR_READY_SAMPLE)
        ready = 0
        for _, b in sample.iterrows():
            code, board_type = str(b["board_code"]), str(b["board_type"])
            try:
                df = self.src.get_board_bar(code, board_type, end, end)
                if not df.empty and pd.to_datetime(df["trade_date"]).max().date() >= end:
                    ready += 1
            except Exception as e:  # noqa: BLE001 —— 探测失败按未就绪计，不掩盖为就绪
                log.debug("板块 %s 指数就绪探测失败: %s", code, e)
        return ready, len(sample)

    def _count_at_end(self, scope_codes: list[str], end: date) -> int:
        """本轮范围内库内已覆盖到 end 的板块数（含续跑已完成的板块，反映落库后的真实新鲜度）。"""
        df = self.c.query_df(
            f"SELECT count(*) AS n FROM board_dict b "
            f"JOIN board_bar bar ON bar.board_code = b.board_code AND bar.trade_date = ? "
            f"WHERE b.board_code IN ({_in_placeholders(len(scope_codes))})",
            [end, *scope_codes])
        return int(df.iloc[0]["n"])

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

    def _validate_fund_snapshot_date(self, target: date | None = None) -> date:
        """解析并校验可采收盘日：集合竞价前归前一交易日，盘中禁止写入。"""
        from datetime import time as day_time

        now = _asia_now()
        today = now.date()
        is_open = eod_dates.is_open_day(self.c, today)
        if is_open and day_time(9, 15) <= now.time() < day_time(15, 30):
            raise DataSourceError(
                "同花顺资金流仅提供当前快照；交易日09:15至15:30不能写为EOD或历史快照"
            )
        # 午夜不产生新的收盘事实；到集合竞价开始才停止接受上一交易日快照。
        # 日历缺历史开市日时明确拒绝，不能回退一个自然日伪造交易日。
        snapshot_day = eod_dates.resolve_end(self.c, today)
        if target is not None and target != snapshot_day:
            raise DataSourceError(
                f"同花顺资金流快照日期不匹配，不支持历史回填："
                f"目标{target}，当前可采快照日{snapshot_day}"
            )
        return snapshot_day

    def ingest_board_fund_flow(self, snapshot_date: date | None = None,
                               periods: tuple[str, ...] | None = None,
                               board_codes: list[str] | None = None,
                               board_type: str | None = None,
                               ctx: object | None = None) -> dict:
        """资金流 upsert + 名称匹配映射；未匹配写质检不伪造代码（R4）。

        periods=None → 全周期（"即时","3日","5日","10日","20日"）；也可由调用方
        显式传入周期子集用于定向修复。当前 update/backfill 主编排均每次刷新全周期。
        ctx：任务上下文，按类型×周期打实时日志。
        """
        live_snapshot = getattr(self.src, "fund_flow_is_live_snapshot", False)
        sdate = snapshot_date or _asia_date()
        if board_codes != [] and live_snapshot:
            sdate = self._validate_fund_snapshot_date(snapshot_date)
        periods = periods or FUND_FLOW_PERIODS
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
        # fund checkpoint 键带采集范围签名：改 board_codes 子集后续跑不会误命中旧范围的已完成组
        # （否则首跑 codes=[A] 记 "concept:即时"，改 codes=[B] 续跑会跳过 B 的资金流）。
        scope_tag = "ALL" if board_codes is None else hashlib.md5(
            ",".join(sorted(board_codes)).encode()).hexdigest()[:8]
        checkpoint = (getattr(ctx, "checkpoint", {}) or {}) if ctx else {}
        # 完成组只对同一快照日有效；跨日续跑和无日期旧 checkpoint 必须重拉，避免漏采新日。
        done_keys = (set(checkpoint.get("fund_done_keys") or [])
                     if checkpoint.get("fund_snapshot_date") == sdate.isoformat() else set())
        valid_keys = {f"{scope_tag}:{bt}:{period}" for bt in target_types for period in periods}
        # 旧格式兼容：改动前 checkpoint 的 fund_done_keys 无 scope 前缀（如 "concept:即时"）。
        # 全量范围（scope_tag=ALL）下旧键等价于当前签名键，平移后保留跳过；指定子集范围下旧键
        # 无法确认来源范围，不信任（丢弃重拉），避免漏采。
        if scope_tag == "ALL":
            legacy_pairs = {f"{bt}:{period}" for bt in target_types for period in periods}
            done_keys = {f"ALL:{k}" if k in legacy_pairs else k for k in done_keys}
        done_keys.intersection_update(valid_keys)
        resumed_groups = len(done_keys)  # 续跑命中的类型×周期组数（done_keys 循环中会继续增长）
        if resumed_groups and ctx:
            ctx.log(f"资金流：{resumed_groups} 个类型×周期组上次已完成，本次跳过")
        if ctx:
            ctx.log(f"资金流快照日：{sdate}（北京时间采集，按已收盘交易日校验）")
        total_groups = len(target_types) * len(periods)
        processed_groups = resumed_groups

        def report(current_item):
            if ctx:
                ctx.set_phase("board_fund_flow", done=len(done_keys), total=total_groups,
                              phase_total=total_groups, phase_done=processed_groups,
                              current_item=current_item, fund_done_keys=sorted(done_keys),
                              fund_snapshot_date=sdate.isoformat())

        report(None)
        for board_type in ("concept", "industry"):
            if board_type not in target_types:
                continue
            for period in periods:
                display_key = f"{board_type}:{period}"
                group_key = f"{scope_tag}:{display_key}"
                if group_key in done_keys:
                    continue
                if ctx:
                    ctx.check_cancel()
                    ctx.set_phase("board_fund_flow", done=len(done_keys), total=total_groups,
                                  phase_total=total_groups, phase_done=processed_groups,
                                  current_item=display_key, fund_done_keys=sorted(done_keys),
                                  fund_snapshot_date=sdate.isoformat())
                processed_groups += 1
                try:
                    df = self.src.get_board_fund_flow(board_type, period)
                except Exception as e:  # noqa: BLE001
                    log.warning("资金流 %s/%s 取数失败: %s", board_type, period, e)
                    failed.append(f"{display_key}: {e}")
                    self._log_update("board_fund_flow", sdate, sdate, 0, "failed",
                                     f"{display_key} {e}")
                    if ctx:
                        ctx.log(f"资金流 {board_type}/{period}：失败 {e}", "error")
                    report(display_key)
                    continue
                if live_snapshot:
                    # 单次拉取含多页、重试；跨过集合竞价或下个交易日后不得沿用请求前日期。
                    self._validate_fund_snapshot_date(sdate)
                if df.empty:
                    failed.append(f"{display_key}: empty")
                    self._log_update("board_fund_flow", sdate, sdate, 0, "failed",
                                     f"{display_key} 资金流为空")
                    if ctx:
                        ctx.log(f"资金流 {board_type}/{period}：无数据，记失败", "error")
                    report(display_key)
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
                                f"{display_key}:{name}: net_inflow={net} != inflow-outflow={expected:.4f}")
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
                if not any(x.startswith(display_key + ":") for x in failed):
                    done_keys.add(group_key)
                report(group_key)
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
        skip_detail = f"，续跑跳过已完成组 {resumed_groups}" if resumed_groups else ""
        log.info("板块资金流入库 %d 行（未匹配 %d，失败 %d%s）",
                 rows, len(unmatched), len(failed), skip_detail)
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
        from backend.dataquality.ignore_rules import filter_ignored_issues
        seen = {(x["board_type"], x["name"]) for x in items}
        candidates = [
            {
                "code": None,
                "trade_date": sdate,
                "issue_type": "board_fund_unmatched",
                "detail": json.dumps({"name": name, "board_type": board_type}, ensure_ascii=False),
            }
            for board_type, name in seen
        ]
        candidates = filter_ignored_issues(
            self.c, candidates, ("board_fund_unmatched",), reconcile_occurrences=True,
        )
        for candidate in candidates:
            payload = json.loads(candidate["detail"])
            board_type, name = payload["board_type"], payload["name"]
            # 幂等：同名同类型的未匹配 issue 已存在（open/fixing/ignored）不重复建——
            # ignored 豁免对齐 board_index_gap/member_incomplete：用户标记正常后重采不得翻回 open。
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
                "VALUES (?, ?, ?, 'board_fund_unmatched', ?, "
                "'open', ?, now(), NULL)",
                [issue_id, None, sdate, severity_for("board_fund_unmatched"),
                 candidate["detail"]])

    def _write_incomplete_quality(self, code: str, sdate: date, reason: str) -> None:
        """成分快照采集不完整/失败写质检（board_member_incomplete），供数据质量页逐板块重采。

        幂等：同板块未解决（open/fixing）或已忽略（ignored）的 board_member_incomplete 不重复建
        （采集失败会反复触发，避免刷屏；ignored 豁免对齐 fund/board_index_gap——用户标记正常后
        重采不得翻回 open；重采成功/复检通过后 resolved 收敛）。
        """
        from backend.dataquality.ignore_rules import filter_ignored_issues
        candidates = filter_ignored_issues(
            self.c,
            [{
                "code": code,
                "trade_date": sdate,
                "issue_type": "board_member_incomplete",
                "detail": json.dumps({"reason": reason, "snapshot_date": sdate.isoformat()},
                                     ensure_ascii=False),
            }],
            ("board_member_incomplete",),
            reconcile_occurrences=False,
        )
        if not candidates:
            return
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
            "VALUES (?, ?, ?, 'board_member_incomplete', ?, "
            "'open', ?, now(), NULL)",
            [issue_id, code, sdate, severity_for("board_member_incomplete"), candidates[0]["detail"]])
