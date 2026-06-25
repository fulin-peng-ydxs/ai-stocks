#!/usr/bin/env node
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = resolve(root, '..')

const ARCHETYPES = new Set(['list', 'master-detail', 'dashboard', 'form', 'detail', 'workbench', 'wizard'])
const DEFAULT_SLOTS = {
  list: [
    ['filter', 'filter-bar', 'action'],
    ['table', 'data-table', 'main', 'grow'],
  ],
  'master-detail': [
    ['toolbar', 'filter-bar', 'action'],
    ['list', 'data-table', 'main'],
    ['detail', 'detail', 'main'],
  ],
  dashboard: [
    ['kpi', 'kpi-grid', 'main'],
    ['chart', 'chart', 'main'],
  ],
  form: [['form', 'form', 'main']],
  detail: [['detail', 'detail', 'main']],
  workbench: [
    ['toolbar', 'toolbar', 'action'],
    ['body', 'section', 'main'],
  ],
  wizard: [['steps', 'steps', 'main']],
}

function parseArgs(argv) {
  const out = {}
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (!arg.startsWith('--')) continue
    const key = arg.slice(2)
    if (key === 'dry-run' || key === 'help') out[key] = true
    else out[key] = argv[++i]
  }
  return out
}

function usage() {
  return `Usage:
  npm run scaffold-page -- --pageKey research --label "研究页" --archetype list --route /research --view ResearchView

Options:
  --pageKey     Registry key, kebab-case recommended. Required.
  --label       Menu/page label. Required.
  --archetype   One of: ${[...ARCHETYPES].join(', ')}. Required.
  --route       Vue route path. Defaults to /<pageKey>.
  --view        View component name without .vue. Defaults to PascalCase(pageKey) + View.
  --slots       CSV id:component:region[:grow], for example filter:filter-bar:action,table:data-table:main:grow.
  --dry-run     Print planned files without writing.
`
}

function pascalCase(value) {
  return value.split(/[-_:]+/).filter(Boolean).map((part) => part[0].toUpperCase() + part.slice(1)).join('')
}

function parseSlots(archetype, raw) {
  const rows = raw
    ? raw.split(',').map((item) => item.split(':').map((part) => part.trim()))
    : DEFAULT_SLOTS[archetype]
  return rows.map(([id, component, region, flag], index) => {
    if (!id || !component || !region) throw new Error(`Invalid slot spec: ${[id, component, region, flag].filter(Boolean).join(':')}`)
    return { id, component, region, grow: flag === 'grow', order: index + 1 }
  })
}

function slotLine(slot) {
  const grow = slot.grow ? ', growMain: true' : ''
  return `        { id: '${slot.id}', component: '${slot.component}', region: '${slot.region}'${grow}, order: ${slot.order} },`
}

function responsiveProfile(archetype) {
  if (archetype === 'dashboard') return 'safe-reflow'
  if (archetype === 'workbench' || archetype === 'master-detail') return 'mixed-panel'
  return 'single-column'
}

function hasAction(slots) {
  return slots.some((slot) => slot.region === 'action')
}

function viewTemplate({ pageKey, label, slots }) {
  const hasActionSlot = slots.some((slot) => slot.region === 'action')
  const mainSlots = slots.filter((slot) => slot.region === 'main')
  return `<script setup lang="ts">
import { ref } from 'vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'

const settingsOpen = ref(false)
const pageLayout = getPageLayout('${pageKey}')
const {
  effective,
  knobs: layoutKnobs,
  setKnob,
  valueOf,
  sourceOf,
  layerValuesOf,
  isDirty: layoutDirty,
  resetAll: resetLayout,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  componentLayerValuesOf,
} = useRemoteLayoutConfig(pageLayout)

const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, layerValuesOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, componentLayerValuesOf }
</script>

<template>
  <LayoutHost :layout="effective">
${hasActionSlot ? `    <template #action>
      <section class="page-toolbar">
        <h1>${label}</h1>
        <PageSettingsTrigger @click="settingsOpen = true" />
      </section>
    </template>` : ''}
${mainSlots.map((slot) => `    <template #${mainSlots.length === 1 ? 'main' : slot.id}>
      <section class="page-placeholder">${slot.id}</section>
    </template>`).join('\n')}
    <template #overlays>
      <PageSettingsDrawer
        v-model="settingsOpen"
        title="${label}设置"
        page-key="${pageKey}"
        :config="drawerConfig"
        :dirty="layoutDirty"
        @reset="resetLayout"
      />
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.page-toolbar h1 {
  margin: 0;
  font-size: 18px;
}
.page-placeholder {
  min-height: 0;
  height: 100%;
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: var(--el-text-color-secondary);
}
</style>
`
}

