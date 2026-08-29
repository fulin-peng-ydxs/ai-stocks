#!/usr/bin/env bash
# ───────────────────────────────────────────────────────────────────────────
# ai-stocks 后端启动脚本
#
# 用法：
#   ./start.sh            开发模式启动（热重载：改 backend/*.py 自动重启 worker）
#   ./start.sh prod       生产模式启动（无热重载，开销更低、无瞬时 502）
#   ./start.sh stop       停止后端
#   ./start.sh restart    重启（开发模式）
#   ./start.sh status     查看运行状态
#   ./start.sh assert-idle  确认没有待执行/运行中的后台任务
#   ./start.sh stop-if-idle 仅在没有后台任务时停止后端
#   ./start.sh logs       跟踪日志（Ctrl-C 退出跟踪，不影响服务）
#   ./start.sh dev-users [参数]  在统一本机环境下维护调试账号
#   ./start.sh e2e-user [参数]   Playwright 临时用户内部入口
#   ./start.sh e2e-backtest-run [参数]  Playwright 公开回测内部入口
#   ./start.sh e2e-board-data seed|cleanup  Playwright 板块行情 DuckDB 夹具
#   ./start.sh e2e-stock-board-correlation seed|cleanup [参数]  走势关联板块 PG + DuckDB 夹具
#   ./start.sh e2e-trade-discipline seed|cleanup [参数]  交易纪律 PG + DuckDB 夹具
#
# 设计要点：
#   - 独立 session 脱离会话：AI 跑别的命令 / 终端关闭 / 对话结束都不会误杀（解决"老挂"）。
#   - dev 模式 --reload：源码改动自动热更，无需手动重启。
#   - 防重复启动：已在跑则直接退出，避免端口抢占。
#
# 前置依赖（多租户混合持久层 stage1 起）：PostgreSQL 与 Redis 须先运行，否则后端启动期
#   三库连通性自检失败、进程退出。本机：brew services start postgresql@16 redis。
#   连接参数见 config/settings.yaml(postgres/redis)，密码/密钥可写入 .env.local（已忽略 Git）。
# ───────────────────────────────────────────────────────────────────────────
set -euo pipefail

cd "$(dirname "$0")"

PY="${PYTHON:-python}"
LOG_DIR="logs"
LOG_FILE="$LOG_DIR/backend.log"
PID_FILE="$LOG_DIR/backend.pid"
RUNTIME_STATE_FILE="$LOG_DIR/backend-runtime.json"
PROC_PATTERN="backend.cli serve"
ENV_FILE_ARG="${AI_STOCKS_ENV_FILE:-.env.local}"

mkdir -p "$LOG_DIR"

# 本机敏感环境变量入口：后端服务、dev-users 与 E2E 临时用户统一消费这一加载函数，
# 避免直接 Python CLI 绕过 .env.local 后连接到另一套 PG。
# shellcheck disable=SC1091
source "scripts/load-local-env.sh"
load_project_local_env

# 是否有存活的后端进程；有则回显 PID
running_pid() {
  pgrep -f "$PROC_PATTERN" | head -1 || true
}

write_runtime_state() {
  local mode="$1"
  local pid="$2"
  umask 077
  "$PY" -m backend.devtools.backend_runtime_state write \
    --target "$RUNTIME_STATE_FILE" \
    --mode "$mode" \
    --pid "$pid" \
    --env-file "$ENV_FILE_ARG" \
    --python-command "$PY"
}

snapshot_runtime_state() {
  local target="${1:-}"
  local pid health_code
  pid="$(running_pid)"
  if [[ -z "$target" || -z "$pid" || ! -f "$RUNTIME_STATE_FILE" ]]; then
    echo "无法取得可信后端运行档案，拒绝停止现有服务" >&2
    return 1
  fi
  health_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 \
    http://127.0.0.1:8000/api/health 2>/dev/null)" || health_code="000"
  if [[ "$health_code" != "200" ]]; then
    echo "现有后端健康检查为 ${health_code}，拒绝快照并停止未知状态服务" >&2
    return 1
  fi
  "$PY" -m backend.devtools.backend_runtime_state snapshot \
    --source "$RUNTIME_STATE_FILE" \
    --target "$target" \
    --expected-pid "$pid"
}

