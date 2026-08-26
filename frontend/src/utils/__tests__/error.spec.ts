import { describe, expect, it } from 'vitest'
import { getApiErrorCode, getErrorMessage, getErrorStatus } from '@/utils/error'

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

  it('区分统一响应业务码与 HTTP 状态码', () => {
    const error = { apiCode: 404, response: { status: 200 } }

    expect(getApiErrorCode(error)).toBe(404)
    expect(getErrorStatus(error)).toBe(200)
  })

  it('优先取 client 拦截器挂上的 uiMessage（可读文案）', () => {
    const error = {
      uiMessage: '服务内部错误，请稍后重试',
      response: { status: 500, data: { detail: 'Internal Server Error' } },
    }

    expect(getErrorMessage(error)).toBe('服务内部错误，请稍后重试')
  })

  it('5xx 且无业务文案时给统一中文兜底，不漏 axios 英文', () => {
    const error = {
      response: { status: 500, data: { detail: 'Internal Server Error' } },
    } as unknown as Error

    expect(getErrorMessage(error)).toBe('服务暂时不可用，请稍后重试')
  })

  it('4xx 带 detail 中文时优先展示 detail', () => {
    const error = {
      response: { status: 400, data: { detail: '不支持的指标字段: xxx' } },
    }

    expect(getErrorMessage(error)).toBe('不支持的指标字段: xxx')
  })

  it('axios 超时（无 HTTP 响应）给中文超时文案，不漏英文 timeout', () => {
    const error = { isAxiosError: true, code: 'ECONNABORTED', message: 'timeout of 30000ms exceeded' }

    expect(getErrorMessage(error)).toBe('请求超时，请稍后重试')
  })

  it('断网（无 HTTP 响应）给中文网络错误，不漏英文 Network Error', () => {
    const error = { isAxiosError: true, message: 'Network Error' }

    expect(getErrorMessage(error)).toBe('网络错误，请检查网络后重试')
  })
})
