import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

// 补丁必须与安装版本和声明版本同时一致；禁止升级时沿用旧补丁后仅留下警告。
const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const manifest = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))
for (const file of readdirSync(join(root, 'patches'))) {
  if (!file.endsWith('.patch')) continue
  const match = /^(?:(@[^+]+)\+)?([^+]+)\+([^+]+)\.patch$/.exec(file)
  if (!match) throw new Error(`不支持的依赖补丁名称：${file}`)
  const name = match[1] ? `${match[1]}/${match[2]}` : match[2]
  const expected = match[3]
  const installed = JSON.parse(readFileSync(join(root, 'node_modules', name, 'package.json'), 'utf8'))
  const declared = manifest.dependencies?.[name] ?? manifest.devDependencies?.[name]
  const declaredVersion = declared?.match(/^npm:.+@([^@]+)$/)?.[1] ?? declared
  if (installed.version !== expected || declaredVersion !== expected) {
    throw new Error(`${name} 补丁版本 ${expected} 与声明 ${declared} / 安装 ${installed.version} 不一致`)
  }
}
