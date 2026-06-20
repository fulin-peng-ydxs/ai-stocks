# 个股与分组

> 围绕单只股票的查询、K线与信号详情，以及用户手动圈定的股票篮子（分组）管理。

<span style="color:#2563eb">●</span> 个股查询　<span style="color:#7c3aed">●</span> 信号详情　<span style="color:#16a34a">●</span> 分组跟踪　<span style="color:#dc2626">●</span> 性能风险

## 核心技术

### 个股列表：服务端排序 + 分页
列表查询全部在 SQL 层完成筛选、排序、分页，不在前端排全量（`backend/api/stocks.py:23` `list_stocks`）。
- 排序字段走白名单映射防注入：`_STOCK_SORT_COLS`（`stocks.py:20`）只放行 `pct_chg / name / industry / code`，其余回落 `pct_chg`；`sort_order` 仅 `asc/desc`。排序统一 `... NULLS LAST, sb.code ASC`（`stocks.py:58`），停牌（当日无行情）的 NULL 涨跌幅恒排末尾，并以 code 作稳定次序键。
- 当日涨跌幅按交易日 `LEFT JOIN daily_bar` 现算 `(close/pre_close-1)*100`（`stocks.py:62`），`trade_date` 缺省取 `max(trade_date)`。
- 退市/ST 口径：`board='退市'` 只看 `delist_date IS NOT NULL`，其余板块一律 `delist_date IS NULL` 排除退市；`board='ST'` 按名称含 `ST` 过滤，其它板块可选 `exclude_st` 再剔 ST（`stocks.py:42-52`）。
- 每行附带所属分组标签：批量查 `StockGroupRepo.groups_for_codes`（`stocks.py:68`、`groups/stock_group.py:209`），一次 JOIN 取齐当页所有 code 的分组，避免 N+1。

### K线 + 指标快照取数
详情页三块数据由前端并发拉取（`StockDetailView.vue:164`）：
- K线 `GET /stocks/{code}/bars`（`stocks.py:78`）经 `MarketRepository.get_bars` 按复权方式（qfq/hfq）输出，含 `pre_close`（算涨幅/振幅）、成交额、换手率。
- 指标序列 `GET /stocks/{code}/indicators`（`stocks.py:201`）由 `IndicatorEngine.compute_series` 实时计算（指标无存储表，动态算），多取 520 行暖机窗口后裁末段 lookback；横截面量 `rs_pct` 在单股序列下不填。
- 详情页展示「最新一日指标快照」（取序列末行，`StockDetailView.vue:172`）。

### 买卖信号：由当前买卖方案推导
个股详情的买卖信号不是固定引擎，而是用「当前选定的买卖指标方案」在该股当日快照上现算（`GET /stocks/{code}/trade-eval`，`stocks.py:156`）：
- 取 `TradeProfileRepo.get(profile_id)` 拿到买/卖条件树（`signals/trade_profile.py:173`），用 `IndicatorEngine.wide_snapshot` 取单股当日截面，`attach_columns` 预补条件树用到的全部指标列（`collect_indicators`）。
- `eval_conditions` 递归按 AND/OR 合并叶子比较得买入/卖出命中布尔（`trade_profile.py:43`）；`_describe_tree`（`stocks.py:123`）把条件树拍平为每个叶子的中文标签 + 该股是否成立明细，供详情页逐条展示。
- 点时安全：只用 `≤ 当日` 数据，方案所用指标均非横截面，单股快照求值即正确。
- 旧的 `GET /stocks/{code}/signal`（`stocks.py:105`）仍在，按 `ScreenScoreService.compute_signals` 给出 `buy_point` 文案 + `risk_flags` + K线买点标记，与方案评估互补。

### 分组篮子：跨页多选累积与导航
- 选择购物车（`StocksView.vue:216` `cart`）在前端维护，按 code 去重，跨分页/跨搜索/跨普通查询与分组视图累积，切换上下文（切分组）才清空（`StocksView.vue:142`）。表头全选只对「当前页」做并/差集（`toggleAllCur`，`StocksView.vue:232`）。
- 进入详情时把「当前集合」写入 `stockSet` store（`stores/stockSet.ts`，localStorage 持久化）：来源可为分组成员、列表当前页或勾选集。集合记录有序 `items`、`query`（可续拉）、`total`、`loadedPages`、`pageSize`。
- 上一只/下一只导航（`StockDetailView.vue:73` `gotoNeighbor`）：先取集合内相邻 code；到达已加载边界且 `query` 存在时，按 `loadSetPage` 续拉上/下一页并合并（`appendPage` 按页号决定 unshift/push），实现跨页连续翻看。连点用 AbortController 取消在途 + 140ms 防抖只发最终一次（`StockDetailView.vue:137,183`）。

