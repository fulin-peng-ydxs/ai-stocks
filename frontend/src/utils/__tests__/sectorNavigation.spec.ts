import { describe, expect, it } from 'vitest'
import {
  sectorDetailLocation,
  sectorListLocation,
  sectorReturnLabel,
  trustedSectorReturnPath,
} from '../sectorNavigation'

describe('sectorListLocation', () => {
  it('无跨模块来源时只通过一次性标记恢复板块列表现场', () => {
    expect(sectorListLocation(undefined)).toEqual({
      path: '/sectors',
      query: { restore: '1' },
    })
  })

  it.each([
    '/limit-ladder?restore=1',
    '/stocks?restore=1',
    '/stocks/600000.SH',
    '/board?date=2026-09-02',
    '/screen?profile_ref=opaque',
  ])('允许返回可信业务来源完整路径：%s', (returnTo) => {
    expect(sectorListLocation(returnTo)).toBe(returnTo)
  })

  it('拒绝开放重定向和非来源业务路由', () => {
    expect(sectorListLocation('//evil.example/steal')).toEqual({
      path: '/sectors',
      query: { restore: '1' },
    })
    expect(trustedSectorReturnPath('/admin?next=/stocks')).toBeUndefined()
  })
})

describe('sectorDetailLocation', () => {
  it('统一编码板块代码并只携带可信跨模块来源', () => {
    expect(sectorDetailLocation('概念/AI', '/board?date=2026-09-02')).toEqual({
      path: '/sectors/%E6%A6%82%E5%BF%B5%2FAI',
      query: { return_to: '/board?date=2026-09-02' },
    })
    expect(sectorDetailLocation('881001', 'https://evil.example')).toEqual({
      path: '/sectors/881001',
      query: undefined,
    })
  })
})

describe('sectorReturnLabel', () => {
  it.each([
    ['/limit-ladder?restore=1', '返回连板天梯'],
    ['/stocks?restore=1', '返回个股查询'],
    ['/stocks/600000.SH', '返回个股详情'],
    ['/board?date=2026-09-02', '返回每日榜单'],
    ['/screen?profile_ref=opaque', '返回策略筛选'],
  ])('按可信来源 %s 展示 %s', (returnTo, label) => {
    expect(sectorReturnLabel(returnTo)).toBe(label)
  })

  it('非法或缺失来源使用板块行情兜底文案', () => {
    expect(sectorReturnLabel('/admin')).toBe('返回板块行情')
    expect(sectorReturnLabel(undefined)).toBe('返回板块行情')
  })
})
