// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import TradeDisciplineView from '@/views/TradeDisciplineView.vue'
import { useAuthStore } from '@/stores/auth'
import { permission } from '@/directives/permission'

const listRules = vi.fn()
const listCheckins = vi.fn()
const ensureTradeDates = vi.fn(async () => undefined)
const tradeDateStatus = { value: 'ready' }

vi.mock('@/api/tradeDiscipline', () => ({
  listTradeDisciplineRules: (...args: unknown[]) => listRules(...args),
  listTradeDisciplineCheckins: (...args: unknown[]) => listCheckins(...args),
}))
vi.mock('@/composables/useTradeDates', async () => {
  const { ref } = await import('vue')
  return {
    useTradeDates: () => ({
      dataMax: ref('2026-08-22'),
      status: tradeDateStatus,
      ensureLoaded: ensureTradeDates,
    }),
  }
})
vi.mock('@/composables/useRemoteLayoutConfig', async () => {
  const { ref } = await import('vue')
  return {
    useRemoteLayoutConfig: (layout: unknown) => ({
      effective: ref(layout), knobs: [], setKnob: vi.fn(), valueOf: vi.fn(), sourceOf: vi.fn(),
      isDirty: ref(false), resetAll: vi.fn(),
      componentValueOf: (_slot: string, field: string) => field === 'pageSize' ? 20 : false,
      setComponentKnob: vi.fn(), componentSourceOf: vi.fn(), layerValuesOf: vi.fn(),
      componentLayerValuesOf: vi.fn(),
    }),
  }
})
vi.mock('@/composables/usePageSettings', async () => {
  const { ref } = await import('vue')
  return { usePageSettings: () => ({ reset: vi.fn(), isDirty: ref(false) }) }
})

async function mountPage(permissions: string[]) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = 'normal'
  auth.permissions = permissions
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/trade-discipline', component: TradeDisciplineView }],
  })
  await router.push('/trade-discipline')
  await router.isReady()
  const wrapper = mount(TradeDisciplineView, {
    global: { plugins: [pinia, router, ElementPlus], directives: { permission } },
  })
  await flushPromises()
  return wrapper
}

describe('交易纪律 T5 工作台壳', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    tradeDateStatus.value = 'ready'
    listRules.mockResolvedValue([])
    listCheckins.mockResolvedValue({ total: 0, page: 1, page_size: 20, list: [] })
  })

  it('加载交易日和规则，并提供三段业务页签与设置入口', async () => {
    const wrapper = await mountPage([
      'trade-discipline:view',
      'trade-discipline:rule-manage',
      'trade-discipline:checkin-view',
    ])
    expect(ensureTradeDates).toHaveBeenCalled()
    expect(listRules).toHaveBeenCalledWith('2026-08-22')
    expect(wrapper.get('[data-testid="trade-discipline-tabs"]')).toBeTruthy()
    expect(wrapper.text()).toContain('今日打卡')
    expect(wrapper.text()).toContain('规则管理')
    expect(wrapper.text()).toContain('历史记录')
    expect(wrapper.text()).toContain('创建第一套规则')
  })

  it('缺少履约查看权限时显示无权限态而非空态', async () => {
    const wrapper = await mountPage(['trade-discipline:view'])
    expect(wrapper.text()).toContain('无权限查看履约打卡')
    expect(wrapper.text()).not.toContain('创建第一套规则')
  })

  it('交易日加载失败时整页 fail-closed 并提供重试', async () => {
    tradeDateStatus.value = 'error'
    const wrapper = await mountPage(['trade-discipline:view'])
    expect(wrapper.text()).toContain('交易纪律加载失败')
    expect(wrapper.text()).toContain('重试')
    expect(listRules).not.toHaveBeenCalled()
  })
})
