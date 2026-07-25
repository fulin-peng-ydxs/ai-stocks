# T13 发布验证与回滚演练记录

## 1. 记录范围与实际执行基线

- 对应任务：`plan.md` T13。
- 对应需求：R3、R4、R8、R16。
- 实际执行日期：2026-07-25。
- 发布烟测所用业务代码提交：`9af8521`。
- T13 状态文档提交：`d874481`。
- 功能开发前前端回滚基线：`6169975`。
- 仓库根目录：`/Users/pengshuaifeng/ai-stocks`。
- 实际快照目录：`/var/tmp/ai-stocks-macd-t13.4FRO57`。
- Playwright HTML 报告：`frontend/playwright-report/index.html`，生成时间
  `2026-07-25 06:35:09 CST`。
- Playwright 结果摘要：`frontend/test-results/.last-run.json`，内容为
  `{"status":"passed","failedTests":[]}`。

本记录只保存命令、哈希和结果，不提交 DuckDB 数据库或快照。实际快照位于仓库外，
可能被操作系统清理；下次发布必须重新执行第 3 节生成新快照，不能依赖本次临时目录。

## 2. 安全前置

1. 从仓库根目录执行，先确认 `git status --short` 没有非预期改动。
2. 先用 `./start.sh status` 记录后端状态；任何 DuckDB 导出、停用、seed 或恢复操作前，
   必须用 `./start.sh stop` 停服。
3. `T13_SNAPSHOT_DIR` 必须来自本轮 `mktemp` 输出，并同时包含
   `indicator_def-before.parquet` 与 `indicator_def-before-canonical.json`。
4. 停用只允许命中五个固定 builtin key，不允许 `DELETE`。
5. 精确恢复前必须确认当前表与本轮快照的差异只来自这五个 key；如果上线后新增了定义、
   修改了管理员分类/启停或已有新方案引用 MACD，应停止恢复并人工评估。
6. PostgreSQL E2E 只允许在明确 `dev/test/local` 且
   `AI_STOCKS_E2E_WRITE=1` 时运行；结束后必须移除写开关并确认临时用户为 0。
7. 本流程没有 PG schema、行情表或指标值表回滚，不得扩大为数据库全量覆盖。

## 3. `indicator_def` 快照、定位与规范化哈希

### 3.1 可复演命令

```bash
set -euo pipefail
cd /Users/pengshuaifeng/ai-stocks
./start.sh status
./start.sh stop

T13_SNAPSHOT_DIR=$(mktemp -d /var/tmp/ai-stocks-macd-t13.XXXXXX)
export T13_SNAPSHOT_DIR
test -n "$T13_SNAPSHOT_DIR"
test -d "$T13_SNAPSHOT_DIR"
printf 'T13_SNAPSHOT_DIR=%s\n' "$T13_SNAPSHOT_DIR"

python - <<'PY'
import hashlib
import json
import os
from datetime import date, datetime
from pathlib import Path

import duckdb

root = Path(os.environ["T13_SNAPSHOT_DIR"])
db = Path("data/ai_stocks.duckdb").resolve()
columns = [
    "key", "name_cn", "category", "dtype", "direction", "kind", "expression", "params",
    "enabled", "is_builtin", "descr", "created_at", "updated_at", "categories",
]
projection = ",".join(columns)


def scalar(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ")
    return value


def canonical(rows):
    records = [dict(zip(columns, map(scalar, row))) for row in rows]
    return (
        json.dumps(
            records,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


con = duckdb.connect(str(db), read_only=True)
try:
    rows = con.execute(
        f"SELECT {projection} FROM indicator_def ORDER BY key"
    ).fetchall()
    builtin_count = con.execute(
        "SELECT count(*) FROM indicator_def WHERE is_builtin=TRUE"
    ).fetchone()[0]
    macd = con.execute(
        """
        SELECT key,name_cn,dtype,category,categories,enabled,is_builtin,updated_at
        FROM indicator_def
        WHERE key IN (
          'macd_diff','macd_dea','macd_hist',
          'macd_golden_cross','macd_dead_cross'
        )
        ORDER BY key
        """
    ).fetchall()
    snapshot_path = str(root / "indicator_def-before.parquet").replace("'", "''")
    con.execute(
        f"""
        COPY (SELECT * FROM indicator_def ORDER BY key)
        TO '{snapshot_path}' (FORMAT PARQUET)
        """
    )
finally:
    con.close()

payload = canonical(rows)
(root / "indicator_def-before-canonical.json").write_bytes(payload)
(root / "baseline.json").write_text(
    json.dumps(
        {
            "database": str(db),
            "columns": columns,
            "row_count": len(rows),
            "builtin_count": builtin_count,
            "macd": [
                dict(
                    zip(
                        [
                            "key", "name_cn", "dtype", "category",
                            "categories", "enabled", "is_builtin", "updated_at",
                        ],
                        row,
                    )
                )
                for row in macd
            ],
        },
        ensure_ascii=False,
        default=str,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print(
    f"rows={len(rows)} builtin={builtin_count} macd={len(macd)} "
    f"canonical_sha256={hashlib.sha256(payload).hexdigest()}"
)
PY

openssl dgst -sha256 \
  "$T13_SNAPSHOT_DIR/baseline.json" \
  "$T13_SNAPSHOT_DIR/indicator_def-before.parquet" \
  "$T13_SNAPSHOT_DIR/indicator_def-before-canonical.json"
```

