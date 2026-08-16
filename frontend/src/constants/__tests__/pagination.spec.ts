import { describe, expect, it } from 'vitest'
import {
  DEFAULT_PAGE_SIZE,
  MAX_PAGE_SIZE,
  MIN_PAGE_SIZE,
  normalizePageSize,
} from '../pagination'

describe('normalizePageSize', () => {
  it('保留合法页面专属值并规范小数', () => {
    expect(normalizePageSize(30)).toBe(30)
    expect(normalizePageSize(50.9)).toBe(50)
  })

  it('把历史越界配置收敛到接口允许范围', () => {
    expect(normalizePageSize(500)).toBe(MAX_PAGE_SIZE)
    expect(normalizePageSize(5)).toBe(MIN_PAGE_SIZE)
  })

  it('非法值回退到调用方默认值', () => {
    expect(normalizePageSize(undefined)).toBe(DEFAULT_PAGE_SIZE)
    expect(normalizePageSize(null, 50)).toBe(50)
    expect(normalizePageSize(false, 50)).toBe(50)
    expect(normalizePageSize('', 50)).toBe(50)
    expect(normalizePageSize('bad', 50)).toBe(50)
    expect(normalizePageSize('bad', 500)).toBe(MAX_PAGE_SIZE)
  })
})
