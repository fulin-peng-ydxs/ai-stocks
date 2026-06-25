# Repository Guidelines

## 项目结构与模块组织

本仓库是本地单用户的 A 股趋势龙头研究系统，采用 FastAPI + Vue + DuckDB。后端代码位于 `backend/`：`api/` 放 REST 路由，`services/` 放业务编排，`storage/` 管理 DuckDB 与 DDL，`indicators/`、`screening/`、`scoring/`、`backtest/` 放核心领域逻辑，测试位于 `backend/tests/`。前端位于 `frontend/`，核心目录包括 `src/views/`、`src/components/`、`src/api/`、`src/layout/`、`src/stores/`。配置在 `config/settings.yaml`，运行数据在 `data/`，日志在 `logs/`，设计和业务留痕文档在 `DESIGN.md` 与 `agent-works/`。

## 版本要求

- Python：`>=3.11`，本机常用 3.12；依赖以 `pyproject.toml` 和 `requirements.txt` 为准。
- Node.js：建议使用 20 LTS；前端锁文件为 npm lockfile v3，使用 npm 安装。
- 主要后端版本：FastAPI `>=0.110`、DuckDB `>=0.10`、pandas `>=2.2`、pytest `>=8.0`。
- 主要前端版本：Vue `^3.4`、Vite `^5.2`、TypeScript `^5.4`、Vitest `^1.6`、Element Plus `^2.7`。

## 构建、测试与开发命令

```bash
pip install -r requirements.txt
cd frontend && npm install
./start.sh              # 启动后端开发服务，监听 127.0.0.1:8000
./start-web.sh          # 启动前端 Vite，访问 http://localhost:5173
pytest                  # 运行后端测试
cd frontend && npm test # 运行前端 Vitest
cd frontend && npm run build
```

生产/集成模式先执行 `frontend` 构建，再运行 `./start.sh prod`，由后端托管 `frontend/dist`。

## 编码风格与命名约定

后端遵循 Python 3.11+ 类型标注习惯，Ruff 配置为 `line-length = 100`、`target-version = py311`。路由层保持薄封装，复杂业务放入 `services/` 或领域模块。测试文件使用 `test_*.py`。前端使用 Vue 3 Composition API 与 TypeScript，组件文件采用 PascalCase，例如 `StockDetailView.vue`；API 封装放在 `frontend/src/api/*.ts`，布局相关逻辑放在 `frontend/src/layout/`。

## 测试指南

后端测试框架为 pytest，默认扫描 `backend/tests/test_*.py`。新增后端业务逻辑时，优先补充领域或服务层单测；涉及数据口径、防未来函数、DDL、回测撮合时必须覆盖边界条件。前端测试使用 Vitest，当前重点在 `frontend/src/layout/__tests__/`；新增布局、校验或配置合并逻辑时同步补充 `*.spec.ts`。

## 前端页面与布局治理

前端页面、组件、布局、表格、弹窗、抽屉改动以 `DESIGN.md` 为规范事实源，以 `agent-works/configurable-layout-system/page-template.md` 为计划模板。`AGENTS.md` 只保留入口要求，不重复前端细则；计划需说明是否触发页面设计闭环和组件/布局维护矩阵。

## 提交与 Pull Request 要求

Git 历史采用中文语义化风格，例如 `Agent 新增(基础功能): ...`、`Agent 更新(数据管理): ...`。提交信息应说明变更类型、影响模块和核心结果。PR 需包含变更摘要、测试结果、关联需求或问题；涉及 UI 的改动附截图，涉及数据结构或配置的改动说明迁移与兼容性。

## 安全与配置提示

不要提交 `data/` 中的本地数据库、`logs/` 日志或个人环境配置。`prod` 会绑定 `0.0.0.0:8000`，系统无登录鉴权，不应直接暴露到公网。调整策略参数优先修改 `config/settings.yaml` 或页面配置，避免把临时研究参数写死在代码中。
