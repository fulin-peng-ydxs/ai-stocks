#!/usr/bin/env bash

# 统一加载仓库根目录的本机变量文件。调用方须先进入项目根目录。
load_project_local_env() {
  local env_file="${AI_STOCKS_ENV_FILE:-.env.local}"
  if [[ ! -f "$env_file" ]]; then
    return 0
  fi
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
}