### 3.2 本次实际结果

```text
T13_SNAPSHOT_DIR=/var/tmp/ai-stocks-macd-t13.4FRO57
rows=44 builtin=43 macd=5
baseline.json:
  cf6ff0c7cf37fefc2177576385af2f4423f199901a84e18d9287e0bd3f7ce812
indicator_def-before.parquet:
  ae86487e559ce62a310cd6e7f018b6c5eaf7c97170d9ea9032b4f36ee3ea941f
indicator_def-before-canonical.json:
  b5fa225e96a93e01698c15b2e3969faf91073bb19a9079421c3902fcd9807a3b
```

规范化哈希按固定列、`key` 排序、UTF-8、紧凑 JSON 和标准时间字符串计算，用于排除
Parquet 文件元数据差异。2026-07-25 复核时，快照和实时表均为 44 行，规范化哈希相同。

## 4. 后端发布门槛、启动 seed 与接口对账

### 4.1 后端定向回归

```bash
cd /Users/pengshuaifeng/ai-stocks
./start.sh stop
python -m pytest \
  backend/tests/test_indicators.py \
  backend/tests/test_indicator_def.py \
  backend/tests/test_screening.py \
  backend/tests/test_score_profile.py \
  backend/tests/test_trade_profile.py \
  backend/tests/test_stock_indicators_api.py \
  backend/tests/test_user_preference.py -q
./start.sh
./start.sh status
```

实际结果：`87 passed, 56 warnings in 8.83s`；告警为既有 FastAPI `on_event`
弃用提示。启动日志为：

```text
内置指标定义校准完成：总数 43，变更 0
混合持久层自检通过：builtin 指标 43 个
```

### 4.2 真实接口 smoke

以下命令从 `.env.local` 读取调试账号密码，不在文档、输出或提交中展开密码与 token：

```bash
cd /Users/pengshuaifeng/ai-stocks
source scripts/load-local-env.sh
load_project_local_env
: "${AI_STOCKS_TEST_USER_PASSWORD:?缺少本地调试账号密码}"

AI_STOCKS_ENV=dev python - <<'PY'
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8000/api"
PASSWORD = os.environ["AI_STOCKS_TEST_USER_PASSWORD"]
MACD = {
    "macd_diff", "macd_dea", "macd_hist",
    "macd_golden_cross", "macd_dead_cross",
}


def call(method, path, token=None, body=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        raw = error.read()
        return error.code, json.loads(raw) if raw else None


def login(account):
    status, body = call(
        "POST",
        "/auth/login",
        body={"account": account, "password": PASSWORD},
    )
    assert status == 200 and body["code"] == 0
    return body["data"]["access_token"]


normal = login("debug_normal")
system = login("debug_system")

status, body = call(
    "GET",
    "/indicators/registry?include_disabled=true",
    system,
)
items = body["data"]["items"]
macd_items = {item["key"]: item for item in items if item["key"] in MACD}
assert status == 200
assert body["data"]["count"] == 44
assert sum(bool(item["is_builtin"]) for item in items) == 43
assert set(macd_items) == MACD
assert all(item["enabled"] and item["is_builtin"] for item in macd_items.values())
print("registry=ok total=44 builtin=43 macd=5")

status, body = call(
    "GET",
    "/stocks/300834.SZ/indicators?lookback=1",
    normal,
)
assert status == 200 and body["code"] == 0
print(f"legacy=ok rows={len(body['data']['indicators'])}")

fields = ",".join(sorted(MACD))
status, body = call(
    "GET",
    f"/stocks/300834.SZ/indicators?lookback=6000&fields={fields}",
    normal,
)
rows = body["data"]["indicators"]
assert status == 200 and rows
assert all(set(row) == {"trade_date", *MACD} for row in rows)
json.dumps(body, allow_nan=False)
print(
    f"macd=ok rows={len(rows)} "
    f"first={rows[0]['trade_date']} last={rows[-1]['trade_date']}"
)

status, _ = call(
    "GET",
    "/stocks/300834.SZ/indicators"
    "?lookback=60&fields=macd_diff,unknown_field",
    normal,
)
assert status == 400
status, _ = call(
    "GET",
    "/stocks/300834.SZ/indicators?lookback=6001&fields=macd_diff",
    normal,
)
assert status == 422
print("boundaries=ok invalid_field=400 lookback_6001=422")
PY
```

