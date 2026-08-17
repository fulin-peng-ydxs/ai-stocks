/**
 * 走势对比队列的稳定顺序状态机（板块/个股/榜单共用）。
 *
 * 设计目标:队列先后 = 进入先后的插入序;激活(点击 chip 或切换主观察)只移动高亮,绝不重排。
 * - `queueCodes`:当前可见队列(激活项 ∪ 固定项),保持插入序;未固定的激活项是“临时槽”,至多一个。
 * - `pinnedCodes`:显式勾选固定的对比项,跨翻页/跨激活保留,保持插入序。
 * - `activeCode`:当前观察(高亮)项;非空时必在 `queueCodes` 中。
 *
 * 模块为纯函数、与 Vue 解耦,消费方(组合式函数或视图)自行用 ref 包裹并触发副作用。
 */

export interface CompareQueueState {
  readonly queueCodes: readonly string[]
  readonly pinnedCodes: readonly string[]
  readonly activeCode: string
}

export interface CompareQueueToggleResult {
  readonly state: CompareQueueState
  /** 本次操作后该项是否处于固定态。 */
  readonly pinned: boolean
  /** 队列已满导致本次固定被拒绝。 */
  readonly limitReached: boolean
}

export function emptyCompareQueue(): CompareQueueState {
  return { queueCodes: [], pinnedCodes: [], activeCode: '' }
}

function isPinned(state: CompareQueueState, code: string): boolean {
  return state.pinnedCodes.includes(code)
}

/**
 * 让 `code` 成为当前观察项。行点击(切主观察)与 chip 点击(激活)是同一操作。
 * - 已在队列:仅移动高亮;原激活项若为临时槽则随焦点离开而退出,其余项顺序不变。
 * - 不在队列:原激活为临时槽则原位替换(复用槽位);否则插到队首并按上限截断。
 * 全程不重排任何既有项。
 */
export function activateCompareCode(
  state: CompareQueueState,
  code: string,
  limit: number,
): CompareQueueState {
  if (!code) return state
  const { queueCodes, pinnedCodes, activeCode } = state
  if (queueCodes.includes(code)) {
    const dropOutgoing =
      Boolean(activeCode) && activeCode !== code && !isPinned(state, activeCode)
    const nextQueue = dropOutgoing ? queueCodes.filter((item) => item !== activeCode) : queueCodes
    return { queueCodes: nextQueue, pinnedCodes, activeCode: code }
  }
  if (activeCode && queueCodes.includes(activeCode) && !isPinned(state, activeCode)) {
    return {
      queueCodes: queueCodes.map((item) => (item === activeCode ? code : item)),
      pinnedCodes,
      activeCode: code,
    }
  }
  return { queueCodes: [code, ...queueCodes].slice(0, limit), pinnedCodes, activeCode: code }
}

/**
 * 切换 `code` 的固定态。
 * - 取消固定:非激活项退出队列;激活项降级为临时槽保留原位。
 * - 固定:当前激活的临时槽转为固定且位置不变;新项追加到队尾;队列已满则拒绝。
 */
export function toggleComparePin(
  state: CompareQueueState,
  code: string,
  limit: number,
): CompareQueueToggleResult {
  const { queueCodes, pinnedCodes, activeCode } = state
  if (isPinned(state, code)) {
    const nextPinned = pinnedCodes.filter((item) => item !== code)
    const nextQueue = code === activeCode ? queueCodes : queueCodes.filter((item) => item !== code)
    return {
      state: { queueCodes: nextQueue, pinnedCodes: nextPinned, activeCode },
      pinned: false,
      limitReached: false,
    }
  }
  if (queueCodes.includes(code)) {
    return {
      state: { queueCodes, pinnedCodes: [...pinnedCodes, code], activeCode },
      pinned: true,
      limitReached: false,
    }
  }
  if (queueCodes.length >= limit) {
    return { state, pinned: false, limitReached: true }
  }
  return {
    state: { queueCodes: [...queueCodes, code], pinnedCodes: [...pinnedCodes, code], activeCode },
    pinned: true,
    limitReached: false,
  }
}

/**
 * 从队列移除 `code`(chip 移除按钮)。若移除的是当前激活项,则回退到队列首项;
 * 队列已空时用 `fallbackCode`(通常是源列表首个可用项)重建临时槽。
 */
export function removeCompareCode(
  state: CompareQueueState,
  code: string,
  fallbackCode = '',
): CompareQueueState {
  let queueCodes = state.queueCodes.filter((item) => item !== code)
  const pinnedCodes = state.pinnedCodes.filter((item) => item !== code)
  let activeCode = state.activeCode
  if (code === activeCode) {
    activeCode = queueCodes[0] ?? fallbackCode ?? ''
    if (activeCode && !queueCodes.includes(activeCode)) queueCodes = [activeCode, ...queueCodes]
  }
  return { queueCodes, pinnedCodes, activeCode }
}
