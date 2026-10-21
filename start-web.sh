#!/usr/bin/env bash
# ───────────────────────────────────────────────────────────────────────────
# ai-stocks 前端启动脚本（Vite dev server）
#
# 用法：
#   ./start-web.sh            开发模式启动（Vite HMR，端口 5173）
#   ./start-web.sh stop       停止前端
#   ./start-web.sh restart    重启
#   ./start-web.sh status     查看运行状态
#   ./start-web.sh logs       跟踪日志（Ctrl-C 退出跟踪，不影响服务）
#
# 设计要点（对齐 start.sh）：
#   - 独立 session 脱离会话：AI 跑别的命令 / 终端关闭 / 对话结束都不会误杀。
#   - --strictPort：端口被占直接报错，不静默漂移到别的端口。
#   - 进程识别用"端口监听者"而非进程名：vite 进程名不稳定，按端口最可靠。
#   - 防重复启动：已在跑则直接退出，避免端口抢占。
#   - 自动化验证请用专用端口 5181（见 README §5.1 / platform 文档），勿占用此 5173。
# ───────────────────────────────────────────────────────────────────────────
set -euo pipefail

cd "$(dirname "$0")"

PORT="${WEB_PORT:-5173}"
PY="${PYTHON:-python}"
LOG_DIR="logs"
# 日常服务沿用原路径；验证实例按端口隔离，日志及归档、PID 各自独立。
LOG_SUFFIX=""
if [[ "$PORT" != "5173" ]]; then
  LOG_SUFFIX="-$PORT"
fi
LOG_FILE="$LOG_DIR/frontend$LOG_SUFFIX.log"
PID_FILE="$LOG_DIR/frontend$LOG_SUFFIX.pid"

mkdir -p "$LOG_DIR"

# 监听 PORT 的进程 PID（即 vite）；无则空
running_pid() {
  lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1 || true
}

start() {
  local pid
  pid="$(running_pid)"
  if [[ -n "$pid" ]]; then
    echo "⚠️  前端已在运行 (PID ${pid}，端口 ${PORT})，如需重启请用 ./start-web.sh restart"
    exit 0
  fi

  echo "🚀 启动前端（dev / HMR，端口 ${PORT}）…"
  # 与后端启动方式一致：nohup 不能隔离命令工具退出时的进程组清理。
  "$PY" - "$PORT" "$LOG_FILE" <<'PY'
import sys

from scripts.service_logs import launch_logged_process

launch_logged_process(
    ["npm", "--prefix", "frontend", "run", "dev", "--", "--port", sys.argv[1], "--strictPort"],
    path=sys.argv[2],
    service="frontend",
)
PY

  # 等待端口就绪（Vite 首次冷启动可能较慢，最多 ~30s）
  local i
  for i in $(seq 1 30); do
    if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$PORT" 2>/dev/null; then
      pid="$(running_pid)"
      echo "$pid" > "$PID_FILE"
      echo "✅ 已启动 (PID $pid) — http://localhost:$PORT  | 日志：$LOG_FILE"
      return 0
    fi
    sleep 1
  done

  echo "❌ 启动后端口 $PORT 未就绪，请查看日志：$LOG_FILE"
  tail -20 "$LOG_FILE" || true
  exit 1
}

stop() {
  local pid
  pid="$(running_pid)"
  if [[ -z "$pid" ]]; then
    echo "ℹ️  前端未在运行"
    rm -f "$PID_FILE"
    return 0
  fi
  echo "🛑 停止前端…"
  kill "$pid" 2>/dev/null || true
  sleep 1
  if [[ -n "$(running_pid)" ]]; then
    echo "进程未退出，强制结束…"
    kill -9 "$(running_pid)" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  echo "✅ 已停止"
}

status() {
  local pid
  pid="$(running_pid)"
  if [[ -z "$pid" ]]; then
    echo "● 前端：未运行"
    return 0
  fi
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://127.0.0.1:$PORT" 2>/dev/null || echo 000)"
  echo "● 前端：运行中 (PID $pid)  HTTP=$code  端口 $PORT"
}

case "${1:-dev}" in
  dev|"")   start ;;
  stop)     stop ;;
  restart)  stop; start ;;
  status)   status ;;
  logs)     tail -F "$LOG_FILE" ;;
  *)        echo "用法: ./start-web.sh [dev|stop|restart|status|logs]"; exit 1 ;;
esac
