import { DEFAULT_E2E_API_URL } from '../e2e/helpers/e2e-backend-health.mjs'

const allowedEnvironments = new Set(['dev', 'test', 'local'])
const environment = process.env.AI_STOCKS_ENV
const writeEnabled = process.env.AI_STOCKS_E2E_WRITE === '1'
const apiUrl = (process.env.E2E_API_URL || DEFAULT_E2E_API_URL).replace(/\/+$/, '')

if (!environment || !allowedEnvironments.has(environment) || !writeEnabled) {
  console.error(
    '完整设计验收要求显式设置本地测试环境：'
    + 'AI_STOCKS_ENV=dev|test|local AI_STOCKS_E2E_WRITE=1 npm run test:design',
  )
  process.exit(1)
}

if (apiUrl !== DEFAULT_E2E_API_URL) {
  console.error(
    `完整设计验收会管理本地后端，仅允许 E2E_API_URL=${DEFAULT_E2E_API_URL}`,
  )
  process.exit(1)
}

console.log(
  `设计验收安全环境检查通过：${apiUrl}；后端运行态由 E2E runner 受控管理`,
)
