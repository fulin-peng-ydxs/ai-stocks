# 交易纪律模块

## 模块定位

交易纪律模块为登录用户提供私人交易规则、规则版本、按交易日履约打卡、操作事实、历史修订和快捷无操作履约闭环。模块入口是 `/trade-discipline`，数据始终按 `tenant_id + owner_user_id` 隔离；当前仅校验可确认的结构化规则违规，不包含自由文本规则自动裁决、AI 分析、收益曲线、券商同步或规则公开分享。

需求与验收边界见 [`../trading-discipline-checkin/requirement.md`](../trading-discipline-checkin/requirement.md)，任务和验证记录见 [`../trading-discipline-checkin/plan.md`](../trading-discipline-checkin/plan.md)。

## 核心技术

| 层次 | 当前实现 | 关键入口 |
| --- | --- | --- |
| 页面 | 三页签工作台承载今日打卡、规则管理和历史记录；用户中心抽屉提供摘要、跳转和快捷无操作履约 | `frontend/src/views/TradeDisciplineView.vue`、`frontend/src/App.vue` |
| 前端组件 | 规则与操作复用摘要展开卡；买卖规则和操作事实统一按买入/卖出分组；历史复用通用表格、分页和页面抽屉 | `frontend/src/components/AppSummaryDisclosureCard.vue`、`frontend/src/components/trade-discipline/`、`frontend/src/views/trade-discipline/components/` |
| API | `/api/trade-discipline` 下 23 个端点，路由层负责请求模型、权限依赖、统一响应和错误映射 | `backend/api/trade_discipline.py` |
| 服务 | 编排草稿、发布、激活事件、履约、修订、原因、操作、摘要和股票点时校验 | `backend/services/trade_discipline_service.py` |
| 仓库 | 所有 PG 查询和写入显式带归属；事务内锁主体、维护版本/事件序号和不可变修订 | `backend/storage/trade_discipline_repository.py` |
| 数据定义 | 15 张 `trade_discipline_*` PG 表、索引、菜单/资源迁移和资产表登记 | `backend/storage/pg_ddl.py` |
| 参考数据 | DuckDB `trade_calendar` 决定下一真实交易日，`stock_basic` 提供轻量股票搜索与点时存续校验 | `backend/services/trade_discipline_service.py`、`backend/storage/trade_discipline_repository.py` |

PG 与 DuckDB 不跨库 JOIN。服务层分别读取私人业务资产与只读参考数据，再在内存中完成校验和组合。

## 结构化选股条件与持仓核对

- 每条选股规则保存 `price_min/price_max`（原始成交价，含边界，最多4位小数）及 `st_filter/loss_filter/st_risk_filter`（`any|exclude|only`）。整套规则保存可空的正整数 `max_positions`；旧版本新增条件默认不限。
- 买入打卡按所选规则展示条件，股价复用成交价；亏损、ST风险在新增操作或换股时按规则预填（排除为 `no`、仅限为 `yes`、不限不预填），可按实际修改为 `yes|no|unknown`。切换规则只补未填写项，保留已有事实及“未知”；历史加载不补写。预填不代表系统已核验财报或风险，ST仍取交易日权威数据。卖出保留规则关联但不核对选股条件。
- `selection_facts` 随操作修订保存：ST由服务端批量读取交易日权威逐日数据，缺失为未知；客户端不能写ST事实。修正同日同股时沿用原快照，旧记录未采集事实不回填。按所选规则的不限/排除/仅限以及价格范围核对买入事实。已确认的 ST、亏损、ST 风险、价格违规及持仓超限禁止整体选择“已履约”，部分履约中的违规操作也不得标记为已履约；前端编辑态禁用已履约并转为未履约，服务端首次提交/修正使用相同条件守卫。未知事实只提示，卖出不套用买入选股条件，历史只读快照不追溯重写。
- 限制持仓时，`peak_positions` 必须填写非负整数，含此前持仓、同股去重，表示本套规则当日最大同时持有股票数；无买卖也需填写。首次填报默认取该日有效规则版本的持仓上限，用户可按实际修改；未设置上限时留空。已有记录展示、修正及取消修正均保留原数量（包括 0），旧记录未采集则保留“未记录”，不按规则上限补写。系统没有持仓账本，不从交易记录推测峰值。
- 有提交权限的待打卡规则统一保留“无操作履约”和“去打卡”，与是否设置持仓上限无关。快捷确认复用 AppDialog；有上限时必须确认当日峰值，默认取规则上限并可按实际修改（含 0），超限不可快捷记为已履约，可转入正式表单。服务端快捷入口复用正式填报校验并保存峰值；仅同一数量的重复快捷请求幂等，数量变化或已有正式记录返回冲突。
- 增量SQL：[选股条件迁移](../trading-discipline-checkin/selection-conditions-migration.sql)。后端 `init_pg_db` 执行相同幂等增量，先升级数据库/后端再发布前端；回退应用保留字段和已采集事实，不自动删列。