## 业务架构

### 三块功能
1. 个股查询（`StocksView.vue` 普通查询视图）：按交易日/板块/ST/退市/关键词筛选，服务端排序分页，行内显示涨跌幅与所属分组。
2. 个股详情（`StockDetailView.vue`）：K线图 + 最新指标快照 + 当前买卖方案在该股的买入/卖出信号与逐条成立明细 + 分组归属编辑 + 集合内上一只/下一只导航。
3. 股票分组（`StocksView.vue` 分组视图 + `stock_groups.py`）：用户手动圈定的股票篮子，含成员加入日期与自加入日起的等权平均涨幅。

### 与其它模块的关系
- 指标模块：详情快照、指标序列、买卖条件求值都依赖 `IndicatorEngine`（实时计算，无指标表）；条件树与评分共用 `resolve_indicator`。
- 买卖方案模块：详情信号直接消费 `trade_profile`（买/卖条件树 + 兜底止盈止损/最大持仓），方案列表由 `tradeProfile` API 提供，默认选首个方案。
- 数据管理模块：列表涨跌幅、K线、分组涨幅均读 `daily_bar`；前复权口径统一 `close*COALESCE(adj_factor_clean, adj_factor)`（`stock_group.py:240,252`）。
- 默认自选分组：`StockGroupRepo` 初始化时确保存在 `grp_default_watchlist`（`stock_group.py:44`），固定红色、不可改名/改色/删除。

### 涉及表
- `stock_group`（`storage/ddl.py:304`）：分组元信息 id/name/group_date/description/color/is_default。
- `stock_group_member`（`ddl.py:317`）：主键 `(group_id, code)`，`add_date` 为该股加入日期即涨幅基准，`note` 备注。
- 读：`stock_basic`（板块/退市/名称）、`daily_bar`（行情/复权）。

### 主要 API
- 个股：`GET /stocks`、`/stocks/{code}/bars`、`/stocks/{code}/indicators`、`/stocks/{code}/trade-eval`、`/stocks/{code}/signal`。
- 分组：`GET/POST /stock-groups`、`GET/PATCH/DELETE /stock-groups/{gid}`、`POST/DELETE /stock-groups/{gid}/members`、`PATCH /stock-groups/{gid}/members/{code}`（改单股加入日）。

## 页面使用说明书

个股与分组模块解决两件事：一是查单只股票当前和历史状态，二是把一批股票保存成可持续跟踪的篮子。

### 1. 个股查询列表

| 控件/列 | 作用 | 说明 |
|---------|------|------|
| 交易日 | 决定涨跌幅和行情截面 | 默认最新交易日 |
| 板块筛选 | 主板/创业板/科创板/ST/退市等 | 退市股单独入口，便于历史复盘 |
| 关键词 | 按代码或名称搜索 | 服务端筛选 |
| 排序 | 涨跌幅、名称、行业、代码 | 服务端排序，停牌 NULL 排后 |
| 所属分组 | 显示该股票已加入哪些篮子 | 便于避免重复维护 |
| 勾选框 | 加入当前选择购物车 | 支持跨页累积 |

**使用路径**：筛选条件缩小范围 → 按涨跌幅或行业排序 → 跨页勾选 → 存为新分组或加入已有分组 → 点击股票进入详情。

### 2. 个股详情页

| 区块 | 展示内容 | 业务用途 |
|------|----------|----------|
| K线图 | 复权 K线、成交量、涨跌幅 | 复盘形态和断档 |
| 最新指标快照 | 均线、强弱、趋势、量能等 | 判断该股处于什么状态 |
| 买卖方案信号 | 当前方案买入/卖出是否触发 | 解释方案在单股上的结果 |
| 条件明细 | 每条条件的当前值与命中状态 | 排查为什么触发/没触发 |
| 分组归属 | 加入/移出分组，维护备注 | 跟踪人工股票池 |
| 上一只/下一只 | 在当前集合中连续翻看 | 适合复盘榜单、筛选结果或分组 |

**详情页和配置管理的关系**：详情页信号来自当前选中的买卖方案，不是固定文案。切换方案或交易日会重新计算条件树，因此它可以用来调试买卖方案。

