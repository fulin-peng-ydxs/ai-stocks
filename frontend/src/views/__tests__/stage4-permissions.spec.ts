// @vitest-environment jsdom
// 阶段四 T9：业务/数据/布局页操作工具栏的按钮级权限组合显隐（v-permission 真实指令 + auth store）。
// 覆盖 T6 的组合风险点：一行工具栏内混有「受控写按钮 + 非受控基础操作(取消/刷新/导出)」时，
// 无权仅移除对应写按钮、保留非受控操作，不留空白工具栏；system 恒全显。
// 说明：不整体 mount 业务 SFC（其依赖 LayoutHost/composable/API，重且脆），改用**代表性工具栏 harness**
// 复刻各层真实按钮行 + 真实 permission 指令，验证接线与组合显隐（各页逐码契约见 stage4-button-permission.spec.ts）。
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { permission } from '@/directives/permission'
import { useAuthStore } from '@/stores/auth'

// 代表性工具栏：非受控按钮无 v-permission（取消/刷新恒在），受控按钮各挂精确码。
const TOOLBARS: Record<string, string> = {
  // 业务页（策略筛选）：运行 screen:run / 保存方案 screen-profile:save / 取消(非受控)
  business: `<div>
    <button class="b-run" v-permission="'screen:run'">运行筛选</button>
    <button class="b-save" v-permission="'screen-profile:save'">保存</button>
    <button class="b-cancel">取消</button>
  </div>`,
  // 数据页（数据质量）：恢复 data-quality:fix / 质检 data-task:manage / 刷新(非受控)
  data: `<div>
    <button class="d-fix" v-permission="'data-quality:fix'">一键恢复</button>
    <button class="d-verify" v-permission="'data-task:manage'">立即质检</button>
    <button class="d-refresh">刷新</button>
  </div>`,
  // 布局页（视觉预设）：新增预设 layout:preset-manage / 导入 layout:preset-manage / 刷新(非受控)
  layout: `<div>
    <button class="l-new" v-permission="'layout:preset-manage'">新增预设</button>
    <button class="l-refresh">刷新</button>
  </div>`,
}

function mountToolbar(kind: keyof typeof TOOLBARS, role: string, permissions: string[]) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = role
  auth.permissions = permissions
  return mount(
    { template: TOOLBARS[kind] },
    { global: { plugins: [pinia, ElementPlus], directives: { permission } } },
  )
}

describe('业务页工具栏（策略筛选）', () => {
  it('仅 screen:run → 保留运行、移除保存、保留取消（非受控）', () => {
    const w = mountToolbar('business', 'normal', ['screen:run'])
    expect(w.find('.b-run').exists()).toBe(true)
    expect(w.find('.b-save').exists()).toBe(false)
    expect(w.find('.b-cancel').exists()).toBe(true)   // 非受控基础操作恒在
  })
  it('无任何码 → 两写按钮移除、取消仍在（不留空白工具栏）', () => {
    const w = mountToolbar('business', 'normal', [])
    expect(w.find('.b-run').exists()).toBe(false)
    expect(w.find('.b-save').exists()).toBe(false)
    expect(w.find('.b-cancel').exists()).toBe(true)
  })
})

describe('数据页工具栏（数据质量，system-only 页）', () => {
  it('仅 data-quality:fix → 保留恢复、移除质检、保留刷新', () => {
    const w = mountToolbar('data', 'normal', ['data-quality:fix'])
    expect(w.find('.d-fix').exists()).toBe(true)
    expect(w.find('.d-verify').exists()).toBe(false)
    expect(w.find('.d-refresh').exists()).toBe(true)
  })
})

describe('布局页工具栏（视觉预设，system-only 页）', () => {
  it('无 layout:preset-manage → 移除新增、保留刷新', () => {
    const w = mountToolbar('layout', 'normal', [])
    expect(w.find('.l-new').exists()).toBe(false)
    expect(w.find('.l-refresh').exists()).toBe(true)
  })
})

describe('system 恒全显（三层工具栏）', () => {
  it.each(['business', 'data', 'layout'] as const)('%s：system 无 permissions 仍全渲染', (kind) => {
    const w = mountToolbar(kind, 'system', [])
    expect(w.findAll('button').every((b) => b.exists())).toBe(true)
    // system 下受控按钮不被移除：按钮总数 = 模板声明数
    const declared = (TOOLBARS[kind].match(/<button/g) || []).length
    expect(w.findAll('button').length).toBe(declared)
  })
})
