import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { createMemoryHistory, createRouter } from 'vue-router'
import { routes } from '../index'

const ROUTER_SOURCE = readFileSync(new URL('../index.ts', import.meta.url), 'utf-8')
const APP_SOURCE = readFileSync(new URL('../../App.vue', import.meta.url), 'utf-8')

describe('阶段五前端路由', () => {
  it('注册审计日志、数据字典和交易纪律静态路由', () => {
    const router = createRouter({ history: createMemoryHistory(), routes })
    const audit = router.resolve('/system/audit')
    expect(audit.name).toBe('audit-log')
    expect(audit.meta.title).toBe('审计日志')

    const dicts = router.resolve('/system/dicts')
    expect(dicts.name).toBe('data-dictionary')
    expect(dicts.meta.title).toBe('数据字典')

    const discipline = router.resolve('/trade-discipline')
    expect(discipline.name).toBe('trade-discipline')
    expect(discipline.meta.title).toBe('交易纪律')
  })

  it('路由、注销和快捷卡共同消费应用级权限与未保存协议', () => {
    expect(ROUTER_SOURCE).toMatch(/confirmLeave\(from\.path, 'route'\)[\s\S]*prepareWorkspaceTabVisit/)
    const logout = APP_SOURCE.match(/async function onLogout\(\) \{([\s\S]*?)\n\}/)?.[1] ?? ''
    expect(logout.indexOf("confirmAll('logout')")).toBeGreaterThanOrEqual(0)
    expect(logout.indexOf("confirmAll('logout')")).toBeLessThan(logout.indexOf('auth.logout()'))
    expect(logout.indexOf('auth.logout()')).toBeLessThan(logout.indexOf('resetWorkspaceTabs()'))
    expect(APP_SOURCE).toMatch(/trade-discipline:view[\s\S]*trade-discipline:checkin-view/)
    expect(APP_SOURCE).toMatch(/<TradeDisciplineQuickCard[\s\S]*:can-submit="canSubmitTradeDisciplineCheckin"/)
  })
})
