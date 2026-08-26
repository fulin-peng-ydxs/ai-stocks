export function getErrorMessage(error: unknown, fallback = '请求失败'): string {
  const response = (error as { response?: { data?: Record<string, unknown>; status?: number } })
    ?.response
  const payload = response?.data
  const is5xx = typeof response?.status === 'number' && response.status >= 500
  // 无 HTTP 响应的 axios 网络错误（超时/断网）：isAxiosError 为 true 且无 response。
  // 纯 JS Error（new Error / 手动 reject）不在此列，保持展示自身 message。
  const isAxiosNetworkError = !response
    && (error as { isAxiosError?: boolean })?.isAxiosError === true
  const candidates = [
    // client.ts 拦截器在 reject 前挂上的可读文案（业务 msg / 状态码分流后的中文），优先级最高。
    (error as { uiMessage?: unknown })?.uiMessage,
    payload?.msg,
    // 4xx 的 detail 承载后端中文业务文案（HTTPException(detail=...)）；5xx 的 detail 是 FastAPI
    // 默认英文系统文本（"Internal Server Error"），不展示，统一走中文兜底。
    ...(is5xx ? [] : [payload?.detail]),
    payload?.message,
    is5xx ? '服务暂时不可用，请稍后重试' : undefined,
    isAxiosNetworkError
      ? (isTimeoutError(error) ? '请求超时，请稍后重试' : '网络错误，请检查网络后重试')
      : undefined,
    error instanceof Error ? error.message : undefined,
  ]
  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.trim()) return candidate
  }
  return fallback
}

// axios 超时特征：code=ECONNABORTED 且 message 含 timeout（无 HTTP 响应）。
export function isTimeoutError(error: unknown): boolean {
  const e = error as { code?: string; message?: string }
  return e?.code === 'ECONNABORTED' && typeof e.message === 'string' && e.message.includes('timeout')
}

export function getErrorStatus(error: unknown): number | undefined {
  return (error as { response?: { status?: number } })?.response?.status
}

/** 读取统一 `{code,msg,data}` 响应在 HTTP 200 中返回的业务错误码。 */
export function getApiErrorCode(error: unknown): number | undefined {
  return (error as { apiCode?: number })?.apiCode
}
