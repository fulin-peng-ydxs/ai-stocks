"""命令行入口（SDD §14：便于手动跑与初始化）。

用法：
    python -m backend.cli serve          启动 Web 服务
    python -m backend.cli health         本地自检（配置 + DuckDB 连通）
    python -m backend.cli backfill       全量回填数据（M1 实现）
    python -m backend.cli update         增量更新数据（M1 实现）
    python -m backend.cli daily          一键日常流程（M7 实现）
    python -m backend.cli public-board   生产公共预设榜单快照
    python -m backend.cli backtest       运行回测（M5 实现）

M0 阶段仅 serve / health 可用，其余为占位（后续里程碑补全）。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from backend.common.logging import get_logger
from backend.common.timeutil import years_before
from backend.config import get_settings, get_effective_settings

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


def cmd_audit_cleanup(_: argparse.Namespace) -> int:
    """人工触发审计日志保留期清理。"""
    from backend.services.audit_service import AuditService

    result = AuditService().cleanup_expired()
    print(
        "审计日志清理结果："
        f"ok={result.get('ok')} "
        f"skipped={result.get('skipped')} "
        f"retention_days={result.get('retention_days')} "
        f"cutoff={result.get('cutoff')} "
        f"affected_count={result.get('affected_count')} "
        f"reason={result.get('reason')}"
    )
    return 0 if result.get("ok") else 1


def cmd_trade_discipline_rbac(args: argparse.Namespace) -> int:
    """受控回滚交易纪律 RBAC；确认串必须与稳定 marker 完全一致。"""
    import json

    from backend.storage.pg_ddl import (
        TRADE_DISCIPLINE_RBAC_MARKER,
        _rollback_trade_discipline_rbac,
    )

    if args.confirm_marker != TRADE_DISCIPLINE_RBAC_MARKER:
        print(
            "拒绝执行：--confirm-marker 必须完全等于 "
            f"{TRADE_DISCIPLINE_RBAC_MARKER}",
            file=sys.stderr,
        )
        return 2
    try:
        report = _rollback_trade_discipline_rbac()
    except Exception as exc:  # 存储层会把事务内拒绝包装成 StorageError
        print(f"交易纪律 RBAC 回滚失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


def cmd_trade_discipline_reset(args: argparse.Namespace) -> int:
    """一次性私人交易纪律重置，默认只读预检，不通过启动 seed 执行。"""
    import json
    import subprocess
    from datetime import date
    from pathlib import Path

    from backend.common.exceptions import AIStocksError
    from backend.devtools.trade_discipline_reset import reset_history
    from backend.services.trade_discipline_service import TradeDisciplineService

    try:
        target = date.fromisoformat(args.effective_date)
        TradeDisciplineService()._require_trade_date(target)
        report = reset_history(
            apply=args.apply, expected_fingerprint=args.expected_pg_fingerprint,
            effective_date=target,
            backup_path=Path(args.backup_path) if args.backup_path else None,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (AIStocksError, RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"交易纪律重置未完成：{exc}", file=sys.stderr)
        return 1


def cmd_task_runtime_storage(args: argparse.Namespace) -> int:
    """Inspect, migrate, or explicitly roll back task runtime storage."""
    import json

    from backend.storage.task_runtime import TASK_RUNTIME_MIGRATION_MARKER
    from backend.storage.task_runtime_migration import (
        inspect_task_runtime_migration,
        migrate_task_runtime_to_postgres,
        rollback_task_runtime_to_duckdb,
    )

    try:
        if args.task_runtime_action == "status":
            report = inspect_task_runtime_migration()
        elif args.task_runtime_action == "migrate":
            report = (
                migrate_task_runtime_to_postgres()
                if args.apply
                else inspect_task_runtime_migration()
            )
            if not args.apply:
                report["dry_run"] = True
        else:
            report = rollback_task_runtime_to_duckdb(
                confirm_marker=args.confirm_marker,
            )
    except Exception as exc:  # noqa: BLE001 -- CLI converts storage failures to a stable exit code
        print(f"任务运行态存储操作失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, default=str))
    if args.task_runtime_action == "migrate" and not args.apply:
        print("[dry-run] 未写入；确认停服且报告无误后追加 --apply。")
    if args.task_runtime_action == "rollback":
        print(f"已按确认标记 {TASK_RUNTIME_MIGRATION_MARKER} 回滚到 DuckDB。")
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
            start = years_before(end, get_effective_settings().datasource.history_years)
    result = IngestionService().ingest_date(
        start=start, end=end, codes=codes, ctx=CliTaskContext(),
        concurrency=getattr(args, "concurrency", None))
    print(f"日线重拉完成: {result}")
    return 0


def cmd_seed_presets(args: argparse.Namespace) -> int:
    from backend.scoring.score_profile import ScoreProfileRepo
    from backend.screening.profile import ProfileRepo
    from backend.signals.trade_profile import TradeProfileRepo
    from backend.storage import get_client
    from backend.storage.pg_client import get_pg_client
    from backend.storage.pg_ddl import PUBLIC_BOARD_OWNER

    tenant_id, owner_user_id = PUBLIC_BOARD_OWNER
    pg = get_pg_client()
    market = get_client()
    counts = {
        "筛选": ProfileRepo(
            pg=pg, tenant_id=tenant_id, owner_user_id=owner_user_id).seed_presets(),
        "评分": ScoreProfileRepo(
            market=market, pg=pg, tenant_id=tenant_id, owner_user_id=owner_user_id).seed_defaults(),
        "买卖": TradeProfileRepo(
            market=market, pg=pg, tenant_id=tenant_id, owner_user_id=owner_user_id).seed_defaults(),
    }
    summary = "，".join(f"{kind} {count} 个" for kind, count in counts.items())
    print(f"系统内置方案入库: {summary}")
    return 0


def cmd_migrate_rbac(args: argparse.Namespace) -> int:
    """存量资产 DuckDB→PG 迁移（stage1·T3）。默认 dry-run；--apply 实迁；--recreate 重建旧 schema。"""
    from backend.services.migrate_rbac import migrate_rbac

    dry = not getattr(args, "apply", False)
    report = migrate_rbac(dry_run=dry, recreate=getattr(args, "recreate", False))
    glob = report.pop("_global", {}).get("problems", [])   # 全局问题(主键失配/外键孤儿)单列
    print(f"=== 存量迁移 {'DRY-RUN（仅预演，未写入）' if dry else 'APPLY（已写入 PG）'} ===")
    print(f"{'表':<24}{'DuckDB源':>10}{'已迁':>8}{'PG(default)后':>14}")
    ok = not glob
    all_problems: list[str] = list(glob)
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
        print(f"\n迁移{'完成，字段映射/行数/归属非空/外键完整 全部核对一致 ✅' if ok else '完成但存在问题 ⚠ 请核查'}")
    return 0 if ok else 1


def cmd_migrate_config_storage(args: argparse.Namespace) -> int:
    """配置存储 DuckDB→PG 迁移。默认实迁；--dry-run 只预演。"""
    from backend.services.migrate_config_storage import migrate_config_storage

    dry = bool(getattr(args, "dry_run", False))
    force = bool(getattr(args, "force", False))
    report = migrate_config_storage(dry_run=dry, force=force)
    glob = report.get("_global", {})
    print(f"=== 配置存储迁移 {'DRY-RUN（未写入）' if dry else 'APPLY（写入 PG）'} ===")
    print(
        f"marker={glob.get('marker')} "
        f"exists_before={glob.get('marker_exists')} "
        f"skipped={glob.get('skipped')} "
        f"force={glob.get('force')}"
    )
    print(f"{'表':<24}{'DuckDB源':>10}{'PG前':>8}{'待新增':>8}{'冲突':>8}{'已写':>8}{'PG后':>8}")
    for table in ("layout_preset", "layout_page_config", "layout_field_policy", "app_config"):
        r = report[table]
        print(
            f"{table:<24}{r.get('duck', 0):>10}{r.get('pg_before', 0):>8}"
            f"{r.get('pending', 0):>8}{r.get('conflicts', 0):>8}{r.get('migrated', 0):>8}"
            f"{str(r.get('pg_after', '-')):>8}"
        )
        missing = r.get("missing_keys") or []
        conflicts = r.get("conflict_keys") or []
        print(f"  conflict_policy={r.get('conflict_policy')}")
        if missing:
            print(f"  pending_keys={', '.join(missing[:20])}{' ...' if len(missing) > 20 else ''}")
        if conflicts:
            print(f"  conflict_keys={', '.join(conflicts[:20])}{' ...' if len(conflicts) > 20 else ''}")
    problems = glob.get("problems") or []
    if problems:
        print("\n问题：")
        for problem in problems:
            print(f"  - {problem}")
    if glob.get("skipped"):
        print("\n已跳过：PG marker 已存在；如需重跑请加 --force。")
    elif dry:
        print("\n预演完成；不加 --dry-run 将执行实际迁移。")
    else:
        print("\n迁移完成。")
    return 1 if problems else 0


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


def cmd_public_board(args: argparse.Namespace) -> int:
    from datetime import date

    from backend.services.public_board import produce_public_board_snapshots

    run_date = date.fromisoformat(args.date) if args.date else None
    profile_ids = [x.strip() for x in args.profile_ids.split(",") if x.strip()] if args.profile_ids else None
    res = produce_public_board_snapshots(run_date=run_date, profile_ids=profile_ids)
    print(f"=== 公共榜单生产 @ {res.get('run_date') or '-'} ===")
    print(f"方案数: {res.get('profile_count', 0)}，明细行: {res.get('total_rows', 0)}")
    for p in res.get("profiles", []):
        print(f"  - {p['profile_id']} v{p['version']}: {p['rows']} 行")
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

    res = DailyPipeline().run(skip_update=args.skip_update, verify=args.verify,
                              board=not args.skip_board)
    print(f"=== 一键日常流程 {'✓' if res['ok'] else '✗'}  run_date={res.get('run_date','-')} ===")
    for s in res["steps"]:
        mark = "✓" if s["status"] == "ok" else "✗"
        print(f"  {mark} {s['step']:14s} {s['secs']:6.1f}s  {s['detail']}")
    return 0 if res["ok"] else 1


def cmd_board(args: argparse.Namespace) -> int:
    """板块采集 CLI（板块概念需求 R21）：--backfill/--update + 分表（--dict/--members/--bar/--fund）+ 子集（--codes/--limit）。"""
    from backend.services.ingest import IngestionService

    mode = "backfill" if args.backfill else "update"
    # 分表选择：显式指定则只跑指定表；否则全量
    only = [name for name, flag in
            (("dict", args.only_dict), ("members", args.only_members),
             ("bar", args.only_bar), ("fund", args.only_fund)) if flag]
    only = only or None
    codes = [x.strip() for x in args.codes.split(",") if x.strip()] if args.codes else None
    svc = IngestionService()
    ingest_kwargs: dict = {
        "ctx": CliTaskContext(), "board_type": args.board_type,
        "board_codes": codes, "only": only, "limit": args.limit,
        "date_start": args.start, "date_end": args.end,
    }
    # 仅显式 --force-members 时传 True；否则不传（None 由 ingest_board 按 mode/board_codes 自动解析，
    # 避免 CLI 指定板块重采被周频跳过挡住）
    if args.force_members:
        ingest_kwargs["force_members"] = True
    res = svc.ingest_board(mode=mode, **ingest_kwargs)
    failed = res.get("failed") or []
    scope = f" only={only}" if only else ""
    print(f"=== 板块采集（{mode}{scope}）{'✓' if not failed else '✗'} ===")
    print(f"  字典: {res.get('dict')}")
    print(f"  成分快照: {len(res.get('members', {}))} 个板块")
    skipped = sum(1 for r in res.get('members', {}).values() if r.get('skipped'))
    if skipped:
        print(f"    跳过未到期板块: {skipped} 个（周频控制，--force-members 可强制全量）")
    print(f"  指数: {res.get('bar')}")
    print(f"  资金流: {res.get('fund_flow')}")
    if failed:
        print(f"  失败项: {failed}")
    return 0 if not failed else 1


def cmd_robust(args: argparse.Namespace) -> int:
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

    from backend.config import get_effective_settings
    from backend.services.data_report import DataIntegrityReport

    s = get_effective_settings()
    end = date.today()
    start = years_before(end, s.datasource.history_years)
    DataIntegrityReport().run(start, end)
    return 0


def cmd_verify_data(args: argparse.Namespace) -> int:
    from backend.services.data_verify import DataVerifier

    ok = DataVerifier().run(cross=not args.no_cross)
    return 0 if ok else 1


def cmd_verify_catalog(_: argparse.Namespace) -> int:
    """校验双库物理发现、业务元数据和字段说明契约。"""
    import json

    from backend.storage.catalog import (
        build_catalog_payload,
        catalog_contract_report,
    )

    try:
        payload = build_catalog_payload(database="all", include_legacy=True)
        report = catalog_contract_report(payload["tables"])
    except Exception as exc:  # noqa: BLE001 -- 任一数据库失败都必须 fail-closed
        print(f"数据资产目录校验失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["ok"] else 1


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
    """核验零成交量候选；必须取得明确逐日停牌状态，才允许清理占位行情。

    默认仅预览；--apply 提交统一 fix 任务，保留删除前行情/市值记录。
    ⚠️ 写操作需独占库——先停掉占用 data/ai_stocks.duckdb 的服务再跑。
    """
    from backend.storage import get_client

    c = get_client()
    cond = "(volume = 0 OR volume IS NULL)"
    s = c.query_df(
        f"SELECT count(*) AS rows, count(DISTINCT code) AS codes, "
        f"min(trade_date) AS d0, max(trade_date) AS d1 FROM daily_bar WHERE {cond}").iloc[0]
    n = int(s["rows"])
    if n == 0:
        print("未发现零成交量/未知成交量候选行。")
        return 0
    print(f"待核验零成交量行：{n} 行，涉及 {int(s['codes'])} 只股票，日期 {s['d0']} ~ {s['d1']}")
    print("待核验样例（前 10 行，尚不能认定停牌）：")
    print(c.query_df(
        f"SELECT code, trade_date, open, high, low, close, volume "
        f"FROM daily_bar WHERE {cond} ORDER BY code, trade_date LIMIT 10").to_string(index=False))
    if not args.apply:
        print("\n[dry-run] 未做任何改动。加 --apply 提交逐日交易状态核验任务，只有证实停牌才清理。")
        return 0
    # 使用同一异步写任务入口，禁止零量直接转停牌或删除行情。
    from backend.services.async_task import AsyncTaskService
    import time
    service = AsyncTaskService()
    task_id = service.create("fix", {"review_suspensions": True, "purge_candidates": True})
    print(f"已提交停牌证据核验任务：{task_id}")
    while True:
        task = service.get(task_id)
        if task["status"] not in ("pending", "running"):
            print(task.get("message"))
            return 0 if task["status"] == "done" and task.get("result", {}).get("ok", False) else 1
        time.sleep(0.5)

    return 0


def cmd_dev_users(args: argparse.Namespace) -> int:
    """创建/查看本地 RBAC 调试用户。"""
    from backend.devtools.environment_guard import require_local_test_environment
    from backend.devtools.rbac_test_users import ensure_debug_users, list_debug_users

    require_local_test_environment()
    if getattr(args, "list", False) and not getattr(args, "ensure", False):
        rows = list_debug_users()
        if not rows:
            print("未找到 RBAC 调试用户；执行 ./start.sh dev-users 创建。")
            return 0
        print("=== RBAC 调试用户 ===")
        for r in rows:
            print(f"{r['account']:<24} tenant={r['tenant_id']:<14} "
                  f"role_code={r['role_code']:<13} status={r['status']:<8} "
                  f"roles={','.join(r['roles'])}")
        return 0

    res = ensure_debug_users(
        reset_password=not getattr(args, "keep_password", False),
        expected_pg_fingerprint=getattr(args, "expected_pg_fingerprint", None),
    )
    print(f"RBAC 调试用户已创建/校准：tenant={res['tenant_id']}")
    print(f"密码来源：{res['password_source']}"
          f"{'，本次统一密码=' + res['password'] if res['password_source'] == 'local-default' else ''}")
    print("账号：")
    for account in res["users"]:
        print(f"  - {account}")
    if getattr(args, "list", False):
        print("")
        return cmd_dev_users(argparse.Namespace(list=True, ensure=False))
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
    p_bf.add_argument("--years", type=int, default=None, help="历史年数（默认按生效配置）")
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
    p_dl.add_argument("--years", type=int, default=None, help="历史年数（默认按生效配置）")
    p_dl.set_defaults(func=cmd_delisted)

    p_val = sub.add_parser("valuation", help="补每日总市值/总股本（stock_value_em）")
    p_val.add_argument("--codes", help="逗号分隔代码子集")
    p_val.add_argument("--limit", type=int, help="只取前 N 只")
    p_val.add_argument("--years", type=int, default=None, help="历史年数（默认按生效配置）")
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

    sub.add_parser(
        "seed-presets", help="三类系统内置方案幂等入库并校准为公开"
    ).set_defaults(func=cmd_seed_presets)

    p_scr = sub.add_parser("screen", help="对某交易日运行筛选方案（M3）")
    p_scr.add_argument("profile", help="方案 id，如 preset_trend_leader")
    p_scr.add_argument("--date", help="交易日 YYYY-MM-DD（默认最新）")
    p_scr.set_defaults(func=cmd_screen)

    p_rk = sub.add_parser("rank", help="打分排序出每日 Top N 榜单（M3）")
    p_rk.add_argument("--date", help="交易日 YYYY-MM-DD（默认最新）")
    p_rk.add_argument("--top", type=int, default=20, help="Top N")
    p_rk.set_defaults(func=cmd_rank)

    p_pb = sub.add_parser("public-board", help="生产 PUBLIC_BOARD_OWNER 公共预设榜单快照")
    p_pb.add_argument("--date", help="交易日 YYYY-MM-DD（默认行情最新日）")
    p_pb.add_argument("--profile-ids", help="逗号分隔公共预设方案 id（默认全部公共预设）")
    p_pb.set_defaults(func=cmd_public_board)

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
    sub.add_parser(
        "verify-catalog",
        help="校验双库表发现、业务元数据、鲜活度/质量策略与字段说明",
    ).set_defaults(func=cmd_verify_catalog)
    p_daily = sub.add_parser("daily", help="一键日常流程：更新行情(含补市值)→板块采集→数据质检→（可选）数据体检")
    p_daily.add_argument("--skip-update", action="store_true", help="跳过增量更新（数据已最新时，最省时）")
    p_daily.add_argument("--skip-board", action="store_true", help="跳过板块采集步骤（板块独立于行情更新）")
    p_daily.add_argument("--verify", action="store_true", help="末尾跑数据体检")
    p_daily.set_defaults(func=cmd_daily)

    p_board = sub.add_parser("board", help="板块采集（板块概念）：全量回填/增量/分表")
    board_mode = p_board.add_mutually_exclusive_group()
    board_mode.add_argument("--backfill", action="store_true",
                            help="全量回填（指数历史 + 首次成分快照 + 资金流全周期）")
    board_mode.add_argument("--update", action="store_true", help="按板块最新水位增量续采（默认模式）")
    p_board.add_argument("--dict", action="store_true", dest="only_dict",
                         help="只采板块字典（board_dict）")
    p_board.add_argument("--members", action="store_true", dest="only_members",
                         help="只采成分快照（board_member，只进不出落库）")
    p_board.add_argument("--bar", action="store_true", dest="only_bar",
                         help="只采板块指数（board_bar）")
    p_board.add_argument("--fund", action="store_true", dest="only_fund",
                         help="只采板块资金流（board_fund_flow）")
    p_board.add_argument("--codes", help="逗号分隔板块代码子集（如 309121,881121）")
    p_board.add_argument("--type", dest="board_type", choices=("concept", "industry"),
                         help="只采概念或行业板块")
    p_board.add_argument("--limit", type=int, help="只取字典前 N 个板块（小批量验证）")
    p_board.add_argument("--start", help="指数采集开始日 YYYY-MM-DD（仅增量模式；留空按最新水位）")
    p_board.add_argument("--end", help="指数采集结束日 YYYY-MM-DD（留空=开始日）")
    p_board.add_argument("--force-members", action="store_true",
                         help="绕过成分周频跳过，强制全量拉成分快照（质量修复/手动补采用）")
    p_board.set_defaults(func=cmd_board)

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

    p_dev = sub.add_parser("dev-users", help="创建/查看本地 RBAC 调试用户（仅开发/测试库）")
    p_dev.add_argument("--ensure", action="store_true",
                       help="创建/校准调试用户（默认动作；可与 --list 组合）")
    p_dev.add_argument("--list", action="store_true", help="列出当前调试用户")
    p_dev.add_argument("--keep-password", action="store_true",
                       help="保留已有密码；仅为缺密码用户填充默认密码")
    p_dev.add_argument(
        "--expected-pg-fingerprint",
        help="写入前必须匹配的 64 位 PostgreSQL 指纹（E2E 物理写入口使用）",
    )
    p_dev.set_defaults(func=cmd_dev_users)

    sub.add_parser("audit-cleanup", help="按 audit.retention_days 清理超保留期审计日志").set_defaults(
        func=cmd_audit_cleanup
    )

    p_reset = sub.add_parser("trade-discipline-reset", help="全用户交易纪律历史重置，默认仅预检")
    p_reset.add_argument("--apply", action="store_true", help="执行已授权的全用户重置")
    p_reset.add_argument("--expected-pg-fingerprint", required=True, help="已核实目标的64位指纹")
    p_reset.add_argument("--effective-date", required=True, help="新v1规则的起算交易日")
    p_reset.add_argument("--backup-path", help="实际执行时必填的 pg_dump 备份路径")
    p_reset.set_defaults(func=cmd_trade_discipline_reset)

    p_td = sub.add_parser("trade-discipline-rbac", help="交易纪律 RBAC 受控运维")
    td_sub = p_td.add_subparsers(dest="trade_discipline_rbac_action", required=True)
    p_td_rollback = td_sub.add_parser("rollback", help="按迁移账本回滚菜单、资源和默认授权")
    p_td_rollback.add_argument(
        "--confirm-marker",
        required=True,
        help="必须精确传入 migration.trade_discipline_default_grants_v1",
    )
    p_td_rollback.set_defaults(func=cmd_trade_discipline_rbac)

    p_runtime = sub.add_parser(
        "task-runtime-storage",
        help="任务/日志/调度运行态 DuckDB→PostgreSQL 迁移与受控回滚",
    )
    runtime_sub = p_runtime.add_subparsers(dest="task_runtime_action", required=True)
    runtime_sub.add_parser("status", help="只读查看两端数量和迁移标记").set_defaults(
        func=cmd_task_runtime_storage
    )
    p_runtime_migrate = runtime_sub.add_parser(
        "migrate", help="迁移到 PostgreSQL；默认 dry-run"
    )
    p_runtime_migrate.add_argument(
        "--apply", action="store_true", help="确认在单事务中复制并写入激活标记"
    )
    p_runtime_migrate.set_defaults(func=cmd_task_runtime_storage)
    p_runtime_rollback = runtime_sub.add_parser(
        "rollback", help="用 PostgreSQL 全量替换 DuckDB 运行态表并切回"
    )
    p_runtime_rollback.add_argument(
        "--confirm-marker",
        required=True,
        help="必须精确传入 migration.task_runtime_pg_v1",
    )
    p_runtime_rollback.set_defaults(func=cmd_task_runtime_storage)

    p_mig = sub.add_parser(
        "migrate-rbac",
        help="存量资产 DuckDB→PG 迁移（多租户 stage1·T3）：默认 dry-run 预演，--apply 实迁")
    p_mig.add_argument("--apply", action="store_true",
                       help="确认执行实际迁移（默认仅预演，不写入 PG）")
    p_mig.add_argument("--recreate", action="store_true",
                       help="DROP+重建资产表后再迁（从旧单主键 schema 升级用；破坏性，配合 --apply）")
    p_mig.set_defaults(func=cmd_migrate_rbac)

    p_cfg = sub.add_parser(
        "migrate-config-storage",
        help="配置存储 DuckDB→PG 迁移：默认执行，--dry-run 仅预演")
    p_cfg.add_argument("--dry-run", action="store_true", dest="dry_run",
                       help="只输出迁移报告，不写入 PG")
    p_cfg.add_argument("--force", action="store_true",
                       help="即使 migration.config_storage_pg_v1 marker 已存在也重新执行")
    p_cfg.set_defaults(func=cmd_migrate_config_storage)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
