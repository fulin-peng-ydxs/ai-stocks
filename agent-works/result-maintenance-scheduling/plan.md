# ST 输入版本驱动的结果缓存自检开发计划

## 1. 目标与结论

本期不扩展“上游任务结果驱动下游任务”的调度协议，也不新建 ST 下游维护事件。改造目标是让每日榜单和连板天梯在读取缓存时，基于当前已发布的 ST 点时事实判断已有结果能否继续命中：

- ST 事实没有有效变化：直接使用原缓存，不失效、不重算；
- ST 事实发生变化：只处置本次正在读取的榜单或天梯结果，复用已有重算路径；
- ST 专项刷新尚未完整发布：拒绝把旧缓存声明为当前有效，避免双态交叉；
- 采集任务不调用评分或天梯服务，继续保持生命周期独立；
- 手动和调度型结果维护任务保持原能力，用于用户主动强制维护以及非 ST 数据变化。

这属于现有缓存契约的扩展，不是现有调度依赖的扩展。

## 2. 当前事实与缺口

### 2.1 已有可复用能力

| 能力 | 当前实现 | 本期复用方式 |
| --- | --- | --- |
| ST 变化识别 | `StockSTStatusService.upsert_facts()` 只对新事实或值/来源/质量变化更新 `updated_at`；相同数据重采不更新 | 从当前事实表生成稳定的日期范围版本 |
| ST 发布门 | `stock_st_status_refresh_state` 与 `assert_published()` | 缓存命中前先确认当前批次已发布 |
| 榜单缓存 | PG `score_snapshot_meta` 的 `stale/param_hash/computed_at`，未命中后锁内物化 | 增加 ST 输入版本判断，复用 `_materialize_locked()` |
| 天梯快照 | DuckDB `limit_ladder_snapshot_state`、不可变 snapshot、日期任务协调器 | 版本不一致时标记当前 T 日失效，复用 `ensure_date_task()` |
| 天梯计算保护 | 发布前后比较 `upstream_fingerprint` | 将历史 ST 输入版本纳入发布前后一致性校验 |
| 强制结果维护 | `recompute`、`limit_ladder_invalidate` | 保持不变，继续供手动和调度使用 |

### 2.2 当前不能直接满足的地方

1. `score_snapshot_meta` 只保存指标参数指纹，没有记录生成榜单时使用的 ST 输入版本，因此当前有效缓存无法判断 ST 是否变化。
2. 天梯的 `upstream_fingerprint` 主要覆盖 T 日股票池、行情和归属，并在计算发布期间比较；它没有形成“截至 T 日全部历史 ST 依赖”的轻量读取版本。
3. 榜单 `_fresh()` 和天梯有效快照读取路径没有统一调用 ST 发布门；已有缓存可能绕过 `status_map()` / `check_coverage()`，在 ST 全量刷新中继续被当成有效结果。
4. 现有调度依赖只支持 `success/failure/completion` 和静态参数，但本方案不要求改它：判断应发生在缓存读取端，而不是依赖上游任务。

## 3. 核心口径

### 3.1 什么叫“ST 发生变化”

以 `stock_st_status_daily` 当前事实为准。受支持写入路径只有在以下情况发生时才更新该行 `updated_at`：

- 原来没有事实，现在新增；
- `is_st` 改变；
- `source/source_ref` 改变；
- `quality` 改变。

相同事实重采不会更新 `updated_at`，因此不会导致缓存版本变化。`captured_at` 不是缓存失效依据。

第一期按“任何权威事实内容变化”处理，不只比较 `is_st`。原因是天梯快照同时冻结 `st_source/st_quality` 作为审计证据；来源或质量变化后继续宣称旧快照完全对应当前事实并不严谨。后续若需要进一步减少重算，可再引入按消费方区分的 `value_version/audit_version`，本期不提前复杂化。

### 3.2 ST 输入版本

在 `StockSTStatusService` 增加只读版本方法，返回带格式版本号的字符串，例如：

