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
#   ./start.sh logs       跟踪日志（Ctrl-C 退出跟踪，不影响服务）
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
PROC_PATTERN="backend.cli serve"

mkdir -p "$LOG_DIR"

# 本机敏感环境变量入口：文件已被 .gitignore 忽略，可放 JWT secret、PG/Redis 密码等。
# 示例见 .env.local.example；文件内变量可写 export KEY=... 或 KEY=...。
if [[ -f ".env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env.local"
  set +a
fi

# 是否有存活的后端进程；有则回显 PID
running_pid() {
  pgrep -f "$PROC_PATTERN" | head -1 || true
}

start() {
  local mode="$1"  # dev | prod
  local pid
  pid="$(running_pid)"
  if [[ -n "$pid" ]]; then
    echo "⚠️  后端已在运行 (PID $pid)，如需重启请先 ./start.sh stop 或用 ./start.sh restart"
    exit 0
  fi

  # dev：热重载 + 绑 127.0.0.1（仅本机，外部走前端 5173 代理）；prod：绑 0.0.0.0（对外托管）。
  local args=("serve")
  if [[ "$mode" == "dev" ]]; then
    args+=("--reload" "--host" "127.0.0.1")
  else
    args+=("--host" "0.0.0.0")
  fi

  echo "🚀 启动后端（$mode 模式）…"
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
  local pid
  pid="$(running_pid)"
  if [[ -z "$pid" ]]; then
    echo "ℹ️  后端未在运行"
    rm -f "$PID_FILE"
    return 0
  fi
  echo "🛑 停止后端…"
  pkill -f "$PROC_PATTERN" || true
  sleep 1
  if [[ -n "$(running_pid)" ]]; then
    echo "进程未退出，强制结束…"
    pkill -9 -f "$PROC_PATTERN" || true
  fi
  rm -f "$PID_FILE"
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
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:8000/api/health 2>/dev/null || echo 000)"
  echo "● 后端：运行中 (PID $pid)  /api/health=$code  端口 8000"
}

case "${1:-dev}" in
  dev|"")   start dev ;;
  prod)     start prod ;;
  stop)     stop ;;
  restart)  stop; start dev ;;
  status)   status ;;
  logs)     tail -f "$LOG_FILE" ;;
  *)        echo "用法: ./start.sh [dev|prod|stop|restart|status|logs]"; exit 1 ;;
esac
