// 全局分页规范：默认页大小 + 可选页大小，凡有分页处统一引用，保证默认值全局一致。
export const DEFAULT_PAGE_SIZE = 20
export const PAGE_SIZE_OPTIONS = [20, 50, 100, 200]
export const MIN_PAGE_SIZE = 10
export const MAX_PAGE_SIZE = Math.max(...PAGE_SIZE_OPTIONS)

/** 兼容历史配置并守住接口分页边界；合法区间内的页面专属值保持不变。 */
export function normalizePageSize(value: unknown, fallback = DEFAULT_PAGE_SIZE): number {
  const fallbackNumber = Number(fallback)
  const safeFallback = Number.isFinite(fallbackNumber)
    ? Math.max(MIN_PAGE_SIZE, Math.min(MAX_PAGE_SIZE, Math.trunc(fallbackNumber)))
    : DEFAULT_PAGE_SIZE
  if (value == null || typeof value === 'boolean' || (typeof value === 'string' && !value.trim())) {
    return safeFallback
  }
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return safeFallback
  return Math.max(MIN_PAGE_SIZE, Math.min(MAX_PAGE_SIZE, Math.trunc(numeric)))
}