restore_runtime_state() {
  local source="${1:-}"
  if [[ -z "$source" || ! -f "$source" ]]; then
    echo "缺少可信后端运行档案，拒绝猜测恢复模式" >&2
    return 1
  fi
  "$PY" -m backend.devtools.backend_runtime_state restore \
    --source "$source" \
    --start-script "$PWD/start.sh" \
    --runtime-file "$RUNTIME_STATE_FILE"
}

start() {
  local mode="$1"  # dev | prod
  local pid
  pid="$(running_pid)"
  if [[ -n "$pid" ]]; then
    echo "⚠️  后端已在运行 (PID $pid)，如需重启请先 ./start.sh stop 或用 ./start.sh restart"
    exit 0
  fi

  # prod 动作是不可绕过的安全边界：即使 .env.local 误写为 dev 或遗留 E2E 开关，
  # 子进程也强制标记 production 并移除物理测试写授权。
  if [[ "$mode" == "prod" ]]; then
    export AI_STOCKS_ENV="production"
    unset AI_STOCKS_E2E_WRITE
  fi

  # dev：热重载 + 绑 127.0.0.1（仅本机，外部走前端 5173 代理）；prod：绑 0.0.0.0（对外托管）。
  local args=("serve")
  if [[ "$mode" == "dev" ]]; then
    args+=("--reload" "--host" "127.0.0.1")
  else
    args+=("--host" "0.0.0.0")
  fi

  echo "🚀 启动后端（$mode 模式）…"
  rm -f "$RUNTIME_STATE_FILE"
  "$PY" - "$PY" "${args[@]}" "$LOG_FILE" <<'PY'
import os
import subprocess
import sys

py = sys.argv[1]
log_file = sys.argv[-1]
cli_args = sys.argv[2:-1]

log = open(log_file, "ab", buffering=0)
proc = subprocess.Popen(
    [py, "-m", "backend.cli", *cli_args],
    cwd=os.getcwd(),
    env=os.environ.copy(),
    stdin=subprocess.DEVNULL,
    stdout=log,
    stderr=subprocess.STDOUT,
    start_new_session=True,
    close_fds=True,
)
PY

  # 等待健康检查通过（最多 ~15s）
  local i
  for i in $(seq 1 15); do
    if curl -s -o /dev/null --max-time 2 http://127.0.0.1:8000/api/health 2>/dev/null; then
      pid="$(running_pid)"
      echo "$pid" > "$PID_FILE"
      if ! write_runtime_state "$mode" "$pid"; then
        echo "❌ 无法写入可信后端运行档案，停止本次服务" >&2
        stop
        return 1
      fi
      echo "✅ 已启动 (PID $pid) — http://127.0.0.1:8000  | 日志：$LOG_FILE"
      return 0
    fi
    sleep 1
  done

  echo "❌ 启动后健康检查未通过，请查看日志：$LOG_FILE"
  tail -20 "$LOG_FILE" || true
  exit 1
}

stop() {
  local pid pgid i
  pid="$(running_pid)"
  if [[ -z "$pid" ]]; then
    echo "ℹ️  后端未在运行"
    rm -f "$PID_FILE"
    rm -f "$RUNTIME_STATE_FILE"
    return 0
  fi
  echo "🛑 停止后端…"
  pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ' || true)"
  if [[ -n "$pgid" && "$pgid" == "$pid" ]]; then
    kill -TERM -- "-$pgid" 2>/dev/null || true
    for i in $(seq 1 20); do
      if ! kill -0 -- "-$pgid" 2>/dev/null; then
        break
      fi
      sleep 0.5
    done
    if kill -0 -- "-$pgid" 2>/dev/null; then
      echo "进程组未在 10 秒内退出，强制结束…"
      kill -KILL -- "-$pgid" 2>/dev/null || true
    fi
  else
    echo "无法确认后端独立进程组，仅终止已识别父进程 PID $pid" >&2
    kill -TERM "$pid" 2>/dev/null || true
    for i in $(seq 1 20); do
      if ! kill -0 "$pid" 2>/dev/null; then
        break
      fi
      sleep 0.5
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "后端父进程未在 10 秒内退出，强制结束…"
      kill -KILL "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$PID_FILE"
  rm -f "$RUNTIME_STATE_FILE"
  echo "✅ 已停止"
}

