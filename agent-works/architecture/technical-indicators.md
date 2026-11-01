# 技术指标架构

## 文档边界

本文维护原子指标的分类、定义仓库、参数归一、计算与治理契约，是下游方案引用指标的技术事实入口。买卖、评分及筛选方案的配置结构见 [配置定义](config-definitions.md)，业务执行见 [选股与榜单](screening-and-board.md) 和 [回测](backtest.md)；本文不保存具体研究方案或重复的下游算法。

指标元数据、公式或计算入口变化时同步本文及对应测试；数据源与逐日事实更新相应采集架构，界面契约更新 [DESIGN.md](../../DESIGN.md)，阶段治理计划和验收结果留在对应功能目录。

## 定义边界

技术指标是筛选、评分、买卖方案和回测共同引用的原子计算定义。定义保存在 DuckDB
`indicator_def`，用户方案及其版本保存在 PostgreSQL；两库需要联合时必须分别查询后在服务层合并。
下游方案只保存稳定指标 key、计算参数和自身的比较阈值、权重或逻辑组合，不复制指标公式。

指标目录使用四层业务模型，且与来源、计算方式和输出类型正交：

- `field`：行情或参考数据基础字段。
- `metric`：输出连续数值的通用指标。
- `signal`：输出成立/不成立的状态或事件。
- `preset`：通用指标的一组固定快捷参数，使用 `parent_key + preset_params` 表达父子关系。
  执行前统一归一为父指标引用；若存在等价的内置向量化列，计算器只把该列作为物理快路径，
  不再让固定 key 自己维护一份重复公式。

固定周期历史 key 继续稳定可用。新指标名称保持中性且不写死周期、阈值；周期属于计算参数，阈值属于下游方案。

## 注册与计算上下文

`backend/indicators/registry.py` 的 `REGISTRY` 提供代码管理的内置定义，`IndicatorDefRepo` 负责持久化到 `indicator_def`。`kind=builtin|expr` 描述向量化列或受限 DSL 的物理求值路径，与四层业务分类独立；自定义表达式的参数经 `render_expression` 按参数 schema 校验和渲染，函数集合以 `backend/screening/expression.py` 的实际白名单为准，不在其它文档复制函数清单。

- **启动校准**：FastAPI 存储自检在 DuckDB schema 就绪后调用 `seed_builtins()`，每次启动对齐整套 `REGISTRY`，不是只补本次新增 key。全新库会持久化全部 builtin；存量库会刷新代码管理的名称、类型、表达式、参数和描述，保留管理员明确设置的 `enabled/categories`，旧库 `NULL` 则回退注册表默认值；元数据未变化时跳过 UPDATE，避免启动写放大和无意义刷新 `updated_at`。
- **MACD 五原子**：`macd_diff`、`macd_dea`、`macd_hist` 为 `number`，`macd_golden_cross`、`macd_dead_cross` 为可空 `bool`；固定参数 12/26/9，主分类“趋势”，预设分类“趋势/动量”，默认启用且不可删除。日/周/月/年只是输入行情粒度上下文，不形成新的指标 key；各周期先按自然边界生成收盘序列，再复用同一严格后向 EMA/交叉定义。单股图表的 MACD 输入固定为前复权，板块使用连续指数原值；筛选、评分、买卖和回测继续使用日 K 上下文，未来开放其它周期时应扩展方案的周期上下文而不是复制指标。五列进入 `_IND_COLS` 后由下游通用求值链直接复用，不建立 MACD 专属分支；历史不足或输入缺失时返回空值，不用短窗口或其它周期结果代填。
- **计算上下文契约**：指标目录接口在定义列表之外返回统一 `calculation_context`。`default_period` 是当前默认输入粒度，`supported_periods` 是方案引擎实际可用粒度；现阶段两者均只包含 `day`。周期属于一次方案计算的上下文，不进入单个指标的参数 schema，也不因图表切换而改变。目录项另返回只读 `calculation_period`：K 线序列指标为 `day`，快照和事件字段为 `null`。管理页以紧凑标签只读展示指标的适用周期，自定义指标编辑器不提供引擎尚未支持的周期选项；下游不得根据指标名称或说明文字猜测周期能力。

## 计算与失效

指标值不落统一预计算表。`IndicatorEngine` 批量加载点时行情后，以 pandas 向量化计算全市场内置列，
表达式指标复用同一批行情和受限 DSL 求值。全市场行情通过 `_bulk_qfq_bars` 的窗口 SQL 批量取各股后向区间，按 `COALESCE(adj_factor_clean, adj_factor)` 复权；RS 按交易日对窗口收益做横截面百分位排名。计算只读取业务日及以前数据，平台突破等事件继续使用
前一交易日窗口，禁止未来函数。