### 分类检查项与人工核对

- 每条选股规则内部按基本条件、风险排除、技术形态三类分组；价格归基本条件，ST/亏损/ST风险归风险排除。`checklist_items` 保存稳定 `item_id`、`category`（`basic|risk|technical`，旧 `other` 作为技术形态兼容读取/保存）、`text`、`display_order`；只在草稿编辑时手动整理，旧文本完整保留为可空的补充说明 `content`，不自动拆分。
- 逐项条件支持增删、分类和组内排序，新增默认技术形态；发布时每项内容非空，选股规则至少有一项有效结构化条件、人工检查项或非空补充说明。检查项变化参与版本差异比较，复制规则重新生成检查项标识。
- 每笔买入提交 `checklist_results=[{item_id,status}]`，状态为 `yes|no|unknown`（符合/不符合/未知）；默认未选择，必须完整对应绑定版本所选规则的检查项。切换股票或规则清空结果；卖出和无操作不核对买入条件。
- 人工“不符合”与原有明确违规共用履约守卫：整体不得已履约，部分履约中对应操作不得已履约；未知仅提示，全部符合也不自动裁决。首次提交和修正均由服务端复核，拒绝重复、遗漏和越界引用。
- 规则管理、今日核对和历史条件共用系统配置的 `ConfigPanelSection` 紧凑子分区，三个分类与补充说明默认独立收起；标题保留范围、检查项数量及今日待核对/不符合/未知数量。收起不卸载字段，按规则/操作隔离展开状态且不保存为用户偏好；新增、改分类与校验失败会展开目标并定位字段。历史分类映射不改写正式快照，保存新草稿时规范为技术形态。
- 核对结果随操作修订不可变保存；当日表单和历史详情通过共用分类条件组件展示版本内容与结果，旧记录未采集显示未记录，不回填。补充说明可展开完整阅读，分类与条件内容仍属于业务资产；展示默认值复用 `trade-discipline.stockConditions` 的 `config-panel.defaultCollapsed`，三个入口共用基本条件、风险排除、技术形态、补充说明四个稳定分区 key，默认全部收起。属性抽屉通过现有布局用户层持久化与恢复默认；页面临时开合按规则/操作隔离，不写回默认。远端默认晚到不覆盖已操作或错误定位的分区；显式修改默认或恢复默认会重置开合，不清除草稿和核对结果。
- 增量 SQL：[分类检查项迁移](../trading-discipline-checkin/selection-checklist-migration.sql)。初始化幂等执行同一升级；先升级数据库和后端，再发布前端。回退须保留字段和已采集快照，旧客户端不支持新项，回退期间暂停规则与打卡写入。

## 系统架构

