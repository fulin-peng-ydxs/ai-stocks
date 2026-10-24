// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElButton, ElMessage, ElMessageBox, ElSelect } from 'element-plus'
import { nextTick } from 'vue'
import LayoutPagesView from '../layout/LayoutPagesView.vue'
import type { LayoutPageConfig } from '@/api/layout'

const api = vi.hoisted(() => ({
  getLayoutPageConfig: vi.fn(), getLayoutUserConfig: vi.fn(), getEffectiveLayoutConfig: vi.fn(),
  listFieldPolicies: vi.fn(), resetLayoutConfig: vi.fn(), saveLayoutPageConfig: vi.fn(),
  saveLayoutUserConfig: vi.fn(), validateLayoutConfig: vi.fn(),
}))
vi.mock('@/api/layout', async (original) => ({ ...await original<object>(), ...api }))
type ConfirmationResult = Awaited<ReturnType<typeof ElMessageBox.confirm>>
// Element Plus 当前声明为交叉类型，confirm 的实际完成值仍是动作字符串。
const confirmed = 'confirm' as ConfirmationResult

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

function pageConfig(pageKey: string): LayoutPageConfig {
  return { pageKey, presetKey: null, config: { schemaVersion: 1, values: {} } }
}

let wrapper: VueWrapper
function button(label: string) {
  return wrapper.findAllComponents(ElButton).find(item => item.text() === label)!
}
function pageSelect() {
  return wrapper.findAllComponents(ElSelect).find(item => item.props('ariaLabel') === '选择配置页面')!
}
function exportSelect() {
  return wrapper.findAllComponents(ElSelect).find(item => item.props('ariaLabel') === '导出范围')!
}
async function selectTab(name: string) {
  await wrapper.get(`#tab-${name}`).trigger('click')
  await flushPromises()
}
async function mountPage() {
  wrapper = mount(LayoutPagesView, {
    global: {
      plugins: [ElementPlus], directives: { permission: {} },
      stubs: {
        LayoutHost: { template: '<div><slot name="action"/><slot name="main"/></div>' },
        AppScrollArea: { template: '<div><slot/></div>' },
        LayoutPagePreview: true, ComponentAutoSettings: true, AppDataTable: true, HelpHint: true,
      },
    },
  })
  await flushPromises()
}

