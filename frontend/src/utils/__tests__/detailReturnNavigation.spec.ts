import { describe, expect, it } from 'vitest'
import { detailReturnLabel, trustedDetailReturnPath } from '../detailReturnNavigation'

describe('trustedDetailReturnPath', () => {
  it.each([
    '/limit-ladder?window=20',
    '/stocks?restore=1',
    '/stocks/600000.SH',
    '/sectors?type=industry',
    '/sectors/881001?return_to=%2Fstocks',
    '/board?date=2026-09-02',
    '/screen',
  ])('保留已知业务返回地址：%s', (path) => {
    expect(trustedDetailReturnPath(path)).toBe(path)
  })

  it.each(['/admin', '//evil.example/steal', 'https://evil.example/steal', '/stocks-archive'])
    ('拒绝非业务返回地址：%s', (path) => {
      expect(trustedDetailReturnPath(path)).toBeUndefined()
    })
})

describe('detailReturnLabel', () => {
  it.each([
    ['/limit-ladder?window=20', '返回连板天梯'],
    ['/stocks?restore=1', '返回个股查询'],
    ['/stocks/600000.SH', '返回个股详情'],
    ['/sectors', '返回板块行情'],
    ['/sectors/881001?return_to=%2Fstocks', '返回板块详情'],
    ['/board?date=2026-09-02', '返回每日榜单'],
    ['/screen', '返回策略筛选'],
  ])('将已解析的业务地址 %s 映射为返回目标', (path, label) => {
    expect(detailReturnLabel(path, '返回默认页')).toBe(label)
  })

  it('未识别地址使用调用页自己的兜底文案', () => {
    expect(detailReturnLabel('/admin', '返回个股查询')).toBe('返回个股查询')
    expect(detailReturnLabel('/stocks-archive', '返回个股查询')).toBe('返回个股查询')
    expect(detailReturnLabel(undefined, '返回板块行情')).toBe('返回板块行情')
  })
})
