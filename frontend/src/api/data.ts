// 数据管理 API（对应 backend/api/data_admin.py + data_tasks.py + stocks.py 的 /data/*）
import http from './client'

// ── 四层质量模型（M2.9 DM-D15）──
export interface QualityLayer {
  layer: 'L1' | 'L2' | 'L3' | 'L4'
  name_cn: string
  desc: string
  pass_stocks: number
  total: number
  pass_rate: number
  issues: number
}

// ── 概览（FR-DM-1 + M2.9 分层质量评分）──
export interface Overview {
  latest_trade_date: string | null
  codes: { active: number; delisted: number }
  bar_rows: number
  quality: { open: number; by_severity: Record<string, number>; score: number; by_layer: QualityLayer[] }
  gaps: { stocks_with_gap: number; gap_days_total: number; latest_trade_date: string | null }
  last_scan_at: string | null
}
export function getOverview(): Promise<Overview> {
  return http.get('/data/overview')
}


export interface CatalogField { name: string; type: string; name_cn: string; desc: string }
export interface CatalogTable {
  table: string
  name_cn: string
  purpose: string
  rows: number
  latest_time: string | null
  fresh: boolean | null
  fields: CatalogField[]
  relations: string[]
  open_issues: number
}
export function getCatalog(): Promise<{ tables: CatalogTable[] }> {
  return http.get('/data/catalog')
}

export interface Dimension {
  dimension: string
  name_cn: string
  status: 'collected' | 'planned' | 'partial'
  source: string
  tables: string[]
  descr: string
}
export function getDimensions(): Promise<{ dimensions: Dimension[] }> {
  return http.get('/data/dimensions')
}

export interface StockQualityLayer {
  name_cn: string
  ok: boolean
  issues?: number
  gap_days?: number
  gap_lo?: string | null
  gap_hi?: string | null
  stale_days?: number
  stale_lo?: string | null
  is_fresh?: boolean
}
export interface StockQualityRow {
  code: string
  name: string
  latest_date: string | null
  is_fresh: boolean
  total_mv_ok: boolean
  gap_days: number
  open_issues: number
  layers: Record<'L1' | 'L2' | 'L3' | 'L4', StockQualityLayer>
}
export interface StockQuality {
  total: number
  page: number
  size: number
  latest_trade_date: string | null
  list: StockQualityRow[]
}
export function getStockQuality(
  params?: { codes?: string; keyword?: string; page?: number; size?: number },
): Promise<StockQuality> {
  return http.get('/data/stock-quality', { params })
}

// ── 数据状态 / 采集日志（FR-DM-6）──
export interface UpdateLog {
  table_name: string
  source: string
  status: string
  row_count: number
  date_start: string | null
  date_end: string | null
  detail: string | null
  updated_at: string
}
export interface DataStatus {
  latest_trade_date: string
  distinct_codes: number
  bar_rows: number
  // 当前活跃质量问题：status in ('open', 'fixing')，与质量页默认筛选一致。
  quality_issues: number
  recent_updates: UpdateLog[]
}
export function getDataStatus(): Promise<DataStatus> {
  return http.get('/data/status')
}

// ── 质检与修复（FR-DM-4）──
export interface QualityIssue {
  id: number
  code: string
  name: string
  trade_date: string | null
  issue_type: string
  severity: 'high' | 'mid' | 'low'
  status: 'open' | 'fixing' | 'resolved' | 'ignored'
  detail: string
  detected_at: string | null
  resolved_at: string | null
}
export interface QualitySummaryItem { issue_type: string; n: number }
export interface DataQuality {
  summary: QualitySummaryItem[]
  total: number
  page: number
  size: number
  list: QualityIssue[]
}
export function getDataQuality(params?: {
  issue_type?: string
  severity?: string
  status?: string
  code?: string
  page?: number
  size?: number
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}): Promise<DataQuality> {
  return http.get('/data/quality', { params })
}
export function fixQualityIssue(issueId: number): Promise<{ task_id: string }> {
  return http.post(`/data/quality/${issueId}/fix`)
}
export function fixQualityBatch(issueIds: number[]): Promise<{ task_id: string }> {
  return http.post('/data/quality/fix-batch', { issue_ids: issueIds })
}
export function ignoreQualityIssue(issueId: number): Promise<{ id: number; status: string }> {
  return http.post(`/data/quality/${issueId}/ignore`)
}
// 手动复位「修复中」→「未处理」：绑定的修复任务已失败/中断/卡死时解套
export function resetQualityIssue(issueId: number): Promise<{ id: number; status: string }> {
  return http.post(`/data/quality/${issueId}/reset`)
}
// 标记退市：人工指定退市日，解决该股缺口/滞后（应对数据源退市识别不准）
export function markDelisted(issueId: number, delistDate: string):
  Promise<{ code: string; delist_date: string; resolved: number }> {
  return http.post(`/data/quality/${issueId}/mark-delisted`, { delist_date: delistDate })
}
export function recoverQualityBatch(
  // issue_type/severity 支持多值（数组，后端按 IN 过滤）
  filter: { issue_type?: string[]; severity?: string[]; code?: string },
): Promise<{ task_id: string; count: number }> {
  return http.post('/data/quality/recover-batch', filter)
}