describe('页面布局操作闭环', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    api.getLayoutPageConfig.mockImplementation(async key => pageConfig(key))
    api.getLayoutUserConfig.mockImplementation(async key => ({
      userId: 'session-user', pageKey: key, config: { schemaVersion: 1, values: {} },
    }))
    api.getEffectiveLayoutConfig.mockImplementation(async key => ({ pageKey: key, values: {}, source: {} }))
    api.listFieldPolicies.mockResolvedValue({ policies: [] })
    api.validateLayoutConfig.mockResolvedValue({ valid: true, errors: [] })
    api.resetLayoutConfig.mockResolvedValue({})
    api.saveLayoutPageConfig.mockImplementation(async key => pageConfig(key))
    api.saveLayoutUserConfig.mockResolvedValue({})
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(confirmed)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
    vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
  })
  afterEach(() => { wrapper?.unmount(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('恢复默认从确认开始锁定上下文，防止重复或与保存交叉执行', async () => {
    await mountPage()
    const confirm = deferred<ConfirmationResult>()
    vi.mocked(ElMessageBox.confirm).mockReturnValueOnce(confirm.promise)
    button('恢复页面系统默认').vm.$emit('click', new MouseEvent('click'))
    button('恢复页面系统默认').vm.$emit('click', new MouseEvent('click'))
    await nextTick()
    expect(button('恢复页面系统默认').props()).toMatchObject({ type: 'warning', loading: true, disabled: false })
    expect(pageSelect().props('disabled')).toBe(true)
    expect(button('保存页面配置').props('disabled')).toBe(true)
    expect(ElMessageBox.confirm).toHaveBeenCalledTimes(1)
    expect(ElMessageBox.confirm).toHaveBeenCalledWith(
      expect.stringContaining('各用户的个性化覆盖会保留'), '恢复页面系统默认', expect.anything(),
    )
    expect(api.resetLayoutConfig).not.toHaveBeenCalled()
    confirm.resolve(confirmed)
    await flushPromises()
    expect(api.resetLayoutConfig).toHaveBeenCalledTimes(1)
    expect(api.resetLayoutConfig).toHaveBeenCalledWith({ scope: 'page', pageKey: 'limit-ladder' })
    expect(button('恢复页面系统默认').props('loading')).toBe(false)
    expect(pageSelect().props('disabled')).toBe(false)
  })

  it('取消恢复不写库，恢复请求失败后解除忙态且不误报成功', async () => {
    await mountPage()
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')
    await button('恢复页面系统默认').trigger('click')
    await flushPromises()
    expect(api.resetLayoutConfig).not.toHaveBeenCalled()
    api.resetLayoutConfig.mockRejectedValueOnce(new Error('恢复失败'))
    await button('恢复页面系统默认').trigger('click')
    await flushPromises()
    expect(button('恢复页面系统默认').props('loading')).toBe(false)
    expect(ElMessage.success).not.toHaveBeenCalled()
  })

  it('报告首次加载不提前显示通过，并明确清除的是当前登录用户', async () => {
    await mountPage()
    const request = deferred<LayoutPageConfig>()
    api.getLayoutPageConfig.mockReturnValueOnce(request.promise)
    await selectTab('report')
    expect(wrapper.text()).toContain('正在校验布局配置')
    expect(wrapper.text()).not.toContain('均通过校验')
    expect(wrapper.find('input[placeholder="userId"]').exists()).toBe(false)
    request.resolve(pageConfig('limit-ladder'))
    await flushPromises()
    const reset = deferred<object>()
    api.resetLayoutConfig.mockReturnValueOnce(reset.promise)
    button('清除用户覆盖').vm.$emit('click', new MouseEvent('click'))
    button('清除用户覆盖').vm.$emit('click', new MouseEvent('click'))
    await flushPromises()
    expect(button('清除用户覆盖').props()).toMatchObject({ type: 'danger', loading: true, disabled: false })
    expect(button('重新校验').props('disabled')).toBe(true)
    expect(ElMessageBox.confirm).toHaveBeenCalledWith(
      expect.stringContaining('当前登录用户'), '清除用户覆盖',
      expect.objectContaining({ confirmButtonType: 'danger' }),
    )
    expect(api.resetLayoutConfig).toHaveBeenCalledTimes(1)
    expect(api.resetLayoutConfig).toHaveBeenCalledWith({ scope: 'user', pageKey: 'limit-ladder' })
    reset.resolve({})
    await flushPromises()
    expect(button('清除用户覆盖').props('loading')).toBe(false)
    expect(api.getLayoutUserConfig.mock.calls.every(args => args.length === 1)).toBe(true)
  })

  it('导出生成共享在途锁，失败保留可重试反馈，切换范围清理旧内容', async () => {
    await mountPage()
    await selectTab('import')
    const request = deferred<LayoutPageConfig>()
    api.getLayoutPageConfig.mockReturnValueOnce(request.promise)
    button('生成').vm.$emit('click', new MouseEvent('click'))
    button('生成').vm.$emit('click', new MouseEvent('click'))
    button('下载').vm.$emit('click', new MouseEvent('click'))
    await nextTick()
    expect(api.getLayoutPageConfig).toHaveBeenCalledTimes(2) // 初始化 + 本次生成
    expect(button('生成').props('loading')).toBe(true)
    expect(button('下载').props('disabled')).toBe(true)
    expect(exportSelect().props('disabled')).toBe(true)
    request.reject(new Error('来源暂时不可用'))
    await flushPromises()
    expect(wrapper.text()).toContain('配置导出失败')
    expect(button('生成').props('loading')).toBe(false)
    await button('生成').trigger('click')
    await flushPromises()
    expect(wrapper.get('textarea[aria-label="导出配置 JSON"]').element).toHaveProperty('value', expect.stringContaining('layout-page-config'))
    exportSelect().vm.$emit('update:modelValue', 'user')
    await nextTick()
    expect(wrapper.get('textarea[aria-label="导出配置 JSON"]').element).toHaveProperty('value', '')
    expect(wrapper.text()).not.toContain('配置导出失败')
  })

  it('下载没有内容时等待生成，失败不下载，成功仅生成一次并释放对象 URL', async () => {
    await mountPage()
    await selectTab('import')
    const createObjectURL = vi.fn().mockReturnValue('blob:layout')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    api.getLayoutPageConfig.mockRejectedValueOnce(new Error('导出失败'))
    await button('下载').trigger('click')
    await flushPromises()
    expect(click).not.toHaveBeenCalled()
    const request = deferred<LayoutPageConfig>()
    api.getLayoutPageConfig.mockReturnValueOnce(request.promise)
    button('下载').vm.$emit('click', new MouseEvent('click'))
    button('下载').vm.$emit('click', new MouseEvent('click'))
    await nextTick()
    expect(button('下载').props('loading')).toBe(true)
    request.resolve(pageConfig('limit-ladder'))
    await flushPromises()
    expect(click).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:layout')
    expect(button('下载').props('loading')).toBe(false)
  })

  it('导入拒绝其他页面的文件，用户文件归属不透传到保存接口', async () => {
    await mountPage()
    await selectTab('import')
    const input = wrapper.get('textarea[placeholder="粘贴页面/用户配置 JSON"]')
    expect(button('校验并导入').props('disabled')).toBe(true)
    await input.setValue(JSON.stringify({ type: 'layout-page-config', page: pageConfig('stocks') }))
    await button('校验并导入').trigger('click')
    await flushPromises()
    expect(api.validateLayoutConfig).not.toHaveBeenCalled()
    expect(api.saveLayoutPageConfig).not.toHaveBeenCalled()
    expect(ElMessage.error).toHaveBeenCalledWith(expect.stringContaining('当前页面一致'))
    await input.setValue(JSON.stringify({ type: 'layout-user-config', user: {
      ...pageConfig('limit-ladder'), userId: 'another-user',
    } }))
    await button('校验并导入').trigger('click')
    await flushPromises()
    expect(api.saveLayoutUserConfig).toHaveBeenCalledWith('limit-ladder', expect.not.objectContaining({ userId: expect.anything() }))
    expect(ElMessage.success).toHaveBeenCalledWith('当前登录用户的配置导入完成')
  })

  it('保存失败保留草稿，保存中防重复提交与草稿变更，成功后才更新基线', async () => {
    await mountPage()
    const density = wrapper.findAllComponents(ElSelect).find(item => item.props('placeholder') === '使用系统默认')!
    density.vm.$emit('update:modelValue', 'compact')
    await nextTick()
    const request = deferred<LayoutPageConfig>()
    api.saveLayoutPageConfig.mockReturnValueOnce(request.promise)
    button('保存页面配置').vm.$emit('click', new MouseEvent('click'))
    button('保存页面配置').vm.$emit('click', new MouseEvent('click'))
    await flushPromises()
    expect(api.saveLayoutPageConfig).toHaveBeenCalledTimes(1)
    expect(button('保存页面配置').props('loading')).toBe(true)
    density.vm.$emit('update:modelValue', 'comfortable')
    await nextTick()
    request.reject(new Error('保存失败'))
    await flushPromises()
    expect(density.props('modelValue')).toBe('compact')
    expect(button('保存页面配置').props('disabled')).toBe(false)
    await button('保存页面配置').trigger('click')
    await flushPromises()
    expect(button('保存页面配置').props('disabled')).toBe(true)
  })

  it('切换页面的迟到响应不能覆盖新页面草稿', async () => {
    await mountPage()
    const older = deferred<LayoutPageConfig>()
    const newer = deferred<LayoutPageConfig>()
    api.getLayoutPageConfig.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise)
    pageSelect().vm.$emit('update:modelValue', 'stocks')
    await nextTick()
    pageSelect().vm.$emit('update:modelValue', 'board')
    await nextTick()
    newer.resolve({ ...pageConfig('board'), config: { schemaVersion: 1, values: { density: 'compact' } } })
    await flushPromises()
    older.resolve({ ...pageConfig('stocks'), config: { schemaVersion: 1, values: { density: 'comfortable' } } })
    await flushPromises()
    const density = wrapper.findAllComponents(ElSelect).find(item => item.props('placeholder') === '使用系统默认')!
    expect(density.props('modelValue')).toBe('compact')
    expect(pageSelect().props('modelValue')).toBe('board')
  })

  it('报告请求失败显示错误，重试完成后才展示校验结果', async () => {
    await mountPage()
    api.getLayoutUserConfig.mockRejectedValueOnce(new Error('用户覆盖读取失败'))
    await selectTab('report')
    expect(wrapper.text()).toContain('校验报告加载失败')
    expect(wrapper.text()).not.toContain('均通过校验')
    await button('重新校验').trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('校验报告加载失败')
    expect(wrapper.text()).toContain('均通过校验')
  })

  it('导入校验期间阻止重复请求，保存失败后保留内容供重试', async () => {
    await mountPage()
    await selectTab('import')
    const input = wrapper.get('textarea[placeholder="粘贴页面/用户配置 JSON"]')
    const content = JSON.stringify({ type: 'layout-user-config', user: pageConfig('limit-ladder') })
    await input.setValue(content)
    const validation = deferred<{ valid: boolean; errors: string[] }>()
    api.validateLayoutConfig.mockReturnValueOnce(validation.promise)
    button('校验并导入').vm.$emit('click', new MouseEvent('click'))
    button('校验并导入').vm.$emit('click', new MouseEvent('click'))
    await nextTick()
    expect(api.validateLayoutConfig).toHaveBeenCalledTimes(1)
    expect(button('校验并导入').props('loading')).toBe(true)
    expect(pageSelect().props('disabled')).toBe(true)
    api.saveLayoutUserConfig.mockRejectedValueOnce(new Error('配置保存失败'))
    validation.resolve({ valid: true, errors: [] })
    await flushPromises()
    expect(input.element).toHaveProperty('value', content)
    expect(button('校验并导入').props('loading')).toBe(false)
    expect(ElMessage.success).not.toHaveBeenCalled()
    await button('校验并导入').trigger('click')
    await flushPromises()
    expect(ElMessage.success).toHaveBeenCalledWith('当前登录用户的配置导入完成')
  })

  it('共享文件选择面板回填导入草稿，选择文件不会自动保存', async () => {
    await mountPage()
    await selectTab('import')
    const content = JSON.stringify({ type: 'layout-page-config', page: pageConfig('limit-ladder') })
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', {
      configurable: true, value: [new File([content], '页面配置.json', { type: 'application/json' })],
    })
    await input.trigger('change')
    await vi.waitFor(() => expect(wrapper.get('textarea[aria-label="导入配置 JSON"]').element).toHaveProperty('value', content))
    expect(wrapper.text()).toContain('页面配置.json')
    expect(api.saveLayoutPageConfig).not.toHaveBeenCalled()
    expect(api.saveLayoutUserConfig).not.toHaveBeenCalled()
  })
})
