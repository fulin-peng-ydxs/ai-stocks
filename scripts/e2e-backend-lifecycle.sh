#!/usr/bin/env bash

# 由调用方先设置 PROJECT_ROOT。这里只提供无副作用的状态判断和条件停服，确保后端初始
# 停止时不会调用要求在线读取任务状态的 stop-if-idle。
backend_is_running() {
  local status_text
  status_text="$("$PROJECT_ROOT/start.sh" status 2>&1 || true)"
  [[ "$status_text" == *"运行中"* ]]
}

stop_backend_if_running() {
  if backend_is_running; then
    "$PROJECT_ROOT/start.sh" stop-if-idle
  fi
}
run_e2e_playwright() {
  # 本地入口保留默认 spec；CI 的文件/项目只由唯一登记生成的 config 选择。
  local count="$1"
  shift
  local files=()
  while [[ "$count" -gt 0 ]]; do
    files+=("$1")
    shift
    count=$((count - 1))
  done
  if [[ -n "${AI_STOCKS_CI_SUITE:-}" ]]; then
    "$PROJECT_ROOT/scripts/run-playwright.sh" --workers=1 "$@"
  else
    "$PROJECT_ROOT/scripts/run-playwright.sh" "${files[@]}" --workers=1 "$@"
  fi
}
