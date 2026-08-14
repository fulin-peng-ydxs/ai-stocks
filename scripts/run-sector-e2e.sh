#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# shellcheck source=scripts/load-local-env.sh
source "$PROJECT_ROOT/scripts/load-local-env.sh"
load_project_local_env

if [[ "${AI_STOCKS_ENV:-}" != "dev" && "${AI_STOCKS_ENV:-}" != "test" && "${AI_STOCKS_ENV:-}" != "local" ]]; then
  echo "请显式设置 AI_STOCKS_ENV=dev|test|local 后再运行板块 E2E"
  exit 1
fi
if [[ "${AI_STOCKS_E2E_WRITE:-}" != "1" ]]; then
  echo "请显式设置 AI_STOCKS_E2E_WRITE=1 后再运行板块 E2E"
  exit 1
fi

status_before="$(./start.sh status 2>&1 || true)"
was_running=0
if [[ "$status_before" == *"运行中"* ]]; then
  was_running=1
fi

cleanup() {
  set +e
  "$PROJECT_ROOT/start.sh" stop
  AI_STOCKS_ENV="$AI_STOCKS_ENV" AI_STOCKS_E2E_WRITE=1 \
    "$PROJECT_ROOT/start.sh" e2e-board-data cleanup
  if [[ "$was_running" == "1" ]]; then
    AI_STOCKS_ENV="$AI_STOCKS_ENV" "$PROJECT_ROOT/start.sh"
  fi
}
trap cleanup EXIT

./start.sh stop
AI_STOCKS_ENV="$AI_STOCKS_ENV" AI_STOCKS_E2E_WRITE=1 ./start.sh e2e-board-data cleanup
AI_STOCKS_ENV="$AI_STOCKS_ENV" AI_STOCKS_E2E_WRITE=1 ./start.sh e2e-board-data seed
AI_STOCKS_ENV="$AI_STOCKS_ENV" AI_STOCKS_E2E_WRITE=1 \
  AI_STOCKS_E2E_LOGIN_BYPASS=1 ./start.sh

cd "$PROJECT_ROOT/frontend"
# 三视口共享固定调试账号、板块自选和页面偏好，必须串行，避免跨 project 相互改写状态。
# 聚焦入口覆盖板块数据管理、质量恢复和业务工作台三条发布链路。
"$PROJECT_ROOT/scripts/run-playwright.sh" \
  e2e/board-data-management.spec.ts \
  e2e/sector-quality-recovery.spec.ts \
  e2e/sectors-workbench.spec.ts \
  --workers=1 "$@"
