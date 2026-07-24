#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Playwright 与后端服务、dev-users、临时用户夹具复用同一变量文件语义。
# shellcheck source=scripts/load-local-env.sh
source "$PROJECT_ROOT/scripts/load-local-env.sh"
load_project_local_env

cd "$PROJECT_ROOT/frontend"
exec "$PROJECT_ROOT/frontend/node_modules/.bin/playwright" test "$@"
