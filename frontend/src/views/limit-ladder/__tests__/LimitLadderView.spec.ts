// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, reactive, ref, type Component } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import type { LimitLadderResult } from '@/api/limitLadder'
import { useAuthStore } from '@/stores/auth'

vi.mock('@/api/limitLadder', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/limitLadder')>()
  return {
    ...actual,
    exportLimitLadder: vi.fn(),
    getLimitLadder: vi.fn(),
    listLimitLadderTradeDates: vi.fn(),
    recomputeLimitLadder: vi.fn(),
  }
})

vi.mock('@/composables/usePageSettings', () => ({
  usePageSettings: (_pageKey: string, defaults: Record<string, unknown>) => ({
    settings: reactive(structuredClone(defaults)),
    isDirty: ref(false),
    reset: vi.fn(),
    whenHydrated: () => Promise.resolve(),
    remoteError: ref(false),
    saving: ref(false),
    saveError: ref(false),
    save: vi.fn(),
  }),
}))

vi.mock('@/composables/useRemoteLayoutConfig', () => ({
  useRemoteLayoutConfig: () => ({
    effective: {},
    knobs: [],
    setKnob: vi.fn(),
    valueOf: vi.fn(),
    sourceOf: vi.fn(),
    layerValuesOf: vi.fn(),
    isDirty: ref(false),
    resetAll: vi.fn(),
    componentValueOf: vi.fn(),
    setComponentKnob: vi.fn(),
    componentSourceOf: vi.fn(),
    componentLayerValuesOf: vi.fn(),
    componentAllowedLayers: vi.fn(),
  }),
}))

vi.mock('@/composables/useKlinePrefs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/composables/useKlinePrefs')>()
  return {
    ...actual,
    useKlinePrefs: () => ({ validDefault: ref(120) }),
  }
})

import * as limitLadderApi from '@/api/limitLadder'
import LimitLadderView from '@/views/LimitLadderView.vue'

const LimitLadderStub = defineComponent({
  name: 'LimitLadder',
  props: {
    result: { type: Object, default: null },
    error: { type: String, default: '' },
    forbidden: { type: Boolean, default: false },
  },
  setup(props) {
    return () => h('section', {
      'data-testid': 'limit-ladder-state-probe',
      'data-business-code': (props.result as LimitLadderResult | null)?.business_code ?? '',
      'data-snapshot-status': (props.result as LimitLadderResult | null)?.snapshot_status ?? '',
      'data-error': props.error,
      'data-forbidden': String(props.forbidden),
    })
  },
})

const stubs = {
  LayoutHost: {
    template: '<main><slot name="action"/><slot name="main"/><slot name="overlays"/></main>',
  },
  MarketMasterDetailWorkspace: {
    template: '<section><slot name="list"/><slot name="analysis"/></section>',
  },
  LimitLadder: LimitLadderStub,
  StockAnalysisPanel: true,
  PageDrawer: true,
  PageSettingsDrawer: true,
  PageSettingsTrigger: true,
}
const mountedWrappers: VueWrapper[] = []

function pendingResult(commandId: string, taskId: string): LimitLadderResult {
  return {
    trade_date: '2026-08-28',
    business_code: 'SNAPSHOT_PENDING',
    snapshot_status: 'calculating',
    stored_snapshot_status: 'calculating',
    has_snapshot: false,
    filters: {},
    snapshot: null,
    requested_window_start_date: null,
    requested_window_trade_days: 31,
    dynamic_window_status: 'pending',
    task: {
      command_id: commandId,
      task_id: taskId,
      status: 'running',
      source: 'auto_first_load',
    },
    summary: { stock_count: 0, highest_board: null, first_board_count: 0 },
    hotspots: { industry: [], concept: [] },
    layers: [],
  }
}

function readyResult(): LimitLadderResult {
  return {
    ...pendingResult('command-ready', 'task-ready'),
    business_code: 'READY',
    snapshot_status: 'valid',
    stored_snapshot_status: 'valid',
    has_snapshot: true,
    snapshot: {
      snapshot_id: 'snapshot-ready',
      trade_date: '2026-08-28',
      computed_at: '2026-08-28T18:00:00',
      stock_count: 0,
      has_approx_st: false,
      coverage: {},
    },
    dynamic_window_status: 'ready',
    task: null,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/limit-ladder', component: LimitLadderView },
      { path: '/stocks/:code', component: { template: '<div />' } },
    ],
  })
  await router.push('/limit-ladder?date=2026-08-28')
  await router.isReady()

  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = 'system'
  auth.permissions = ['limit-ladder:view', 'limit-ladder:recompute']
  auth.menusStatus = 'ready'

  const wrapper = shallowMount(LimitLadderView as Component, {
    global: {
      plugins: [pinia, router, ElementPlus],
      directives: { permission: {} },
      stubs,
    },
  })
  await flushPromises()
  mountedWrappers.push(wrapper)
  return wrapper
}