function registryEntry({ pageKey, label, route, archetype, slots }) {
  return `  {
    pageKey: '${pageKey}',
    label: '${label}',
    path: '${route}',
    archetype: '${archetype}',
    responsiveProfile: '${responsiveProfile(archetype)}',
    supportsComponentConfig: false,
    layout: {
      pageKey: '${pageKey}',
      archetype: '${archetype}',
      hasActionRegion: ${hasAction(slots)},
      density: 'standard',
      responsive: singleColumn(),
      slots: [
${slots.map(slotLine).join('\n')}
      ],
      editable: [densityKnob()],
    },
  },
`
}

function routeEntry({ route, pageKey, label, viewFile }) {
  return `  {
    path: '${route}',
    name: '${pageKey}',
    component: () => import('@/views/${viewFile}'),
    meta: { title: '${label}' },
  },
`
}

function designRow({ viewName, label, archetype, slots }) {
  const components = slots.map((slot) => `${slot.region}:${slot.component}${slot.grow ? '(growMain)' : ''}`).join(' / ')
  return `| \`${viewName}\`（${label}，pageKey \`${slots.pageKey ?? ''}\`） | \`${archetype}\` | \`density\` 信息密度 | 组件清单：${components}；由 scaffold-page 生成骨架，需补业务内容并完成视口验证 |`
}

function insertBefore(text, marker, insert) {
  const index = text.indexOf(marker)
  if (index < 0) throw new Error(`Marker not found: ${marker}`)
  return `${text.slice(0, index)}${insert}${text.slice(index)}`
}

function main() {
  const args = parseArgs(process.argv.slice(2))
  if (args.help) {
    console.log(usage())
    return
  }
  const pageKey = args.pageKey
  const label = args.label
  const archetype = args.archetype
  if (!pageKey || !label || !ARCHETYPES.has(archetype)) throw new Error(usage())
  const route = args.route ?? `/${pageKey}`
  const viewName = args.view ?? `${pascalCase(pageKey)}View`
  const viewFile = `${viewName}.vue`
  const slots = parseSlots(archetype, args.slots)
  slots.pageKey = pageKey

  const files = {
    view: join(root, 'src/views', viewFile),
    registry: join(root, 'src/layout/pageRegistry.ts'),
    router: join(root, 'src/router/index.ts'),
    design: join(repoRoot, 'DESIGN.md'),
  }
  if (existsSync(files.view)) throw new Error(`View already exists: ${files.view}`)

  const plan = [
    `create ${files.view}`,
    `insert registry entry into ${files.registry}`,
    `insert route ${route} into ${files.router}`,
    `insert DESIGN.md §9 row`,
    `optional backend endpoint: create one under backend/api/ when this page needs server data`,
  ]
  if (args['dry-run']) {
    console.log(plan.join('\n'))
    return
  }

  writeFileSync(files.view, viewTemplate({ pageKey, label, slots }), 'utf-8')
  writeFileSync(
    files.registry,
    insertBefore(readFileSync(files.registry, 'utf-8'), ']\n\n// P13 overlay', registryEntry({ pageKey, label, route, archetype, slots })),
    'utf-8',
  )
  writeFileSync(
    files.router,
    insertBefore(readFileSync(files.router, 'utf-8'), '  // 兜底：未匹配路径', routeEntry({ route, pageKey, label, viewFile })),
    'utf-8',
  )
  writeFileSync(
    files.design,
    insertBefore(readFileSync(files.design, 'utf-8'), '\n> **存量页面迁移', `${designRow({ viewName, label, archetype, slots })}\n`),
    'utf-8',
  )
  console.log(plan.join('\n'))
}

main()