```mermaid
flowchart LR
  U[交易纪律工作台 / 用户中心快捷卡] --> A[tradeDiscipline.ts]
  A --> API[FastAPI /api/trade-discipline]
  API --> AUTH[四项功能码与请求归属]
  API --> SVC[TradeDisciplineService]
  SVC --> REPO[TradeDisciplineRepository]
  REPO --> PG[(PostgreSQL 私人规则与履约事实)]
  SVC --> CAL[(DuckDB trade_calendar)]
  SVC --> STOCK[(DuckDB stock_basic)]
  PG --> SVC
  SVC --> API
  API --> U
```

## 页面使用说明

### 今日打卡

- 选择真实交易日和该日有效规则版本，查看待打卡、已履约或未履约状态。
- 支持“履约/未履约 × 有操作/无操作”四种组合。
- 部分履约必须至少记录一笔操作，每笔单独保存已履约/未履约状态，但不要求至少两笔或同时出现两种状态；整体偏差可以来自选股、资金等非操作执行维度。
- 有操作时按买入、卖出分组新增记录；分组决定操作方向，卡片内选择股票、具体选股规则、同方向买卖规则及可选成交事实。
- 新增操作默认使用所选履约交易日和当前时分秒；操作卡按“操作依据、成交明细、操作说明”分区，时间仍可清空或修改。
- 未履约时必须选择或输入一个原因，并填写保留换行的详细说明。
- 已有记录只读展示；进入修正后只有发生实质变化才能提交新修订。
- 历史交易日没有生效规则时展示真实空状态并提供“返回最新交易日”；最新交易日无规则时只引导前往规则管理，不在空态中直接创建服务端草稿。
- 日期切换保持主从工作台稳定，左侧规则列表和右侧履约摘要/打卡详情独立加载、独立失败；打卡详情与规则编辑均通过 `AppScrollArea` 内部滚动，主从网格限制行高，长内容不撑开整页。窄宽时转为上下两区，规则栏最多占工作区 45% 且不超过 210px，详情占其余空间并保留草稿；规则卡片合并版本/状态为可换行的一行。已有打卡的修正、取消与提交统一位于详情顶部操作区，“取消修正”使用红色描边按钮，首次打卡仍在表单末尾提交。规则编辑底部操作栏在滚动视口内侧吸底，不使用负定位偏移；空间不足时自然换行，末条规则及完整按钮均可达。
- 打卡表单以同一分区容器承载“履约判断”和“操作事实”，规则管理的“买卖规则”也复用该容器；分区标题和说明位于边框外，实际表单或买入/卖出方向组位于完整边框内，与“选股规则”的页面层级一致。历史详情先展示操作快照、再展示规则版本快照，部分履约的操作快照显式展示逐笔履约状态。

### 规则管理

- 左侧规则轨道展示主体状态、目标交易日有效状态、当前正式版本、草稿和待生效动作；右侧就地编辑，不使用规则编辑抽屉。
- 规则详情的只读说明和“编辑规则”入口位于三栏状态摘要之前；正式版本、归档及只读权限保留输入框外形，基础字段、今日打卡与展开明细保留统一的禁用边框和弱文字，编辑态继续使用普通控件样式。规则轨道的普通项与选中项均保留共享卡片边框。
- 新建、复制和保存草稿不产生正式版本号；发布才生成连续版本。
- 选股规则每条使用独占一行的摘要卡；买卖规则和打卡操作均按买入在上、卖出在下单列分组。内置类型不可删除，自定义类型随草稿保存登记并可从候选中删除。
- 打卡中的买卖规则下拉选项及选中值复用 `BuiltinOptionRow`：名称在左，类型使用右侧小号中性标签，长名称与长类型分别省略。类型名称与规则管理共用映射，支持自定义及历史类型；提交仍使用明细 ID。
- 发布、归档和恢复均从操作自然日之后的第一个真实交易日生效，不倒灌当日或历史交易日。

### 历史记录

