import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const ROOT = resolve(import.meta.dirname, '../..')

function source(path: string): string {
  return readFileSync(resolve(ROOT, path), 'utf8')
}

describe('全站金额格式消费契约', () => {
  it.each([
    'views/BacktestView.vue',
    'views/TrainingView.vue',
    'utils/sectorCompare.ts',
    'views/SectorDetailView.vue',
    'views/StocksView.vue',
    'components/EquityChart.vue',
    'components/SectorCompareChart.vue',
    'components/stock-chart/chartUtils.ts',
    'views/StockDetailView.vue',
    'views/trade-discipline/components/TradeRuleEditor.vue',
    'views/trade-discipline/components/TradeOperationEditor.vue',
    'views/trade-discipline/components/TradeCheckinRevisionDrawer.vue',
  ])('%s 的金额展示消费统一工具', (path) => {
    expect(source(path)).toContain("@/utils/money")
  })

  it('页面不得重新声明 money/wan 私有格式化器或使用金额本地化捷径', () => {
    const pages = [
      source('views/BacktestView.vue'),
      source('views/TrainingView.vue'),
      source('utils/sectorCompare.ts'),
      source('views/SectorDetailView.vue'),
      source('views/StocksView.vue'),
    ].join('\n')
    expect(pages).not.toMatch(/\b(?:const|function)\s+(?:money|wan)\b/)
    expect(pages).not.toMatch(/(?:amount|capital|cash|equity|fee|pnl|price|inflow)[^\n]{0,80}toLocaleString/i)
  })
})
