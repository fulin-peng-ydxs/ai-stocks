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
  echo "请显式设置 AI_STOCKS_ENV=dev|test|local 后再运行关联板块 E2E"
  exit 1
fi
if [[ "${AI_STOCKS_E2E_WRITE:-}" != "1" ]]; then
  echo "请显式设置 AI_STOCKS_E2E_WRITE=1 后再运行关联板块 E2E"
  exit 1
fi

status_before="$(./start.sh status 2>&1 || true)"
was_running=0
owns_backend=0
runtime_snapshot=""
if [[ "$status_before" == *"运行中"* ]]; then
  was_running=1
  "$PROJECT_ROOT/start.sh" assert-idle
  runtime_snapshot="$(mktemp "${TMPDIR:-/tmp}/ai-stocks-backend-runtime.XXXXXX")"
  rm -f "$runtime_snapshot"
  if ! "$PROJECT_ROOT/start.sh" snapshot-runtime "$runtime_snapshot"; then
    echo "现有后端缺少可信运行档案；请先用 ./start.sh restart 受控重启后再执行 E2E" >&2
    exit 1
  fi
fi
pg_fingerprint=""

start_e2e_backend() {
  AI_STOCKS_ENV_FILE=/dev/null \
    AI_STOCKS_ENV="$AI_STOCKS_ENV" \
    AI_STOCKS_E2E_WRITE=1 \
    AI_STOCKS_E2E_LOGIN_BYPASS=1 \
    AI_STOCKS_DUCKDB_READ_ONLY=0 \
    "$PROJECT_ROOT/start.sh"
}

fixture() {
  if [[ -z "$pg_fingerprint" ]]; then
    echo "缺少 PostgreSQL 指纹，拒绝执行关联板块夹具" >&2
    return 1
  fi
  AI_STOCKS_ENV_FILE=/dev/null \
    AI_STOCKS_ENV="$AI_STOCKS_ENV" \
    AI_STOCKS_E2E_WRITE=1 \
    AI_STOCKS_DUCKDB_READ_ONLY=0 \
    "$PROJECT_ROOT/start.sh" e2e-stock-board-correlation "$@" \
      --expected-pg-fingerprint "$pg_fingerprint"
}

cleanup_fixture_with_retry() {
  local attempt output status
  if [[ -z "$pg_fingerprint" ]]; then
    return 0
  fi
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if output="$(fixture cleanup 2>&1)"; then
      printf '%s\n' "$output"
      return 0
    else
      status=$?
    fi
    if [[ "$output" != *"Conflicting lock is held"* ]]; then
      printf '%s\n' "$output" >&2
      return "$status"
    fi
    if [[ "$attempt" != "10" ]]; then
      echo "DuckDB 仍在释放锁，1 秒后重试关联板块夹具清理（$attempt/10）" >&2
      sleep 1
    else
      printf '%s\n' "$output" >&2
    fi
  done
  return "$status"
}

read_pg_fingerprint() {
  local body
  body="$(curl -fsS --max-time 3 http://127.0.0.1:8000/api/health/e2e)" || return 1
  E2E_HEALTH_BODY="$body" python - <<'PY'
import json
import os
import re

body = json.loads(os.environ["E2E_HEALTH_BODY"])
value = (body.get("data") or {}).get("pgFingerprint") if body.get("code") == 0 else None
if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
    raise SystemExit(1)
print(value)
PY
}

restore_and_cleanup() {
  local original_exit="$?"
  local cleanup_exit=0
  local restore_exit=0
  trap - EXIT
  set +e
  if [[ "$owns_backend" != "1" ]]; then
    exit "$original_exit"
  fi
  "$PROJECT_ROOT/start.sh" stop
  cleanup_fixture_with_retry || cleanup_exit=$?
  if [[ "$cleanup_exit" != "0" ]]; then
    echo "关联板块 E2E 清理失败，可能存在专属前缀残留" >&2
  fi
  if [[ "$was_running" == "1" ]]; then
    "$PROJECT_ROOT/start.sh" restore-runtime "$runtime_snapshot" || restore_exit=$?
  fi
  if [[ -n "$runtime_snapshot" ]]; then
    rm -f "$runtime_snapshot"
  fi
  if [[ "$original_exit" != "0" ]]; then
    exit "$original_exit"
  fi
  if [[ "$cleanup_exit" != "0" || "$restore_exit" != "0" ]]; then
    exit 1
  fi
  exit 0
}
trap restore_and_cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

pg_fingerprint="$(read_pg_fingerprint || true)"
if [[ -z "$pg_fingerprint" ]]; then
  stop_backend_if_running
  owns_backend=1
  start_e2e_backend
  pg_fingerprint="$(read_pg_fingerprint || true)"
fi
if [[ -z "$pg_fingerprint" ]]; then
  echo "无法从 /api/health/e2e 取得合法 PostgreSQL 指纹，拒绝准备夹具" >&2
  exit 1
fi

AI_STOCKS_ENV_FILE=/dev/null AI_STOCKS_ENV="$AI_STOCKS_ENV" \
  "$PROJECT_ROOT/start.sh" dev-users --keep-password \
    --expected-pg-fingerprint "$pg_fingerprint" >/dev/null

stop_backend_if_running
owns_backend=1
cleanup_fixture_with_retry
fixture seed
start_e2e_backend

current_fingerprint="$(read_pg_fingerprint || true)"
if [[ "$current_fingerprint" != "$pg_fingerprint" ]]; then
  echo "被测后端 PostgreSQL 在 seed 后发生变化，拒绝运行 Playwright" >&2
  exit 1
fi

cd "$PROJECT_ROOT/frontend"
"$PROJECT_ROOT/scripts/run-playwright.sh" \
  e2e/stock-board-correlation.spec.ts \
  --workers=1 "$@"