```text
st-v2:<scope>:<target_date>:<date_count>:<revision_sum>:<max_updated_at_iso>
```

范围分两种：

- `date=D`：榜单使用，只覆盖 D 日事实；
- `through=T`：天梯使用，覆盖 `trade_date <= T` 的事实。

真实 636 万行规模测试表明直接聚合历史事实超过 80ms 门槛，因此实现日期级修订账本 `stock_st_status_date_revision`。`upsert_facts()` 每次真实变化都与事实写入同事务递增相应日期；单日读取一行，截至日只聚合约千级日期行。存量库按当前事实数加不可变历史数建立修订基线，已有修订行不覆盖。生产代码不支持绕开服务物理删除 ST 当前事实；若未来新增删除入口，必须同事务维护修订号。

版本计算必须先检查发布门。`refreshing/failed` 不返回可比较版本，而是抛出已有的 `STStatusNotReadyError`。

### 3.3 各业务依赖范围

| 结果 | ST 版本范围 | 不一致后的动作 |
| --- | --- | --- |
| D 日某评分方案榜单 | 仅 D 日 | 当前日期、当前方案缓存不命中；可写入口锁内重算，只读入口返回未命中 |
| T 日连板天梯 | 截至 T 日 | 仅把当前 T 日状态标记失效；当前请求复用日期协调器创建单日重算 |
| 历史回测 | 运行区间版本已进入运行签名 | 不改旧结果；新运行使用当前版本 |

天梯采用 `<=T` 的保守范围，是因为连续板高度没有固定回溯上限，且 10/20/31/60 日窗口指标也使用历史 ST。D 日变化只会让读取的 `T>=D` 快照版本不一致；`T<D` 的版本查询自然不包含 D，不会误重算。

## 4. 目标运行流程

### 4.1 榜单

```text
请求 D 日榜单
  → assert_published()
  → 计算当前 ST date=D 版本
  → 读取 score_snapshot_meta
      ├─ stale=true / 参数指纹不一致 / ST版本为空或不一致
      │    ├─ get_board_cached：返回缓存未命中
      │    └─ get_board：进入现有 PG advisory lock
      │          → 锁内再次校验
      │          → 记录 ST version_before
      │          → score_day()
      │          → 记录 ST version_after
      │          → 前后一致才替换快照并保存版本
      └─ 全部一致：读取现有明细
```

ST 发布态不是 `ready` 时不重算，也不返回“有效缓存”。旧 PG 明细保留，待 ST 恢复 ready 后再判断版本。

### 4.2 连板天梯

```text
请求 T 日天梯
  → assert_published()
  → 计算当前 ST through=T 版本
  → 读取 limit_ladder_snapshot_state.st_input_version
      ├─ 无快照：沿用首次访问任务
      ├─ 版本为空或不一致：短事务把 T 标 invalid
      │    → 沿用 ensure_date_task(T)
      │    → 页面返回旧快照 + stale/recalculating 真实状态
      └─ 版本一致：直接读取现有快照
```

天梯计算开始前记录版本，正式发布事务前再次读取版本；版本变化或发布门关闭时拒绝切换 `current_snapshot_id`，保留最后成功快照。

`status()` 只报告版本状态，不主动创建计算任务；`query(trigger_missing=true)` 才沿用现有规则触发重算。CSV 的 `trigger_missing=false` 不创建任务，版本不一致时拒绝把旧数据导出成有效结果。

## 5. 数据结构调整

### 5.1 PostgreSQL

为 `score_snapshot_meta` 增加：

```text
st_input_version TEXT NULL
```

- 新生成快照必须非空写入；
- 存量行保持 NULL，首次读取按失效处理并自愈；
- 不回填伪版本，因为无法证明旧快照使用过哪一版 ST；
- 继续遵守 `tenant_id + owner_user_id` 归属和现有复合主键。

### 5.2 DuckDB

为以下两表增加：

