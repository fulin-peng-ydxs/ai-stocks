import { describe, expect, it } from 'vitest'
import { auditDateTimeConsumers as dates, auditHeadings as headings, auditPrimaryActions as actions, auditSpacingMotion as styles } from '../../../scripts/check-design-consistency.mjs'

const sample = (source: string) => [{file:'views/Probe.vue',source}]
const button = '<el-button type="primary"/>'

describe('门禁解析回归：区分非法消费与合法近邻', () => {
  it.each([
    `<template>${button}<div v-for="x in xs">${button}</div></template>`,
    `<script setup>import Command from 'element-plus/es/components/button/index'</script><template><Command type="primary"/>${button}</template>`,
    `<template><el-button v-bind="{type:'primary'}"/>${button}</template>`,
    `<script setup>const kind='primary';function other(){const kind='info'}</script><template><el-button :type="kind"/>${button}</template>`,
  ])('识别循环、别名、批量绑定与词法作用域：%s', source => {
    expect(actions(sample(source))).not.toEqual([])
  })
  it('数字和字符串的严格比较是互斥状态', () => {
    expect(actions(sample(`<template><el-button v-if="mode===1" type="primary"/><el-button v-if="mode==='1'" type="primary"/></template>`))).toEqual([])
  })
  it('标题检查输出文本，不把被替换的参数当成标题，也不豁免整个 muted 区域', () => {
    expect(headings(sample(`<script setup>const label='标题'</script><template><h3>{{ label.replace('(旧)', '') }}</h3></template>`))).toEqual([])
    expect(headings(sample('<template><h3><span class="muted">标题（说明）</span></h3></template>'))).not.toEqual([])
  })
  it('样式检查函数返回、大小写单位和 v-bind，保留最终覆盖顺序', () => {
    for (const source of [
      `<script setup>function fieldStyle(){return {padding:'7px'}}</script><template><div :style="fieldStyle()"/></template>`,
      '<template><div style="padding:7PX;transition:opacity 333MS"/></template>',
      `<template><div v-bind="{style:{padding:'7px'}}"/></template>`,
    ]) expect(styles(sample(source))).not.toEqual([])
    expect(styles(sample(`<template><div :style="[{padding:'7px'},{padding:'8px'}]"/></template>`))).toEqual([])
    expect(styles(sample(`<template><div class="a"/><div class="b"/></template><style>.a{--spacing:7px;width:var(--spacing)}.b{--spacing:8px;padding:var(--spacing)}</style>`))).toEqual([])
    expect(styles(sample(`<script setup>const description='参数示例 padding:7px，不是样式'</script>`))).toEqual([])
  })
  it('日期识别导入身份与每个输出分支，数组截取仍合法', () => {
    expect(dates(sample(`<template><span>{{ items.slice(0,10).join(',') }}</span></template>`))).toEqual([])
    expect(dates(sample(`<script setup>import {formatDateTimeSeconds as seconds} from '@/utils/dateTime'</script><template><span>{{ seconds(row.created_at) }}</span></template>`))).toEqual([])
    expect(dates(sample(`<script setup>const formatDateTimeSeconds=(x:string)=>x</script><template><span>{{ formatDateTimeSeconds(row.created_at) }}</span></template>`))).not.toEqual([])
    expect(dates(sample(`<script setup>import {formatDateOnly} from '@/utils/dateTime'</script><template><span>{{ formatDateOnly(row.created_at) + row.updated_at }}</span></template>`))).not.toEqual([])
    expect(dates(sample(`<template><span v-text="row.observed_at"/><AppTableColumn prop="created_at"/></template>`))).toHaveLength(2)
  })
})

it('CSS 同选择器分离声明与嵌套 fallback 继续检查，合法别名不串作用域', () => {
  expect(styles(sample('<template><div/></template><style>.a{--space:7px}.a{padding:var(--space)}</style>'))).not.toEqual([])
  expect(styles(sample('<template><div/></template><style>.a{padding:var(--unknown,var(--unknown2,7px))}</style>'))).not.toEqual([])
  expect(styles(sample('<template><div/></template><style>.a{padding:07PX;animation:spin var(--app-motion-spin) ease}</style>'))).toHaveLength(2)
})

it('动态组件、属性覆盖和复合条件按最终值判断', () => {
  expect(actions(sample(`<script setup>const componentName='el-button'</script><template><component :is="componentName" type="primary"/>${button}</template>`))).not.toEqual([])
  expect(actions(sample(`<template><el-button type="primary" :plain="true" v-bind="{plain:false}"/>${button}</template>`))).not.toEqual([])
  expect(actions(sample(`<script setup>const show=computed(()=>ready)</script><template><div v-if="!form.show">${button}</div><div v-if="show">${button}</div></template>`))).not.toEqual([])
})

it('日期检查 computed 与字符串转换，公共命名空间及业务包装器保持合法', () => {
  expect(dates(sample(`<script setup>import {computed} from 'vue';const label=computed(()=>row.checked_at)</script><template><span>{{ label }}</span></template>`))).not.toEqual([])
  expect(dates(sample(`<template><span>{{ String(row.created_at) }}</span></template>`))).not.toEqual([])
  expect(dates(sample(`<script setup>import {formatDateOnly} from 'fake/dateTime'</script><template><span>{{ formatDateOnly(row.created_at) }}</span></template>`))).not.toEqual([])
  expect(dates(sample(`<script setup>import * as dates from '@/utils/dateTime'</script><template><span>{{ dates.formatDateOnly(row.created_at) }}</span></template>`))).toEqual([])
  const business = {file:'utils/businessTime.ts',source:`import {formatDateTimeSeconds as seconds} from './dateTime';export function formatBusinessTime(value:string){return seconds(value)}`}
  expect(dates([...sample(`<script setup>import {formatBusinessTime as display} from '@/utils/businessTime'</script><template><span>{{ display(row.created_at) }}</span></template>`),business])).toEqual([])
  expect(dates([...sample(`<script setup>import {formatBusinessTime as display} from '@/utils/businessTime'</script><template><span>{{ display(row.created_at) }}</span></template>`),{...business,source:business.source.replace('seconds(value)','value.slice(0,19)')}])).not.toEqual([])
})
