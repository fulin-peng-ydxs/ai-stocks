# 连板天梯 T11 后端综合测试与代表性规模报告

归档状态：已归档

## T17 快照窗口冻结回归

- 2026-08-31 在隔离临时 DuckDB 上重跑 5,200 股 × 61 交易日（317,200 条日线）完整入口，新增的 10/20/31/60 日窗口指标与快照同事务落表。
- 首次物化 2.746276s，二次物化 2.61609s，查询 0.018221s/0.016191s，失效后旧版读取 0.015591s，全链路 7.033921s。
- 发布 257 股、最高 5 板、CSV 257 行、两个不可变版本；连续板主计算批量查询仍为 2，无逐股查询，临时数据库零残留。

## 1. 结论

- 连板天梯后端聚焦测试共 90 项，全部通过。
- 代表性规模夹具覆盖 5,200 只股票、61 个交易日和 317,200 条日线，通过真实领域服务完成数据加载、完整性门禁、计算、不可变快照落表、状态指针切换、查询、热点聚合、CSV、失效及失效后旧版本读取。
- 规模链路发布 257 只涨停股票，最高 5 板；批量计算只执行 2 次读取查询，未出现逐股查询。
- 二次物化生成两个不可变成功版本并切换状态指针；夹具结束后临时 DuckDB 文件随临时目录自动删除，不读写项目 `data/`、PostgreSQL 或外部网络。

## 2. 验证环境与命令

- 系统：macOS 15.0 arm64
- Python：3.12.7
- DuckDB：1.5.3
- pandas：2.2.2

```bash
python -m pytest backend/tests/test_limit_ladder_*.py -q
python -m backend.devtools.benchmark_limit_ladder_pipeline
```

规模入口 `backend/devtools/benchmark_limit_ladder_pipeline.py` 默认创建独立临时数据库，并在异常或正常退出时由临时目录生命周期统一清理。它直接调用 `LimitLadderSnapshotService`、`LimitLadderCalculator` 和 `LimitLadderQueryService`，不以 Mock 响应替代业务链路。由于入口不接触项目 DuckDB 和 PG，无需扩大 `start.sh` 的生产运维命令面。

## 3. 代表性规模结果

| 指标 | 结果 |
| --- | ---: |
| 股票数 | 5,200 |
| 交易日数 | 61 |
| 日线行数 | 317,200 |
| 预期/实际发布股票数 | 257 / 257 |
| 最高板位 | 5 |
| CSV 数据行 | 257 |
| 批量计算读取查询数 | 2 |
| 首次物化 | 1.863907 秒 |
| 首次查询 | 0.771625 秒 |
| 失效 | 0.005067 秒 |
| 失效后旧版本读取 | 0.606079 秒 |
| 二次物化 | 1.709881 秒 |
| 二次查询 | 0.639311 秒 |
| 夹具生成 | 0.592290 秒 |
| 批量验证 | 0.969387 秒 |
| 全流程 | 7.863179 秒 |
| 成功快照版本数 | 2 |
| 临时数据库已删除 | 是 |

需求与计划未规定硬性耗时 SLA，因此本阶段的阻断条件是结果正确、批量查询边界成立、发布/失效/旧版本读取闭环成立以及夹具可清理；上述条件全部满足。

## 4. 后端验收证据映射

| 验收方向 | 证据 |
| --- | --- |
| 市场规则、普通/ST/20% 板块、特殊上市日、停牌和无效价格 | `backend/tests/test_limit_ladder_rules.py` |
| DDL、状态枚举、PG 协调账本终态释放、审计唯一性 | `backend/tests/test_limit_ladder_storage.py` |
| 点时 ST 历史、75 连板、批量读取、概念聚合、缺失及短历史 | `backend/tests/test_limit_ladder_t3.py` |
| coverage 原因、结构化采集终态、合法空、原子回滚、失败保留、失效和指纹 | `backend/tests/test_limit_ladder_t4.py` |
| 三来源四种先后顺序、活动态幂等、权威身份、outbox、interrupted 和任务处理器 | `backend/tests/test_limit_ladder_t5.py` |
| 查询、筛选状态、降级、CSV 和接口权限 | `backend/tests/test_limit_ladder_t6.py` |
| 菜单、资源与 RBAC seed 契约 | `backend/tests/test_limit_ladder_t7.py` |
| 200 股 × 60 日规模契约及批量查询上限 | `backend/tests/test_limit_ladder_t11.py` |
| 5,200 股 × 61 日真实服务全链路、两版本发布和自动清理 | `backend/devtools/benchmark_limit_ladder_pipeline.py` |

## 5. 阶段边界与配套检查

本阶段只完成 T11 的后端综合测试、代表性规模验证、夹具生命周期和证据文档，没有提前开发 T12 的前端综合回归。没有页面改动，因此不新增浏览器截图；没有新增权限码、菜单、配置、SQL、seed、部署参数、生产表或生产数据写入，因此无需新增相应迁移和运维记录。
