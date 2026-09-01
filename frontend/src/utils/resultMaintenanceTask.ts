import type { TaskType } from '@/api/data'

export type ResultMaintenanceTaskType =
  | 'stock_board_correlation'
  | 'limit_ladder_invalidate'
  | 'recompute'
export type ResultTargetMode = 'latest' | 'fixed' | 'all'
export type ResultStockScope = 'all' | 'selected'

export interface ResultMaintenanceTaskForm {
  target_mode: ResultTargetMode
  trade_date: string
  stock_scope: ResultStockScope
  codes: string[]
}

let pendingScheduleIntent: ResultMaintenanceTaskType | null = null

/** 在同一次前端会话中传递一次性的“新建结果调度”意图，消费后立即清空。 */
export function queueResultMaintenanceScheduleIntent(type: ResultMaintenanceTaskType) {
  pendingScheduleIntent = type
}

export function consumeResultMaintenanceScheduleIntent(): ResultMaintenanceTaskType | null {
  const type = pendingScheduleIntent
  pendingScheduleIntent = null
  return type
}

export function isResultMaintenanceTask(type: TaskType | string): type is ResultMaintenanceTaskType {
  return ['stock_board_correlation', 'limit_ladder_invalidate', 'recompute'].includes(type)
}

export function createResultMaintenanceTaskForm(
  patch: Partial<ResultMaintenanceTaskForm> = {},
): ResultMaintenanceTaskForm {
  return {
    target_mode: 'latest',
    trade_date: '',
    stock_scope: 'all',
    codes: [],
    ...patch,
  }
}

export function buildResultMaintenanceTaskParams(
  taskType: ResultMaintenanceTaskType,
  form: ResultMaintenanceTaskForm,
): { params?: Record<string, unknown>; error?: string } {
  if (form.target_mode === 'fixed' && !form.trade_date) {
    return { error: '固定交易日不能为空' }
  }
  if (form.target_mode === 'all' && taskType !== 'recompute') {
    return { error: '该结果维护任务不支持全部快照范围' }
  }
  if (taskType === 'stock_board_correlation') {
    if (form.stock_scope === 'selected' && !form.codes.length) {
      return { error: '指定股票范围时请至少选择一只股票' }
    }
    const params: Record<string, unknown> = { force: true }
    if (form.target_mode === 'fixed') params.trade_date = form.trade_date
    if (form.stock_scope === 'selected') params.codes = [...form.codes]
    return { params }
  }
  const params: Record<string, unknown> = { target_mode: form.target_mode }
  if (form.target_mode === 'fixed') params.trade_date = form.trade_date
  return { params }
}

export function resultMaintenanceTaskFormFromParams(
  taskType: ResultMaintenanceTaskType,
  params: Record<string, unknown> | null | undefined,
): ResultMaintenanceTaskForm {
  const codes = Array.isArray(params?.codes) ? params.codes.map(String) : []
  const targetMode = params?.target_mode === 'all'
    ? 'all'
    : (typeof params?.trade_date === 'string' && params.trade_date ? 'fixed' : 'latest')
  return createResultMaintenanceTaskForm({
    target_mode: taskType !== 'recompute' && targetMode === 'all' ? 'latest' : targetMode,
    trade_date: typeof params?.trade_date === 'string' ? params.trade_date : '',
    stock_scope: codes.length ? 'selected' : 'all',
    codes,
  })
}

export const RESULT_MAINTENANCE_DESCRIPTION: Record<ResultMaintenanceTaskType, string> = {
  stock_board_correlation: '按当前版本强制计算并原子发布，失败时保留最后成功结果。',
  limit_ladder_invalidate: '仅标记快照失效；访问对应日期时再按天梯门禁重算。',
  recompute: '仅标记评分快照失效；下次读取对应榜单时按需重算。',
}