实际结果：

```text
registry=ok total=44 builtin=43 macd=5
legacy=ok rows=1
macd=ok rows=1094 first=2022-01-13 last=2026-07-22
boundaries=ok invalid_field=400 lookback_6001=422
```

### 4.3 三类下游固定样本

```bash
cd /Users/pengshuaifeng/ai-stocks
./start.sh stop
python -m pytest \
  backend/tests/test_screening.py::test_screen_engine_uses_all_registered_macd_results \
  backend/tests/test_score_profile.py::test_macd_columns_score_without_special_resolver_branch \
  backend/tests/test_trade_profile.py::test_all_macd_results_work_as_buy_and_sell_conditions \
  -q
./start.sh
./start.sh status
```

实际结果：`3 passed in 0.56s`。

## 5. 前端构建、页面与偏好 smoke

### 5.1 当前前端构建

```bash
cd /Users/pengshuaifeng/ai-stocks/frontend
npm run build
```

实际结果：构建通过，仅有既有依赖注释和大 chunk 告警。

### 5.2 Playwright

```bash
cd /Users/pengshuaifeng/ai-stocks
AI_STOCKS_ENV=dev ./start.sh dev-users
AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 ./start.sh restart
AI_STOCKS_ENV=dev ./start.sh dev-users --list

cd frontend
AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 \
  npm run test:e2e -- stock-detail-chart-workspace.spec.ts

cd ..
AI_STOCKS_ENV=dev ./start.sh restart
./start.sh status
curl -sS http://127.0.0.1:8000/api/health/e2e
```

实际结果：

```text
10 passed (42.3s)
14 skipped
/api/health=200
/api/health/e2e -> {"code":403,"msg":"E2E 写环境未启用","data":null}
```

报告位置：

- HTML：`frontend/playwright-report/index.html`
- 机器结果：`frontend/test-results/.last-run.json`
- 明暗截图附件：`frontend/playwright-report/data/*.png`

临时用户零残留复核：

```bash
cd /Users/pengshuaifeng/ai-stocks
source scripts/load-local-env.sh
load_project_local_env

AI_STOCKS_ENV=dev python - <<'PY'
from backend.storage.pg_client import get_pg_client

pg = get_pg_client()
try:
    frame = pg.query_df(
        "SELECT count(*) AS n FROM sys_user WHERE account LIKE %s",
        ["e2e_%"],
    )
    print(f"temporary_e2e_users={int(frame.iloc[0]['n'])}")
finally:
    pg.close()
PY
```

实际结果：`temporary_e2e_users=0`。

### 5.3 `debug_system` 技术指标页

该项是一次性发布 smoke，不替代仓库内稳定 Playwright 用例：

