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

from backend.common.logging import get_logger
from backend.config import get_settings

log = get_logger("cli")


def cmd_serve(_: argparse.Namespace) -> int:
    import uvicorn

    s = get_settings()
    log.info("启动服务 http://%s:%s", s.server.host, s.server.port)
    uvicorn.run(
        "backend.main:app", host=s.server.host, port=s.server.port, log_level=s.server.log_level
    )
    return 0


def cmd_health(_: argparse.Namespace) -> int:
    s = get_settings()
    log.info("配置加载成功：history_years=%s, db=%s", s.datasource.history_years, s.duckdb_path())
    from backend.storage import get_client

    client = get_client()
    version = client.query_df("SELECT version() AS v").iloc[0]["v"]
    log.info("DuckDB 连通：%s @ %s", version, client.db_path)
    print("OK: 配置与 DuckDB 自检通过")
    return 0


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
    result = IngestionService().backfill(codes=codes, years=args.years)
    print(f"回填完成: {result}")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    from backend.services import IngestionService

    codes = _resolve_codes(args)
    result = IngestionService().update(codes=codes, concurrency=args.concurrency)
    print(f"增量更新完成: {result}")
    return 0


def cmd_valuation(args: argparse.Namespace) -> int:
    from backend.services import IngestionService

    codes = _resolve_codes(args)
    result = IngestionService().ingest_valuation(codes=codes, years=args.years)
    print(f"估值入库完成: {result}")
    return 0


def cmd_seed_presets(args: argparse.Namespace) -> int:
    from backend.screening.profile import ProfileRepo

    n = ProfileRepo().seed_presets()
    print(f"内置预设方案入库: {n} 个")
    return 0


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

    res = DailyPipeline().run(skip_update=args.skip_update,
                              presets=not args.no_presets, verify=args.verify)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-stocks", description="A股趋势龙头选股系统 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="启动 Web 服务").set_defaults(func=cmd_serve)
    sub.add_parser("health", help="本地自检").set_defaults(func=cmd_health)

    p_bf = sub.add_parser("backfill", help="全量回填数据（M1）")
    p_bf.add_argument("--codes", help="逗号分隔的代码子集（如 600000.SH,000001.SZ）")
    p_bf.add_argument("--limit", type=int, help="只取列表前 N 只（小批量验证）")
    p_bf.add_argument("--years", type=int, default=None, help="历史年数（默认按配置 5 年）")
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
    p_val.set_defaults(func=cmd_valuation)

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
    p_daily = sub.add_parser("daily", help="一键日常流程：更新→指标→榜单→预设筛选→（可选）数据体检")
    p_daily.add_argument("--skip-update", action="store_true", help="跳过增量更新（数据已最新时，最省时）")
    p_daily.add_argument("--no-presets", action="store_true", help="不跑预设筛选")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