```text
limit_ladder_snapshot.st_input_version VARCHAR NULL
limit_ladder_snapshot_state.st_input_version VARCHAR NULL
stock_st_status_date_revision(trade_date DATE PRIMARY KEY, revision BIGINT, updated_at TIMESTAMP)
```

- snapshot 列保存不可变审计证据；
- state 列供读取端轻量比较；
- 存量 NULL 首读自愈，不覆盖旧 snapshot；
- 新版本原子发布时两处写入同一个版本。

### 5.3 迁移要求

- 更新 `backend/storage/pg_ddl.py`、`backend/storage/ddl.py` 的新库 DDL和幂等补列迁移。
- 在 `agent-works/result-maintenance-scheduling/` 增加专项升级 SQL，写明执行时机、影响范围和回滚方式。
- 启动初始化后校验新列存在；旧数据不做批量重算。
- 本期不新增任务表、不修改 `scheduled_job` 或 `scheduled_trigger_event` 结构。

## 6. 代码改造清单

### T1：ST 版本服务

涉及：`backend/services/stock_st_status.py`、对应测试。

- 新增 `input_version_for_date(D)` 和 `input_version_through(T)`，内部复用日期修订账本聚合方法。
- 统一时间序列化到微秒，不使用秒级截断。
- 版本计算前调用 `assert_published()`。
- 空范围也返回稳定版本，不把“0 行”误当异常；业务自身的 coverage 继续决定能否计算。
- 增加相同事实重采版本不变、新增/修改版本变化、未来日期不影响历史版本、发布门关闭拒绝读取测试。

### T2：榜单缓存接入

涉及：`backend/scoring/snapshot.py`、PG DDL/迁移、榜单服务与测试。

- `_fresh/_fresh_cur` 同时比较 `stale`、`param_hash`、`st_input_version`。
- `get_board/get_board_cached` 在命中缓存前走 ST 发布门和 D 日版本。
- `_materialize_locked` 等锁后重新读取版本，避免等待期间事实已变化。
- `score_day()` 前后比较版本；不一致时不得删除/覆盖旧明细，可有限重试一次，仍变化则返回明确错误。
- `_replace_snapshot_cur` 与快照明细同一 PG 事务写入版本。
- 保持 owner/tenant 过滤不变；ST 版本从 DuckDB 单独读取后以内存参数参与 PG 判断，不做跨库 JOIN。

### T3：天梯缓存接入

涉及：`backend/services/limit_ladder_snapshot.py`、`limit_ladder_query.py`、DuckDB DDL/迁移及测试。

- coverage 增加 `st_input_version`，并纳入计算前后的一致性判断。
- 发布时同时写 snapshot 和 state 版本。
- 查询到 `valid` 快照后比较当前 `through=T` 版本；不一致时使用原因 `st_input_version_changed` 将当前 T 标记 invalid。
- 继续使用 `LimitLadderTaskCoordinator.ensure_date_task()`，不直接在请求线程计算。
- 同日并发读取复用现有 PG 同日活动命令，不能重复创建任务。
- ST 发布门未 ready 时返回明确业务码，不把状态改成“已成功重算”，也不丢弃最后成功 snapshot。
- 导出接口发现版本不一致时拒绝导出旧结果并提示先等待/打开页面完成重算。

### T4：接口与页面状态

涉及：榜单、天梯 API 响应，`LimitLadderView`、榜单页面及相关组件测试。

- 增加统一可读业务码 `ST_STATUS_NOT_READY`；真实版本变化沿用已有 `SNAPSHOT_STALE/recalculating`，并以 `invalid_reason=st_input_version_changed` 提供诊断。复用现有状态组件，不新增平行页面。
- 天梯显示“ST 事实已变化，正在重算/等待重算”；若保留旧快照展示，必须带明显过期标记。
- 榜单只读缓存未命中时区分“从未计算”和“ST 输入已变化”。
- 数据概览和 ST 架构说明补充“结果在读取时校验”的口径。

