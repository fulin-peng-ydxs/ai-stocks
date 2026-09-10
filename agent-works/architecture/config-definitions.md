# 配置定义（统一基座）

> 技术指标是系统唯一的原子定义，买卖方案、评分方案、筛选条件都引用指标 key 组合；指标全部动态实时计算（无落库值表），方案按"日期+方案+版本"做版本化存储与惰性物化。

---

<span style="color:#2563eb">●</span> 指标定义　<span style="color:#7c3aed">●</span> 方案配置　<span style="color:#16a34a">●</span> 即时生效　<span style="color:#dc2626">●</span> 变更风险

## 核心技术

### 1. 指标注册表与定义仓库

- **静态注册表** `backend/indicators/registry.py`：用 `@dataclass(frozen=True)` 的 `IndicatorDef`（registry.py:28-40）描述每个指标的元数据——`key`（英文标识）、`name_cn`（中文名）、`dtype`（`number`/`bool`）、`category`、`direction`、`params`（`Param` 列表）、`kind`（`builtin`/`expr`）、`expression`（含 `{param}` 占位的 DSL 模板）、`is_builtin`、`enabled`。`REGISTRY`（registry.py:44-175）是全部内置指标的列表，`PRESET_CATEGORIES`（registry.py:181-194）给每个指标打多分类标签。
- **两类指标计算路径**：
  - `kind="builtin"`：映射到 `compute.py` 预先算好的宽表列（如 `ma5`/`is_bull_arrange`/`rs_pct`），通过 `wide_snapshot` 一次产出。
  - `kind="expr"`：表达式型，`expression` 是 `MA(C,{n}) > REF(MA(C,{n}),{k})` 这类模板，使用时由 `render_expression`（definition.py:22-37）把 `{param}` 用方案传入的参数渲染为可执行字符串，再走 `backend/screening/expression.py` 的白名单 DSL 沙箱（`ALLOWED_FUNCS` 仅 `MA/HHV/LLV/REF/COUNT/SUM/ABS`，expression.py:34-38）逐股求值。
- **动态参数**：`Param`（name/label/type/default/min/max）声明指标可调参数 schema，前端据此渲染参数表单；同一指标（如 `consec_up` 连续上涨 N 天）每次引用可传不同 N，无需新建指标。
- **运行态全局参数**：指标、评分、回测、股票池等运行期默认值从生效配置读取；环境变量、变量文件、YAML 基线与 `app_config` 覆盖层的优先级见 [environment-configuration.md](environment-configuration.md)。
- **定义仓库** `backend/indicators/definition.py`：`IndicatorDefRepo` 把内置指标 seed 进 `indicator_def` 表（`seed_builtins` 幂等、保留用户改过的 `enabled` 与 `categories`，definition.py:139-151），并管理用户自定义表达式指标（`save_custom` 校验 key 合法/不与内置冲突/表达式白名单通过，definition.py:102-123）。内置指标不可删、仅可启停。
- **启动校准**：FastAPI 存储自检在 DuckDB schema 就绪后调用 `seed_builtins()`，每次启动对齐整套 `REGISTRY`，不是只补本次新增 key。全新库会持久化全部 builtin；存量库会刷新代码管理的名称、类型、表达式、参数和描述，保留管理员明确设置的 `enabled/categories`，旧库 `NULL` 则回退注册表默认值；元数据未变化时跳过 UPDATE，避免启动写放大和无意义刷新 `updated_at`。
- **MACD 五原子**：`macd_diff`、`macd_dea`、`macd_hist` 为 `number`，`macd_golden_cross`、`macd_dead_cross` 为可空 `bool`；固定参数 12/26/9，主分类“趋势”，预设分类“趋势/动量”，默认启用且不可删除。单股和全市场向量化路径使用同一严格后向 EMA/交叉口径，五列进入 `_IND_COLS` 后由筛选、评分和买卖条件通用求值链直接复用，不建立 MACD 专属下游分支。

### 2. param_hash 与单次运行内存缓存

