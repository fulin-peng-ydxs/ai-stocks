export type UnsavedLeaveReason =
  | 'route'
  | 'tab-close'
  | 'tab-evict'
  | 'logout'
  | 'context-change'

export interface UnsavedChangesHandler {
  isDirty: () => boolean
  requestLeave: (reason: UnsavedLeaveReason) => boolean | Promise<boolean>
}

const handlers = new Map<string, UnsavedChangesHandler>()
const routeLeavePermits = new Set<string>()

/**
 * 按工作标签 key 登记未保存现场。返回注销函数，页面卸载或业务上下文销毁时必须调用。
 */
export function registerUnsavedHandler(
  tabKey: string,
  handler: UnsavedChangesHandler,
): () => void {
  handlers.set(tabKey, handler)
  return () => {
    if (handlers.get(tabKey) === handler) handlers.delete(tabKey)
    routeLeavePermits.delete(tabKey)
  }
}

export function hasUnsavedChanges(tabKey?: string): boolean {
  if (tabKey) return handlers.get(tabKey)?.isDirty() ?? false
  return [...handlers.values()].some((handler) => handler.isDirty())
}

/** 只确认指定现场；干净或未登记的标签直接放行。 */
export async function confirmLeave(
  tabKey: string,
  reason: UnsavedLeaveReason,
): Promise<boolean> {
  const handler = handlers.get(tabKey)
  if (!handler?.isDirty()) return true
  return Boolean(await handler.requestLeave(reason))
}

/** 注销等全局动作逐个确认；任一现场拒绝即停止，调用方不得先清标签或缓存。 */
export async function confirmAll(reason: UnsavedLeaveReason): Promise<boolean> {
  for (const [tabKey] of handlers) {
    if (!(await confirmLeave(tabKey, reason))) return false
  }
  return true
}

/** 标签关闭已完成业务确认后，允许紧随其后的路由切换跳过重复询问。 */
export function permitNextRouteLeave(tabKey: string): void {
  routeLeavePermits.add(tabKey)
}

export function consumeRouteLeavePermit(tabKey: string): boolean {
  if (!routeLeavePermits.has(tabKey)) return false
  routeLeavePermits.delete(tabKey)
  return true
}

/** 浏览器刷新/关闭只能使用原生确认；该入口由应用壳安装一次。 */
export function installUnsavedChangesBeforeUnload(): () => void {
  const listener = (event: BeforeUnloadEvent) => {
    if (!hasUnsavedChanges()) return
    event.preventDefault()
    event.returnValue = ''
  }
  window.addEventListener('beforeunload', listener)
  return () => window.removeEventListener('beforeunload', listener)
}

/** 仅供测试和身份清理，正常页面通过 register 返回的注销函数释放。 */
export function resetUnsavedChangesGuard(): void {
  handlers.clear()
  routeLeavePermits.clear()
}
