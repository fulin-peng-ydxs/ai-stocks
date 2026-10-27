import { spawnSync } from 'node:child_process'
import { frontendRoot } from './design-source.mjs'

// 构建、普通测试与 CI 共同使用，门禁只扫描本地源码，不连接后端或改动数据库。
for (const name of ['typography', 'css-variables', 'table-headers', 'settings-structure', 'close-controls', 'tooltips', 'scrollbars', 'borders', 'control-rows', 'contracts']) {
  const scripts = { tooltips: 'tooltip-contract', contracts: 'design-contracts' }
  const result = spawnSync(process.execPath, [`scripts/check-${scripts[name] ?? name}.mjs`], {
    cwd: frontendRoot, stdio: 'inherit',
  })
  if (result.error) throw result.error
  if (result.status !== 0) process.exit(result.status ?? 1)
}