```bash
cd /Users/pengshuaifeng/ai-stocks
source scripts/load-local-env.sh
load_project_local_env
: "${AI_STOCKS_TEST_USER_PASSWORD:?缺少本地调试账号密码}"

cd frontend
node --input-type=module <<'JS'
import { chromium, request } from "@playwright/test"

const apiBase = "http://127.0.0.1:8000/api"
const password = process.env.AI_STOCKS_TEST_USER_PASSWORD
const api = await request.newContext()
const login = await api.post(`${apiBase}/auth/login`, {
  data: { account: "debug_system", password },
})
if (!login.ok()) throw new Error(`debug_system login HTTP ${login.status()}`)
const body = await login.json()
if (body.code !== 0) throw new Error(body.msg || "debug_system login failed")
const data = body.data
const snapshot = {
  accessToken: data.access_token,
  refreshToken: data.refresh_token,
  user: {
    id: data.user.id,
    account: data.user.account,
    email: data.user.email ?? null,
    status: data.user.status ?? null,
  },
  tenant: { id: data.user.tenant_id },
  role: data.user.role,
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({
  viewport: { width: 1366, height: 768 },
})
const page = await context.newPage()
const consoleErrors = []
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text())
})
await page.addInitScript(([key, value]) => {
  window.localStorage.setItem(key, JSON.stringify(value))
}, ["ai-stocks-auth", snapshot])
const registry = page.waitForResponse(
  (response) =>
    response.url().includes("/api/indicators/registry")
    && response.status() === 200,
)
await page.goto(
  "http://127.0.0.1:5173/system/config/tech",
  { waitUntil: "domcontentloaded" },
)
await registry
await page.getByText("技术指标定义", { exact: false }).first().waitFor()

const labels = ["MACD DIFF", "MACD DEA", "MACD柱", "MACD金叉", "MACD死叉"]
for (const label of labels) {
  const row = page.locator(".el-table__row", { hasText: label })
  if (await row.count() !== 1) {
    throw new Error(`${label} row count is ${await row.count()}`)
  }
  const className = await row.locator(".el-switch").getAttribute("class")
  if (!className?.includes("is-checked")) {
    throw new Error(`${label} is not enabled`)
  }
}
if (consoleErrors.length) {
  throw new Error(`console errors: ${consoleErrors.join(" | ")}`)
}
console.log(
  `debug_system_tech_page=ok macd_rows=${labels.length} `
  + `enabled=${labels.length} console_errors=${consoleErrors.length}`,
)
await browser.close()
await api.dispose()
JS
```

实际结果：

```text
debug_system_tech_page=ok macd_rows=5 enabled=5 console_errors=0
```

## 6. 旧前端 detached worktree 回滚演练

`frontend/dist` 是本地构建产物，不在 Git 中直接提取。回滚必须切换到旧源码重新构建，
不能把当前 dist 误称为旧版本。

```bash
set -euo pipefail
cd /Users/pengshuaifeng/ai-stocks

T13_SNAPSHOT_DIR=${T13_SNAPSHOT_DIR:?先执行第 3 节并保留快照目录}
ROLLBACK_WORKTREE="$T13_SNAPSHOT_DIR/rollback-worktree"
case "$ROLLBACK_WORKTREE" in
  /var/tmp/ai-stocks-macd-t13.*/rollback-worktree) ;;
  *) echo "拒绝使用非 T13 临时工作树路径" >&2; exit 1 ;;
esac
test ! -e "$ROLLBACK_WORKTREE"

git worktree add --detach "$ROLLBACK_WORKTREE" 6169975
ln -s \
  /Users/pengshuaifeng/ai-stocks/frontend/node_modules \
  "$ROLLBACK_WORKTREE/frontend/node_modules"
npm --prefix "$ROLLBACK_WORKTREE/frontend" run build

ROLLBACK_DIST="$ROLLBACK_WORKTREE/frontend/dist"
export ROLLBACK_DIST
python - <<'PY'
import os
import re
from pathlib import Path

root = Path(os.environ["ROLLBACK_DIST"])
index = (root / "index.html").read_text(encoding="utf-8")
refs = re.findall(r'(?:src|href)="/([^"?]+)', index)
missing = [ref for ref in refs if not (root / ref).is_file()]
assert refs and not missing, (refs, missing)
print(
    f"rollback_index_refs={len(refs)} missing={len(missing)} "
    f"files={sum(1 for path in root.rglob('*') if path.is_file())}"
)
PY

if rg -l "stock-chart-workspace" "$ROLLBACK_DIST/assets" >/dev/null; then
  echo "rollback_workspace_marker=present"
else
  echo "rollback_workspace_marker=absent"
fi
if rg -l "stock-chart-workspace" frontend/dist/assets >/dev/null; then
  echo "current_workspace_marker=present"
else
  echo "current_workspace_marker=absent"
fi

git worktree remove --force "$ROLLBACK_WORKTREE"
git worktree list
```

实际结果：

