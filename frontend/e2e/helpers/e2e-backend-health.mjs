export const DEFAULT_E2E_API_URL = 'http://127.0.0.1:8000/api'

export function e2eBackendHealthUrl(apiUrl = DEFAULT_E2E_API_URL) {
  const healthUrl = `${apiUrl.replace(/\/+$/, '')}/health/e2e`
  new URL(healthUrl)
  return healthUrl
}

export function requireE2EBackendHealth(body) {
  if (!body || typeof body !== 'object' || body.code !== 0) {
    const reason = typeof body?.msg === 'string' && body.msg
      ? body.msg
      : `业务码 ${String(body?.code)}`
    throw new Error(`后端未按 E2E 写模式启动：${reason}`)
  }

  const pgFingerprint = body.data?.pgFingerprint
  if (typeof pgFingerprint !== 'string' || !/^[a-f0-9]{64}$/.test(pgFingerprint)) {
    throw new Error('后端 E2E 健康检查响应缺少合法 PostgreSQL 指纹')
  }
  return pgFingerprint
}
