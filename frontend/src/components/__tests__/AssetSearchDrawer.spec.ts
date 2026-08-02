// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { nextTick } from 'vue'
import AssetSearchDrawer from '@/components/asset-search/AssetSearchDrawer.vue'
import { useAuthStore } from '@/stores/auth'
import type {
  AssetBrowseParams,
  AssetBrowseResult,
  BacktestRunSummary,
  ProfileSummary,
} from '@/components/asset-search/types'

const presetItem: ProfileSummary = {
  id: 'preset_score',
  profile_ref: 'ref_preset_score',
  name: '趋势龙头·基础评分',
  version: 3,
  is_preset: true,
  visibility: 'public',
  source: 'preset',
  readonly: true,
  owner_label: null,
  updated_at: '2026-07-20 10:00:00',
}
const tenantItem: ProfileSummary = {
  id: 'tenant_a',
  profile_ref: 'ref_tenant_a',
  name: '本租户·北向增强评分',
  version: 2,
  is_preset: false,
  visibility: 'tenant',
  source: 'tenant',
  readonly: true,
  owner_label: '同租户用户',
  updated_at: '2026-07-22 09:30:00',
}

function makeBrowse(bySource: Record<string, ProfileSummary[]>) {
  return vi.fn(async (params: AssetBrowseParams): Promise<AssetBrowseResult> => ({
    items: bySource[params.source] ?? [],
    total: (bySource[params.source] ?? []).length,
    page: params.page,
    page_size: params.pageSize,
    source: params.source,
  }))
}

function mountDrawer(extra: Record<string, unknown> = {}, permissions: string[] = ['screen-profile:save']) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = 'normal'
  auth.permissions = permissions
  const browse = (extra.browse as ReturnType<typeof makeBrowse>) ?? makeBrowse({ preset: [presetItem], tenant: [tenantItem], public: [] })
  const wrapper = mount(AssetSearchDrawer, {
    props: {
      modelValue: true,
      assetLabel: '评分方案',
      browse,
      copyItem: async () => ({ id: 'new_id', profile_ref: 'ref_new', name: '趋势龙头·基础评分 副本', version: 1 }),
      copyPermission: 'screen-profile:save',
      ...extra,
    },
    attachTo: document.body,
    global: { plugins: [pinia, ElementPlus] },
  })
  return { wrapper, browse }
}

async function flush(times = 8) {
  for (let i = 0; i < times; i += 1) await nextTick()
}

