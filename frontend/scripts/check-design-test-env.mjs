import {
  DEFAULT_E2E_API_URL,
  e2eBackendHealthUrl,
  requireE2EBackendHealth,
} from '../e2e/helpers/e2e-backend-health.mjs'

const allowedEnvironments = new Set(['dev', 'test', 'local'])
const environment = process.env.AI_STOCKS_ENV
const writeEnabled = process.env.AI_STOCKS_E2E_WRITE === '1'
const apiUrl = process.env.E2E_API_URL || DEFAULT_E2E_API_URL

if (!environment || !allowedEnvironments.has(environment) || !writeEnabled) {
  console.error(
    '完整设计验收要求显式设置本地测试环境：'
    + 'AI_STOCKS_ENV=dev|test|local AI_STOCKS_E2E_WRITE=1 npm run test:design',
  )
  process.exit(1)
}

const restartGuide = [
  '请在仓库根目录重启后端并确认健康状态：',
  `AI_STOCKS_ENV=${environment} AI_STOCKS_E2E_WRITE=1 ./start.sh restart`,
  './start.sh status',
  '然后重新执行完整设计验收。',
].join('\n')

let healthUrl
try {
  healthUrl = e2eBackendHealthUrl(apiUrl)
} catch {
  console.error(`E2E_API_URL 非法：${apiUrl}\n${restartGuide}`)
  process.exit(1)
}

const controller = new AbortController()
const timeout = setTimeout(() => controller.abort(), 5_000)
let response

try {
  response = await fetch(healthUrl, {
    headers: { Accept: 'application/json' },
    signal: controller.signal,
  })
} catch (error) {
  const reason = error instanceof Error ? error.message : String(error)
  console.error(
    `无法访问后端 E2E 健康检查 ${healthUrl}：${reason}\n${restartGuide}`,
  )
  process.exit(1)
} finally {
  clearTimeout(timeout)
}

if (!response.ok) {
  console.error(
    `后端 E2E 健康检查请求失败：HTTP ${response.status} ${healthUrl}\n${restartGuide}`,
  )
  process.exit(1)
}

let body
try {
  body = await response.json()
} catch {
  console.error(`后端 E2E 健康检查未返回合法 JSON：${healthUrl}\n${restartGuide}`)
  process.exit(1)
}

try {
  requireE2EBackendHealth(body)
} catch (error) {
  const reason = error instanceof Error ? error.message : String(error)
  console.error(`${reason}\n${restartGuide}`)
  process.exit(1)
}

console.log(`设计验收环境检查通过：${healthUrl}`)
