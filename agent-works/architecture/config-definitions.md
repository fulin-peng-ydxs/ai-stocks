# 研究方案配置

本文说明买卖、评分与筛选方案的配置结构、版本、校验和生效链路。方案保存指标 key 与参数组合；指标按请求日期动态计算，已保存评分方案的榜单按“日期＋方案＋版本”惰性物化。

参考：[技术指标](technical-indicators.md) · [环境配置](environment-configuration.md) · [设计规范](../../DESIGN.md)。

## 核心技术

### 1. 指标注册表与定义仓库

方案通过 `IndicatorDefRepo` 读取已持久化的指标目录，保存稳定 key 和本次引用的参数，不复制指标定义。注册表、内置 seed、元数据分类、参数 schema、MACD 与计算周期的完整契约统一见 [技术指标架构](technical-indicators.md)。

指标候选的可用性与既有方案能否继续执行遵守指标治理契约；禁用指标不等于改写历史方案。运行期默认参数从生效配置读取，加载层次见 [环境配置架构](environment-configuration.md)。

### 2. 指标指纹与分层内存缓存

单次筛选、评分、买卖预览和回测复用同一个 `IndicatorEngine`，表达式引用按 key 与有效参数去重后批量补列；同一指标的不同参数实例不得互相覆盖。调用方只读消费缓存结果，需要修改时先复制；缓存隔离机制见下方指标架构入口。