- `build_params`（compute.py:27-40）从 `settings.indicators` 抽取参与计算的全局参数（MA/HHV 周期、放量倍数、平台窗口、换手健康区间等），`param_hash`（compute.py:43-46）对其 JSON 取 MD5 前 12 位作为参数版本指纹。
- `IndicatorEngine`（engine.py:55-64）在 `__init__` 算出 `self.phash`，作为单次运行内存缓存 key 的一部分：`range_frame` 的缓存键是 `(codes_key, lo, hi, phash)`（engine.py:135），用 `OrderedDict` 做 LRU（容量 `_CACHE_MAX=6`，engine.py:46/126-129）。参数一变 → phash 变 → 缓存不命中 → 自动重算。这是"改全局指标参数即重算"的底层机制。
- 全市场算指标用 `_bulk_qfq_bars`（engine.py:79-104）一条窗口 SQL 取每股末段 lookback 行（替代逐股 5000+ 次查询），按各股末日因子前复权（`COALESCE(adj_factor_clean, adj_factor)`）；RS 通过 `_cross_sectional_rs`（engine.py:115-124）按 `trade_date` 对 W 日收益做横截面百分位排名。

### 3. 方案的版本化存储

三类方案均为"主表存当前版本 + version 表存历史"双表结构（DDL 见 `backend/storage/pg_ddl.py`；`ddl.py` 为迁移保留的旧 DuckDB 定义）：

| 方案 | 主表 | 历史表 | 核心 JSON 字段 |
|------|------|--------|---------------|
| 评分方案 | `score_profile` (ddl.py:211) | `score_profile_version` (ddl.py:224) | `items`（[{indicator,params,weight,scoring}]）、`grade_thresholds` |
| 买卖方案 | `trade_profile` (ddl.py:264) | `trade_profile_version` (ddl.py:278) | `buy_tree`、`sell_tree`、`backstop` |
| 筛选方案 | `screen_profile` (ddl.py:196) | `screen_profile_version` (ddl.py:292) | `expression`（条件 AST）、`params` |

- 版本递增逻辑（以 `ScoreProfileRepo.save` 为例，score_profile.py:176-208）：保存时比对当前主表的 name/items/grade_thresholds，**完全相同则返回原版本号不写新版**；有实质变更才 `version+1`，同时 upsert 主表与 version 表。`created_at` 在多次保存间保留。
- JSON 字段统一以 VARCHAR 存 `json.dumps` 字符串，不依赖 DuckDB JSON 扩展。
- `is_preset` 标记内置预设方案；`seed_defaults` 把默认方案（`DEFAULT_SCORE_PROFILES`/`DEFAULT_TRADE_PROFILES`）入库。
- 评分方案、买卖方案和筛选方案均支持 `visibility=private|tenant|public`、`published_at`、`published_by`。API 返回 opaque `profile_ref`、`source`、`readonly`、`owner_label`，非 owner 公开方案只读，可复制当前版本或指定历史版本为当前用户自己的 private；跨租户 public 资产的 `owner_label` 使用脱敏占位，不暴露原始 owner_user_id。可见性收窄会保留历史结果并同步收窄引用该方案的公开回测，响应返回 `affected_run_count`。

### 4. 配置覆盖层与即时生效

环境变量、变量文件、YAML 基线、PostgreSQL `app_config` 覆盖层、DuckDB 同名旧表和生效优先级统一见 [environment-configuration.md](environment-configuration.md)。本文只保留配置定义视角：

- 运行期业务参数使用生效配置读取，Web 系统设置白名单只开放数据源、回测成本、认证与防滥用、审计设置。
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

- **统一解析入口**：评分项叶子、买卖条件叶子都通过 `resolve_indicator(indicator, params, snap)`（score_profile.py:38-62）取值——优先取快照同名列（含已 attach 的表达式型/自定义列），其次内置别名（`_ALIASES`）与 `ma`/`hhv` 带参映射。买卖条件树 `eval_conditions`（trade_profile.py:43-56）复用同一解析，因此天然支持内置 + 自定义指标。
- **表达式型指标补列**：评分/筛选/买卖在打分前调 `IndicatorEngine.attach_columns`（engine.py:269-282），对条件中用到、但快照里没有的表达式型指标，渲染参数后逐股求值补成列（列名=指标 key），再供按列读取。
- **方案校验依赖指标目录**：`ScoreProfileRepo.save` / `TradeProfileRepo.save` 保存前从 `IndicatorDefRepo` 取全部已知 key 作为 `known_keys`（score_profile.py:178-180、trade_profile.py:136-138），校验方案里引用的指标都存在；评分项还校验权重为正、打分方式 ∈ `bool/band/linear`。

### 三种评分打分方式（score_profile.py:65-85）

- `bool`：满足=100 / 否=0；
- `band`：分段阈值 `[[lo,hi,score],...]`，末段含右端；
- `linear`：在 `[min,max]` 间线性映射到 `[0,100]`（`min>max` 即"越小越高"）。
- 综合分 = Σ(达标分 × 权重)/Σ权重（权重自动归一），按 `grade_thresholds`（观察/龙头候选/主升浪核心）分档（score_profile.py:102-126）。

