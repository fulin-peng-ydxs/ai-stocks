import { describe, expect, it } from 'vitest'
import {
  activateCompareCode,
  emptyCompareQueue,
  removeCompareCode,
  toggleComparePin,
  type CompareQueueState,
} from '@/utils/compareQueue'

const LIMIT = 6

function stateOf(queue: string[], pinned: string[], active: string): CompareQueueState {
  return { queueCodes: queue, pinnedCodes: pinned, activeCode: active }
}

describe('compareQueue 稳定顺序', () => {
  it('激活队列中已有项只移动高亮,顺序不变', () => {
    // 三项皆固定,激活末位项:不得插到队首。
    const state = stateOf(['银行', 'PCB', '存储'], ['银行', 'PCB', '存储'], '银行')
    const next = activateCompareCode(state, '存储', LIMIT)
    expect(next.queueCodes).toEqual(['银行', 'PCB', '存储'])
    expect(next.activeCode).toBe('存储')
  })

  it('激活固定项时退出临时槽,但保留其余项相对顺序', () => {
    // 银行为未固定临时槽,激活已固定的存储:银行退出,PCB/存储 顺序不变且存储不前置。
    const state = stateOf(['银行', 'PCB', '存储'], ['PCB', '存储'], '银行')
    const next = activateCompareCode(state, '存储', LIMIT)
    expect(next.queueCodes).toEqual(['PCB', '存储'])
    expect(next.activeCode).toBe('存储')
  })

  it('选中未入队且当前为临时槽时原位替换,其余顺序不变', () => {
    const state = stateOf(['银行', 'PCB'], ['PCB'], '银行')
    const next = activateCompareCode(state, '券商', LIMIT)
    expect(next.queueCodes).toEqual(['券商', 'PCB'])
    expect(next.activeCode).toBe('券商')
  })

  it('选中未入队且当前激活已固定时插到队首', () => {
    const state = stateOf(['银行', 'PCB'], ['银行', 'PCB'], '银行')
    const next = activateCompareCode(state, '券商', LIMIT)
    expect(next.queueCodes).toEqual(['券商', '银行', 'PCB'])
    expect(next.activeCode).toBe('券商')
  })

  it('空码与空队列安全返回', () => {
    const empty = emptyCompareQueue()
    expect(activateCompareCode(empty, '', LIMIT)).toEqual(empty)
    const next = activateCompareCode(empty, '银行', LIMIT)
    expect(next.queueCodes).toEqual(['银行'])
    expect(next.activeCode).toBe('银行')
  })

  it('固定当前激活的临时槽:位置不变,转为固定', () => {
    const state = stateOf(['银行', 'PCB'], ['PCB'], '银行')
    const result = toggleComparePin(state, '银行', LIMIT)
    expect(result.pinned).toBe(true)
    expect(result.state.queueCodes).toEqual(['银行', 'PCB'])
    expect(result.state.pinnedCodes).toEqual(['PCB', '银行'])
  })

  it('固定未入队新项追加到队尾;满员拒绝并标记', () => {
    const state = stateOf(['银行', 'PCB'], ['PCB'], '银行')
    const appended = toggleComparePin(state, '存储', 3)
    expect(appended.state.queueCodes).toEqual(['银行', 'PCB', '存储'])
    expect(appended.limitReached).toBe(false)

    const full = toggleComparePin(appended.state, '券商', 3)
    expect(full.limitReached).toBe(true)
    expect(full.state.queueCodes).toEqual(['银行', 'PCB', '存储'])
  })

  it('取消固定:非激活项退出队列,激活项降级为临时槽保留', () => {
    const state = stateOf(['银行', 'PCB', '存储'], ['PCB', '存储'], '银行')
    const unpinInactive = toggleComparePin(state, 'PCB', LIMIT)
    expect(unpinInactive.state.queueCodes).toEqual(['银行', '存储'])
    expect(unpinInactive.state.pinnedCodes).toEqual(['存储'])

    const unpinActive = toggleComparePin(stateOf(['银行', '存储'], ['银行', '存储'], '银行'), '银行', LIMIT)
    expect(unpinActive.state.queueCodes).toEqual(['银行', '存储'])
    expect(unpinActive.state.pinnedCodes).toEqual(['存储'])
    expect(unpinActive.state.activeCode).toBe('银行')
  })

  it('移除当前激活项回退到队列首项;队列空时用回退码重建临时槽', () => {
    const state = stateOf(['银行', 'PCB', '存储'], ['PCB', '存储'], '银行')
    const next = removeCompareCode(state, '银行', '默认')
    expect(next.activeCode).toBe('PCB')
    expect(next.queueCodes).toEqual(['PCB', '存储'])

    const emptied = removeCompareCode(stateOf(['银行'], [], '银行'), '银行', '默认')
    expect(emptied.activeCode).toBe('默认')
    expect(emptied.queueCodes).toEqual(['默认'])
  })

  it('移除非激活项不影响激活与顺序', () => {
    const state = stateOf(['银行', 'PCB', '存储'], ['PCB', '存储'], '银行')
    const next = removeCompareCode(state, '存储')
    expect(next.activeCode).toBe('银行')
    expect(next.queueCodes).toEqual(['银行', 'PCB'])
  })
})
