import { describe, expect, it } from 'vitest'
import { adaptiveWorkspaceHeight } from '../marketWorkspaceSizing'

describe('marketWorkspaceSizing', () => {
  it('用滚动容器剩余空间填高工作台', () => {
    expect(adaptiveWorkspaceHeight({
      scrollportHeight: 900,
      contentTop: 260,
      minHeight: 480,
      bottomInset: 16,
    })).toBe(624)
  })

  it('剩余空间不足时守住可读下限', () => {
    expect(adaptiveWorkspaceHeight({
      scrollportHeight: 700,
      contentTop: 560,
      minHeight: 480,
    })).toBe(480)
  })
})
