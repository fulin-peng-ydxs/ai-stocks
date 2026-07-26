// @vitest-environment jsdom
// 阶段四 T9：角色权限树 PermissionTree 的 baseline_locked 行为（勾选 + 置灰 + 不可反选 + 基线标签）。
// baseline 共享读码在角色页对所有角色**恒勾选、置灰不可反选**（与 sysLocked 相反语义：sysLocked=off 置灰、
// baselineLocked=on 置灰）。此处直接 mount 展示组件、构造含三类功能点的叶子菜单节点，断言渲染态。
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import PermissionTree from '@/views/system/PermissionTree.vue'
import type { PermNode } from '@/views/system/permissionTree'

// 叶子菜单，挂三类功能点：baseline（恒 on 置灰）/ 普通（随 stateOf）/ sysLocked（恒 off 置灰）。
function leaf(): PermNode {
  return {
    key: '/board', label: '每日榜单', kind: 'menu', nodeType: 'leaf', sysLocked: false,
    children: [
      { key: 'layout:view', label: '布局生效读', kind: 'resource', nodeType: 'api', sysLocked: false, baselineLocked: true },
      { key: 'board:view', label: '查看榜单', kind: 'resource', nodeType: 'api', sysLocked: false, baselineLocked: false },
      { key: 'config:view', label: '系统配置', kind: 'resource', nodeType: 'api', sysLocked: true, baselineLocked: false },
    ],
  }
}

async function mountTree(opts: { stateOf?: (n: PermNode) => 'on' | 'half' | 'off'; readonly?: boolean; toggle?: (n: PermNode) => void }) {
  const wrapper = mount(PermissionTree, {
    props: {
      node: leaf(),
      stateOf: opts.stateOf ?? (() => 'off'),
      toggle: opts.toggle ?? (() => {}),
      readonly: opts.readonly ?? false,
    },
    global: { plugins: [ElementPlus] },
  })
  await wrapper.find('.pt-resource-trigger').trigger('click')
  return wrapper
}

// 按功能点标签取对应 chip 的 el-checkbox class 列表。
function chipCheckbox(w: Awaited<ReturnType<typeof mountTree>>, label: string): string[] {
  const chip = w.findAll('.pt-func').find((c) => c.find('.pt-fname').text() === label)
  if (!chip) throw new Error(`未找到功能点 chip: ${label}`)
  return chip.find('.el-checkbox').classes()
}

describe('PermissionTree baseline_locked（stage4 T9）', () => {
  it('baseline 功能点：即便 stateOf=off 也恒勾选 + 置灰 + 显示「基线」标签', async () => {
    const w = await mountTree({ stateOf: () => 'off' })
    const cls = chipCheckbox(w, '布局生效读')
    expect(cls).toContain('is-checked')     // 恒 on
    expect(cls).toContain('is-disabled')    // 不可反选
    const baselineChip = w.findAll('.pt-func').find((c) => c.find('.pt-fname').text() === '布局生效读')!
    expect(baselineChip.find('.pt-baseline').exists()).toBe(true)   // 「基线」标签
  })

  it('普通功能点：随 stateOf 勾选、可编辑（非置灰）', async () => {
    const off = await mountTree({ stateOf: () => 'off' })
    expect(chipCheckbox(off, '查看榜单')).not.toContain('is-checked')
    expect(chipCheckbox(off, '查看榜单')).not.toContain('is-disabled')
    const on = await mountTree({ stateOf: () => 'on' })
    expect(chipCheckbox(on, '查看榜单')).toContain('is-checked')
  })

  it('sysLocked 功能点：置灰且不勾选（非 system 不可授）', async () => {
    const cls = chipCheckbox(await mountTree({ stateOf: () => 'off' }), '系统配置')
    expect(cls).toContain('is-disabled')
    expect(cls).not.toContain('is-checked')
  })

  it('readonly：全部置灰（含普通功能点）', async () => {
    const w = await mountTree({ stateOf: () => 'on', readonly: true })
    expect(chipCheckbox(w, '查看榜单')).toContain('is-disabled')
    expect(chipCheckbox(w, '布局生效读')).toContain('is-disabled')
  })

  it('toggle：普通功能点可触发；baseline 置灰不触发（不可反选）', async () => {
    const toggle = vi.fn()
    const w = await mountTree({ stateOf: () => 'off', toggle })
    const plain = w.findAll('.pt-func').find((c) => c.find('.pt-fname').text() === '查看榜单')!
    await plain.find('input').trigger('change')
    expect(toggle).toHaveBeenCalledTimes(1)
    expect(toggle.mock.calls[0][0].key).toBe('board:view')
    // baseline chip 的 checkbox 置灰：change 不应触发 toggle
    toggle.mockClear()
    const baseline = w.findAll('.pt-func').find((c) => c.find('.pt-fname').text() === '布局生效读')!
    await baseline.find('input').trigger('change')
    expect(toggle).not.toHaveBeenCalled()
  })
})
