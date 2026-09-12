import {
  closestSizeProfile,
  SIZE_PROFILE_MATCH_TOLERANCE,
  SIZE_PROFILE_MERGE_TOLERANCE,
  sizeProfileDistance,
  sizeProfileWithinTolerance,
  type SizeProfileDimensions,
} from './sizeProfileMatching'

export const STOCK_CHART_RATIO_PROFILE_LIMIT = 50

export interface StockChartRatioProfile extends Required<SizeProfileDimensions> {
  ratios: number[]
}

export interface StockChartRatioSample extends StockChartRatioProfile {}

function normalizeRatios(value: unknown, length: number): number[] | undefined {
  if (!Array.isArray(value) || value.length !== length) return undefined
  if (!value.every((item) => typeof item === 'number' && Number.isFinite(item) && item > 0)) {
    return undefined
  }
  const total = value.reduce((sum, item) => sum + item, 0)
  if (Math.abs(total - 1) > 1e-6) return undefined
  return value.map((item) => item / total)
}

function normalizeDimension(value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return undefined
  return Math.round(value)
}

/** 过滤旧数据和非法项，并按尺寸去重，保证档案集合有界且可稳定匹配。 */
export function normalizeStockChartRatioProfiles(
  value: unknown,
  ratioLength: number,
): StockChartRatioProfile[] {
  if (!Array.isArray(value)) return []
  const profiles = value.flatMap((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return []
    const raw = item as Record<string, unknown>
    const width = normalizeDimension(raw.width)
    const height = normalizeDimension(raw.height)
    const ratios = normalizeRatios(raw.ratios, ratioLength)
    return width && height && ratios ? [{ width, height, ratios }] : []
  })
  return [...new Map(profiles.map((profile) => [`${profile.width}:${profile.height}`, profile])).values()]
    .sort((left, right) => left.width - right.width || left.height - right.height)
    .slice(-STOCK_CHART_RATIO_PROFILE_LIMIT)
}

export function closestStockChartRatioProfile(
  value: unknown,
  current: SizeProfileDimensions,
  ratioLength: number,
): StockChartRatioProfile | undefined {
  return closestSizeProfile(
    normalizeStockChartRatioProfiles(value, ratioLength),
    current,
    SIZE_PROFILE_MATCH_TOLERANCE,
  )
}

export function upsertStockChartRatioProfile(
  value: unknown,
  sample: StockChartRatioSample,
): StockChartRatioProfile[] {
  const ratios = normalizeRatios(sample.ratios, sample.ratios.length)
  const width = normalizeDimension(sample.width)
  const height = normalizeDimension(sample.height)
  const normalized = normalizeStockChartRatioProfiles(value, sample.ratios.length)
  if (!width || !height || !ratios) return normalized

  const next = { width, height, ratios }
  const nearest = normalized
    .map((profile, index) => ({ index, distance: sizeProfileDistance(next, profile) }))
    .filter(({ index }) => (
      sizeProfileWithinTolerance(next, normalized[index], SIZE_PROFILE_MERGE_TOLERANCE)
    ))
    .sort((left, right) => left.distance - right.distance)[0]
  const profiles = [...normalized]
  if (nearest) {
    profiles.splice(nearest.index, 1, next)
  } else {
    profiles.push(next)
  }
  return profiles
    .sort((left, right) => left.width - right.width || left.height - right.height)
    .slice(-STOCK_CHART_RATIO_PROFILE_LIMIT)
}
