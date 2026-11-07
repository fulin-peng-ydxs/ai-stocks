import { readFileSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import postcss from 'postcss'
import { designSources, frontendRoot, sourceParts } from './design-source.mjs'

const START = '<!-- responsive-components:start -->'
const END = '<!-- responsive-components:end -->'
const TABLE = '| 文件 | 查询原文（去重） | 行为 / 恢复入口 | 直接消费方 |\n|---|---|---|---|'
const PENDING = '待补充'
const normalize = value => value.replace(/\s+/g, ' ').trim()

/** 只读取真实 style 块，避免注释、脚本字符串中的查询被登记为响应式规则。 */
export function responsiveQueries(file, source) {
  const queries = new Set()
  for (const style of sourceParts(file, source).styles) {
    postcss.parse(style.content, { from: file }).walkAtRules(/^(container|media)$/, rule => {
      queries.add(normalize(`@${rule.name} ${rule.params}`))
    })
  }
  return [...queries]
}

/** 自动字段来自源码，人工语义原样保留；新增项保留待补充状态，不能伪造适配结论。 */
export function syncResponsiveInventory(document, sources) {
  if (document.split(START).length !== 2 || document.split(END).length !== 2
      || document.indexOf(START) > document.indexOf(END)) {
    throw new Error('响应式清单必须有唯一且有序的 start/end marker')
  }
  const begin = document.indexOf(START) + START.length
  const end = document.indexOf(END)
  const entries = new Map()
  const lines = document.slice(begin, end).trim().split('\n')
  if (lines.slice(0, 2).join('\n') !== TABLE) throw new Error('响应式清单缺少四列表头')
  for (const line of lines.slice(2).filter(line => line.trim())) {
    const row = line.match(/^\| `([^`]+)` \| (.*?) \| (.*?) \| (.*?) \|$/)
    if (!row || entries.has(row[1])) throw new Error(`响应式清单行格式错误或重复：${line}`)
    entries.set(row[1], { behavior: row[3], consumers: row[4] })
  }
  const production = new Map(sources.filter(item => item.file.endsWith('.vue'))
    .map(item => [`frontend/src/${item.file}`, item]))
  if (!production.size) throw new Error('未找到生产 Vue 文件，拒绝清空响应式清单')
  // 保持已有人工阅读顺序，只将新增文件按路径追加；删除文件不再保留假登记。
  const paths = [...entries.keys()].filter(path => production.has(path))
  paths.push(...[...production.keys()].filter(path => !entries.has(path)).sort())
  const violations = []
  const rows = paths.map(path => {
    const { file, source } = production.get(path)
    const queries = responsiveQueries(file, source)
      .map(query => `\`${query.replaceAll('|', '\\|')}\``).join('<br>') || '无自身 CSS 查询'
    const { behavior, consumers } = entries.get(path) ?? {
      behavior: `${PENDING}适配行为与恢复入口`, consumers: `${PENDING}消费方`,
    }
    if (!behavior.trim() || !consumers.trim() || behavior.includes(PENDING) || consumers.includes(PENDING)) {
      violations.push(`${path}：补充适配行为、恢复入口与消费方后再交付`)
    }
    return `| \`${path}\` | ${queries} | ${behavior} | ${consumers} |`
  })
  const updated = document.slice(0, begin) + `\n\n${TABLE}\n` + rows.join('\n') + '\n\n' + document.slice(end)
  if (updated !== document) violations.unshift('响应式自动字段与源码不一致：运行 npm run docs:responsive')
  return { document: updated, violations }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const args = process.argv.slice(2)
  if (args.some(arg => arg !== '--write') || args.length > 1) throw new Error('仅支持 --write')
  const path = join(frontendRoot, '../agent-works/configurable-layout-system/responsive-components.md')
  const sources = designSources()
  const result = syncResponsiveInventory(readFileSync(path, 'utf8'), sources)
  if (args.includes('--write')) writeFileSync(path, result.document)
  const violations = args.includes('--write')
    ? syncResponsiveInventory(result.document, sources).violations : result.violations
  if (violations.length) {
    console.error(violations.join('\n'))
    process.exitCode = 1
  } else console.log('响应式清单与源码一致，人工行为与消费方说明齐全；不代表浏览器验收通过。')
}
