// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  confirmAll,
  confirmLeave,
  consumeRouteLeavePermit,
  hasUnsavedChanges,
  installUnsavedChangesBeforeUnload,
  permitNextRouteLeave,
  registerUnsavedHandler,
  resetUnsavedChangesGuard,
} from '@/composables/useUnsavedChangesGuard'

describe('应用级未保存变更协议', () => {
  beforeEach(resetUnsavedChangesGuard)

  it('按标签确认并在注销时遇到拒绝立即停止', async () => {
    const first = vi.fn(async () => true)
    const second = vi.fn(async () => false)
    registerUnsavedHandler('/one', { isDirty: () => true, requestLeave: first })
    registerUnsavedHandler('/two', { isDirty: () => true, requestLeave: second })

    expect(hasUnsavedChanges()).toBe(true)
    expect(await confirmLeave('/one', 'tab-close')).toBe(true)
    expect(first).toHaveBeenCalledWith('tab-close')
    expect(await confirmAll('logout')).toBe(false)
    expect(second).toHaveBeenCalledWith('logout')
  })

  it('注销函数只释放自己的当前登记，路由 permit 只消费一次', () => {
    const old = { isDirty: () => true, requestLeave: () => true }
    const current = { isDirty: () => true, requestLeave: () => true }
    const unregisterOld = registerUnsavedHandler('/one', old)
    registerUnsavedHandler('/one', current)
    unregisterOld()
    expect(hasUnsavedChanges('/one')).toBe(true)

    permitNextRouteLeave('/one')
    expect(consumeRouteLeavePermit('/one')).toBe(true)
    expect(consumeRouteLeavePermit('/one')).toBe(false)
  })

  it('beforeunload 仅在存在脏现场时触发浏览器原生确认', () => {
    const remove = installUnsavedChangesBeforeUnload()
    const cleanEvent = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(cleanEvent)
    expect(cleanEvent.defaultPrevented).toBe(false)

    registerUnsavedHandler('/one', { isDirty: () => true, requestLeave: () => true })
    const dirtyEvent = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(dirtyEvent)
    expect(dirtyEvent.defaultPrevented).toBe(true)
    remove()
  })
})
