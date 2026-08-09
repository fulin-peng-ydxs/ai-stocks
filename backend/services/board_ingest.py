"""板块概念数据采集服务（板块概念需求 R1-R4/R2 候选保存，agent-works/concept-industry-board/）。

编排逻辑（承接 plan §6.4 T4）：
1. 字典两阶段：概念/行业字典 upsert（阶段一）→ 资金流并集补充 + has_fund_flow（阶段二）
   → 能力字段与 last_seen_at 收口。
2. 成分快照：逐板块 `ThsBoardSource.get_board_members` → 完整性判定（缺页/失败/登录墙/波动超阈值）
   → 完整快照 diff 落库（[in_date,out_date)）+ 刷新 member_count/member_history_start_date（已应用路径）；
   被拦截快照 → payload_hash（SHA-256）→ 同 hash 幂等四态 → 同一 DuckDB 事务写
   board_member_candidate + data_quality_issue（事务①）。
3. 指数：board_bar 幂等 upsert 原值。
4. 资金流：board_fund_flow 全周期 upsert + 名称匹配映射、未匹配写质检不伪造代码。

关键语义：
- 快照日期 = Asia/Shanghai 实际成功采集日期（需求 R2）。
- 成分股代码补交易所后缀对齐 stock_basic.code（复用 akshare_source.to_full_code）。
- member_count 仅「已应用」路径刷新：T4 完整快照直接落库路径；T9 候选确认应用路径。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from backend.common.logging import get_logger
from backend.datasource.akshare_source import to_full_code
from backend.datasource.ths_board import ThsBoardSource
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient, get_client

log = get_logger("services.board_ingest")

# 成分数异常波动阈值（R12）读生效配置 get_effective_settings().board_quality
# （与 T7 scan_board_quality 同一口径，避免双口径；默认值 0.5/20 见 Settings BoardQualityConfig）

# issue 类型（候选恢复闭环）
ISSUE_TYPE_MEMBER_SURGE_SHRINK = "member_surge_shrink"


def _asia_date() -> date:
    """Asia/Shanghai 当前日期（快照日期语义）。"""
    return datetime.now(timezone.utc).astimezone(tz=timezone(timedelta(hours=8))).date()


def _in_placeholders(n: int) -> str:
    """DuckDB `IN (?,?,...)` 占位符串（DuckDB 对 `IN (?)` 传 list 会 Conversion Error，须展开）。"""
    return ",".join(["?"] * n)


class BoardIngestService:
    """板块数据采集编排（R1-R4 + R2 候选保存）。"""

    def __init__(self, client: DuckDBClient | None = None, source: ThsBoardSource | None = None):
        self.c = client or get_client()
        init_db(self.c)
        self.src = source or ThsBoardSource()

    # ── 1. 字典两阶段 ─────────────────────────────────────────

    def ingest_board_dict(self, snapshot_date: date | None = None) -> dict:
        """字典两阶段：概念/行业字典 upsert → 资金流并集补充 + 能力字段收口。

        阶段一（本方法）：概念 + 行业字典全量 upsert 进 board_dict（能力字段按各自接口初判，
        has_fund_flow 暂 false）；阶段二由 ingest_board_fund_flow 补充资金流独有板块与 has_fund_flow。
        返回 {"concept": n, "industry": n, "total": n}。
        """
        sdate = snapshot_date or _asia_date()
        result = {"concept": 0, "industry": 0, "total": 0}
        for board_type in ("concept", "industry"):
            df = self.src.get_board_dict(board_type)
            if df.empty:
                log.warning("字典 %s 为空，跳过", board_type)
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
        result["total"] = result["concept"] + result["industry"]
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

    # ── 2. 成分快照（diff + 候选保存事务①）───────────────────

    def ingest_board_members(self, snapshot_date: date | None = None,
                             board_codes: list[str] | None = None) -> dict:
        """逐板块成分快照：完整快照 diff 落库；被拦截快照写候选 + issue（事务①）。

        board_codes=None → 全量（从 board_dict 读取有成分数据的板块）。单板块失败记日志不中断，
        返回 {board_code: {"total"/"added"/"removed"/"blocked"/"candidate_id"...}}。
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
        for _, b in df_boards.iterrows():
            code, board_type = str(b["board_code"]), str(b["board_type"])
            try:
                results[code] = self._ingest_one_member(code, board_type, sdate)
            except Exception as e:  # noqa: BLE001 —— 单板块失败跳过不中断
                log.warning("板块 %s 成分快照失败: %s", code, e)
                results[code] = {"error": str(e)}
        return results

    def _ingest_one_member(self, code: str, board_type: str, sdate: date) -> dict:
        m = self.src.get_board_members(code, board_type)
        codes_full = [to_full_code(c) for c in m["codes"]]
        cur_set = set(codes_full)
        # 波动阈值判定（R12 公式；读生效配置，与 T7 scan_board_quality 同一口径，避免双口径）
        from backend.config import get_effective_settings
        bq = get_effective_settings().board_quality
        prev = self.c.query_df(
            "SELECT member_count FROM board_dict WHERE board_code=?", [code])
        prev_count = 0
        if not prev.empty:
            mc = prev.iloc[0]["member_count"]
            if mc is not None and not pd.isna(mc):
                prev_count = int(mc)
        threshold = max(bq.absolute_change_threshold, int(prev_count * bq.relative_change_ratio))
        wave_blocked = bool(prev_count) and abs(len(cur_set) - prev_count) >= threshold

        if not m["complete"] or wave_blocked:
            # 不完整快照 / 异常波动 → 不执行退出 diff，写候选 + issue（事务①）
            return self._save_candidate(code, board_type, sdate, cur_set, wave_blocked)

        # 完整快照 → diff 落库 + 刷新 member_count/member_history_start_date
        # （同事务：member_count 冗余值与有效成员关系原子一致，违反 R2 验收）
        diff = self._apply_member_diff(code, sdate, cur_set, member_count=len(cur_set))
        return {"total": len(cur_set), "added": diff["added"], "removed": diff["removed"]}

    def _apply_member_diff(self, code: str, sdate: date, cur_set: set[str],
                           member_count: int | None = None) -> dict:
        """完整快照 diff：新股 in_date=sdate/out_date=NULL；缺席股 out_date=sdate（[in_date,out_date)）。

        同一事务内落 diff + 刷新 board_dict.member_count（冗余值）与 member_history_start_date（首次写入），
        保证「member_count 与有效成员数一致」原子成立（R2 验收）。
        """
        # 当前有效成员
        eff = self.c.query_df(
            "SELECT code FROM board_member WHERE board_code=? AND in_date<=? "
            "AND (out_date IS NULL OR out_date>?)",
            [code, sdate, sdate])
        eff_set = set(eff["code"].tolist())
        added = sorted(cur_set - eff_set)
        removed = sorted(eff_set - cur_set)
        with self.c.transaction():
            for c in added:
                self.c.execute(
                    "INSERT INTO board_member (board_code, code, in_date, out_date) "
                    "VALUES (?, ?, ?, NULL)",
                    [code, c, sdate])
            for c in removed:
                self.c.execute(
                    "UPDATE board_member SET out_date=? WHERE board_code=? AND code=? "
                    "AND out_date IS NULL",
                    [sdate, code, c])
            if member_count is not None:
                self.c.execute(
                    "UPDATE board_dict SET member_count=?, updated_at=now() WHERE board_code=?",
                    [member_count, code])
                self.c.execute(
                    "UPDATE board_dict SET member_history_start_date="
                    "COALESCE(member_history_start_date, ?), updated_at=now() WHERE board_code=?",
                    [sdate, code])
        return {"added": len(added), "removed": len(removed)}

    def _payload_hash(self, sdate: date, codes: set[str]) -> str:
        """payload_hash = SHA-256(ISO日期 + "\\n" + sorted(set(归一化代码)).join("\\n"))（UTF-8 小写 hex）。"""
        norm = sorted(codes)
        payload = f"{sdate.isoformat()}\n" + "\n".join(norm)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _save_candidate(self, code: str, board_type: str, sdate: date,
                        cur_set: set[str], wave_blocked: bool) -> dict:
        """被拦截快照 → 同 hash 幂等四态 → 事务①写候选 + issue。"""
        h = self._payload_hash(sdate, cur_set)
        # 幂等四态：同 hash + pending → 返回已有；+ applied/discarded → 跳过；不同 hash → 新候选
        existing = self.c.query_df(
            "SELECT candidate_id, status FROM board_member_candidate "
            "WHERE board_code=? AND snapshot_date=? AND payload_hash=?",
            [code, sdate, h])
        if not existing.empty:
            st = str(existing.iloc[0]["status"])
            if st in ("applied", "discarded"):
                return {"blocked": True, "reason": f"same_hash_{st}", "total": len(cur_set)}
            return {"blocked": True, "reason": "same_hash_pending",
                    "candidate_id": existing.iloc[0]["candidate_id"], "total": len(cur_set)}
        # 同日多候选：同日已有 applied → 新候选 apply_allowed=false（接口层判定）；入库允许 pending 并存
        cid = f"bc_{code}_{sdate.strftime('%Y%m%d')}_{h[:8]}"
        issue_id = int(self.c.query_df("SELECT nextval('seq_quality_issue') AS v").iloc[0]["v"])
        diff = self._candidate_diff_summary(code, sdate, cur_set)
        with self.c.transaction():
            self.c.execute(
                "INSERT INTO board_member_candidate "
                "(candidate_id, issue_id, board_code, snapshot_date, codes_json, payload_hash, "
                "diff_summary, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')",
                [cid, issue_id, code, sdate,
                 json.dumps(sorted(cur_set)), h,
                 json.dumps(diff, ensure_ascii=False)])
            self.c.execute(
                "INSERT INTO data_quality_issue "
                "(id, code, trade_date, issue_type, severity, status, "
                "detail, detected_at, fix_task_id) "
                "VALUES (?, ?, ?, ?, 'high', 'open', ?, now(), NULL)",
                [issue_id, code, sdate, ISSUE_TYPE_MEMBER_SURGE_SHRINK,
                 json.dumps({"reason": "wave" if wave_blocked else "incomplete",
                             "snapshot_date": sdate.isoformat(),
                             "diff": diff}, ensure_ascii=False)])
        return {"blocked": True, "reason": "wave" if wave_blocked else "incomplete",
                "candidate_id": cid, "issue_id": issue_id, "total": len(cur_set)}

    def _candidate_diff_summary(self, code: str, sdate: date, cur_set: set[str]) -> dict:
        """候选 diff 摘要：新增/退出/净变化（相对当前有效成员）。"""
        eff = self.c.query_df(
            "SELECT code FROM board_member WHERE board_code=? AND in_date<=? "
            "AND (out_date IS NULL OR out_date>?)",
            [code, sdate, sdate])
        eff_set = set(eff["code"].tolist())
        added = len(cur_set - eff_set)
        removed = len(eff_set - cur_set)
        return {"added": added, "removed": removed, "net": len(cur_set) - len(eff_set)}

    # ── 3. 指数 ──────────────────────────────────────────────

    def ingest_board_bar(self, start: date, end: date | None = None,
                         board_codes: list[str] | None = None) -> dict:
        """板块指数日线：幂等 upsert 原值。end 缺省=今天。返回 {"rows": n, "boards": n}。"""
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
        for _, b in df_boards.iterrows():
            code, board_type = str(b["board_code"]), str(b["board_type"])
            try:
                df = self.src.get_board_bar(code, board_type, start, end)
                if df.empty:
                    continue
                df["board_code"] = code
                self._upsert_board_bar(df)
                total_rows += len(df)
                boards += 1
            except Exception as e:  # noqa: BLE001
                log.warning("板块 %s 指数取数失败: %s", code, e)
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
                               periods: tuple[str, ...] | None = None) -> dict:
        """资金流 upsert + 名称匹配映射；未匹配写质检不伪造代码（R4）。

        periods=None → 全周期（"即时","3日","5日","10日","20日"）；update 模式只传 ("即时",)。
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
                    continue
                if df.empty:
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
                # 阶段二：资金流独有板块补充进字典（has_fund_flow=true，has_members/bar=false）
                self._fund_flow_union_supplement(board_type, df, sdate, name_to_code)
        # 未匹配写质检（不伪造代码）
        self._write_unmatched_quality(unmatched, sdate)
        # 能力字段收口：有资金流数据的板块 has_fund_flow=true
        self.c.execute(
            "UPDATE board_dict SET has_fund_flow=true, updated_at=now() "
            "WHERE board_code IN (SELECT DISTINCT board_code FROM board_fund_flow)")
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
