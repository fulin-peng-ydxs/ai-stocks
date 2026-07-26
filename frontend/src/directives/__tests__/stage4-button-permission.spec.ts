// @vitest-environment jsdom
// 阶段四 T6：存量业务/系统页按钮级 v-permission 契约（数据驱动，覆盖代表性资源码）。
// 复用 v-permission 指令机制（其通用行为见 permission.spec.ts），此处锁定 stage4 各页按钮所用精确码
// 在「有码保留 / 无码移除 / system 恒保留」三种角色态下的表现，防止后续误改码或误删指令。
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { permission } from '@/directives/permission'
import { useAuthStore } from '@/stores/auth'

function gated(role: string, permissions: string[], code: string) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = role
  auth.permissions = permissions
  return mount(
    { props: ['code'], template: '<div><button v-permission="code" class="g">x</button></div>' },
    { props: { code }, global: { plugins: [pinia], directives: { permission } } },
  ).find('.g').exists()
}

// stage4 业务页按钮码（授予 normal/tenant_admin，自定义角色可能仅持读码）。
const BUSINESS_BUTTON_CODES = [
  'screen-profile:save', 'screen:run',
  'backtest:run', 'backtest:robust', 'backtest:delete',
  'training:start', 'training:trade', 'training:review', 'training:delete',
  'stock-group:create', 'stock-group:update', 'stock-group:delete', 'stock-group:member-update',
]

// stage4 系统页按钮码（system-only 页面，仅 system 可达 → 对其恒保留；非 system 即便直达也无码移除）。
const SYSTEM_BUTTON_CODES = [
  'score-profile:save', 'score-profile:delete', 'score:run',
  'trade-profile:save', 'trade-profile:delete', 'trade-profile:preview',
  'indicator:def-manage',
  'data-task:manage', 'data-quality:fix', 'data-schedule:manage', 'data-source:test', 'data-settings:manage',
  'layout:preset-manage', 'layout:page-manage', 'layout:field-policy',
]

describe('阶段四 T6 按钮级权限契约', () => {
  it.each(BUSINESS_BUTTON_CODES)('业务码 %s：持码保留 / 缺码移除', (code) => {
    expect(gated('normal', [code], code)).toBe(true)
    expect(gated('normal', ['unrelated:x'], code)).toBe(false)
  })

  it.each([...BUSINESS_BUTTON_CODES, ...SYSTEM_BUTTON_CODES])('system 恒保留：%s', (code) => {
    expect(gated('system', [], code)).toBe(true)
  })

  it.each(SYSTEM_BUTTON_CODES)('system-only 码 %s：非 system 无码 → 移除（后端 require_system_perm 硬兜底）', (code) => {
    expect(gated('normal', [], code)).toBe(false)
  })
})
