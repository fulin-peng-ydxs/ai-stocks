import { formatMoney, type MoneyValue } from '@/utils/money'

/** 交易纪律 NUMERIC 价格契约支持四位；行情价格仍由普通 price 规则展示两位。 */
export const TRADE_PRICE_DIGITS = 4
export function formatTradePrice(value: MoneyValue): string {
  return formatMoney(value, { digits: TRADE_PRICE_DIGITS })
}