- 按日期、规则、履约结果、有无操作、股票、原因和修正状态做服务端筛选、排序和分页。
- 规则名称是唯一详情入口；详情抽屉可切换任意不可变修订，并从当前修订发起修正。

### 用户中心快捷卡

- 同时拥有页面查看和履约查看权限时展示摘要；拥有提交权限时可确认“已履约 + 无操作”。
- 快捷成功后刷新共享摘要和已打开工作台；冲突转入正式页面处理。

## 业务流程

### 规则发布与生效

1. 用户创建或打开每个规则主体唯一的工作草稿。
2. 保存草稿时校验名称占用、买卖类型方向占用、金额、明细启用态和 `draft_revision`。
3. 发布事务锁定规则主体，生成连续正式版本和不可变明细。
4. 服务从 DuckDB 查询操作自然日后的首个开市日；日历缺失时整个 PG 事务回滚并保留草稿。
5. 同一事务分配单调 `event_seq`、写入激活事件、更新主体指针并删除草稿。
6. 履约日有效状态只按 `(effective_from_trade_date, event_seq)` 解析；时间戳仅用于审计和生效日计算。

### 履约提交与修正

1. 服务校验交易日、归属和该日有效正式版本。
2. 对每笔操作校验股票点时存续、方向、具体选股规则和同方向买卖规则；股票名称由服务端生成提交时快照。
3. 股票搜索、已选股票和历史操作快照按打卡交易日附加 `is_st + st_as_of_date` 并使用统一 ST 标签；该展示事实不写入用户操作快照。ST 事实暂不可用时保留操作和候选、明确返回未知，不把缺失状态解释为非 ST。
4. 首次提交创建唯一 `(归属, rule_id, trade_date)` 打卡主体和 r1；修正使用 `expected_revision` 乐观锁追加不可变修订。
5. 修订、违规原因、操作和当前修订指针在同一 PG 事务提交。
6. 页面刷新当前表单、规则轨道、历史列表和用户中心共享摘要。

## 数据模型

| 数据组 | 表 | 主要不变量 |
| --- | --- | --- |
| 规则主体与占用 | `trade_discipline_rule`、`trade_discipline_rule_name_claim`、`trade_discipline_action_subtype` | 未删除规则名称在归属内唯一；自定义买卖类型名在归属内唯一且固定方向 |
| 工作草稿 | `trade_discipline_rule_draft`、`trade_discipline_draft_stock_rule`、`trade_discipline_draft_action_rule` | 每主体至多一个草稿；用 `draft_revision` 乐观锁；草稿没有正式版本号 |
| 正式版本 | `trade_discipline_rule_version`、`trade_discipline_stock_rule`、`trade_discipline_action_rule` | 只有发布生成版本；正式版本和明细不可变 |
| 生命周期 | `trade_discipline_rule_activation` | 事件只增不改；主体内 `event_seq` 严格单调并决定同生效日顺序 |
| 履约与修订 | `trade_discipline_checkin`、`trade_discipline_checkin_revision` | 规则 + 交易日唯一；修订只增不改，当前指针受乐观锁保护 |
| 违规与操作 | `trade_discipline_reason`、`trade_discipline_violation`、`trade_discipline_operation` | 原因软删除不改历史快照；操作固定绑定同一规则版本内的具体明细 |

金额使用 PostgreSQL `NUMERIC` 和前端十进制定点字符串链路，不使用 JavaScript 浮点数作为资金约束事实源。

## API 与权限

