#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# shellcheck source=scripts/load-local-env.sh
source "$PROJECT_ROOT/scripts/load-local-env.sh"
load_project_local_env

if [[ "${AI_STOCKS_ENV:-}" != "dev" && "${AI_STOCKS_ENV:-}" != "test" && "${AI_STOCKS_ENV:-}" != "local" ]]; then
  echo "请显式设置 AI_STOCKS_ENV=dev|test|local 后再运行交易纪律 E2E"
  exit 1
fi
if [[ "${AI_STOCKS_E2E_WRITE:-}" != "1" ]]; then
  echo "请显式设置 AI_STOCKS_E2E_WRITE=1 后再运行交易纪律 E2E"
  exit 1
fi

status_before="$(./start.sh status 2>&1 || true)"
was_running=0
if [[ "$status_before" == *"运行中"* ]]; then
  was_running=1
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

start_normal_backend() {
  AI_STOCKS_ENV_FILE=/dev/null \
    AI_STOCKS_ENV="$AI_STOCKS_ENV" \
    AI_STOCKS_E2E_WRITE=0 \
    AI_STOCKS_E2E_LOGIN_BYPASS=0 \
    AI_STOCKS_DUCKDB_READ_ONLY=0 \
    "$PROJECT_ROOT/start.sh"
}

fixture() {
    AI_STOCKS_ENV_FILE=/dev/null \
    AI_STOCKS_ENV="$AI_STOCKS_ENV" \
    AI_STOCKS_E2E_WRITE=1 \
    AI_STOCKS_DUCKDB_READ_ONLY=0 \
    "$PROJECT_ROOT/start.sh" e2e-trade-discipline "$@" \
      --expected-pg-fingerprint "$pg_fingerprint"
}

cleanup_fixture_with_retry() {
  local attempt output status
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
      echo "DuckDB 仍在释放锁，1 秒后重试交易纪律夹具清理（$attempt/10）" >&2
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
  "$PROJECT_ROOT/start.sh" stop
  if [[ -n "$pg_fingerprint" ]]; then
    cleanup_fixture_with_retry || cleanup_exit=$?
    if [[ "$cleanup_exit" != "0" ]]; then
      echo "交易纪律 E2E 清理失败，可能存在专属前缀残留" >&2
    fi
  else
    echo "尚未取得可信 PostgreSQL 指纹，按 fail-closed 规则跳过物理清理" >&2
  fi
  if [[ "$was_running" == "1" ]]; then
    start_normal_backend || restore_exit=$?
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

# 优先复用已按 E2E 模式运行的后端；否则受控切换后端，只把指纹保存在本脚本变量中。
pg_fingerprint="$(read_pg_fingerprint || true)"
if [[ -z "$pg_fingerprint" ]]; then
  "$PROJECT_ROOT/start.sh" stop
  start_e2e_backend
  pg_fingerprint="$(read_pg_fingerprint || true)"
fi
if [[ -z "$pg_fingerprint" ]]; then
  echo "无法从 /api/health/e2e 取得合法 PostgreSQL 指纹，拒绝准备夹具" >&2
  exit 1
fi

# 账号校准与被测后端使用同一份已加载环境；密码仍由既有 dev-users 规则管理。
AI_STOCKS_ENV_FILE=/dev/null AI_STOCKS_ENV="$AI_STOCKS_ENV" \
  "$PROJECT_ROOT/start.sh" dev-users --keep-password >/dev/null

"$PROJECT_ROOT/start.sh" stop
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
  e2e/trade-discipline.spec.ts \
  --workers=1 "$@"
