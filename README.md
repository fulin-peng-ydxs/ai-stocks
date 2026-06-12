# 趋势选股 · A股龙头选股 / 打分 / 回测系统

本地单用户 **EOD（收盘后）** 的 A 股趋势龙头选股系统：从数据采集、指标计算、条件筛选、多维打分榜单，到信号质量分析与事件驱动策略回测、买点/风险识别、观察池跟踪，形成一条可解释、可回测、防未来函数的完整闭环。

> 仅供个人研究，不构成投资建议。数据源为公开免费接口（新浪/东财/baostock），近 5 年、主板/创业板/科创板（不含北交所）。

---

## 功能一览

| 模块 | 说明 |
|------|------|
| 📈 **每日榜单** | 全市场打分排序（位置/趋势/量/换手/RS，0–100 分 + 分档），含买点列、风险标记、分项分热力色块；排除 ST；可导出 CSV |
| 🧮 **策略筛选** | 三种方式：①预设/已存方案 ②**可视化勾选构建**（选指标+阈值+AND/OR）③手写表达式 DSL；命中按综合分排序；方案可保存 + **版本历史回看/恢复** |
| 🧪 **策略回测** | **信号质量分析**（分档命中率 vs 全市场基线 base rate）+ **事件驱动策略回测**（T+1 开盘成交、含成本、涨跌停/停牌/退市硬约束）；资金曲线、绩效、逐笔交易、**K 线交易回放**（买卖点 + 卖后表现 + 每日榜单排名）；历史回测可重载/删除/导出 |
| ⭐ **观察池** | 进 Top-N 入池、综合分跌破观察线才移出（缓冲带，防 rank 抖动）；按日回看入池/保留/移出与入池至今表现 |
| 🔍 **个股查询** | 搜索/板块筛选/分页（含退市股，防幸存者偏差）；个股详情：同花顺风格 K 线（全量+缩放）、买点/风险标注、最新指标快照 |
| 🗄️ **数据管理** | 最新数据日期、数据量、更新日志、质检问题 |

---

## 技术栈

- **后端**：Python 3.11+ / FastAPI / DuckDB（嵌入式列存）/ pandas / APScheduler
- **前端**：Vue 3 + TypeScript + Element Plus + ECharts + Pinia + Vite
- **数据**：AKShare（新浪系）+ baostock（退市股/复权因子兜底）

## 目录结构

```
backend/        FastAPI 后端
  datasource/   数据源适配（akshare / baostock，限流/重试/超时）
  storage/      DuckDB 连接、DDL、点时安全仓库（防未来/幸存者偏差总闸门）
  dataquality/  入库清洗 + 质检
  indicators/   指标引擎（后向算子、param_hash）
  screening/    条件 AST + 表达式 DSL 沙箱 + 筛选引擎
  scoring/      评分模型
  signals/      买点状态机 / 风险识别
  backtest/     前向收益 / 信号质量 / 撮合 Broker / 事件驱动引擎 / 绩效 / expr 预计算
  services/     编排：入库、筛选打分、回测、一键日常流程(DailyPipeline)
  scheduler/    APScheduler 定时调度
  api/          REST 接口
  cli.py        命令行入口
frontend/       Vue3 前端（构建产物由 FastAPI 托管）
config/         settings.yaml（所有阈值/权重/参数，改参不改码）
data/           DuckDB 数据文件
docs/           需求 / 系统设计 / 任务清单
```

---

## 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt          # 后端
cd frontend && npm install && npm run build && cd ..   # 前端（产物进 frontend/dist）
```

### 2. 准备数据（首次）
```bash
python -m backend.cli backfill            # 全市场近 5 年日线全量回填（耗时较长，支持断点续跑）
python -m backend.cli delisted --enrich   # 退市股历史 + 上市/退市日（防幸存者偏差）
python -m backend.cli valuation           # 总市值/总股本
python -m backend.cli indicators          # 计算全市场指标
python -m backend.cli seed-presets        # 内置预设筛选方案入库
python -m backend.cli verify-data         # 数据正确性 + 完整性核查
```

### 3. 启动服务
```bash
python -m backend.cli serve               # http://127.0.0.1:8000
```

### 4. 日常使用（每天收盘后）
```bash
python -m backend.cli daily               # 一键：更新→指标→榜单(含买点/风险)→观察池→预设筛选
python -m backend.cli daily --skip-update # 数据已最新时，只重算榜单等（最省时）
```
或开启定时调度：把 `config/settings.yaml` 的 `scheduler.enabled` 设为 `true`，服务会在每交易日 18:00 自动跑 `daily`（非交易日跳过）。

---

## 常用 CLI

| 命令 | 作用 |
|------|------|
| `serve` / `health` | 启动 Web 服务 / 本地自检 |
| `backfill` / `update` | 全量回填 / 增量更新日线 |
| `delisted` / `valuation` | 退市股历史 / 总市值 |
| `indicators` / `rank` / `screen` | 算指标 / 出榜单 / 跑筛选 |
| `daily` | 一键日常流程（见上） |
| `backtest --kind signal\|strategy --start ... --end ...` | 信号质量 / 策略回测 |
| `check-data` / `verify-data` | 数据体检 / 正确性核查 |

---

## 正确性约定（本系统的命脉）

- **防未来函数**：所有指标/均线后向计算；选股用 ≤T 数据，回测 T 日选股、**T+1 开盘成交**；平台突破用 `shift(1)` 防自指（AST 单测拦截 `shift(负)`）。
- **防幸存者偏差**：universe 点时构造含"当时存活、后来退市"的票；退市股历史已入库。
- **撮合不失真**：涨跌停价按板块/ST，开盘封死涨/跌停不可成交、停牌顺延、退市强平；计佣金/印花/过户/方向性滑点。
- **复权一致**：前向收益/回测记账统一**后复权(hfq)**（比值即真实复权收益、无未来）；涨跌停可成交性用**原始价**（涨跌停按分四舍五入）。
- **base rate**：分档命中率必减同期全市场无条件命中率，得超额，附样本量。

> 配置即时生效：所有阈值/权重在 `config/settings.yaml`，编辑后 `POST /api/config/reload` 或重启即生效。

## 测试
```bash
python -m pytest backend/tests/ -q        # 全部后端单测（需先停掉占用 DuckDB 的服务）
```

## 状态

**M0–M7 全部完成，MVP 100% 交付**（67/67 任务）。完整闭环：选股→打分→筛选→回测(信号质量+事件驱动)→买点/风险→观察池→可视化方案构建→一键日常流程→定时调度→配置即时生效→导出，且可在交易日自动运行。93 后端单测全绿；SDD §18 正确性自检清单逐条复核通过。

## 已知限制 / 后续优化
- ST 历史每日状态免费源缺，按当前名称尽力而为（入库已按名称置标）；点时 ST 时间线待更优数据源。
- 日更并发提速已实现（`datasource.update_concurrency`），默认串行最稳；全市场提速幅度需联网整日运行实测，并注意源封禁风险。
- 缺失/停牌缺口由数据体检 coverage 汇总，不逐条记 `data_quality_issue`（避免淹没真异常）；adj_jump 复权异常逐条记录。
- 导出暂为 CSV（未做 Excel）；九号公司 CDR 历史可按需 baostock 兜底。
- 评分模型各分档超额命中率均为正、但非严格单调（详见 SDD §19.9 实证结论），后续可据此调权重/加因子。

详见 `docs/`：《需求文档》《系统设计文档》《任务清单》。