function stateProbe(wrapper: Awaited<ReturnType<typeof mountView>>) {
  return wrapper.get('[data-testid="limit-ladder-state-probe"]')
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  localStorage.clear()
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  })
  vi.mocked(limitLadderApi.listLimitLadderTradeDates).mockResolvedValue({
    dates: ['2026-08-28'],
    latest_candidate_date: '2026-08-28',
    latest_complete_date: '2026-08-28',
    latest_candidate_coverage: {},
    latest_candidate_ready: true,
  })
})

afterEach(() => {
  mountedWrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('LimitLadderView polling deadline', () => {
  it('403 转为无权限状态，不退化成普通可重试错误', async () => {
    vi.mocked(limitLadderApi.getLimitLadder).mockRejectedValue({
      response: { status: 403 },
      uiMessage: '无权查看连板天梯',
    })
    const wrapper = await mountView()

    expect(stateProbe(wrapper).attributes('data-forbidden')).toBe('true')
    expect(stateProbe(wrapper).attributes('data-error')).toBe('')
  })

  it('120 秒触发页面超时并停止后续请求', async () => {
    vi.mocked(limitLadderApi.getLimitLadder)
      .mockResolvedValue(pendingResult('command-1', 'task-1'))
    const wrapper = await mountView()

    await vi.advanceTimersByTimeAsync(120_000)
    await flushPromises()
    expect(stateProbe(wrapper).attributes('data-error')).toContain('计算任务等待超时')

    const callsAtTimeout = vi.mocked(limitLadderApi.getLimitLadder).mock.calls.length
    await vi.advanceTimersByTimeAsync(60_000)
    await flushPromises()
    expect(limitLadderApi.getLimitLadder).toHaveBeenCalledTimes(callsAtTimeout)
  })

  it('deadline 后到达的慢响应不能覆盖超时状态', async () => {
    const slowRequest = deferred<LimitLadderResult>()
    vi.mocked(limitLadderApi.getLimitLadder)
      .mockResolvedValueOnce(pendingResult('command-1', 'task-1'))
      .mockImplementationOnce(() => slowRequest.promise)
    const wrapper = await mountView()

    await vi.advanceTimersByTimeAsync(1_500)
    expect(limitLadderApi.getLimitLadder).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(118_500)
    expect(stateProbe(wrapper).attributes('data-error')).toContain('计算任务等待超时')

    slowRequest.resolve(readyResult())
    await flushPromises()
    expect(stateProbe(wrapper).attributes('data-business-code')).toBe('SNAPSHOT_PENDING')
    expect(stateProbe(wrapper).attributes('data-snapshot-status')).toBe('calculating')
    expect(stateProbe(wrapper).attributes('data-error')).toContain('计算任务等待超时')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(limitLadderApi.getLimitLadder).toHaveBeenCalledTimes(2)
  })

  it('同 command 的 task_id 变化不会重置页面 deadline', async () => {
    const slowRequest = deferred<LimitLadderResult>()
    vi.mocked(limitLadderApi.getLimitLadder)
      .mockResolvedValueOnce(pendingResult('command-1', 'task-1'))
      .mockResolvedValueOnce(pendingResult('command-1', 'task-2'))
      .mockImplementationOnce(() => slowRequest.promise)
    const wrapper = await mountView()

    await vi.advanceTimersByTimeAsync(119_999)
    expect(limitLadderApi.getLimitLadder).toHaveBeenCalledTimes(3)
    expect(stateProbe(wrapper).attributes('data-error')).toBe('')
    await vi.advanceTimersByTimeAsync(1)
    expect(stateProbe(wrapper).attributes('data-error')).toContain('计算任务等待超时')
  })

  it('新 command 会开启新的 120 秒轮询周期', async () => {
    const slowRequest = deferred<LimitLadderResult>()
    vi.mocked(limitLadderApi.getLimitLadder)
      .mockResolvedValueOnce(pendingResult('command-1', 'task-1'))
      .mockResolvedValueOnce(pendingResult('command-2', 'task-2'))
      .mockImplementationOnce(() => slowRequest.promise)
    const wrapper = await mountView()

    await vi.advanceTimersByTimeAsync(120_000)
    expect(limitLadderApi.getLimitLadder).toHaveBeenCalledTimes(3)
    expect(stateProbe(wrapper).attributes('data-error')).toBe('')
    await vi.advanceTimersByTimeAsync(1_500)
    expect(stateProbe(wrapper).attributes('data-error')).toContain('计算任务等待超时')
  })
})
