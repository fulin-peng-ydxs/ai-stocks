import { describe, expect, it } from 'vitest'
import { getErrorMessage, getErrorStatus } from '@/utils/error'

describe('error utils', () => {
  it('读取 API 状态码和服务端可读文案', () => {
    const error = {
      response: {
        status: 403,
        data: { msg: '无权限查看' },
      },
    }

    expect(getErrorStatus(error)).toBe(403)
    expect(getErrorMessage(error)).toBe('无权限查看')
  })

  it('非 HTTP 错误保持状态为空并使用 Error 文案', () => {
    const error = new Error('网络断开')

    expect(getErrorStatus(error)).toBeUndefined()
    expect(getErrorMessage(error)).toBe('网络断开')
  })
})
