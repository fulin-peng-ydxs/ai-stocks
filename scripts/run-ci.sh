#!/usr/bin/env bash
# 独立 CI 入口不加载 .env.local，后端执行器自行创建隔离环境。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
CI_PYTHON="${PYTHON:-python3}"
if [[ "$#" == 0 ]]; then
  set -- run
fi
exec "$CI_PYTHON" -m backend.devtools.ci "$@"
