export const AUTO_SCALE_RESPONSIVE_EXPONENT_DEFAULT = 0.10
export const AUTO_SCALE_RESPONSIVE_EXPONENT_MIN = 0
export const AUTO_SCALE_RESPONSIVE_EXPONENT_MAX = 1

/** 系统配置缺项或缓存值非法时，统一回退到默认策略。 */
export function normalizeAutoScaleExponent(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value)
    && value >= AUTO_SCALE_RESPONSIVE_EXPONENT_MIN && value <= AUTO_SCALE_RESPONSIVE_EXPONENT_MAX
    ? value : AUTO_SCALE_RESPONSIVE_EXPONENT_DEFAULT
}
