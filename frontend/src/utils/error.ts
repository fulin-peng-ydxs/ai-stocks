export function getErrorMessage(error: unknown, fallback = '请求失败'): string {
  const payload = (error as { response?: { data?: { msg?: unknown; detail?: unknown; message?: unknown } } })
    ?.response?.data
  const candidates = [
    payload?.msg,
    payload?.detail,
    payload?.message,
    error instanceof Error ? error.message : undefined,
  ]
  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.trim()) return candidate
  }
  return fallback
}
