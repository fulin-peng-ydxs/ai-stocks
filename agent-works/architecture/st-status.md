# ST 点时事实：采集、存储、质检与业务消费闭环

> 本文是 ST 状态的唯一技术口径。它回答四个问题：从哪里触发、实际怎样抓取、数据怎样发布、下游何时使用或重算。任何业务不得从当前股票名称或 `daily_bar.is_st` 推断历史 ST。

## 1. 边界与不变量

- 当前结构化事实源是 Baostock `query_history_k_data_plus` 的逐股逐日 `isST`。它是本系统统一的可执行口径，并非交易所法律文件；来源、抓取时间和每次纠错均落库审计。
- `stock_st_status_daily` 是唯一当前事实；`daily_bar.is_st` 只是兼容旧查询的物化投影。
- 行情、ST、质检与业务结果是四个不同生命周期。采集只更新行情/ST 事实及同表派生标记，不自动把评分快照或连板天梯标成失效。
- 业务读取必须经过 `StockSTStatusService` 发布门。缺失、非权威或批次未发布时失败关闭，不把未知当作非 ST。
- 主板 ST 限幅切换日、IPO 无涨跌幅限制期等规则统一在 `backend/market_rules.py`，采集、质检、回测和天梯不得各自复制。

## 2. 数据怎样存

三张 DuckDB 表由 `backend/storage/ddl.py` 幂等创建：

| 表 | 粒度与关键字段 | 职责 |
| --- | --- | --- |
| `stock_st_status_daily` | 主键 `(code, trade_date)`；`is_st/source/source_ref/quality/captured_at/updated_at` | 当前唯一逐日 ST 事实。生产采集写 `quality=accurate` |
| `stock_st_status_history` | `version_id`；新旧 ST、来源、质量、`change_reason/changed_at/task_id` | 仅在已有事实的值、来源或质量实际改变时追加，不保存无变化重抓 |
| `stock_st_status_refresh_state` | 固定 `scope_key=market`；`status/task_id/target_count/date_start/date_end/last_error/updated_at` | 全市场发布门，状态为 `refreshing/ready/failed` |

`daily_bar` 中以下字段不是第二套 ST 事实：

- `is_st`：从当前事实表同步的过渡投影；
- `limit_status`、`is_one_word`：结合当日原始价、点时 ST 和统一市场规则计算的派生标记；
- `is_suspended`：行情行自身的兼容标记，权威停牌确认另见 `stock_suspension`。

`StockSTStatusService.upsert_facts()` 在单个事务内完成当前事实 upsert 与变更历史追加。已存在的 `accurate` 事实不能被测试/受控导入的 `approximate` 值降级覆盖。

## 3. 所有触发入口

| 场景 | 用户/系统入口 | 提交参数 | 最终执行入口 |
| --- | --- | --- | --- |
| 日常同步 | 数据采集 → 个股采集 → 日常同步；或对应调度 | `task_type=stock_ingest`、`recipe=daily_update` | `_h_stock_ingest()` → `IngestionService.update()` → `ingest_one_daily()` |
| 历史补全 | 数据采集 → 历史行情补全 | `recipe=history_backfill` | `backfill()` → `ingest_one_daily()` |
| 区间重采 | 数据采集/质量恢复跳转 → 日期区间重采 | `recipe=range_refetch`、股票与日期 | `ingest_date()` → `ingest_one_daily()` |
| 退市历史 | 数据采集 → 退市股历史补全 | `recipe=delisted_history` | `enrich_basic_dates()` → `ingest_delisted()` → `ingest_one_daily()` |
| ST 专项刷新 | 数据概览“ST 点时事实”卡片，或数据采集 → ST状态刷新 | `recipe=st_status_refresh`；全市场/指定股票；可选日期 | `_h_stock_ingest()` → `refresh_st_status()` |
| ST 质量恢复 | 数据质量页恢复 `st_status_missing/approximate/mismatch` | `task_type=fix`、问题 id | `_recover_one()` → 指定股票 `refresh_st_status()` → 复检 |
| 定时校准 | 数据调度新增“个股采集”，方案选 ST状态刷新 | 与手动入口同一 `stock_ingest` 参数 | APScheduler 只负责创建同一种 `async_task`，不走旁路 |