### 买卖条件树（trade_profile.py:1-101）

- 节点 `{"op":"AND"|"OR","children":[...]}`，叶子 `{"indicator","params","cmp","value"}`，`cmp ∈ ==/!=/>/>=/</<=/between`（`_CMP`，trade_profile.py:25-33）。
- `backstop` 兜底 `{take_profit, stop_loss, max_hold_days}` 可空；校验要求"卖出条件树与兜底至少配一个"（`validate_trade_profile`，trade_profile.py:89-100）。
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

- 评分试算 `/api/score-profiles/run`（score_profiles.py:56-107）：已保存方案走**评分快照层**（`ScoreSnapshotRepo.get_board`，命中即用/失效重算），未保存的 inline 方案当场 `score_day` 实时算不入库。
- 评分快照 `ScoreSnapshotRepo` 按 `(tenant_id, owner_user_id, profile_id, profile_version, trade_date)` 惰性物化到 `score_snapshot`+`score_snapshot_meta`（结果归方案 owner 缓存槽，可见者共读，详见 screening-and-board.md「评分快照惰性物化与失效」）：读取同时比较 `stale`、指标 `param_hash` 和当日 `st_input_version`；显式维护只标 stale，版本不一致只让当前缓存不命中，均沿用同一锁内重算入口。
- 三类方案 `/copy` 请求体可传 `version`；后端在可见性校验后按来源真实 `tenant_id + owner_user_id + id + version` 读取版本快照，副本固定从 v1、private 开始。只读公开方案的历史版本操作只能“复制此版本为我的”，不得把历史内容载入为可写原方案。
- 配置页和筛选页的外部“加载查看”状态不进入 mine 数组。行内“×”只移除临时预览，不调用删除接口；方案删除只由编辑区右上角独立按钮承接。移除事件以临时项身份为准，不依赖 `readonly`（本人名下系统内置资产也可能可编辑）；收到事件后先取消在途详情并清空方案身份、参数、只读态、试算/筛选结果和错误，再刷新 mine，刷新失败仍保持空白新建态。

### 前端配置中心

`frontend/src/views/ConfigView.vue` 是统一配置入口，四个 Tab（ConfigView.vue:32/537-842）：

- **评分规则**（score）：编辑 `items`（指标+打分方式+权重）、试算榜单预览；
- **技术指标**（tech）：指标目录表（名称/标识/分类/类型/来源/参数/表达式/启用/操作），可启停、改分类、新建自定义；
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

Web 系统设置当前只开放数据源限流/并发/容错、回测成本、认证防滥用和审计保留期。股票池过滤、市值边界、TopN、指标全局周期等属于 YAML 基线或方案级配置，不在系统设置页展示；涉及采集压力或回测口径的参数，建议改动后记录原因，并用回测或体检验证影响。

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

### 内置指标启动校准

1. 应用启动先完成 DuckDB 连通与 `indicator_def` schema 初始化。
2. `seed_builtins()` 遍历完整 `REGISTRY`：新增缺失定义，刷新代码管理元数据，保留管理员启停与分类。
3. 五个 MACD key 与其它 builtin 一起进入统一指标目录；管理页、筛选、评分和买卖方案读取同一份 `indicator_def`。
4. 重复启动若元数据无变化不执行 UPDATE；内置定义只能启停或调分类，不能删除。

### 新增（自定义）技术指标

1. 前端「技术指标」页填 key / 中文名 / dtype / DSL 表达式（含 `{param}` 占位）/ 参数 schema / 分类 → `POST /api/indicators/def`。
2. `IndicatorDefRepo.save_custom`（definition.py:102-123）校验：key 为英文/数字/下划线、不与内置冲突、dtype ∈ `bool/number`、用默认参数试渲染 + 白名单校验表达式。
3. upsert 进 `indicator_def`（`kind=expr`、`is_builtin=False`、`enabled=True`）。
4. 该 key 即刻可被评分/买卖/筛选方案引用；使用时由 `attach_columns` 逐股求值补列。

### 配置买卖方案