`backend/cli.py::cmd_indicators` 保留旧 `indicators` 子命令兼容，但只输出动态计算说明，不实际计算或落库；它不是采集、筛选或回测前的预计算步骤。指标由上述消费链按业务日期按需计算。

进程级 LRU 仅缓存受规模上限保护的小结果，key 包含行情更新版本、全局指标参数指纹、股票集合和日期范围。
共享层仅保存不超过 10 万行的文件库结果，`:memory:` 测试库不共享；进程共享缓存的写入与取出均深拷贝，实例内缓存直接复用当前帧，消费方需要修改时须先复制。
行情或全局参数变化自然产生新 key；指标计算语义修改会主动清空进程缓存。评分快照指纹包含被方案引用指标的
`key、dtype、kind、expression`、参数计算字段以及预设的 `parent_key + preset_params` 和父指标定义；名称、分类、
标签、单位与说明不参与指纹，避免展示修改触发重算。

## 自定义指标契约

公式创建与编辑分别通过 `POST /api/indicators/def`、`PATCH /api/indicators/def/{key}` 进入 `backend/services/indicator_definition_service.py::IndicatorDefinitionService.save`，再调用 `IndicatorDefRepo.save_custom` 落库。服务层区分新建与编辑、禁止覆盖内置定义，并在计算语义变化时审计当前与历史方案引用；存在引用则拒绝原地变更。删除同样先经该服务的引用审计，再进入仓储，业务入口不得绕过服务直接写定义表。

key 须以英文字母开头，其余字符只允许英文、数字或下划线，输出类型限定 `bool/number`。参数、表达式占位符与 DSL 白名单校验通过后，定义保存到 `indicator_def`；仓储负责校验并写入、维护计算缓存失效，跨库引用保护由服务层负责。

自定义定义只允许安全 DSL，变量为 `C/O/H/L/V/TURN`，函数由表达式白名单控制。参数 schema 固定包含
`name、label、type、default、min、max、unit、description`。参数名、类型、范围、默认值和表达式占位符
必须一一校验；保存前使用代表性股票和交易日试算。

管理页面将这套能力称为“公式创建”，并明确它不是 Python 或 SQL；“DSL”只用于代码和架构文档中的
技术称谓。模板创建隐藏公式编辑细节，只呈现模板用途、计算参数和只读公式摘要。

指标被当前方案或任一历史方案版本引用后，key、输出类型、表达式和参数结构锁定；新口径必须另存新 key。
显示名称、说明和分类仍可维护。禁用表示不再进入新方案候选，已有方案和历史回测继续按原定义运行。
删除自定义指标前必须审计筛选、评分、买卖方案及关联回测；存在引用时拒绝删除。内置指标永不物理删除。

方案中的指标引用可带 `enabled`。历史记录缺省视为启用；评分权重只统计启用项，筛选和买卖条件在执行前递归裁剪停用叶子与空分组，禁止用固定真/假替代，以免改变 AND、OR、NOT 语义。保存、试算、快照、回测必须消费同一口径，至少保留一个有效计算项。

## 当前通用指标

- `close`：当日未复权收盘价，作为“股价”基础字段供绝对价格区间筛选和评分使用。
- `total_mv/float_mv`：指定交易日的总市值/流通市值，作为可直接参与筛选和评分的基础字段；
  日常采集维持最新交易日，历史缺口由 `valuation --fill-gaps` 回补。
- `float_share/total_share`：直接读取 `stock_share_capital_daily` 指定交易日的流通 A 股股本/总股本，
  单位为股；不读取 `stock_basic` 最新股本快照，保证历史筛选、评分和回测的点时口径。
- `pct_change`：N 日涨跌幅。N 日跌幅使用负阈值筛选，不另建跌幅指标。
- `range_amplitude_pct`：`(HHV(H,N) / LLV(L,N) - 1) × 100`。一年区间振幅使用 `N=240`。
- `ma/new_high/vol_break/platform_break/ma_up/above_ma`：承载对应固定周期历史 key 的通用定义。

定义表结构调整由 `backend/storage/ddl.py` 幂等执行，SQL 审计副本见
`agent-works/technical-indicator-governance/indicator-definition-layer-migration.sql`。新增或修改字段后必须执行
`python -m backend.cli verify-catalog`。

股本/市值实际值变更登记 `stock_share_capital_daily` 的更新日志，纳入指标缓存和评分快照的输入修订指纹；幂等采集不更新版本。四字段从逐日表读取，不在指标引擎中反算股本。