API 统一为 `POST /api/data/tasks`，任务中心使用 PostgreSQL 的 `async_task/task_log` 展示状态、进度、检查点和结果。旧 `update/backfill/ingest_date/ingest_codes` 类型只作历史兼容；新入口统一提交 `stock_ingest`。

日常行情采集已同步抓取新增区间的 ST，不要求每天额外跑全历史专项任务。专项刷新用于首次迁移、源端纠错、批量校准和指定问题恢复。

## 4. 实际怎样抓取

### 4.1 数据源调用

`IngestionService._source_for("st_status")` 按能力选择 Baostock 适配器，最终调用：

```text
query_history_k_data_plus(
  code=<baostock 代码>,
  fields="date,tradestatus,isST",
  start_date=<起始日>,
  end_date=<结束日>,
  frequency="d",
  adjustflag="3"
)
```

- 只取 `date/tradestatus/isST`，ST 身份不依赖复权价格。
- `isST` 只接受 `0/1`；空值或其他枚举直接报数据源错误。
- 保留 `tradestatus=0` 的停牌记录，因为停牌不等于没有 ST 身份。
- Baostock 使用进程级会话，所有 ST 请求经过 `_BAO_FALLBACK_LOCK` 串行执行，避免 socket 游标串线。
- 网络、协议、游标中途失败时，`_collect()` 不返回已读部分；连接被置为失效，完整请求重新登录重试。超过重试次数后该股票记失败，不发布部分批次。

### 4.2 日线采集内的逐股流程

`ingest_one_daily(code, start, end)` 的顺序是：

```text
主行情源取原始日线
  └─ 空/异常时整段切换 Baostock 日线，不混拼同一股票区间
      ↓
sanitize_bars：清洗价格/OHLC/零成交字段，坏行进入 L1 台账
      ↓
校准除权参考价 pre_close
      ↓
按同一请求区间向 Baostock 读取逐日 isST
      ↓
要求每个待入库行情日都有 ST；缺一日则该股本次失败
      ↓
用原始价 + 当日 ST + 中央规则计算 is_st/limit_status/is_one_word
      ↓
upsert daily_bar，再 upsert stock_st_status_daily/history
```

若行情源返回空，只有 Baostock 对请求区间每个开市日都返回 `tradestatus=0`，系统才把它认定为确认停牌：保存 ST 事实、日线写 0 行。周末、源端空响应或覆盖不全不能伪装成停牌成功。

日线与 ST 是连续两次写入，不是跨表大事务；两次写入之间的并发业务读取最多会因 ST 缺失而失败关闭，不会得到“默认非 ST”的错误结果。写任务全局单写者互斥也禁止另一个采集/修复任务交叉写入。

### 4.3 ST 专项刷新的目标与区间

`_st_refresh_spans()` 只计算一次目标集合，同时供 `refresh_state.target_count` 和实际循环使用，避免任务显示数与执行数分叉：

1. 目标股票为 `daily_bar` 已有股票与 `stock_basic.list_date <= 市场最新行情日` 股票的并集；因此刚上市但尚无日线的股票也在范围内。
2. 每股默认起点为已有日线最早日，没有日线则为 `list_date`。
3. 每股默认终点为市场最新行情日，并受 `delist_date` 截断。
4. 用户指定日期时，再用 `start/end` 收窄上述自然区间。
5. 每股强制整段重抓，源端返回的区间记录全部写入；已有日线日期和市场最新日必须被源端覆盖，否则该股失败。

循环严格串行。每完成一股，将 `st_done_codes` 与累计 `st_changed_dates` 写入任务检查点；服务中断后“续跑”跳过已完成股票。`st_changed_dates` 只是事实变化报告，不是自动下游失效指令。

## 5. 批次怎样发布，为什么不会双态交叉