1. 前端编辑买/卖条件树（选指标 key + 参数 + 比较符 + 阈值）与可选兜底 → `POST /api/trade-profiles`。
2. `TradeProfileRepo.save`（trade_profile.py:140-171）取已知指标 key 校验树合法性 → 比对是否实质变更 → 变更则 `version+1`，写主表 + version 表。
3. 试算：`POST /api/trade-profiles/preview`（trade_profiles.py:61-96）对某交易日全市场（排除 ST）`wide_snapshot` + `attach_columns` + `eval_conditions`，返回命中数与样例。
4. 回测引用 `trade_profile_id`/opaque `profile_ref` + 运行时版本（`backtest_run` 记录版本与签名）做买/卖/兜底信号；公开买卖方案按可见性解析，不写入方案 owner 的运行结果。

### 配置评分方案

1. 前端编辑指标项（indicator + params + weight + scoring）与分档阈值 → `POST /api/score-profiles`。
2. `ScoreProfileRepo.save`（score_profile.py:176-208）`validate_profile` 校验（权重为正、打分方式合法、指标可解析或为已知自定义）→ 版本递增 → 写主表 + version 表。
3. 试算：`POST /api/score-profiles/run`（已保存走快照层、未保存实时算）→ 返回 Top N（含分项达标分 `sub_scores`）。
4. 每日榜单 / 回测排名 / 评分验证统一走 `ScoreSnapshotRepo`，口径一致。

### 改参即时生效

- **白名单系统参数**（数据源并发/限流/容错、回测成本、认证防滥用、审计保留期）：前端表单保存后按 [environment-configuration.md](environment-configuration.md) 的 PG 覆盖层规则生效。
- **YAML 基线参数**（股票池、市值边界、TopN、指标全局周期等，含成段中文注释）：按 [environment-configuration.md](environment-configuration.md) 的 YAML reload 规则刷新。
- **全局指标参数变更**：参数进 `build_params` → `param_hash` 变 → `IndicatorEngine` 单次运行缓存键失效；已物化评分快照在下次读取时也会因 meta 指纹不匹配而按需重算。需要提前批量维护、或变化不在现有指纹内时，才由用户执行「结果维护」或配置调度。

---

## 风险事项

| 等级 | 风险点 | 影响 | 建议 |
|------|--------|------|------|
| <span style="color:#dc2626">●</span> 高 | 已实例化服务可能持有旧配置对象 | 长任务或已创建的领域服务实例不会自动重建，可能继续使用创建时的 effective settings | 配置改动后新任务/新请求生效；需要严格切换口径时重启服务或重建相关服务实例 |
| <span style="color:#f59e0b">●</span> 中 | 部分结果输入没有读取版本 | `param_hash` 与 ST 版本能让所读榜单自愈，但其它行情/基础资料变化不会自动批量失效历史结果 | 按影响范围显式执行「结果维护」或配置调度；新增关键输入时同步扩展缓存指纹 |
| <span style="color:#f59e0b">●</span> 中 | 启动 seed 覆盖整套 builtin | 首次启用时会持久化全部注册表定义，不只是新指标；回滚旧代码前若下游已引用新 key 会无法计算 | 发布前备份 `indicator_def` 并对账完整 builtin；回滚优先停用新增定义，不直接删除 |
| <span style="color:#f59e0b">●</span> 中 | 评分指标解析仅支持固定周期映射 | 非预设 `ma/hhv` 周期在试算时失败（score_profile.py:48-56） | 任意周期先走表达式型指标 |
| <span style="color:#f59e0b">●</span> 中 | RS 指标不可逐方案调参 | `rs_pct` 使用全局窗口，方案里传参无效 | 需要多窗口 RS 时新增独立表达式/内置指标 |
| <span style="color:#f59e0b">●</span> 中 | 删除方案会断开历史引用 | 历史回测只记录 id+version，删方案后无法回溯内容 | 对已用于回测的方案优先停用/改名，不直接删除 |
| <span style="color:#f59e0b">●</span> 中 | 指标启停/删除不校验下游引用 | 已有方案可能运行时才报错或缺列 | 删除/停用前先搜索方案引用 |
| <span style="color:#16a34a">●</span> 低 | 方案版本按 JSON 字符串全等去重 | 字段顺序差异可能产生多余版本 | 前端保存前稳定 JSON 顺序 |
| <span style="color:#16a34a">●</span> 低 | 配置覆盖层回落静默 | DB 异常时会回落 YAML，改参不生效缺少信号 | 按 [environment-configuration.md](environment-configuration.md) 的风险清单排查日志、PG 和 overridden 状态 |
| <span style="color:#16a34a">●</span> 低 | 表达式型指标异常被吞为 None | 坏表达式或缺数只表现为空值（engine.py:214-215） | 新指标先小样本试算，确认缺失率 |