| 能力 | 主要端点 | 权限 |
| --- | --- | --- |
| 页面摘要 | `GET /summary` | 同时需要 `trade-discipline:view`、`trade-discipline:checkin-view` |
| 规则与类型目录 | `/rules`、`/rules/{rule_id}`、`/rule-types` | 读取用 `trade-discipline:view`；写入用 `trade-discipline:rule-manage` |
| 草稿与生命周期 | `/rules/{rule_id}/draft`、`publish`、`archive`、`restore`、`copy` | `trade-discipline:rule-manage` |
| 履约和历史 | `/checkins/current`、`/checkins`、`/checkins/{id}/revisions/{no}` | 读取用 `trade-discipline:checkin-view` |
| 提交和修正 | `POST /checkins`、`/amendments`、`/quick-no-operation` | `trade-discipline:checkin-submit` |
| 原因 | `GET /reasons`、`DELETE /reasons/{id}` | 读取用 `checkin-view`；删除用 `checkin-submit` |
| 股票轻量搜索 | `GET /stock-options` | `checkin-view` 或 `checkin-submit` 任一权限 |

菜单和四项资源由 `migration.trade_discipline_default_grants_v1` 状态机维护。首次迁移默认授权 system、normal、tenant_admin；管理员后续撤销的授权不会在启动时补回。回滚入口：

```bash
python -m backend.cli trade-discipline-rbac rollback \
  --confirm-marker migration.trade_discipline_default_grants_v1
```

回滚只撤销账本中仍存在的 RBAC 行并写 tombstone，不删除业务事实；发现账本外角色授权时拒绝级联。

## 配置与运行边界

- 生产没有新增业务环境变量或业务 `app_config`；页面密度和历史分页复用既有布局/用户偏好链路。
- E2E 复用 `AI_STOCKS_ENV`、`AI_STOCKS_E2E_WRITE`、`AI_STOCKS_E2E_LOGIN_BYPASS` 安全门控，这些变量不属于生产业务配置。
- 发布、归档、恢复依赖 DuckDB 已有下一真实开市日；缺失时 fail-closed，不在生命周期事务内联网补采或用工作日推算。
- 页面未保存保护由应用级工作标签协议统一调度，交易纪律页面集中承载规则三选和打卡二选决策；浏览器刷新使用原生 `beforeunload`。

## 验证入口

```bash
# 后端聚焦测试；执行前遵守 AGENTS.md 的 DuckDB 锁与服务恢复规则
python -m pytest backend/tests/test_trade_discipline_t*.py backend/tests/test_e2e_trade_discipline.py -q

# 前端组件与构建
cd frontend
npm test -- --run src/views/__tests__/TradeDisciplineView.spec.ts \
  src/views/trade-discipline/components/__tests__ \
  src/components/trade-discipline/__tests__
npm run build

# 真实 PG + DuckDB 聚焦 E2E；脚本负责指纹、夹具、服务状态与清理
AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:e2e:trade-discipline
```

确定性夹具仅使用 `debug_tenant` 下固定调试账号、`e2e_td_`/`E2E纪律-`/`E2E类型-` 前缀、DuckDB `9988*.SZ` 和 2098 年专属日期。seed/cleanup 必须在后端停服时执行，并校验 `/api/health/e2e` 与直连 PG 指纹一致。

## 风险事项

| 等级 | 风险点 | 影响 | 当前控制 |
| --- | --- | --- | --- |
| 高 | 未来交易日历缺失 | 发布、归档或恢复暂时不可用 | 服务 fail-closed；采集、启动和数据体检检查跨年覆盖 |
| 高 | RBAC marker 冲突或账本外授权 | 错误覆盖管理员配置或误删授权 | advisory lock、严格 marker 校验、普通 seed 只补缺失、回滚拒绝账本外授权 |
| 中 | 多入口未保存状态 | 路由、标签关闭或注销可能丢失输入 | 应用级 preflight、页面级决策、组件契约和 Playwright 覆盖 |
| 中 | 历史和原因数据增长 | 模糊筛选性能下降 | 服务端分页、归属过滤、受控股票查询和现有索引；达到真实容量阈值后再评估新索引 |
| 中 | 生产回滚尚未演练 | 实际发布回退仍存在操作风险 | 本地已验证代码与确定性夹具；生产备份、部署和 RBAC 回滚演练仍必须在发布授权范围内单独执行 |
