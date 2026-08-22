import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { routes } from '../index'

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
})
