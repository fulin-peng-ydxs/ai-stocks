"""命令行入口（SDD §14：便于手动跑与初始化）。

用法：
    python -m backend.cli serve          启动 Web 服务
    python -m backend.cli health         本地自检（配置 + DuckDB 连通）
    python -m backend.cli backfill       全量回填数据（M1 实现）
    python -m backend.cli update         增量更新数据（M1 实现）
    python -m backend.cli daily          一键日常流程（M7 实现）
    python -m backend.cli backtest       运行回测（M5 实现）

M0 阶段仅 serve / health 可用，其余为占位（后续里程碑补全）。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from backend.common.logging import get_logger
from backend.config import get_settings

log = get_logger("cli")


class CliTaskContext:
    """CLI 侧轻量任务上下文：完整鸭子类型 TaskContext（log/progress/flush/set_phase/
    set_checkpoint/check_cancel + checkpoint 属性），把进度/日志映射到 stdout 实时打印，
    让 CLI 与任务中心同源同标准。CLI 单次前台执行：不续跑、不协作终止，故 check_cancel 空操作、
    checkpoint 仅进程内保存（单次运行内自洽，不落库）。"""

    def __init__(self) -> None:
        self.checkpoint: dict = {}

    def check_cancel(self) -> None:
        return None

    def log(self, message: str, level: str = "info") -> None:
        # flush=True：命令行 stdout 重定向到文件时默认块缓冲，不刷新会让进度
        # 长时间积压在缓冲区里"看不到"（黑盒）。强制刷新让 CLI 实时可见。
        print(message, flush=True)

    def progress(self, progress: float, message: str) -> None:
        print(f"{progress * 100:.1f}% {message}", flush=True)

    def flush(self) -> None:
        return None

    def set_checkpoint(self, **data: object) -> None:
        self.checkpoint.update(data)

    def set_phase(self, phase: str, **data: object) -> None:
        self.checkpoint.update({"phase": phase, **data})


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    s = get_settings()
    reload = bool(getattr(args, "reload", False))
    # --host 覆盖配置：dev 通常绑 127.0.0.1（仅本机/供前端代理），prod 绑 0.0.0.0（对外）。
    host = getattr(args, "host", None) or s.server.host
    log.info("启动服务 http://%s:%s%s", host, s.server.port, "（热重载）" if reload else "")
    uvicorn.run(
        "backend.main:app",
        host=host,
        port=s.server.port,
        log_level=s.server.log_level,
        # --reload：监控 backend 源码目录，改 .py 自动重启 worker（开发期热更，无需手动重启）。
        reload=reload,
        reload_dirs=["backend"] if reload else None,
    )
    return 0


def cmd_health(_: argparse.Namespace) -> int:
    """混合持久层三库连通性自检（行情 DuckDB + 资产 PG + 短状态 Redis）。"""
    s = get_settings()
    log.info("配置加载成功：history_years=%s, db=%s", s.datasource.history_years, s.duckdb_path())
    from backend.storage import get_client, get_pg_client, get_redis_client

    results: list[tuple[str, bool, str]] = []
    try:
        v = get_client().query_df("SELECT version() AS v").iloc[0]["v"]
        results.append(("DuckDB(行情)", True, f"{v}"))
    except Exception as e:  # noqa: BLE001
        results.append(("DuckDB(行情)", False, str(e)))
    try:
        ok = get_pg_client().ping()
        results.append(("PostgreSQL(资产)", ok, f"{s.postgres.host}:{s.postgres.port}/{s.postgres.database}"))
    except Exception as e:  # noqa: BLE001
        results.append(("PostgreSQL(资产)", False, str(e)))
    try:
        ok = get_redis_client().ping()
        results.append(("Redis(短状态)", ok, f"{s.redis.host}:{s.redis.port}/{s.redis.db}"))
    except Exception as e:  # noqa: BLE001
        results.append(("Redis(短状态)", False, str(e)))

    all_ok = all(ok for _, ok, _ in results)
    for name, ok, detail in results:
        print(f"  [{'OK ' if ok else 'FAIL'}] {name}: {detail}")
    print("三库自检通过 ✅" if all_ok else "三库自检存在失败 ❌")
    return 0 if all_ok else 1


def _todo(name: str):
    def _run(_: argparse.Namespace) -> int:
        log.warning("命令 '%s' 尚未实现（见任务清单对应里程碑）", name)
        print(f"[占位] '{name}' 将在后续里程碑实现")
        return 0

    return _run


def _resolve_codes(args: argparse.Namespace) -> list[str] | None:
    """从 --codes / --limit 解析目标股票子集（用于小批量验证）。"""
    if getattr(args, "codes", None):
        return [c.strip() for c in args.codes.split(",") if c.strip()]
    if getattr(args, "limit", None):
        from backend.datasource.akshare_source import AKShareSource

        listing = AKShareSource().get_stock_list()
        return listing["code"].head(args.limit).tolist()
    return None


def cmd_backfill(args: argparse.Namespace) -> int:
    from backend.services import IngestionService

    codes = _resolve_codes(args)
    result = IngestionService().backfill(
        codes=codes, years=args.years, concurrency=getattr(args, "concurrency", None),
        ctx=CliTaskContext())
    print(f"回填完成: {result}")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    from backend.services import IngestionService

    codes = _resolve_codes(args)
    result = IngestionService().update(codes=codes, concurrency=args.concurrency, ctx=CliTaskContext())
    print(f"增量更新完成: {result}")
    return 0


def cmd_valuation(args: argparse.Namespace) -> int:
    from backend.services import IngestionService

    codes = _resolve_codes(args)
    svc = IngestionService()
    conc = getattr(args, "concurrency", None)
    if getattr(args, "fill_gaps", False):
        # 一次性历史回补（WS2）：补在市股 total_mv 缺口（逐缺口驱动，不受整股断点跳过限制）
        result = svc.ingest_valuation_gaps(codes=codes, concurrency=conc)
        print(f"市值缺口回补完成: {result}")
        return 0
    result = svc.ingest_valuation(codes=codes, years=args.years, concurrency=conc)
    print(f"估值入库完成: {result}")
    return 0


def cmd_rebuild_price_factors(args: argparse.Namespace) -> int:
    from backend.services import IngestionService

    codes = _resolve_codes(args)
    result = IngestionService().rebuild_price_factors(codes=codes)
    print(f"干净复权因子/前收盘重算完成: {result}")
    return 0


def cmd_refetch_daily(args: argparse.Namespace) -> int:
    from backend.services import IngestionService
    from backend.storage import get_client

    codes = _resolve_codes(args)
    end = date.fromisoformat(args.end) if args.end else date.today()
    if args.start:
        start = date.fromisoformat(args.start)
    else:
        c = get_client()
        if codes:
            placeholders = ",".join(["?"] * len(codes))
            df = c.query_df(
                f"SELECT min(trade_date) AS d FROM daily_bar WHERE code IN ({placeholders})",
                codes,
            )
        else:
            df = c.query_df("SELECT min(trade_date) AS d FROM daily_bar")
        if not df.empty and df.iloc[0]["d"] is not None:
            import pandas as pd

            start = pd.Timestamp(df.iloc[0]["d"]).date()
        else:
            start = end - timedelta(days=365 * 5)
    result = IngestionService().ingest_date(
        start=start, end=end, codes=codes, ctx=CliTaskContext(),
        concurrency=getattr(args, "concurrency", None))
    print(f"日线重拉完成: {result}")
    return 0


def cmd_seed_presets(args: argparse.Namespace) -> int:
    from backend.screening.profile import ProfileRepo

    n = ProfileRepo().seed_presets()
    print(f"内置预设方案入库: {n} 个")
    return 0


def cmd_migrate_rbac(args: argparse.Namespace) -> int:
    """存量资产 DuckDB→PG 迁移（stage1·T3）。默认 dry-run；--apply 实迁。"""
    from backend.services.migrate_rbac import migrate_rbac

    dry = not getattr(args, "apply", False)
    report = migrate_rbac(dry_run=dry)
    print(f"=== 存量迁移 {'DRY-RUN（仅预演，未写入）' if dry else 'APPLY（已写入 PG）'} ===")
    print(f"{'表':<24}{'DuckDB源':>10}{'已迁':>8}{'PG(default)后':>14}")
    ok = True
    all_problems: list[str] = []
    for t, r in report.items():
        after = r.get("pg_after", "-")
        probs = r.get("problems") or []
        all_problems += probs
        # app_config 平台表走 DO NOTHING 合并语义，行数可不等于源（UI 可后置改），不按行数判错
        count_bad = (not dry and t != "app_config" and after not in ("-", r["duck"]))
        bad = bool(probs) or count_bad
        if bad:
            ok = False
        flag = "  ⚠" + ("/".join(["映射" if probs else "", "行数不一致" if count_bad else ""]).strip("/")) if bad else ""
        print(f"{t:<24}{r['duck']:>10}{r['migrated']:>8}{str(after):>14}{flag}")
    if all_problems:
        print("\n校验问题：")
        for p in all_problems:
            print(f"  - {p}")
    if dry:
        print(f"\n预演{'通过，可加 --apply 实际迁移。' if ok else '发现问题（见上），修复后再迁。'}")
    else:
        print(f"\n迁移{'完成，字段映射/行数/归属非空 全部核对一致 ✅' if ok else '完成但存在问题 ⚠ 请核查'}")
    return 0 if ok else 1


def cmd_screen(args: argparse.Namespace) -> int:
    from datetime import date

    from backend.services.screen_score import ScreenScoreService

    run_date = date.fromisoformat(args.date) if args.date else None
    svc = ScreenScoreService()
    if run_date is None:
        from backend.storage import get_client
        d = get_client().query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]
        import pandas as pd
        run_date = pd.Timestamp(d).date()
    hits = svc.run_profile(args.profile, run_date)
    print(f"方案 {args.profile} @ {run_date} 命中 {len(hits)} 只: {hits[:20]}")
    return 0


def cmd_rank(args: argparse.Namespace) -> int:
    from datetime import date

    import pandas as pd

    from backend.services.screen_score import ScreenScoreService
    from backend.storage import get_client

    if args.date:
        run_date = date.fromisoformat(args.date)
    else:
        d = get_client().query_df("SELECT max(trade_date) AS d FROM daily_bar").iloc[0]["d"]
        run_date = pd.Timestamp(d).date()
    svc = ScreenScoreService()
    board = svc.rank_board(run_date, top_n=args.top, with_signals=True)
    cols = ["rank", "code", "total_score", "grade"]
    print(f"=== 每日榜单 Top {args.top} @ {run_date} ===")
    print(board[cols].to_string(index=False))
    return 0


def cmd_indicators(args: argparse.Namespace) -> int:
    # v2.0：指标已改为动态实时计算（无 indicator 落库表），不再需要预计算步骤。
    print("v2.0：技术指标已动态实时计算，无需预计算落库；此命令已无操作。")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    import json

    from backend.services.backtest_service import BacktestService

    params: dict = {"date_start": args.start, "date_end": args.end}
    if args.profile:
        params["profile_id"] = args.profile
    if args.top:
        params["top_n"] = args.top
    svc = BacktestService()
    if args.kind == "signal":
        r = svc.run_signal(params, persist=not args.no_persist)
        print(f"=== 信号质量分析 {args.start}~{args.end} (run={r.get('run_id')}) ===")
        print(f"总信号 {r.get('total_signals')}，base_rate: ", end="")
        print({k: v["hit_rate"] for k, v in r.get("base_rate", {}).items()})
        for g in r.get("grades_order", []):
            e = r["by_grade"][g]
            line = f"  {g}: n={e['n_signals']}"
            for key in [k for k in e if k.startswith("N")]:
                c = e[key]
                line += f" | {key} hit={c['hit_rate']} 超额={c['excess']}(n={c['n']})"
            print(line)
    else:
        r = svc.run_strategy(params, persist=not args.no_persist)
        if "error" in r:
            print(f"回测失败: {r['error']}")
            return 1
        m = r["metrics"]
        print(f"=== 策略回测 {args.start}~{args.end} (run={r['run_id']}) ===")
        print(json.dumps(m, ensure_ascii=False, indent=1))
    return 0


def cmd_daily(args: argparse.Namespace) -> int:
    from backend.services.pipeline import DailyPipeline

    res = DailyPipeline().run(skip_update=args.skip_update, verify=args.verify)
    print(f"=== 一键日常流程 {'✓' if res['ok'] else '✗'}  run_date={res.get('run_date','-')} ===")
    for s in res["steps"]:
        mark = "✓" if s["status"] == "ok" else "✗"
        print(f"  {mark} {s['step']:14s} {s['secs']:6.1f}s  {s['detail']}")
    return 0 if res["ok"] else 1


def cmd_robust(args: argparse.Namespace) -> int:
    import json

    from backend.backtest.robustness import RobustnessAnalyzer
    ra = RobustnessAnalyzer()
    base = {"date_start": args.start, "date_end": args.end, "top_n": args.top}
    if args.profile:
        base["profile_id"] = args.profile
    print(f"=== 稳健性测试 {args.start}~{args.end} ===")
    if args.param and args.values:
        vals = [int(v) if v.isdigit() else float(v) for v in args.values.split(",")]
        res = ra.param_sweep(base, args.param, vals)
        print(f"--- 参数敏感性: {args.param} ---")
        for r in res["rows"]:
            print(f"  {args.param}={r['value']}: 收益{r['total_return']:+.1%} 超额{r['excess_return']:+.1%} "
                  f"夏普{r['sharpe']} 回撤{r['max_drawdown']:.1%} 胜率{r['win_rate']:.0%} 交易{r['n_trades']}")
    if args.split:
        io = ra.in_out_sample(base, args.split)
        for k in ("in_sample", "out_sample"):
            s = io[k]
            print(f"  {k} {s['range'][0]}~{s['range'][1]}: 收益{s['total_return']:+.1%} 超额{s['excess_return']:+.1%} 夏普{s['sharpe']}")
    return 0


def cmd_check_data(args: argparse.Namespace) -> int:
    from datetime import date

    from backend.config import get_settings
    from backend.services.data_report import DataIntegrityReport

    s = get_settings()
    end = date.today()
    start = date(end.year - s.datasource.history_years, end.month, end.day)
    DataIntegrityReport().run(start, end)
    return 0


def cmd_verify_data(args: argparse.Namespace) -> int:
    from backend.services.data_verify import DataVerifier

    ok = DataVerifier().run(cross=not args.no_cross)
    return 0 if ok else 1


def cmd_delisted(args: argparse.Namespace) -> int:
    from backend.services import IngestionService

    svc = IngestionService()
    if args.enrich:
        n = svc.enrich_basic_dates()
        print(f"baostock 补全上市/退市日: {n} 只")
    result = svc.ingest_delisted(years=args.years, limit=args.limit)
    print(f"退市股灌入完成: {result}")
    return 0


def cmd_purge_suspension_bars(args: argparse.Namespace) -> int:
    """清理误插入 daily_bar 的停牌日行（volume=0：停牌无成交，却被兜底源写成"直线"行情）。

    默认仅预览（dry-run）；--apply 才执行：先把这些 (code, trade_date) 记入 stock_suspension
    （收敛，质检不再反复上报），再从 daily_bar 与 daily_metrics 删除。
    ⚠️ 写操作需独占库——先停掉占用 data/ai_stocks.duckdb 的服务再跑。
    """
    from datetime import datetime

    from backend.storage import get_client

    c = get_client()
    cond = "(volume = 0 OR volume IS NULL)"
    s = c.query_df(
        f"SELECT count(*) AS rows, count(DISTINCT code) AS codes, "
        f"min(trade_date) AS d0, max(trade_date) AS d1 FROM daily_bar WHERE {cond}").iloc[0]
    n = int(s["rows"])
    if n == 0:
        print("未发现 volume=0 的停牌日行，daily_bar 已干净。")
        return 0
    print(f"待清理停牌日行：{n} 行，涉及 {int(s['codes'])} 只股票，日期 {s['d0']} ~ {s['d1']}")
    print("样例（前 10 行，应都是 volume=0 的平板行）：")
    print(c.query_df(
        f"SELECT code, trade_date, open, high, low, close, volume "
        f"FROM daily_bar WHERE {cond} ORDER BY code, trade_date LIMIT 10").to_string(index=False))
    if not args.apply:
        print("\n[dry-run] 未做任何改动。确认无误后加 --apply 执行（记入 stock_suspension 并删除）。")
        return 0
    # 1) 记入 stock_suspension（仅写库中尚无的，去重）——删除前先记，保证收敛
    c.execute(
        "INSERT INTO stock_suspension (code, trade_date, confirmed_at) "
        f"SELECT DISTINCT b.code, b.trade_date, ? FROM daily_bar b WHERE {cond} "
        "AND NOT EXISTS (SELECT 1 FROM stock_suspension s "
        "WHERE s.code = b.code AND s.trade_date = b.trade_date)", [datetime.now()])
    # 2) 删对应 daily_metrics（停牌日的衍生市值同样无意义）——须在删 daily_bar 之前
    c.execute(
        "DELETE FROM daily_metrics WHERE EXISTS (SELECT 1 FROM daily_bar b "
        "WHERE b.code = daily_metrics.code AND b.trade_date = daily_metrics.trade_date "
        "AND (b.volume = 0 OR b.volume IS NULL))")
    # 3) 删 daily_bar 停牌日行
    c.execute(f"DELETE FROM daily_bar WHERE {cond}")
    print(f"已完成：记入 stock_suspension 并从 daily_bar/daily_metrics 删除 {n} 行停牌日数据。")
    print("建议随后在应用「任务中心」跑一次『刷新评分缓存』(recompute)，让受影响榜单/方案下次自动重算；"
          "若关心指标，可对受影响股重算指标。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-stocks", description="A股趋势龙头选股系统 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="启动 Web 服务")
    p_serve.add_argument("--reload", action="store_true", help="开发期热重载：改后端 .py 自动重启 worker")
    p_serve.add_argument("--host", help="覆盖监听地址（默认取 config.server.host；dev 建议 127.0.0.1，prod 用 0.0.0.0）")
    p_serve.set_defaults(func=cmd_serve)
    sub.add_parser("health", help="本地自检").set_defaults(func=cmd_health)

    p_bf = sub.add_parser("backfill", help="全量回填数据（M1）")
    p_bf.add_argument("--codes", help="逗号分隔的代码子集（如 600000.SH,000001.SZ）")
    p_bf.add_argument("--limit", type=int, help="只取列表前 N 只（小批量验证）")
    p_bf.add_argument("--years", type=int, default=None, help="历史年数（默认按配置 5 年）")
    p_bf.add_argument("--concurrency", type=int, default=None, help="并发线程数（默认 1 串行；>1 提速但总速率≈N×限流）")
    p_bf.set_defaults(func=cmd_backfill)

    p_up = sub.add_parser("update", help="增量更新数据（M1）")
    p_up.add_argument("--codes", help="逗号分隔的代码子集")
    p_up.add_argument("--limit", type=int, help="只取列表前 N 只")
    p_up.add_argument("--concurrency", type=int, default=None, help="并发线程数（提速；默认按配置；注意源封禁风险）")
    p_up.set_defaults(func=cmd_update)

    p_dl = sub.add_parser("delisted", help="灌入退市股历史（baostock，防幸存者偏差）")
    p_dl.add_argument("--enrich", action="store_true", help="同时用 baostock 补全全市场上市/退市日")
    p_dl.add_argument("--limit", type=int, help="只灌前 N 只退市股（小批量验证）")
    p_dl.add_argument("--years", type=int, default=None, help="历史年数（默认按配置 5 年）")
    p_dl.set_defaults(func=cmd_delisted)

    p_val = sub.add_parser("valuation", help="补每日总市值/总股本（stock_value_em）")
    p_val.add_argument("--codes", help="逗号分隔代码子集")
    p_val.add_argument("--limit", type=int, help="只取前 N 只")
    p_val.add_argument("--years", type=int, default=None, help="历史年数（默认配置5年）")
    p_val.add_argument("--concurrency", type=int, default=None, help="并发线程数（默认 1 串行；>1 提速但总速率≈N×限流）")
    p_val.add_argument("--fill-gaps", action="store_true", dest="fill_gaps",
                       help="一次性历史回补：补在市股 total_mv 缺口（逐缺口驱动，不受整股断点跳过限制）")
    p_val.set_defaults(func=cmd_valuation)

    p_pf = sub.add_parser("rebuild-price-factors", help="全序列重算 adj_factor_clean/pre_close/涨跌停标记（不联网，不改源 adj_factor）")
    p_pf.add_argument("--codes", help="逗号分隔代码子集")
    p_pf.add_argument("--limit", type=int, help="只取列表前 N 只")
    p_pf.set_defaults(func=cmd_rebuild_price_factors)

    p_rf = sub.add_parser("refetch-daily", help="重新联网拉取日线并覆盖入库（恢复源 adj_factor）")
    p_rf.add_argument("--codes", help="逗号分隔代码子集")
    p_rf.add_argument("--limit", type=int, help="只取列表前 N 只")
    p_rf.add_argument("--start", help="开始日 YYYY-MM-DD（默认取目标股票已入库最早日）")
    p_rf.add_argument("--end", help="结束日 YYYY-MM-DD（默认今天）")
    p_rf.add_argument("--concurrency", type=int, help="并发线程数（默认 1 串行；>1 提速但总请求速率≈N×限流）")
    p_rf.set_defaults(func=cmd_refetch_daily)

    p_ind = sub.add_parser("indicators", help="计算全市场指标（M2）")
    p_ind.add_argument("--codes", help="逗号分隔代码子集")
    p_ind.add_argument("--limit", type=int, help="只取前 N 只")
    p_ind.add_argument("--incremental", action="store_true", help="增量：只算新增交易日（params 不变时用，省时）")
    p_ind.set_defaults(func=cmd_indicators)

    sub.add_parser("seed-presets", help="内置预设筛选方案入库（M3）").set_defaults(func=cmd_seed_presets)

    p_scr = sub.add_parser("screen", help="对某交易日运行筛选方案（M3）")
    p_scr.add_argument("profile", help="方案 id，如 preset_trend_leader")
    p_scr.add_argument("--date", help="交易日 YYYY-MM-DD（默认最新）")
    p_scr.set_defaults(func=cmd_screen)

    p_rk = sub.add_parser("rank", help="打分排序出每日 Top N 榜单（M3）")
    p_rk.add_argument("--date", help="交易日 YYYY-MM-DD（默认最新）")
    p_rk.add_argument("--top", type=int, default=20, help="Top N")
    p_rk.set_defaults(func=cmd_rank)

    p_rb = sub.add_parser("robust", help="稳健性测试（M7）：参数敏感性 / 样本内外")
    p_rb.add_argument("--start", required=True, help="开始日 YYYY-MM-DD")
    p_rb.add_argument("--end", required=True, help="结束日 YYYY-MM-DD")
    p_rb.add_argument("--profile", help="选股方案 id")
    p_rb.add_argument("--top", type=int, default=10, help="Top N 持仓")
    p_rb.add_argument("--param", help="敏感性扫描的参数名，如 top_n / sell_ma_period")
    p_rb.add_argument("--values", help="逗号分隔取值，如 5,10,20")
    p_rb.add_argument("--split", help="样本内外切分日 YYYY-MM-DD")
    p_rb.set_defaults(func=cmd_robust)

    sub.add_parser("check-data", help="数据完整性体检报告（M1）").set_defaults(func=cmd_check_data)

    p_vf = sub.add_parser("verify-data", help="数据正确性+完整性系统性核查（M1）")
    p_vf.add_argument("--no-cross", action="store_true", help="跳过独立数据源交叉验证（不联网）")
    p_vf.set_defaults(func=cmd_verify_data)
    p_daily = sub.add_parser("daily", help="一键日常流程：更新行情(含补市值)→数据质检→（可选）数据体检")
    p_daily.add_argument("--skip-update", action="store_true", help="跳过增量更新（数据已最新时，最省时）")
    p_daily.add_argument("--verify", action="store_true", help="末尾跑数据体检")
    p_daily.set_defaults(func=cmd_daily)

    p_bt = sub.add_parser("backtest", help="运行回测（M5）：信号质量分析 / 完整策略回测")
    p_bt.add_argument("--kind", choices=["signal", "strategy"], default="strategy", help="回测类型")
    p_bt.add_argument("--start", required=True, help="开始日 YYYY-MM-DD")
    p_bt.add_argument("--end", required=True, help="结束日 YYYY-MM-DD")
    p_bt.add_argument("--profile", help="选股方案 id（限制候选，仅 strategy）")
    p_bt.add_argument("--top", type=int, help="Top N 持仓")
    p_bt.add_argument("--no-persist", action="store_true", help="不落库（只算不存）")
    p_bt.set_defaults(func=cmd_backtest)

    p_purge = sub.add_parser(
        "purge-suspension-bars",
        help="清理误插入 daily_bar 的停牌日行(volume=0)：默认预览，--apply 才执行")
    p_purge.add_argument("--apply", action="store_true",
                         help="确认执行（默认仅 dry-run 预览，不改数据）")
    p_purge.set_defaults(func=cmd_purge_suspension_bars)

    p_mig = sub.add_parser(
        "migrate-rbac",
        help="存量资产 DuckDB→PG 迁移（多租户 stage1·T3）：默认 dry-run 预演，--apply 实迁")
    p_mig.add_argument("--apply", action="store_true",
                       help="确认执行实际迁移（默认仅预演，不写入 PG）")
    p_mig.set_defaults(func=cmd_migrate_rbac)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
