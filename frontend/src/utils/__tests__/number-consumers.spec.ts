import { describe, expect, it } from 'vitest'
// @ts-expect-error 本地静态门禁与 CLI 共用检查器
import { auditNumbers } from '../../../scripts/check-numbers.mjs'

describe('数值展示门禁', () => {
  it.each([
    '<script setup>const fmt = v => v.toFixed(2)</script>',
    '<template>{{ row.price.toFixed(2) }}</template>',
    '<template><el-input-number :precision="2" /></template>',
    '<script setup>const fmt = v => v.toLocaleString()</script>',
    '<script setup>const fmt = new Intl.NumberFormat()</script>',
    '<template>{{ (row.win_rate * 100) }}%</template>',
    '<script setup>const fmt = v => v.toPrecision(4)</script>',
    '<template>{{ row.n_trades ?? "—" }}</template>',
    '<template>{{ detail.n_rounds }}</template>',
    '<template>{{ rows.length - 3 }}</template>',
    '<template>{{ ready ? `共 ${row.stock_count} 只` : "等待" }}</template>',
    '<template><AppDetailField :value="row.peak_positions" /></template>',
    '<template><AppTableColumn prop="hold_days" /></template>',
    '<template><b class="down">{{ pct(detail.max_drawdown) }}</b></template>',
    '<template><span :class="{ pos: row.excess >= 0 }">{{ formatPercentPoints(row.excess, "ratio") }}</span></template>',
  ])('阻断分叉实现 %s', source => {
    expect(auditNumbers([{ file: 'views/Example.vue', source }]).length).toBeGreaterThan(0)
  })
  it('允许共享入口、输入换算和几何坐标；不允许借计算文件豁免私有展示', () => {
    expect(auditNumbers([{ file: 'views/Example.vue', source: '<script setup>const weight = raw * 100</script><template>{{ formatReturn(row.ret) }}</template>' }])).toEqual([])
    expect(auditNumbers([{ file: 'components/marketCompareChart.ts', source: 'const label = value.toFixed(2)' }]).length).toBeGreaterThan(0)
  })
  it.each([
    '<template><span v-if="row.count > 0">{{ formatNumber(row.count, "count") }}</span></template>',
    '<template>{{ rows.length > 0 ? "有记录" : "无记录" }}</template>',
    '<template>{{ row.count == 0 }} {{ !rows.length }}</template>',
    '<template><el-input-number v-model="form.max_positions" :max="rows.length" /></template>',
    '<template><AppDetailField :value="formatNumber(row.peak_positions, \'count\', { empty: \'未记录\' })" /></template>',
    '<template><AppTableColumn prop="hold_days"><template #default="{ row }">{{ formatNumber(row.hold_days, "count") }}</template></AppTableColumn></template>',
    '<template><b :class="marketValueClass(value, { input: \'ratio\' })">{{ formatReturn(value) }}</b></template>',
    '<template><span class="up">买入 {{ formatNumber(row.quantity, "quantity") }}</span></template>',
  ])('保留条件、编辑值和业务身份色的边界 %s', source => {
    expect(auditNumbers([{ file: 'views/Example.vue', source }])).toEqual([])
  })
})