### T5：手动任务与调度兼容

涉及：`backend/services/result_maintenance.py`、`async_task.py`、`scheduler.py`、任务页面回归测试；原则上不改业务逻辑，只补兼容证明。

- `recompute` 继续按用户选择的最新/固定/全部范围显式标记榜单 stale。
- `limit_ladder_invalidate` 继续按用户选择的起始日向后失效。
- `success/failure/completion` 条件、延迟、重试和静态参数完全不变。
- 已存在的 ST采集→榜单/天梯依赖继续按原配置触发；系统不自动删除或转换。
- 即使依赖任务先标记失效，读取端版本校验仍是幂等的：已 stale/invalid 时不重复制造结果或任务。
- 调度页补一条说明：结果读取会自动校验 ST；依赖关系仍适合盘后预维护、非 ST 数据变化或希望提前标记整段失效的场景。
- 页面改动只补状态说明和已有控件文案，复用 `AppStateBlock/AppStatusNotice` 与现有结果维护表单；不新增页面、布局或视觉模式，不触发设计系统重构。实现前仍按 `frontend-reuse-enforcer` 检查同类状态组件。

### T6：文档与数据字典

- 更新 `agent-works/architecture/st-status.md`：补充两个版本范围、缓存读取门和发布竞态保护。
- 更新 `agent-works/architecture/limit-ladder.md`、`screening-and-board.md`、`platform.md`。
- 更新数据字典中的新增字段、是否可空、存量 NULL 自愈语义。
- 更新本功能闭环文档的“不自动联动”表述，明确采集联动与读取自检的区别。

## 7. 已有依赖任务的影响

### 7.1 不变的行为

- 不迁移 `scheduled_job.dependency_condition`。
- 不修改任何现有任务的 `params`、启停状态、依赖上游、延迟或重试配置。
- 现有“成功后”仍是上游状态为 done 就触发，不增加“有变化”条件。
- 现有依赖事件仍按原 `source_task_id + attempt + target_job_id` 幂等。

### 7.2 可能出现但属于正确幂等的重复判断

若用户已经配置“ST 刷新成功后执行榜单/天梯失效”：

1. 该依赖任务仍会先按原参数标记结果失效；
2. 结果读取时再次检查 ST 版本；
3. 因状态已经 stale/invalid，只会沿用现有重算，不会重复创建同日天梯任务；
4. 该依赖可能在 ST 无变化时仍按原约定执行，这是用户既有配置，不自动改变。

上线后可以在调度页提示用户：如果该依赖只为 ST 变化而建，可以人工停用；如果还承担盘后预维护或其他数据变化维护，则继续保留。系统不得擅自删除。

### 7.3 当前运行配置核对

本计划编写时已只读检查当前 `scheduled_job`：没有直接以 `stock_ingest(recipe=st_status_refresh)` 为上游的榜单或天梯失效任务，因此不存在“ST 自检刚重算、延迟依赖随后又失效”的现成冲突。

当前相关链路不能因本功能删除：

- “个股滞后修复 → 每日榜单失效”还覆盖历史行情补齐等非 ST 输入变化；
- “走势相关重算 → 连板天梯失效”还覆盖天梯冻结的行业/概念归属变化；
- 质检、板块修复和走势相关的其他依赖仍有独立业务意义。

因此上线迁移只增加说明和兼容测试，不自动停用任何实际任务。如果以后发现直接 ST 刷新依赖，页面给出“可选精简”提示，由用户决定是否停用。

## 8. 性能与并发设计