### 3. 股票分组

| 功能 | 说明 |
|------|------|
| 默认自选 | 系统初始化固定存在，不可删除 |
| 新建分组 | 名称、日期、颜色、说明、成员 |
| 加入已有分组 | 可指定加入日期，作为组内收益基准 |
| 分组详情 | 查看成员、自加入日起涨幅、组内平均涨幅 |
| 组内维护 | 移出成员、编辑备注、调整加入日 |

**分组闭环**：

```mermaid
flowchart LR
  A["榜单/筛选/个股列表发现股票"] --> B["跨页勾选"]
  B --> C["存为分组或加入分组"]
  C --> D["分组视图跟踪等权涨幅"]
  D --> E["详情页连续复盘"]
  E --> F["调整备注/移出/保留"]
```

### 4. 与其它模块的关联关系

| 模块 | 关联方式 |
|------|----------|
| 数据管理 | 提供 K线、涨跌幅、市值、退市状态；数据缺口会直接反映在详情页 |
| 配置管理 | 买卖方案决定详情页信号；指标注册表决定快照字段 |
| 每日榜单 | 榜单股票可进入详情复盘，也可手动沉淀进分组 |
| 策略筛选 | 筛选命中股票可进入详情或转入人工分组 |
| 回测验证 | 逐笔成交股票可回详情页复盘买卖点是否合理 |

### 5. 使用注意事项

| 注意项 | 说明 |
|--------|------|
| 跨页选择 | 表头全选只作用当前页，购物车负责跨页累积 |
| 集合导航 | 详情页上一只/下一只基于进入详情时的集合快照 |
| 加入日期 | 分组涨幅从加入日基准价开始算，加入日不同涨幅不同 |
| 退市股 | 退市股可查历史，但不会进入普通在市板块 |
| 信号为空 | 可能是数据不足、指标无法计算或方案条件未满足，需要看条件明细和数据质量 |

## 业务流程

### 查个股详情看信号
1. 个股查询页选交易日/板块/关键词，服务端返回当页列表（含涨跌幅、所属分组）。
2. 点击某行进入详情：写入「当前集合」（含本页查询快照），跳 `/stocks/{code}`。
3. 详情页并发拉 K线 + 最新指标快照 + 当日实时行情；默认选首个买卖方案调 `trade-eval`，展示买入/卖出是否触发及每条条件成立明细、兜底参数。
4. 切换买卖方案或交易日即重算信号；用上一只/下一只在集合内连续翻看，到边界自动续拉下一页。

### 建 / 用股票分组
1. 普通查询中跨页/跨搜索勾选股票，累积进底部购物车。
2. 「存为新分组」（填名称/建组日期/颜色/说明，成员加入日默认=建组日期）或「加入已有分组」（指定加入日为涨幅基准，已在组内者保留原加入日）。
3. 切到分组视图：横幅显示整组等权平均涨幅，成员表服务端分页/排序/组内搜索，列含加入日期、自加入日起最近涨幅、截至日。
4. 组内可勾选成员「从本组移出」、编辑分组元信息、删除分组（默认自选除外）；点成员进详情后以该组为集合导航。

## 风险事项

| 等级 | 风险点 | 影响 | 建议 |
|------|--------|------|------|
| <span style="color:#dc2626">●</span> 高 | 分组涨幅逐成员查 SQL（`stock_group.py:229`） | 超大分组打开耗时随成员数线性放大 | 大分组控制规模；后续批量化基准价查询 |
| <span style="color:#f59e0b">●</span> 中 | 分组详情搜索/排序/分页在 Python 内存层完成 | 成员极多时需全量物化再切片 | 大分组避免复杂排序；后续下推 SQL |
| <span style="color:#f59e0b">●</span> 中 | `add_members` 返回 added 计数含已存在成员（`stock_group.py:124`） | 前端提示数量可能偏大 | 返回实际插入数，或提示"已提交成员数" |
| <span style="color:#16a34a">●</span> 低 | `stockSet` 依赖 localStorage 快照 | 多标签页变更后相邻导航不会同步 | 需要最新集合时从列表重新进入详情 |
| <span style="color:#16a34a">●</span> 低 | `trade-eval` 指标无法计算时返回 400（`stocks.py:188`） | 详情页信号卡可能清空，难区分缺数和未触发 | 同时查看数据质量和条件明细 |