```text
rollback_index_refs=3 missing=0 files=90
rollback_workspace_marker=absent
current_workspace_marker=present
/Users/pengshuaifeng/ai-stocks  9af8521 [main]
```

旧包只在临时 worktree 中构建和验证，未替换当前 `frontend/dist`。若当前
`node_modules` 不可复用，应在临时 worktree 中执行锁文件对应的 `npm ci`，不要修改依赖版本。

## 7. 五定义停用、seed 守卫与事务精确恢复

### 7.1 完整可复演命令

此命令把停用和精确恢复都放进显式事务；任何断言失败都会回滚当前事务。外层
`finally` 保证 seed 验证结束后尝试恢复五个定义，但执行前仍必须保留第 3 节快照。

```bash
set -euo pipefail
cd /Users/pengshuaifeng/ai-stocks
./start.sh stop

T13_SNAPSHOT_DIR=${T13_SNAPSHOT_DIR:?先执行第 3 节并保留快照目录}
export T13_SNAPSHOT_DIR
case "$T13_SNAPSHOT_DIR" in
  /var/tmp/ai-stocks-macd-t13.*) ;;
  *) echo "拒绝使用非 T13 快照目录" >&2; exit 1 ;;
esac
test -f "$T13_SNAPSHOT_DIR/indicator_def-before.parquet"

python - <<'PY'
import hashlib
import json
import os
from datetime import date, datetime
from pathlib import Path

import duckdb

from backend.indicators.definition import IndicatorDefRepo
from backend.storage.duckdb_client import DuckDBClient

DB = Path("data/ai_stocks.duckdb").resolve()
SNAPSHOT = Path(os.environ["T13_SNAPSHOT_DIR"]) / "indicator_def-before.parquet"
MACD = (
    "macd_diff",
    "macd_dea",
    "macd_hist",
    "macd_golden_cross",
    "macd_dead_cross",
)
KEY_SQL = ",".join(f"'{key}'" for key in MACD)
COLUMNS = [
    "key", "name_cn", "category", "dtype", "direction", "kind", "expression", "params",
    "enabled", "is_builtin", "descr", "created_at", "updated_at", "categories",
]
PROJECTION = ",".join(COLUMNS)


def connect_with_snapshot():
    con = duckdb.connect(str(DB))
    con.execute(
        "CREATE TEMP TABLE t13_before AS SELECT * FROM read_parquet(?)",
        [str(SNAPSHOT)],
    )
    return con


def symmetric_diff(con):
    return con.execute(
        f"""
        SELECT count(*) FROM (
          (SELECT {PROJECTION} FROM indicator_def
           EXCEPT SELECT {PROJECTION} FROM t13_before)
          UNION ALL
          (SELECT {PROJECTION} FROM t13_before
           EXCEPT SELECT {PROJECTION} FROM indicator_def)
        )
        """
    ).fetchone()[0]


def normalized_hash(con, source):
    rows = con.execute(
        f"SELECT {PROJECTION} FROM {source} ORDER BY key"
    ).fetchall()

    def scalar(value):
        if isinstance(value, (datetime, date)):
            return value.isoformat(sep=" ")
        return value

    records = [dict(zip(COLUMNS, map(scalar, row))) for row in rows]
    payload = (
        json.dumps(
            records,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    return len(records), hashlib.sha256(payload).hexdigest()


def non_macd_diff(con):
    return con.execute(
        f"""
        SELECT count(*) FROM (
          (SELECT * FROM indicator_def WHERE key NOT IN ({KEY_SQL})
           EXCEPT SELECT * FROM t13_before WHERE key NOT IN ({KEY_SQL}))
          UNION ALL
          (SELECT * FROM t13_before WHERE key NOT IN ({KEY_SQL})
           EXCEPT SELECT * FROM indicator_def WHERE key NOT IN ({KEY_SQL}))
        )
        """
    ).fetchone()[0]


disable_committed = False
try:
    con = connect_with_snapshot()
    try:
        assert symmetric_diff(con) == 0, "演练前当前表与快照不一致，拒绝停用"
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(
                f"""
                UPDATE indicator_def
                SET enabled=FALSE, updated_at=CURRENT_TIMESTAMP
                WHERE is_builtin=TRUE AND key IN ({KEY_SQL})
                """
            )
            disabled = con.execute(
                f"""
                SELECT count(*) FROM indicator_def
                WHERE enabled=FALSE AND key IN ({KEY_SQL})
                """
            ).fetchone()[0]
            builtin = con.execute(
                "SELECT count(*) FROM indicator_def WHERE is_builtin=TRUE"
            ).fetchone()[0]
            other_diff = non_macd_diff(con)
            assert (disabled, builtin, other_diff) == (5, 43, 0)
            con.execute("COMMIT")
            disable_committed = True
        except Exception:
            con.execute("ROLLBACK")
            raise
        print(
            f"disable_commit=ok disabled={disabled} "
            f"builtin={builtin} non_macd_diff={other_diff}"
        )
    finally:
        con.close()

    with DuckDBClient(DB) as client:
        seeded = IndicatorDefRepo(client).seed_builtins()
        disabled_after_seed = int(
            client.query_df(
                f"""
                SELECT count(*) AS n FROM indicator_def
                WHERE enabled=FALSE AND key IN ({KEY_SQL})
                """
            ).iloc[0]["n"]
        )
        assert (seeded, disabled_after_seed) == (43, 5)
        print(
            f"seed_guard=ok seeded={seeded} "
            f"disabled_after_seed={disabled_after_seed}"
        )
finally:
    if disable_committed:
        con = connect_with_snapshot()
        try:
            con.execute("BEGIN TRANSACTION")
            try:
                assert non_macd_diff(con) == 0, (
                    "停用后出现非 MACD 变更，拒绝覆盖并保持停服"
                )
                assignments = ", ".join(
                    f"{column}=b.{column}"
                    for column in COLUMNS
                    if column != "key"
                )
                con.execute(
                    f"""
                    UPDATE indicator_def AS d
                    SET {assignments}
                    FROM t13_before AS b
                    WHERE d.key=b.key AND d.key IN ({KEY_SQL})
                    """
                )
                restored_enabled = con.execute(
                    f"""
                    SELECT count(*) FROM indicator_def
                    WHERE enabled=TRUE AND key IN ({KEY_SQL})
                    """
                ).fetchone()[0]
                restored_diff = symmetric_diff(con)
                assert (restored_enabled, restored_diff) == (5, 0)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise

            live_rows, live_hash = normalized_hash(con, "indicator_def")
            before_rows, before_hash = normalized_hash(con, "t13_before")
            assert (live_rows, live_hash) == (before_rows, before_hash)
            print(
                f"restore_commit=ok enabled={restored_enabled} "
                f"full_table_diff={restored_diff}"
            )
            print(
                f"normalized_hash=ok rows={live_rows} sha256={live_hash}"
            )
        finally:
            con.close()
PY

./start.sh
./start.sh status
```