缓存层级、容量、点时行情批量加载与指纹失效由 [技术指标架构「计算与失效」](technical-indicators.md#计算与失效) 维护。方案层只消费统一引擎与结果版本，不另建页面或业务服务私有缓存，也不复制指标 SQL 或公式。

### 3. 方案的版本化存储

三类方案均为"主表存当前版本 + version 表存历史"双表结构（DDL 见 `backend/storage/pg_ddl.py`；`ddl.py` 为迁移保留的旧 DuckDB 定义）：

| 方案 | 主表 | 历史表 | 核心 JSON 字段 |
|------|------|--------|---------------|
| 评分方案 | `score_profile` | `score_profile_version` | `items`（指标引用、参数、启停、权重与打分结构）、`grade_thresholds`、`include_st` |
| 买卖方案 | `trade_profile` | `trade_profile_version` | `buy_tree`、`sell_tree`、`backstop` |
| 筛选方案 | `screen_profile` | `screen_profile_version` | `expression`（条件 AST）、`params` |

- 版本递增逻辑（以 `backend/scoring/score_profile.py::ScoreProfileRepo.save` 为例）：保存时比对当前主表的 `name/items/grade_thresholds/include_st`，四项完全一致才返回原版本号、不写新版；任一变化均 `version+1`，并更新主表、写入 version 表。只切换 ST 纳入选项也会生成新版本；`created_at` 在多次保存间保留。
- 三类方案不设业务编码。新建和复制时由后端生成 32 位 UUIDv4 十六进制内部 `id`，名称不参与身份生成；页面不展示内部 `id`，只展示方案名称、版本和可见范围。存量可读 `id` 继续兼容，不批量改写其版本、快照和回测引用。
- 方案 JSON 字段在 PG DDL 中使用 TEXT 保存序列化内容；版本表与主表均按真实 owner 归属访问。
- 评分与买卖方案的历史版本由 `ProfileVersionContent` 共同展示指标名称、已保存参数、启停、权重/条件关系和兜底规则；不补入当前默认参数。载入历史版本仍由原操作完成，原始配置放在默认收起的具名入口供核对。
- `is_preset` 标记内置预设方案；`seed_defaults` 把默认方案（`DEFAULT_SCORE_PROFILES`/`DEFAULT_TRADE_PROFILES`）入库。
- 评分方案、买卖方案和筛选方案均支持 `visibility=private|tenant|public`、`published_at`、`published_by`。API 返回 opaque `profile_ref`、`source`、`readonly`、`owner_label`，非 owner 公开方案只读，可复制当前版本或指定历史版本为当前用户自己的 private；跨租户 public 资产的 `owner_label` 使用脱敏占位，不暴露原始 owner_user_id。可见性收窄会保留历史结果并同步收窄引用该方案的公开回测，响应返回 `affected_run_count`。

### 4. 配置覆盖层与即时生效

环境变量、变量文件、YAML 基线、PostgreSQL `app_config` 覆盖层、DuckDB 同名旧表和生效优先级统一见 [environment-configuration.md](environment-configuration.md)。本文只保留配置定义视角：

- 运行期业务参数使用生效配置读取，系统设置开放字段由后端白名单元数据决定；具体分组和加载规则见环境配置正文。
- 股票池、市值边界、TopN、指标全局周期等未开放为 Web 表单的默认参数继续由 YAML 基线或方案配置承载。
- 方案级配置仍走评分/买卖/筛选 profile/version 表，保存即版本化，不属于环境变量链路。

---

## 业务架构

### 三大定义的引用关系

```
技术指标（indicator_def / registry）── 唯一原子定义
        │ 被引用（indicator key + params）
        ├──────────────┬──────────────┐
        ▼              ▼              ▼
   评分方案         买卖方案        筛选方案
 score_profile   trade_profile   screen_profile
   items[]        buy/sell_tree   expression(AST)
        │              │              │
        ▼              ▼              ▼
  评分快照/榜单    回测买卖信号    选股结果
 score_snapshot   backtest        screen_result
```

- **统一解析入口**：评分项、买卖条件和筛选 `ind` 叶子都通过 `resolve_indicator(indicator, params, snap)` 取值——优先取 `key+params` 对应的内部列，其次取兼容同名列，再解析内置别名与 `ma`/`hhv` 带参映射。
- **表达式型指标补列**：评分/筛选/买卖在求值前调用 `IndicatorEngine.attach_columns` 或区间版 `attach_range_columns`。同一批请求只加载一次历史行情；同一 key 的不同参数写入不同内部列，因此可以在一个方案中同时引用多个参数实例而不会相互覆盖。
- **方案校验依赖指标目录**：`ScoreProfileRepo.save` / `TradeProfileRepo.save` 保存前从 `IndicatorDefRepo` 取全部已知 key 作为 `known_keys`（`backend/scoring/score_profile.py`、`backend/signals/trade_profile.py`），校验方案里引用的指标都存在；评分项还校验权重为正、打分方式 ∈ `bool/band/linear`。

### 评分配置与执行边界

方案保存指标引用、参数、启停、`bool/band/linear` 打分结构、权重、评级阈值和 `include_st`。具体映射、权重归一、稳定排名与缓存物化由 [选股与榜单](screening-and-board.md) 维护；配置层只校验并保存这些输入，不建立第二套评分公式。

### 买卖条件树（`backend/signals/trade_profile.py`）

- 节点 `{"op":"AND"|"OR","children":[...]}`，叶子 `{"indicator","params","cmp","value"}`，`cmp ∈ ==/!=/>/>=/</<=/between`（`_CMP`）。
- `backstop` 兜底 `{take_profit, stop_loss, max_hold_days}` 可空；校验要求"卖出条件树与兜底至少配一个"（`validate_trade_profile`）。
- 内置默认「趋势买卖」方案：买入条件为多头排列 `bull_arrange == true` 且放量突破 `is_vol_breakout == true`；卖出条件为跌破 20 日均线；兜底为止盈 20%、止损 8%、最长持仓 30 日。
- 买卖方案本身只定义买入/卖出信号，不保存独立股票池。预览接口按运行日全市场 `wide_snapshot` 评估条件，并按 `stock_st_status_daily` 准确点时事实强制排除当日 ST；事实未就绪时拒绝预览。市值、板块、上市天数、一字涨停等过滤需要写入买入条件或由回测筛选方案承接。

### 涉及的 API

| 模块 | 文件 | 关键端点 |
|------|------|---------|
| 技术指标 | `backend/api/indicators.py` | `GET /api/indicators/registry`、`POST /api/indicators/def`、`PATCH .../enabled`、`PATCH .../categories`、`DELETE .../{key}` |
| 评分方案 | `backend/api/score_profiles.py` | `GET/POST /api/score-profiles`、`GET .../{pid}`、`GET .../{pid}/versions`、`DELETE .../{pid}`、`POST .../{pid}/visibility`、`POST .../{pid}/copy`、`POST /api/score-profiles/run`（试算榜单） |
| 买卖方案 | `backend/api/trade_profiles.py` | `GET/POST /api/trade-profiles`、`GET .../{pid}`、`GET .../{pid}/versions`、`DELETE .../{pid}`、`POST .../{pid}/visibility`、`POST .../{pid}/copy`、`POST /api/trade-profiles/preview`（条件命中预览） |
| 筛选方案 | `backend/api/profiles.py` | `GET/POST /api/profiles`、`GET .../{pid}`、`GET .../{pid}/versions`、`DELETE .../{pid}`、`POST .../{pid}/visibility`、`POST .../{pid}/copy`、`POST /api/screen/run` |
| 配置生效 | `backend/api/config.py`、`backend/api/data_admin.py` | YAML 基线 reload 与 Web 系统设置；加载优先级见 [environment-configuration.md](environment-configuration.md) |

- 评分试算 `/api/score-profiles/run`（`backend/api/score_profiles.py::run_score_profile`）：已保存方案走**评分快照层**（`ScoreSnapshotRepo.get_board`，命中即用/失效重算），未保存的 inline 方案当场 `score_day` 实时算不入库。
- 已保存评分方案的缓存 owner、物化键、综合指纹和 ST 输入版本由 [选股与榜单](screening-and-board.md) 维护；配置页只消费试算结果。
- 三类方案 `/copy` 请求体可传 `version`；后端在可见性校验后按来源真实 `tenant_id + owner_user_id + id + version` 读取版本快照，副本固定从 v1、private 开始。只读公开方案的历史版本操作只能“复制此版本为我的”，不得把历史内容载入为可写原方案。
- 配置页移除当前预览时，`onScoreTempRemoved/onTradeTempRemoved` 先使在途详情失效，清空对应方案身份、评分项或买卖树及兜底、只读态、试算结果和错误，再刷新 mine；刷新失败仍保持空白新建态。筛选页的清理对象见[选股与榜单](screening-and-board.md#2-策略筛选页)。

### 前端配置中心

`frontend/src/views/ConfigView.vue` 是统一配置入口，四个 Tab：

- **评分规则**（score）：编辑 `items`（指标+打分方式+权重）、试算榜单预览；
- **技术指标**（tech）：展示统一业务计算周期与指标目录表（名称/标识/分类/类型/来源/参数/表达式/启用/操作），可启停、改分类、新建自定义；
- **买卖**（trade）：买/卖条件树 + 兜底；
- **系统**（system）：白名单系统参数表单（懒加载 `loadSystem`）。

## 页面使用说明书

配置管理是全系统的"定义中心"。它不直接产生榜单或回测收益，但它定义了其它模块使用的原子指标、评分规则和买卖信号。

### 1. 技术指标管理

| 能做什么 | 说明 | 下游影响 |
|----------|------|----------|
| 查看指标注册表 | 包含内置指标、表达式指标、中文名、分类、参数 | 策略筛选、评分方案、买卖方案都引用这里的 key |
| 启用/停用指标 | 内置指标不可删除，但可控制是否展示/可选 | 停用后前端不应再作为新方案候选 |
| 调整分类 | 便于前端按趋势、量能、强弱、风险等分组 | 改善配置体验，不改变计算口径 |
| 新建表达式指标 | 用 DSL 封装可复用条件或数值 | 可在评分/筛选/买卖方案里复用 |

**指标设计建议**：

- 能用内置指标就优先用内置指标，性能和口径更稳定。
- 表达式指标适合沉淀常用逻辑，不适合临时试验；临时试验可先在策略筛选页用 `expr`。
- 指标 key 一旦被方案引用，不要随意改名；新增指标比改旧 key 更安全。

### 2. 评分方案管理

评分方案回答"一只股票强不强、强在哪里"。

| 配置项 | 含义 | 示例 |
|--------|------|------|
| 指标项 | 引用指标 key + 参数 | `rs_pct`、`is_bull_arrange` |
| 打分方式 | `bool` / `band` / `linear` | 布尔达标、区间分段、线性映射 |
| 权重 | 综合分贡献比例 | 趋势 30%、强弱 25%、量能 20% |
| 分档阈值 | 综合分对应中文评级 | 观察、龙头候选、主升浪核心 |

```mermaid
flowchart LR
  A["配置评分项和权重"] --> B["保存 score_profile\n生成版本"]
  B --> C["每日榜单按方案排序"]
  C --> D["回测页做评分验证"]
  D --> E["根据分层命中率调整权重/阈值"]
```

### 3. 买卖方案管理

买卖方案回答"什么时候允许买、什么时候卖、兜底怎么退出"。

| 配置项 | 说明 | 下游 |
|--------|------|------|
| 买入条件树 | AND/OR 组合多个指标条件 | 回测买入过滤、个股详情买入信号 |
| 卖出条件树 | AND/OR 组合多个退出信号 | 回测卖出原因、个股详情卖出信号 |
| 兜底止盈 | 达到收益率后卖出 | 回测撮合 |
| 兜底止损 | 亏损达到阈值后卖出 | 回测风控 |
| 最大持仓天数 | 到期退出 | 防止长时间无卖点悬空 |

```mermaid
flowchart LR
  A["配置买入/卖出树"] --> B["个股详情查看逐条命中"]
  B --> C["回测验证成交与卖出原因"]
  C --> D["按逐笔交易复盘条件有效性"]
  D --> A
```

### 4. 系统参数与环境配置

环境变量、变量文件、YAML 基线和数据库覆盖层的加载生效规则只维护在 [environment-configuration.md](environment-configuration.md)。本页的系统参数说明只关注“哪些配置服务于指标、评分、买卖、筛选和回测定义”。

系统参数界面由后端白名单元数据驱动；股票池过滤、市值边界、TopN 和指标全局周期等默认值按环境配置规定归入 YAML 或方案。涉及采集压力或回测口径的变更，须复核其实际消费者，不能将系统配置保存误认为研究方案版本已更新。

### 5. 与其它模块的关联关系

| 下游模块 | 使用哪些配置 |
|----------|--------------|
| 每日榜单 | 评分方案、指标注册表、YAML/effective 系统参数 |
| 策略筛选 | 指标注册表、筛选方案、表达式 DSL |
| 回测验证 | 筛选方案、评分方案、买卖方案、成本参数 |
| 个股与分组 | 买卖方案用于详情页信号，指标引擎用于快照 |
| 数据管理 | 数据源限流/并发、路径、审计保留期等系统参数 |

### 6. 配置变更检查清单

| 改动类型 | 保存后要检查 |
|----------|--------------|
| 新增指标 | 策略筛选页是否可选；表达式是否合法；缺数股票表现 |
| 改评分方案 | 每日榜单分布是否合理；回测评分验证是否有超额 |
| 改买卖方案 | 个股详情逐条命中是否符合预期；回测卖出原因是否可解释 |
| 改系统参数 | 数据任务是否正常；回测口径是否需要重新说明 |

---

## 业务流程

### 指标定义接入

指标启动校准、公式创建、参数 schema、引用锁定与删除保护统一见 [技术指标](technical-indicators.md)。配置中心的指标页只是该能力的管理入口；方案保存稳定 key 和引用参数，不复制指标定义或重写 seed 流程。

### 配置买卖方案

1. 前端编辑买/卖条件树（选指标 key + 参数 + 比较符 + 阈值）与可选兜底 → `POST /api/trade-profiles`。
2. `TradeProfileRepo.save`（`backend/signals/trade_profile.py`）取已知指标 key 校验树合法性 → 比对是否实质变更 → 变更则 `version+1`，写主表 + version 表。
3. 试算：`POST /api/trade-profiles/preview`（`backend/api/trade_profiles.py::preview_conditions`）对某交易日全市场（排除 ST）`wide_snapshot` + `attach_columns` + `eval_conditions`，返回命中数与样例。
4. 回测引用 `trade_profile_id`/opaque `profile_ref` + 运行时版本（`backtest_run` 记录版本与签名）做买/卖/兜底信号；公开买卖方案按可见性解析，不写入方案 owner 的运行结果。

### 配置评分方案

1. 前端编辑指标项（indicator + params + weight + scoring）与分档阈值 → `POST /api/score-profiles`。
2. `ScoreProfileRepo.save`（`backend/scoring/score_profile.py`）`validate_profile` 校验（权重为正、打分方式合法、指标可解析或为已知自定义）→ 版本递增 → 写主表 + version 表。
3. 试算：`POST /api/score-profiles/run`（已保存走快照层、未保存实时算）→ 返回 Top N（含分项达标分 `sub_scores`）。
4. 每日榜单复用 `ScoreSnapshotRepo`；回测排名与评分验证按区间动态计算，但复用同一 `wide_snapshot`、表达式补列和 `ScoreProfileModel` 口径，不重复读取已完成的同区间指标快照。

### 配置变更的消费链

方案实质变更生成新版本，消费者按所选版本执行；系统参数按 [环境配置](environment-configuration.md) 的缓存与生效阶段读取；指标参数和定义变化按 [技术指标](technical-indicators.md) 与 [选股榜单](screening-and-board.md) 的指纹协议影响缓存。三个变化入口不可混为同一“保存即全部重算”。

## 风险事项

| 等级 | 风险点 | 影响 | 建议 |
|------|--------|------|------|
| <span style="color:#dc2626">●</span> 高 | 已实例化服务可能持有旧配置对象 | 长任务或已创建的领域服务实例不会自动重建，可能继续使用创建时的 effective settings | 配置改动后新任务/新请求生效；需要严格切换口径时重启服务或重建相关服务实例 |
| <span style="color:#f59e0b">●</span> 中 | 绕过更新日志直接改行情表 | 进程共享缓存与榜单指纹无法感知未登记的手工 SQL，可能短时读取旧结果 | 行情变更统一走采集/修复任务；确需手工处理后执行结果维护并重启服务 |
| <span style="color:#f59e0b">●</span> 中 | 启动 seed 覆盖整套 builtin | 首次启用时会持久化全部注册表定义，不只是新指标；回滚旧代码前若下游已引用新 key 会无法计算 | 发布前备份 `indicator_def` 并对账完整 builtin；回滚优先停用新增定义，不直接删除 |
| 中 | 参数实例与快照列映射混用 | 同指标不同参数可能被错误覆盖 | 统一消费指标引擎补列与解析入口，参数边界见技术指标正文 |
| <span style="color:#f59e0b">●</span> 中 | RS 指标不可逐方案调参 | `rs_pct` 使用全局窗口，方案里传参无效 | 需要多窗口 RS 时新增独立表达式/内置指标 |
| <span style="color:#f59e0b">●</span> 中 | 删除方案会断开历史引用 | 历史回测只记录 id+version，删方案后无法回溯内容 | 对已用于回测的方案优先停用/改名，不直接删除 |
| 中 | 指标定义变更影响历史方案 | 被当前或历史方案引用的计算结构需要保持稳定 | 遵守技术指标的引用锁定；禁用不改写历史定义，删除前审计引用 |
| <span style="color:#16a34a">●</span> 低 | 方案版本按 JSON 字符串全等去重 | 字段顺序差异可能产生多余版本 | 前端保存前稳定 JSON 顺序 |
| <span style="color:#16a34a">●</span> 低 | 配置覆盖层回落静默 | DB 异常时会回落 YAML，改参不生效缺少信号 | 按 [environment-configuration.md](environment-configuration.md) 的风险清单排查日志、PG 和 overridden 状态 |
| <span style="color:#16a34a">●</span> 低 | 表达式型指标异常被吞为 None | 坏表达式或缺数只表现为空值（`backend/indicators/engine.py::_eval_expr_indicator`） | 新指标先小样本试算，确认缺失率 |