// ── 定时任务（调度系统重构）──
export type FreqType = 'daily' | 'weekly' | 'monthly' | 'cron'
export interface FreqConfig {
  time?: string          // 'HH:MM'（daily/weekly/monthly）
  weekdays?: number[]    // 1..7（weekly）
  day?: number           // 1..28（monthly）
  cron?: string          // cron 表达式（cron）
}
export interface ScheduledJob {
  id: string
  name: string
  task_type: TaskType
  params: Record<string, any>
  freq_type: FreqType
  freq_config: FreqConfig
  trading_day_only: boolean
  enabled: boolean
  last_run_at: string | null
  last_task_id: string | null
  created_at: string
  updated_at: string
  freq_text: string
  next_run_time: string | null
}
export interface ScheduledJobInput {
  name: string
  task_type: TaskType
  params?: Record<string, unknown>
  freq_type: FreqType
  freq_config: FreqConfig
  trading_day_only: boolean
  enabled: boolean
}
export function listSchedules(): Promise<{ jobs: ScheduledJob[]; task_types: TaskType[] }> {
  return http.get('/data/schedules')
}
export function createSchedule(body: ScheduledJobInput): Promise<ScheduledJob> {
  return http.post('/data/schedules', body)
}
export function updateSchedule(id: string, body: ScheduledJobInput): Promise<ScheduledJob> {
  return http.put(`/data/schedules/${id}`, body)
}
export function setScheduleEnabled(id: string, enabled: boolean): Promise<ScheduledJob> {
  return http.post(`/data/schedules/${id}/enabled`, null, { params: { enabled } })
}
export function deleteSchedule(id: string): Promise<{ id: string }> {
  return http.delete(`/data/schedules/${id}`)
}
export function runSchedule(id: string): Promise<{ task_id: string }> {
  return http.post(`/data/schedules/${id}/run`)
}

// ── 数据源状态（FR-DM-5）──
export interface SourceStatus {
  source: string
  role: 'primary' | 'fallback'
  up: boolean | null
  last_success_at: string | null
  timeout_sec: number
}
export function getSources(ping = false): Promise<{ sources: SourceStatus[] }> {
  return http.get('/data/sources', { params: { ping } })
}
export function testSources(): Promise<{ sources: SourceStatus[] }> {
  return http.post('/data/sources/test')
}

// ── 系统设置（FR-DM-12）──
export interface SettingField {
  path: string
  label: string
  desc?: string
  type: 'int' | 'number' | 'bool' | 'enum'
  value: any
  default: any
  overridden: boolean
  options?: string[]
  min?: number
  max?: number
}
export interface SettingGroup { key: string; label: string; desc?: string; fields: SettingField[] }
export function getSettingsView(): Promise<{ groups: SettingGroup[] }> {
  return http.get('/data/settings')
}
export function saveSettings(updates: Record<string, any>): Promise<{ saved: number }> {
  return http.post('/data/settings', { updates })
}
export function resetSettings(paths: string[]): Promise<{ reset: number }> {
  return http.post('/data/settings/reset', { paths })
}

// ── 异步数据任务（M2.6 + M2.8-B）──
export type TaskType =
  | 'update' | 'backfill' | 'ingest_date' | 'ingest_codes' | 'rebuild_price_factors'
  | 'recompute' | 'verify' | 'checkup' | 'fix'
  | 'enrich_basic' | 'audit_cleanup'

// ── 数据结构体检报告（checkup 任务 result.checkup）──
export interface CheckupCheck { name: string; ok: boolean; detail: string }
export interface CheckupGroup { group: string; checks: CheckupCheck[] }
export interface CheckupReport {
  passed: number
  total: number
  all_ok: boolean
  fails: string[]
  groups: CheckupGroup[]
}
export type TaskStatus = 'pending' | 'running' | 'done' | 'failed' | 'interrupted'
export type TriggerSource = 'manual' | 'scheduled'
export interface AsyncTask {
  id: string
  task_type: TaskType
  status: TaskStatus
  progress: number
  message: string
  result?: Record<string, any> | null
  params?: Record<string, any> | null
  trigger_source?: TriggerSource | null
  job_id?: string | null
  job_name?: string | null
  capability?: {
    can_cancel?: boolean
    can_resume?: boolean
    cancel_mode?: 'checkpoint' | 'none' | string
    resume_granularity?: string | null
    current_phase?: string | null
    current_item?: string | number | null
    cancel_message?: string | null
    checkpoint?: Record<string, any>
  }
  created_at: string
  updated_at: string
}
export interface TaskLogLine { seq: number; ts: string; level: string; message: string }