describe('AssetSearchDrawer', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('打开时按默认来源段（方案类=系统内置）拉取并渲染行', async () => {
    const { wrapper, browse } = mountDrawer()
    await flush()
    expect(browse).toHaveBeenCalledWith({ source: 'preset', q: '', page: 1, pageSize: 20 })
    const text = document.body.textContent || ''
    expect(text).toContain('趋势龙头·基础评分')
    expect(text).toContain('系统内置')
    expect(text).toContain('加载查看')
    expect(text).toContain('复制为我的')
    wrapper.unmount()
  })

  it('切换来源分段触发重查', async () => {
    const { wrapper, browse } = mountDrawer()
    await flush()
    const tenantBtn = document.querySelector<HTMLElement>('[data-testid="asset-search-drawer-segment-tenant"]')
    expect(tenantBtn).not.toBeNull()
    tenantBtn!.click()
    await flush()
    expect(browse).toHaveBeenLastCalledWith({ source: 'tenant', q: '', page: 1, pageSize: 20 })
    expect(document.body.textContent).toContain('本租户·北向增强评分')
    expect(document.body.textContent).toContain('租户公开')
    wrapper.unmount()
  })

  it('关键字输入防抖后带 q 重查', async () => {
    vi.useFakeTimers()
    try {
      const { wrapper, browse } = mountDrawer()
      await flush()
      const input = document.querySelector<HTMLInputElement>('[data-testid="asset-search-drawer-q"]')
      expect(input).not.toBeNull()
      expect(input!.tagName).toBe('INPUT')
      input!.value = '龙头'
      input!.dispatchEvent(new Event('input'))
      await vi.advanceTimersByTimeAsync(350)
      await flush()
      const calls = browse.mock.calls
      expect(calls[calls.length - 1][0]).toMatchObject({ source: 'preset', q: '龙头', page: 1 })
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('空态文案按来源与资产类型拼接', async () => {
    const { wrapper } = mountDrawer({ browse: makeBrowse({ preset: [] }) })
    await flush()
    expect(document.body.textContent).toContain('暂无系统内置评分方案')
    wrapper.unmount()
  })

  it('加载失败显示错误态并可重试', async () => {
    const browse = vi.fn()
      .mockRejectedValueOnce(new Error('network down'))
      .mockImplementation(makeBrowse({ preset: [presetItem] }))
    const { wrapper } = mountDrawer({ browse })
    await flush()
    expect(document.body.textContent).toContain('评分方案加载失败')
    const retry = Array.from(document.querySelectorAll('button'))
      .find((b) => b.textContent?.includes('重试'))
    retry?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flush()
    expect(document.body.textContent).toContain('趋势龙头·基础评分')
    wrapper.unmount()
  })

  it('复制为我的：调用 copyItem 并发出 copied', async () => {
    const copyItem = vi.fn(async () => ({ id: 'new_id', profile_ref: 'ref_new', name: '趋势龙头·基础评分 副本', version: 1 }))
    const { wrapper } = mountDrawer({ copyItem })
    await flush()
    const copyBtn = document.querySelector<HTMLElement>('[data-testid="asset-search-drawer-copy"]')
    expect(copyBtn).toBeTruthy()
    copyBtn!.click()
    await flush()
    expect(copyItem).toHaveBeenCalledTimes(1)
    const copied = wrapper.emitted('copied')
    expect(copied).toBeTruthy()
    expect((copied![0][0] as { id: string }).id).toBe('new_id')
    wrapper.unmount()
  })

  it('无复制权限的角色不显示复制动作', async () => {
    const { wrapper } = mountDrawer({}, [])
    await flush()
    expect(document.querySelector('[data-testid="asset-search-drawer-copy"]')).toBeNull()
    expect(document.querySelector('[data-testid="asset-search-drawer-load"]')).not.toBeNull()
    wrapper.unmount()
  })

  it('加载查看：发出 load 并关闭抽屉', async () => {
    const { wrapper } = mountDrawer()
    await flush()
    const loadBtn = document.querySelector<HTMLElement>('[data-testid="asset-search-drawer-load"]')
    expect(loadBtn).toBeTruthy()
    loadBtn!.click()
    await flush()
    expect(wrapper.emitted('load')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([false])
    wrapper.unmount()
  })

  it('数据请求完成前不渲染空 scope 幻影操作，完成后每行仅一组操作', async () => {
    let resolveBrowse!: (value: AssetBrowseResult) => void
    const browse = vi.fn(() => new Promise<AssetBrowseResult>((resolve) => {
      resolveBrowse = resolve
    }))
    const { wrapper } = mountDrawer({ browse })
    await flush()
    expect(document.querySelectorAll('[data-testid="asset-search-drawer-load"]')).toHaveLength(0)
    expect(document.querySelectorAll('[data-testid="asset-search-drawer-copy"]')).toHaveLength(0)

    resolveBrowse({ items: [presetItem], total: 1, page: 1, page_size: 20, source: 'preset' })
    await flush()
    expect(document.querySelectorAll('[data-testid="asset-search-drawer-load"]')).toHaveLength(1)
    expect(document.querySelectorAll('[data-testid="asset-search-drawer-copy"]')).toHaveLength(1)
    wrapper.unmount()
  })

  it('回测模型：无系统内置段、默认全体公开、操作含复用参数重跑', async () => {
    const rerunItem = vi.fn(async () => undefined)
    const browse = makeBrowse({ public: [], tenant: [] })
    const { wrapper } = mountDrawer({
      kind: 'backtest',
      assetLabel: '回测',
      browse,
      rerunItem,
      copyItem: undefined,
    })
    await flush()
    expect(browse).toHaveBeenCalledWith({ source: 'public', q: '', page: 1, pageSize: 20 })
    expect(document.querySelector('[data-testid="asset-search-drawer-segment-preset"]')).toBeNull()
    expect(document.querySelector('[data-testid="asset-search-drawer-segment-public"]')).not.toBeNull()
    wrapper.unmount()
  })

  it('回测类型与状态显示中文业务文案，不暴露内部枚举', async () => {
    const item: BacktestRunSummary = {
      id: 'bt_public', run_ref: 'run_ref_public', kind: 'score_check', status: 'done',
      date_start: '2024-01-01', date_end: '2024-06-30', created_at: '2024-07-01',
      finished_at: '2024-07-01', visibility: 'public', source: 'public', readonly: true,
    }
    const browse = vi.fn(async (params: AssetBrowseParams): Promise<AssetBrowseResult> => ({
      items: [item], total: 1, page: params.page, page_size: params.pageSize, source: params.source,
    }))
    const { wrapper } = mountDrawer({
      kind: 'backtest', assetLabel: '回测', browse, rerunItem: vi.fn(), copyItem: undefined,
    })
    await flush()
    const text = document.body.textContent || ''
    expect(text).toContain('评分验证')
    expect(text).toContain('已完成')
    expect(text).not.toContain('score_check')
    wrapper.unmount()
  })

  it('无浏览权限（canBrowse=false）时不调 browse，显示无权态而非空态', async () => {
    const browse = makeBrowse({ preset: [presetItem] })
    const { wrapper } = mountDrawer({ browse, canBrowse: false })
    await flush()
    expect(browse).not.toHaveBeenCalled()
    const text = document.body.textContent || ''
    expect(text).toContain('无权限查看评分方案')
    expect(text).toContain('请联系系统管理员调整权限')
    expect(text).not.toContain('暂无系统内置评分方案')
    expect(text).not.toContain('加载查看')
    // 无权态整体隐藏工具栏与分页页脚（不呈可操作假象）
    expect(document.querySelector('.asset-search__toolbar')).toBeNull()
    expect(document.querySelector('.asset-search__footer')).toBeNull()
    wrapper.unmount()
  })

  it('关闭抽屉清理未触发的防抖搜索，重开不再携带旧关键字', async () => {
    vi.useFakeTimers()
    try {
      const browse = makeBrowse({ preset: [presetItem] })
      const { wrapper } = mountDrawer({ browse })
      await flush()
      browse.mockClear()
      // 输入关键字（未达防抖阈值）后立即关闭
      const input = document.querySelector<HTMLInputElement>('[data-testid="asset-search-drawer-q"]')!
      input.value = '龙头'
      input.dispatchEvent(new Event('input'))
      await wrapper.setProps({ modelValue: false })
      await vi.advanceTimersByTimeAsync(500)
      await flush()
      // 关闭清理了 searchTimer，不应再发起隐藏请求
      expect(browse).not.toHaveBeenCalled()
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })
})