- 榜单版本查询只聚合单个交易日，目标规模约全市场股票数。
- 天梯版本查询聚合 `trade_date<=T` 的日期修订行，不扫描历史 ST 事实。
- 验收目标：单日版本查询 p95 ≤ 20ms，截至日版本查询 p95 ≤ 80ms，不得让缓存命中退化为重计算级开销。
- 首轮真实库基准：单日事实聚合冷/热约 7.2/4.9ms；截至日事实聚合冷/热约 282/157ms，不达标，因此启用日期修订账本。
- 迁移后 6,374,331 条 ST 事实、1,283 个日期修订行实测：单日 30 次中位 1.706ms、最大 10.071ms；截至日中位 1.540ms、最大 2.082ms。重复 `init_db()` 约 103.6ms，迁移守卫不会在已有账本时重扫全量事实，满足门槛。
- 榜单同日期同方案继续由 PG advisory lock 防重；天梯同日期继续由 PG 活动态唯一约束防重。
- 版本比较采用“计算前 + 发布前”双检。检测到变化时保留旧成功结果，不发布半成品。

## 9. 测试计划

### 9.1 后端单元与集成

1. 相同 ST 重采：榜单缓存命中、天梯快照命中，不产生重算。
2. D 日 `is_st` 改变：D 日榜单当前方案重算；D-1/D+1 榜单不被读取动作连带修改。
3. D 日任一权威字段改变：读取 T<D 天梯仍命中；读取 T>=D 天梯进入 stale/recalculating。
4. 存量 NULL 版本：首次读取自愈；第二次稳定命中。
5. `refreshing/failed`：两类业务均不把旧缓存声明为有效。
6. 计算期间 ST 版本变化：拒绝发布，旧结果保留。
7. 同日并发天梯读取：只创建一个活动命令和一个异步任务。
8. 榜单 `get_board_cached` 不写库；`get_board` 才允许物化。
9. 手动 `recompute/limit_ladder_invalidate` 原测试全部保持通过。
10. `test_pipeline.py` 覆盖已有三种依赖条件、事件分发、延迟、重试和编辑后语义完全不变。
11. PostgreSQL 与 DuckDB 分别查询、内存比较，增加禁止跨库 SQL 的回归断言。

### 9.2 前端

- 天梯 ST 变化、刷新中、刷新失败、重算中和旧结果保留状态。
- 榜单缓存失效与首次无结果文案不混淆。
- 现有调度编辑表单加载和保存旧依赖条件不变。
- 结果维护卡片继续可以手动执行，不因自动自检隐藏。

### 9.3 代表性规模

- 使用约 5,200 股、近 5 年 ST 事实测单日与截至日版本聚合。
- 连续访问同一榜单/天梯 100 次，验证只有版本查询和缓存读取，没有重复重算或任务创建。
- 修改一个历史 ST 事实后并发访问同一 T 日天梯，验证只创建一个重算任务。

## 10. 发布、迁移与回滚

### 发布顺序

1. 先执行/验证 PG 与 DuckDB 幂等补列。
2. 部署后端版本服务和写入新版本能力。
3. 开启读取自检；存量 NULL 快照随访问渐进自愈。
4. 部署前端状态说明。
5. 观察版本查询耗时、ST 门禁错误数和重算任务创建量。

### 回滚

- 回滚应用代码后，新列保留不影响旧版本；它们是可空扩展列。
- 不删除已生成的新快照或任务记录。
- 若读取自检出现性能问题，可临时关闭读取比较但保留发布时写版本；手动结果维护仍可使用。
- 禁止通过清空快照表回滚。

## 11. 验收标准

- ST 相同事实重复采集后，读取榜单和天梯均不重算。
- ST 真正变化后，无需配置依赖任务：读取受影响结果即可识别过期并走现有重算路径。
- 榜单只影响正在读取的日期与方案；天梯只处置正在读取的 T 日，且历史变化对 `T>=D` 生效、对 `T<D` 无影响。
- ST 批次未发布时，两类缓存不被标记为当前有效。
- 计算期间 ST 变化不会发布混合版本。
- 所有现有调度定义、触发条件、静态参数、延迟和重试行为保持原样。
- 手动结果维护仍可用于强制维护、非 ST 变化和提前预维护。
- 代表性规模版本查询达到性能门槛，测试、迁移演练和相关架构文档全部通过。
