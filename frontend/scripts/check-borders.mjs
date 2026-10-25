import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse } from '@vue/compiler-sfc'
import { inspectBorderStyles, inspectStockChartBoundaries } from './border-contract.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src')
function files(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    if (entry.name === '__tests__') return []
    const path = join(dir, entry.name)
    return entry.isDirectory() ? files(path) : [path]
  })
}
const findings = []
for (const file of files(root)) {
  if (!file.endsWith('.vue') && !file.endsWith('.css')) continue
  const name = relative(root, file)
  const source = readFileSync(file, 'utf8')
  const descriptor = file.endsWith('.vue') ? parse(source).descriptor : undefined
  if (descriptor?.template) {
    for (const finding of inspectStockChartBoundaries(descriptor.template.content)) {
      findings.push(`${name}:${descriptor.template.loc.start.line + finding.line - 1} ${finding.message}`)
    }
  }
  const styles = descriptor ? descriptor.styles
    : file.endsWith('.css') ? [{ content: source, loc: { start: { line: 1 } } }] : []
  // 共享角色常量是唯一可以定义普通形态值的位置。
  for (const style of styles) {
    for (const finding of inspectBorderStyles(style.content, name)) {
      findings.push(`${name}:${style.loc.start.line + finding.line - 1} ${finding.message}`)
    }
  }
}
if (findings.length) {
  console.error(`边界角色检查失败：\n${findings.join('\n')}`)
  process.exitCode = 1
} else console.log('边界角色检查通过。')
