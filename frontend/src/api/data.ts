// 数据管理 API（对应 backend/api/data_admin.py + data_tasks.py + stocks.py 的 /data/*）
import http from './client'

// ── 概览（FR-DM-1）──
export interface Overview {
  latest_trade_date: string | null
  codes: { active: number; delisted: number }
  bar_rows: number
  quality: { open: number; by_severity: Record<string, number> }
  gaps: { stocks_with_gap: number; gap_days_total: number; latest_trade_date: string | null }
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

export interface StockQualityRow {
  code: string
  name: string
  latest_date: string | null
  is_fresh: boolean
  total_mv_ok: boolean
  gap_days: number
  open_issues: number
}
export interface StockQuality {
  total: number
  page: number
  size: number
  latest_trade_date: string | null
  list: StockQualityRow[]
}
export function getStockQuality(params?: { codes?: string; page?: number; size?: number }): Promise<StockQuality> {
  return http.get('/data/stock-quality', { params })
}

// ── 数据状态 / 采集日志（FR-DM-6）──
export interface UpdateLog {
  table_name: string
  source: string
  status: string
  row_count: number
  updated_at: string
}
export interface DataStatus {
  latest_trade_date: string
  distinct_codes: number
  bar_rows: number
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
}): Promise<DataQuality> {
  return http.get('/data/quality', { params })
}
export function fixQualityIssue(issueId: number): Promise<{ task_id: string }> {
  return http.post(`/data/quality/${issueId}/fix`)
}
export function fixQualityBatch(issueIds: number[]): Promise<{ started: string[]; skipped: number[] }> {
  return http.post('/data/quality/fix-batch', { issue_ids: issueIds })
}

// ── 调度（FR-DM-7）──
export interface SchedulerStatus {
  enabled: boolean
  cron_hour: number
  cron_minute: number
  next_run_time: string | null
  running: boolean
  last_result: Record<string, any> | null
}
export function getScheduler(): Promise<SchedulerStatus> {
  return http.get('/data/scheduler')
}
export function setScheduler(body: { enabled: boolean; cron_hour: number; cron_minute: number }): Promise<SchedulerStatus> {
  return http.post('/data/scheduler', body)
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
  type: 'int' | 'number' | 'bool' | 'enum'
  value: any
  default: any
  overridden: boolean
  options?: string[]
  min?: number
  max?: number
}
export interface SettingGroup { key: string; label: string; fields: SettingField[] }
export function getSettingsView(): Promise<{ groups: SettingGroup[] }> {
  return http.get('/data/settings')
}
export function saveSettings(updates: Record<string, any>): Promise<{ saved: number }> {
  return http.post('/data/settings', { updates })
}

// ── 异步数据任务（M2.6 + M2.8-B）──
export type TaskType =
  | 'update' | 'backfill' | 'ingest_date' | 'ingest_codes' | 'recompute' | 'verify' | 'fix'
export type TaskStatus = 'pending' | 'running' | 'done' | 'failed' | 'interrupted'
export interface AsyncTask {
  id: string
  task_type: TaskType
  status: TaskStatus
  progress: number
  message: string
  result?: Record<string, any> | null
  params?: Record<string, any> | null
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
export function listTasks(limit = 20, status?: string): Promise<{ tasks: AsyncTask[] }> {
  return http.get('/data/tasks', { params: { limit, status } })
}

// ── 中文化映射（FR-DM-6，UI 用）──
export const TASK_LABEL: Record<TaskType, string> = {
  update: '增量更新', backfill: '历史补数', ingest_date: '指定日期采集',
  ingest_codes: '指定股票采集', recompute: '重算评分', verify: '数据体检', fix: '问题修复',
}
export const STATUS_LABEL: Record<TaskStatus, string> = {
  pending: '排队中', running: '运行中', done: '已完成', failed: '失败', interrupted: '已中断',
}
export const ISSUE_TYPE_LABEL: Record<string, string> = {
  ohl_repaired: '开高低修补', abnormal_change: '异常涨跌幅',
  missing_or_suspended: '缺失/停牌', adj_jump: '复权跳变',
}
export const SEVERITY_LABEL: Record<string, string> = { high: '高', mid: '中', low: '低' }
export const ISSUE_STATUS_LABEL: Record<string, string> = {
  open: '未处理', fixing: '修复中', resolved: '已解决', ignored: '已忽略',
}
export const SOURCE_LABEL: Record<string, string> = { akshare: 'AKShare', baostock: 'BaoStock' }