专项刷新采用“关门抓取、完整后开门”：

```text
begin_refresh
  state = refreshing
      ↓
逐股抓取并原子 upsert 当前事实 + 历史
      ↓
任一股票失败 ───────────────→ state = failed；不重建全量投影
      ↓ 全部成功
set-based 重建目标 daily_bar.is_st/limit_status/is_one_word
      ↓
核对全体 daily_bar：ST accurate == expected
      ↓
state = ready
```

- `refreshing/failed` 时，`assert_published()` 阻断业务读取，因此业务不会消费“部分股票已更新、部分仍是旧值”的混合批次。
- 成功股票的事实和历史不会因其他股票失败而回滚；它们用于后续幂等续跑，但发布门保持关闭。
- 若全市场批次失败后只刷新失败子集，开门前会全量重建所有日线投影，避免事实已完整而旧派生标记仍混杂。
- `ready` 同时要求源端本批零失败、全市场日线 ST 全覆盖且全部 `accurate`。覆盖率 100% 但状态不是 `ready`，业务仍不可用。

这解决的是 ST 事实发布的双态交叉；它不等于自动重算历史业务结果。已发布的评分、回测、天梯有各自的版本和维护生命周期。

## 6. 质检、结构体检和概览怎样体现

### 6.1 可恢复质量台账

统一质检 `verify` 由 `DataIntegrityReport.scan_quality_issues()` 写入：

| 问题类型 | 发现条件 | 恢复动作 |
| --- | --- | --- |
| `st_status_missing` | 有日线、无当前 ST 事实 | 指定股票专项刷新 → 复检 |
| `st_status_approximate` | 事实仍为测试/受控导入口径 | Baostock 重抓为 `accurate` → 复检 |
| `st_status_mismatch` | `daily_bar.is_st` 与唯一事实不同 | 重抓并重建投影 → 复检 |

三类均进入 ST 层高严重度台账。恢复失败时 issue 回到 `open`，不会悬在 `fixing`；复检通过才置 `resolved`。

异常涨跌质检只检查存在有效 `pre_close` 且已经过新股前五交易日豁免的行。新股首日 `pre_close=NULL` 是合法结构，不应生成异常记录；连板天梯也必须先识别 IPO 无涨跌幅限制，再决定是否要求 `pre_close`。

### 6.2 只读体检和页面概览

- “结构体检”检查所有 `daily_bar` 是否有 `accurate` ST 事实，以及 `daily_bar.is_st` 是否与唯一事实一致。
- “数据概览”的“ST 点时事实”卡片展示 `expected/present/accurate/approximate/missing/coverage_rate` 和批次发布状态；点击直接打开 ST状态刷新方案。
- 该覆盖率以已有 `daily_bar` 行为分母；连板天梯还会独立核对目标交易日的点时股票池、确认停牌、IPO 规则和行情合法性。因此概览 100% 不代表任意天梯日期必然可发布，天梯会给出自己的 coverage 原因码和样本股票。

## 7. 业务怎样消费

`StockSTStatusService.status_map(trade_date, codes)` 是通用业务读取入口。请求范围只要存在缺失、`approximate` 或全局发布态非 `ready`，就抛出 `STStatusNotReadyError`，不返回残缺映射。

| 业务 | 使用方式 |
| --- | --- |
| 个股列表/点时股票池/分组股票池 | 按目标交易日取 ST，用于展示和排除 ST |
| 策略筛选/每日评分/买卖方案 | 在形成候选或结果前通过点时门禁 |
| 回测 | 每日候选和撮合使用点时 ST；运行签名记录精确到微秒的事实版本与发布状态，纠错后不复用旧结果 |
| 盘感训练 | 原始价成交性判断读取当日 ST 与统一限幅规则 |
| 连板天梯 | 日期级 coverage 先校验 ST、行情、停牌与 IPO 规则，再计算连续板并原子发布快照 |

指标引擎可把未知 ST 暴露为空，但不能自行判定业务可用；真正形成候选、排名、成交或快照的服务必须负责门禁。

