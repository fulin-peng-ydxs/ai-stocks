import { describe, expect, it } from 'vitest'
import { createLatestRequestGuard } from '@/utils/latestRequestGuard'

describe('createLatestRequestGuard', () => {
  it('只允许最后启动的请求提交状态', () => {
    const guard = createLatestRequestGuard()
    const first = guard.begin()
    const second = guard.begin()

    expect(guard.isCurrent(first)).toBe(false)
    expect(guard.isCurrent(second)).toBe(true)
  })

  it('失效后拒绝仍在途的请求', () => {
    const guard = createLatestRequestGuard()
    const request = guard.begin()
    guard.invalidate()

    expect(guard.isCurrent(request)).toBe(false)
  })
})
