#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# shellcheck source=scripts/load-local-env.sh
source "$PROJECT_ROOT/scripts/load-local-env.sh"
load_project_local_env
# shellcheck source=scripts/e2e-backend-lifecycle.sh
source "$PROJECT_ROOT/scripts/e2e-backend-lifecycle.sh"

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
owns_backend=0
runtime_snapshot=""
if [[ "$status_before" == *"运行中"* ]]; then
  was_running=1
  "$PROJECT_ROOT/start.sh" assert-idle
  runtime_snapshot="$(mktemp "${TMPDIR:-/tmp}/ai-stocks-sector-runtime.XXXXXX")"
  rm -f "$runtime_snapshot"
  if ! "$PROJECT_ROOT/start.sh" snapshot-runtime "$runtime_snapshot"; then
    rm -f "$runtime_snapshot"
    echo "现有后端缺少可信运行档案，拒绝在无法恢复原参数时运行板块 E2E" >&2
    exit 1
  fi
fi

fixture() {
  AI_STOCKS_ENV_FILE=/dev/null AI_STOCKS_ENV="$AI_STOCKS_ENV" \
    AI_STOCKS_E2E_WRITE=1 AI_STOCKS_DUCKDB_READ_ONLY=0 \
    "$PROJECT_ROOT/start.sh" e2e-board-data "$@"
}

cleanup() {
  local original_exit="$?"
  local cleanup_exit=0
  local restore_exit=0
  trap - EXIT
  set +e
  if [[ "$owns_backend" == "1" ]]; then
    if "$PROJECT_ROOT/start.sh" stop --force; then
      fixture cleanup || cleanup_exit=$?
      if [[ "$was_running" == "1" ]]; then
        "$PROJECT_ROOT/start.sh" restore-runtime "$runtime_snapshot" || restore_exit=$?
      fi
    else
      cleanup_exit=$?
      restore_exit=1
    fi
  fi
  if [[ -n "$runtime_snapshot" ]]; then
    if [[ "$restore_exit" == "0" ]]; then
      rm -f "$runtime_snapshot"
    else
      echo "后端恢复未完成，原运行档案保留于 $runtime_snapshot" >&2
    fi
  fi
  if [[ "$original_exit" != "0" ]]; then exit "$original_exit"; fi
  if [[ "$cleanup_exit" != "0" || "$restore_exit" != "0" ]]; then exit 1; fi
  exit 0
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

stop_backend_if_running
owns_backend=1
fixture cleanup
fixture seed
AI_STOCKS_ENV_FILE=/dev/null AI_STOCKS_ENV="$AI_STOCKS_ENV" AI_STOCKS_E2E_WRITE=1 \
  AI_STOCKS_E2E_LOGIN_BYPASS=1 AI_STOCKS_DUCKDB_READ_ONLY=0 ./start.sh

cd "$PROJECT_ROOT/frontend"
# 三视口共享固定调试账号、板块自选和页面偏好，必须串行，避免跨 project 相互改写状态。
# 聚焦入口覆盖板块数据管理、质量恢复和业务工作台三条发布链路。
"$PROJECT_ROOT/scripts/run-playwright.sh" \
  e2e/board-data-management.spec.ts \
  e2e/sector-quality-recovery.spec.ts \
  e2e/sectors-workbench.spec.ts \
  --workers=1 "$@"