## 8. 下游结果维护契约

ST 刷新完成后返回：

- `changed_dates`：发生事实新增或改变的交易日数量；
- `changed_date_values`：具体日期列表，供用户判断影响范围；
- `projection_rows`：本次重建的日线投影行数；
- `downstream_results_untouched=true`：明确表示未修改下游结果状态。

采集代码不再调用 `ScoreSnapshotRepo.mark_stale_dates()`，也不调用 `LimitLadderSnapshotService.request_invalidation()`。原因是“事实发生变化”和“业务结果现在就要更新”不是同一项用户决策：历史页面可能需要保留旧发布结果做复核，某些变更也可能与当前使用范围无关。

需要更新时，由用户在任务中心手动执行，或在调度页显式配置依赖：

| 结果维护任务 | 实际含义 | 后续行为 |
| --- | --- | --- |
| 每日榜单失效 `recompute` | 将用户选择日期/全部评分快照标为 stale | 下次读取按当前事实重新物化 |
| 连板天梯失效 `limit_ladder_invalidate` | 从用户选择日期起标记已发布天梯失效 | 下次访问失效日期时创建内部 `limit_ladder_recompute` |
| 连板天梯单日重算 | 页面重算按钮或失效后按需创建内部任务 | coverage 通过才原子发布新版本；失败保留最后成功版本 |
| 回测 | 不修改旧运行 | 用户显式新建回测；ST 数据版本阻止把新事实命中旧缓存 |

调度依赖只决定“何时创建另一个任务”，不把 `changed_date_values` 自动推断成下游参数。用户应根据任务结果选择固定起始日、最新日或全部范围。采集成功本身不会删除、覆盖或失效任何既有业务结果。

## 9. ST 涨跌停规则截止点

统一规则来自 `backend/market_rules.py`：

| 股票范围 | ST 限幅 |
| --- | --- |
| 沪深主板，2026-07-06 之前 | 5% |
| 沪深主板，2026-07-06 起 | 10% |
| 创业板、科创板 | 20% |

主板切换常量为 `MAIN_BOARD_ST_10_EFFECTIVE_DATE = date(2026, 7, 6)`。规则按每行 `trade_date` 判定，不能按任务运行日或当前名称判断。分价统一用 `ROUND_HALF_UP` 到分。

IPO 规则同样集中维护：科创板、注册制创业板和注册制主板上市前五个交易日无涨跌幅限制。此时 `pre_close` 可以为空，天梯将该行识别为 `NO_PRICE_LIMIT`，不会把它算作涨停，也不会作为坏行情阻断发布；普通限价日缺少 `pre_close` 仍会失败关闭。

规则依据：[证监会上海监管局说明](https://www.csrc.gov.cn/shanghai/c105566/c7643909/content.shtml)、[上交所交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)、[深交所交易规则 PDF](https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf)。

## 10. 运维与验证

首次上线或全局校准：

1. 在“数据采集”运行“ST状态刷新”，范围选全市场，日期留空。
2. 等任务终态完成且 `publication_status=ready`；失败时按任务日志续跑或重跑失败范围。
3. 在“数据概览”确认覆盖率 100%、缺失 0、非权威 0、发布态 ready。
4. 运行“数据质检”和“结构体检”。
5. 查看刷新结果的 `changed_date_values`，由用户决定是否执行每日榜单、连板天梯或新回测。

主要验证入口：

- 数据源协议、事实审计、刷新目标、检查点、发布门和“不自动失效”：`backend/tests/test_st_status_pipeline.py`
- 主板 ST 截止点、IPO 规则与分价：`backend/tests/test_limit_ladder_rules.py`、`backend/tests/test_quality.py`
- 天梯完整性门禁与原子发布：`backend/tests/test_limit_ladder_t3.py`、`backend/tests/test_limit_ladder_t4.py`
- 质检与恢复：`backend/tests/test_data_mgmt_c.py`
- 筛选、评分、回测与点时股票池：对应 `test_screening.py`、`test_pit.py`、`test_backtest.py`