status() {
  local pid
  pid="$(running_pid)"
  if [[ -z "$pid" ]]; then
    echo "● 后端：未运行"
    return 0
  fi
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 \
    http://127.0.0.1:8000/api/health 2>/dev/null)" || code="000"
  if [[ "$code" == "200" ]]; then
    echo "● 后端：运行中 (PID $pid)  /api/health=200  端口 8000"
    return 0
  fi
  echo "● 后端：异常（进程存活但服务不可用，PID ${pid}）  /api/health=$code  端口 8000"
  return 1
}

assert_idle() {
  local body count
  if ! body="$(curl -fsS --max-time 3 http://127.0.0.1:8000/api/health 2>/dev/null)"; then
    echo "无法读取后端任务状态，拒绝执行可能中断任务的操作" >&2
    return 1
  fi
  if ! count="$(HEALTH_BODY="$body" "$PY" - <<'PY'
import json
import os

body = json.loads(os.environ["HEALTH_BODY"])
value = (body.get("data") or {}).get("active_task_count") if body.get("code") == 0 else None
if not isinstance(value, int) or isinstance(value, bool) or value < 0:
    raise SystemExit(1)
print(value)
PY
  )"; then
    echo "健康检查未返回可信的活跃任务数量，拒绝执行可能中断任务的操作" >&2
    return 1
  fi
  if [[ "$count" != "0" ]]; then
    echo "检测到 $count 个待执行或运行中的后台任务，拒绝停止后端；请等待任务结束或先显式终止任务" >&2
    return 1
  fi
  echo "✅ 后端当前无待执行或运行中的后台任务"
}

restart_safely() {
  local pid code
  pid="$(running_pid)"
  if [[ -z "$pid" ]]; then
    start dev
    return
  fi
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 \
    http://127.0.0.1:8000/api/health 2>/dev/null)" || code="000"
  if [[ "$code" == "200" ]]; then
    assert_idle
  else
    echo "后端健康检查为 ${code}，执行恢复性重启" >&2
  fi
  stop
  start dev
}

case "${1:-dev}" in
  dev|"")   start dev ;;
  prod)     start prod ;;
  stop)     stop ;;
  restart)  restart_safely ;;
  status)   status ;;
  assert-idle) assert_idle ;;
  stop-if-idle) assert_idle; stop ;;
  snapshot-runtime)
    shift
    snapshot_runtime_state "${1:-}"
    ;;
  restore-runtime)
    shift
    restore_runtime_state "${1:-}"
    ;;
  logs)     tail -f "$LOG_FILE" ;;
  dev-users)
    shift
    "$PY" -m backend.cli dev-users "$@"
    ;;
  e2e-user)
    shift
    "$PY" -m backend.devtools.e2e_test_users "$@"
    ;;
  e2e-backtest-run)
    shift
    "$PY" -m backend.devtools.e2e_backtest_runs "$@"
    ;;
  e2e-board-data)
    shift
    "$PY" -m backend.devtools.e2e_board_data "$@"
    ;;
  e2e-stock-board-correlation)
    shift
    "$PY" -m backend.devtools.e2e_stock_board_correlation "$@"
    ;;
  e2e-trade-discipline)
    shift
    "$PY" -m backend.devtools.e2e_trade_discipline "$@"
    ;;
  *)
    echo "用法: ./start.sh [dev|prod|stop|restart|status|assert-idle|stop-if-idle|logs|dev-users|e2e-user|e2e-backtest-run|e2e-board-data|e2e-stock-board-correlation|e2e-trade-discipline]"
    exit 1
    ;;
esac
