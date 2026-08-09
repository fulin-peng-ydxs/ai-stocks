# 概念 / 行业板块实施计划与状态

## 1. 当前结论

板块功能采用四表模型，并已接入数据管理全链路。采集闭环不是以“能抓到数据”为完成标准，而是以下各层均成立：

- 来源适配与配置；
- DDL、迁移和目录；
- 全量 / 增量编排；
- 异步任务、写互斥、日志、终止和续跑；
- 每日流程、CLI 和定时任务；
- 质量扫描、定向修复和复检；
- 数据概览和数据源健康；
- 板块业务查询 API 和 RBAC；业务页面仍待实施，不计入本轮数据管理闭环完成范围；
- 自动化测试与事实文档。

## 2. 实施状态

| 工作项 | 状态 | 主要落点 |
| --- | --- | --- |
| T1 数据源事实验证 | 已完成 | `backend/datasource/ths_board.py`、`research.md` |
| T2 四表 DDL 与迁移 | 已完成 | `backend/storage/ddl.py` |
| T3 字典 / clid 采集 | 已完成 | `backend/services/board_ingest.py` |
| T4 成分完整快照 | 已完成 | `backend/services/board_ingest.py` |
| T5 指数全量 / 增量 | 已完成 | `backend/services/board_ingest.py`、`backend/services/ingest.py` |
| T6 资金流采集和校验 | 已完成 | `backend/services/board_ingest.py` |
| T7 异步任务与续跑 | 已完成 | `backend/services/async_task.py` |
| T8 每日流程、CLI、定时任务 | 已完成 | `backend/services/pipeline.py`、`backend/cli.py`、`backend/scheduler/scheduler.py` |
| T9 质量发现 / 修复 / 复检 | 已完成 | `backend/services/data_report.py`、`backend/dataquality/checker.py` |
| T10 数据概览 / 目录 / 健康 | 已完成 | `backend/api/data_admin.py`、`backend/storage/catalog.py`、`backend/services/data_sources.py` |
| T11 板块只读 API 与查询性能 | 已完成 | `backend/api/sectors.py`、`backend/services/board_query.py` |
| T12 数据管理前端承接 | 已完成 | `frontend/src/views/data/OverviewView.vue`、`IngestView.vue`、`ScheduleView.vue`、`QualityView.vue` |
| T13 板块业务页面 | 待实施 | 后端 `/api/sectors*` 与 `sectors:view` 已完成；前端页面、路由、pageRegistry 尚未落地 |
| T14 数据管理自动化验证 | 已完成 | 后端 pytest、前端 Vitest / build、数据管理相关 Playwright |
| T15 事实文档同步 | 已完成 | 本目录四份文档 |

## 3. 采集实现基线

### 3.1 数据结构

- `board_dict`：字典、路径代码、App clid、能力、最近完整快照元数据；
- `board_member`：累计出现过的成员关系，只进不出；
- `board_bar`：板块指数日线；
- `board_fund_flow`：板块资金流多周期。

没有 `board_member_candidate`，没有成员进出日期，没有成分波动阈值。

### 3.2 模式

- 增量：最近开市日附近指数 + 即时资金流；
- 全量：2024-01-01 起指数 + 五个资金流周期；
- 两种模式都会刷新字典并拉完整成分快照；
- 支持分表、指定板块和 limit。

### 3.3 失败语义

- 字典类型、成分板块、指数板块 / 年份、资金流类型 / 周期各自隔离；
- 成功数据保留，失败项进入统一 `failed` 清单；
- `failed` 非空时 `ok=false`；异步任务和流水线必须标失败；
- 只有成功工作单元写 checkpoint，失败工作单元可续跑；
- `data_update_log` 使用 `partial` 表示同一步骤内部分成功。

## 4. 质量与修复计划基线

| 问题 | 扫描 | 修复 | 复检 |
| --- | --- | --- | --- |
| 成分快照不完整 | 采集时写问题 | 重采单板块成员 | 新完整快照时间 + 无活动同类问题 |
| 板块指数滞后 | 与全局行情最新日比较 | 重采单板块指数 | 最新日追平 |
| 资金流未匹配 | 采集时按名称写问题 | 刷新字典 + 重采即时资金流 | 详情名称 / 类型可映射 |

修复失败或复检未过回到 `open`；修复成功才 `resolved`。板块问题扫描事务化替换，扫描异常保留上一轮问题。

## 5. 数据管理对齐矩阵

| 现有数据管理能力 | 板块接入状态 |
| --- | --- |
| 手动异步任务 | 已接入 `board` |
| 写库互斥 | 已接入 |
| 实时日志 | 已接入四阶段与单元日志 |
| 终止 / 续跑 | 已接入阶段 checkpoint |
| 部分失败 | 已接入 `ok=false` 和 `partial` 日志 |
| 每日流程 | 默认增量，可跳过 |
| CLI | `board --update/--backfill` + 分表 / codes / limit |
| 定时任务 | 默认增量，页面可选全量 |
| 数据源健康 | `ths_board` 可见并可测试 |
| 数据目录 | 四表字段、鲜活度、问题映射 |
| 数据概览 | 分类数、覆盖率、最新日、问题分项、最近更新 |
| 质量台账 | 三种板块问题 |
| 单条 / 按类型修复 | 已接入 |

## 6. 测试计划

### 后端专项

- `backend/tests/test_ths_board_source.py`：解析、cookie、clid 缓存、部分年份；
- `backend/tests/test_board_ingest.py`：四阶段写入、实际新增数、完整性、映射幂等、资金流算术、checkpoint；
- `backend/tests/test_pipeline.py`：每日流程、部分失败、定时模式、目录；
- `backend/tests/test_data_mgmt_b.py`：异步失败态、续跑、扫描事务、三类修复、概览；
- `backend/tests/test_sectors_api.py`：列表、详情、走势、成员、排序、分页和查询口径。

### 前端

- Vitest：任务标签和关键状态映射；
- `npm run build`：TypeScript 与产物同步；
- Playwright：数据概览板块摘要、跳转采集；任务调度板块模式创建链路。

### 执行约束

可能访问项目 DuckDB 的测试前先执行 `./start.sh status`；若后端运行则通过脚本停服，结束后按原状态恢复。Playwright 使用 5181，后端由 `start.sh` 管理，按 E2E guide 准备调试用户和环境门控。

## 7. 交付检查

- [x] 采集返回结果真实反映部分失败；
- [x] 成分完整性与最近成功快照有明确证据；
- [x] 指数年份失败不被错误 checkpoint；
- [x] 资金流范围、算术和未匹配问题闭环；
- [x] 定时任务默认模式持久化；
- [x] 概览和目录包含板块细分状态；
- [x] 修复复检不依据历史脏值误解决；
- [x] 文档删除旧 diff / 候选 / 阈值方案；
- [x] 本轮全部验证命令通过并记录结果。
- [x] 事实文档不再把尚未落地的 `/sectors` 前端页面标记为已完成。

## 8. 发布与回滚

发布前确认后端专项测试、前端测试 / build 和相关 E2E 通过。DDL 变更只新增 `member_snapshot_at`，旧库通过 `ADD COLUMN IF NOT EXISTS` 幂等迁移。

回滚代码时保留已写板块数据和新增列，避免破坏性删表；停用入口和调度即可停止后续采集。不得删除本地数据库作为回滚手段。