### 7.2 本次实际结果

2026-07-25 17:27 CST 直接从本 Markdown 提取以上命令块重新演练，输出为：

```text
disable_commit=ok disabled=5 builtin=43 non_macd_diff=0
内置指标定义校准完成：总数 43，变更 0
seed_guard=ok seeded=43 disabled_after_seed=5
restore_commit=ok enabled=5 full_table_diff=0
normalized_hash=ok rows=44 sha256=b5fa225e96a93e01698c15b2e3969faf91073bb19a9079421c3902fcd9807a3b
/api/health=200
```

该结果证明：

- scoped 停用只影响五个 MACD builtin；
- 完整 seed 不会覆盖管理员明确停用；
- 恢复覆盖五行的所有持久化字段，包括 `enabled`、`categories`、`created_at` 和
  `updated_at`；
- 恢复后当前表与发布前快照双向 `EXCEPT` 差异为 0；
- 恢复后的规范化哈希与发布前快照一致。

## 8. 最终现场

```bash
cd /Users/pengshuaifeng/ai-stocks
git status --short
git worktree list
./start.sh status
curl -sS -o /dev/null -w 'frontend_5173=%{http_code}\n' \
  http://127.0.0.1:5173
curl -sS http://127.0.0.1:8000/api/health/e2e
```

本次最终结果：

```text
工作区无非预期改动（补文档前）
仅保留主工作树
/api/health=200
frontend_5173=200
{"code":403,"msg":"E2E 写环境未启用","data":null}
```

快照保留仅用于本地审计。确认不再需要后，可删除本轮明确的
`/var/tmp/ai-stocks-macd-t13.4FRO57` 目录；不得使用未解析变量、通配符或宽泛路径清理。