export function createTask(task_type: TaskType, params?: Record<string, unknown>): Promise<{ task_id: string }> {
  return http.post('/data/tasks', { task_type, params: params || {} })
}
export function getTask(id: string): Promise<AsyncTask> {
  return http.get(`/data/tasks/${id}`)
}
export function getTaskLogs(id: string, afterSeq = 0): Promise<{ logs: TaskLogLine[] }> {
  return http.get(`/data/tasks/${id}/logs`, { params: { after_seq: afterSeq } })
}
export function resumeTask(id: string): Promise<{ task_id: string }> {
  return http.post(`/data/tasks/${id}/resume`)
}
export function cancelTask(id: string): Promise<{ task_id: string; cancelling: boolean }> {
  return http.post(`/data/tasks/${id}/cancel`)
}
export interface TaskListParams {
  page?: number; size?: number; status?: string; task_type?: string
  sort?: 'time' | 'type' | 'status'; order?: 'asc' | 'desc'; limit?: number
}
export function listTasks(params: TaskListParams = {}): Promise<{ tasks: AsyncTask[]; total?: number }> {
  return http.get('/data/tasks', { params })
}

// ── 采集日志（服务端分页/排序/筛选，M2.9.5）──
export interface UpdateLogPage {
  list: UpdateLog[]; total: number; page: number; size: number; tables: string[]
}
export function getUpdateLogs(params: {
  page?: number; size?: number; status?: string; table_name?: string
  sort?: 'time' | 'table' | 'status'; order?: 'asc' | 'desc'
} = {}): Promise<UpdateLogPage> {
  return http.get('/data/update-logs', { params })
}

// ── 中文化映射（FR-DM-6，UI 用）──
export const TASK_LABEL: Record<TaskType, string> = {
  update: '增量更新', backfill: '历史补数', ingest_date: '指定日期采集',
  ingest_codes: '指定股票采集', rebuild_price_factors: '重算价格因子',
  recompute: '评分维护', verify: '数据质检',
  checkup: '结构体检', fix: '问题修复', enrich_basic: '退市标记刷新',
  audit_cleanup: '审计日志清理',
}
export const STATUS_LABEL: Record<TaskStatus, string> = {
  pending: '排队中', running: '运行中', done: '已完成', failed: '失败', interrupted: '已中断',
}
// 当前在用的问题类型（下拉筛选用此顺序；missing_or_suspended 已废弃，不再产出/不再列出）。
export const ISSUE_TYPES_ACTIVE = [
  'null_close', 'ohl_repaired', 'mv_missing', 'mv_gap', 'abnormal_change', 'adj_jump', 'data_gap', 'stale',
] as const
export const ISSUE_TYPE_LABEL: Record<string, string> = {
  null_close: '收盘价非法(丢弃)', ohl_repaired: '开高低修补', mv_missing: '市值缺失',
  mv_gap: '市值缺口(近端)', abnormal_change: '异常涨跌幅', adj_jump: '复权跳变',
  data_gap: '行情缺口(疑似漏采)', stale: '数据滞后',
}
// 各问题类型归属的质量层（M2.9 DM-D15 / M2.9.2 DM-D20），用于质量页/概览按层归类。
export const ISSUE_LAYER: Record<string, string> = {
  null_close: 'L1', ohl_repaired: 'L1', mv_missing: 'L2', mv_gap: 'L2',
  abnormal_change: 'L3', adj_jump: 'L3', data_gap: 'L4', stale: 'L4',
}
// 各问题类型的恢复动作文案（DM-D22）：按类型分派，不再统一“重拉/重算”。
export const RECOVER_ACTION_LABEL: Record<string, string> = {
  null_close: '重采该日', ohl_repaired: '重采该日', mv_missing: '补市值', mv_gap: '补市值缺口',
  abnormal_change: '重采该日', adj_jump: '重采整段重算复权',
  data_gap: '重采缺口', stale: '增量补尾',
}
export const LAYER_LABEL: Record<string, string> = {
  L1: 'L1 入库闸门', L2: 'L2 字段契约', L3: 'L3 正确性', L4: 'L4 覆盖鲜活',
}
// 四层质量模型的权威说明（单一出处）：质量页 HelpTip / 概览逐股列等处统一引用此处，
// 以后调整口径或新增层/指标只改这里，不再各页各写一份（避免漏改）。
export const LAYER_DESC: Record<string, string> = {
  L1: 'L1 入库闸门：收盘价合法、开高低正常',
  L2: 'L2 字段契约：市值字段（总市值 / 流通市值）完整',
  L3: 'L3 正确性：无复权跳变 / 异常涨跌',
  L4: 'L4 覆盖鲜活：无缺口且更新到最新交易日',
}
export const SEVERITY_LABEL: Record<string, string> = { high: '高', mid: '中', low: '低' }
export const ISSUE_STATUS_LABEL: Record<string, string> = {
  open: '未处理', fixing: '修复中', resolved: '已解决', ignored: '已忽略',
}
export const SOURCE_LABEL: Record<string, string> = { akshare: 'AKShare', baostock: 'BaoStock' }
