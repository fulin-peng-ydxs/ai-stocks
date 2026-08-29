#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# shellcheck source=scripts/load-local-env.sh
source "$PROJECT_ROOT/scripts/load-local-env.sh"
load_project_local_env

if [[ "${AI_STOCKS_ENV:-}" != "dev" && "${AI_STOCKS_ENV:-}" != "test" && "${AI_STOCKS_ENV:-}" != "local" ]]; then
  echo "请显式设置 AI_STOCKS_ENV=dev|test|local 后再运行完整设计 E2E" >&2
  exit 1
fi
if [[ "${AI_STOCKS_E2E_WRITE:-}" != "1" ]]; then
  echo "请显式设置 AI_STOCKS_E2E_WRITE=1 后再运行完整设计 E2E" >&2
  exit 1
fi
if [[ -n "${E2E_API_URL:-}" && "${E2E_API_URL}" != "http://127.0.0.1:8000/api" ]]; then
  echo "完整设计 E2E 会管理本地后端和夹具，仅允许 E2E_API_URL=http://127.0.0.1:8000/api" >&2
  exit 1
fi

status_before="$(./start.sh status 2>&1 || true)"
was_running=0
owns_backend=0
runtime_snapshot=""
pg_fingerprint=""
if [[ "$status_before" == *"运行中"* ]]; then
  was_running=1
  "$PROJECT_ROOT/start.sh" assert-idle
  runtime_snapshot="$(mktemp "${TMPDIR:-/tmp}/ai-stocks-design-runtime.XXXXXX")"
  rm -f "$runtime_snapshot"
  if ! "$PROJECT_ROOT/start.sh" snapshot-runtime "$runtime_snapshot"; then
    echo "现有后端缺少可信运行档案；请先用 ./start.sh restart 受控重启后再执行设计验收" >&2
    exit 1
  fi
fi

read_pg_fingerprint() {
  local body
  body="$(curl -fsS --max-time 3 "${E2E_API_URL:-http://127.0.0.1:8000/api}/health/e2e")" || return 1
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

start_backend() {
  local read_only="$1"
  AI_STOCKS_ENV_FILE=/dev/null \
    AI_STOCKS_ENV="$AI_STOCKS_ENV" \
    AI_STOCKS_E2E_WRITE=1 \
    AI_STOCKS_E2E_LOGIN_BYPASS=1 \
    AI_STOCKS_DUCKDB_READ_ONLY="$read_only" \
    "$PROJECT_ROOT/start.sh"
}

stop_and_start_backend() {
  local read_only="$1"
  "$PROJECT_ROOT/start.sh" stop-if-idle
  owns_backend=1
  start_backend "$read_only"
}

cleanup_backtest_fixture() {
  if [[ -z "$pg_fingerprint" ]]; then
    return 0
  fi
  AI_STOCKS_ENV_FILE=/dev/null \
    AI_STOCKS_ENV="$AI_STOCKS_ENV" \
    AI_STOCKS_E2E_WRITE=1 \
    "$PROJECT_ROOT/start.sh" e2e-backtest-run cleanup \
      --expected-pg-fingerprint "$pg_fingerprint"
  rm -f "${TMPDIR:-/tmp}/ai-stocks-e2e-backtest-seed.json"
  rm -f "${TMPDIR:-/tmp}/ai-stocks-e2e-backtest-seed.lock"
}

restore_runtime() {
  local original_exit="$?"
  local cleanup_exit=0
  local restore_exit=0
  trap - EXIT
  set +e
  if [[ "$owns_backend" == "1" ]]; then
    "$PROJECT_ROOT/start.sh" stop
    cleanup_backtest_fixture || cleanup_exit=$?
    if [[ "$was_running" == "1" ]]; then
      "$PROJECT_ROOT/start.sh" restore-runtime "$runtime_snapshot" || restore_exit=$?
    fi
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
trap restore_runtime EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

stop_and_start_backend 0
pg_fingerprint="$(read_pg_fingerprint || true)"
if [[ -z "$pg_fingerprint" ]]; then
  echo "无法从 /api/health/e2e 取得合法 PostgreSQL 指纹，拒绝运行设计验收" >&2
  exit 1
fi

AI_STOCKS_ENV_FILE=/dev/null AI_STOCKS_ENV="$AI_STOCKS_ENV" \
  "$PROJECT_ROOT/start.sh" dev-users --keep-password \
    --expected-pg-fingerprint "$pg_fingerprint" >/dev/null

# 无专属物理夹具的用例共享读写后端；互斥用例由下方专用 runner 独立管理生命周期。
standard_specs=()
while IFS= read -r spec; do
  standard_specs+=("$spec")
done < <(
  find "$PROJECT_ROOT/frontend/e2e" -maxdepth 1 -name '*.spec.ts' -print \
    | sort \
    | grep -Ev '/(backtest-public-runs|board-data-management|sector-quality-recovery|sectors-workbench|stock-board-correlation|trade-discipline)\.spec\.ts$'
)
if [[ "${#standard_specs[@]}" == "0" ]]; then
  echo "未找到普通 Playwright 用例，拒绝跳过设计验收" >&2
  exit 1
fi
standard_args=()
for spec in "${standard_specs[@]}"; do
  standard_args+=("e2e/$(basename "$spec")")
done
"$PROJECT_ROOT/scripts/run-playwright.sh" "${standard_args[@]}" --workers=1

# 三组固定行情夹具日期互斥，必须依次 seed、验证、cleanup。
AI_STOCKS_ENV="$AI_STOCKS_ENV" AI_STOCKS_E2E_WRITE=1 \
  "$PROJECT_ROOT/scripts/run-sector-e2e.sh"
stop_and_start_backend 0
AI_STOCKS_ENV="$AI_STOCKS_ENV" AI_STOCKS_E2E_WRITE=1 \
  "$PROJECT_ROOT/scripts/run-stock-board-correlation-e2e.sh"
AI_STOCKS_ENV="$AI_STOCKS_ENV" AI_STOCKS_E2E_WRITE=1 \
  "$PROJECT_ROOT/scripts/run-trade-discipline-e2e.sh"

# 公开回测夹具会独立读取 DuckDB 并写 PG；被测后端按项目契约切换为 DuckDB 只读。
stop_and_start_backend 1
current_fingerprint="$(read_pg_fingerprint || true)"
if [[ "$current_fingerprint" != "$pg_fingerprint" ]]; then
  echo "只读后端 PostgreSQL 与设计验收起点不一致，拒绝运行公开回测 E2E" >&2
  exit 1
fi
"$PROJECT_ROOT/scripts/run-playwright.sh" \
  e2e/backtest-public-runs.spec.ts --workers=1
"$PROJECT_ROOT/start.sh" stop-if-idle
cleanup_backtest_fixture
start_backend 0

echo "完整设计 E2E 分组验收通过"
