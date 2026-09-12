import {
  closestSizeProfile,
  SIZE_PROFILE_MATCH_TOLERANCE,
  SIZE_PROFILE_MERGE_TOLERANCE,
  sizeProfileDistance,
  sizeProfileWithinTolerance,
} from './sizeProfileMatching'

export interface DisplayScaleProfile {
  width: number
  height: number
  percent: number
}

export const DISPLAY_SCALE_PROFILE_LIMIT = 50

function finiteRounded(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? Math.round(value) : undefined
}

export function normalizeDisplayScaleProfiles(value: unknown): DisplayScaleProfile[] {
  if (!Array.isArray(value)) return []
  const profiles = value.flatMap((item) => {
    if (!item || typeof item !== 'object') return []
    const width = finiteRounded((item as { width?: unknown }).width)
    const height = finiteRounded((item as { height?: unknown }).height)
    const percent = finiteRounded((item as { percent?: unknown }).percent)
    if (width === undefined || width <= 0 || height === undefined || height <= 0) return []
    if (percent === undefined || percent < 50 || percent > 150) return []
    return [{ width, height, percent }]
  })
  return [...new Map(profiles.map((profile) => [`${profile.width}:${profile.height}`, profile])).values()]
    .sort((left, right) => left.width - right.width || left.height - right.height)
    .slice(0, DISPLAY_SCALE_PROFILE_LIMIT)
}

export function closestDisplayScaleProfile(
  profiles: unknown,
  area: { width: number; height: number },
): DisplayScaleProfile | undefined {
  return closestSizeProfile(normalizeDisplayScaleProfiles(profiles), area, SIZE_PROFILE_MATCH_TOLERANCE)
}

export function upsertDisplayScaleProfile(
  profiles: unknown,
  sample: DisplayScaleProfile,
): DisplayScaleProfile[] {
  const normalized = normalizeDisplayScaleProfiles(profiles)
  const width = finiteRounded(sample.width)
  const height = finiteRounded(sample.height)
  const percent = finiteRounded(sample.percent)
  if (width === undefined || width <= 0 || height === undefined || height <= 0) return normalized
  if (percent === undefined || percent < 50 || percent > 150) return normalized

  const current = { width, height }
  const nearest = normalized
    .map((profile, index) => ({ index, distance: sizeProfileDistance(current, profile) }))
    .filter(({ index }) => (
      sizeProfileWithinTolerance(current, normalized[index], SIZE_PROFILE_MERGE_TOLERANCE)
    ))
    .sort((left, right) => left.distance - right.distance)[0]
  const next = [...normalized]
  if (nearest) next.splice(nearest.index, 1, { width, height, percent })
  else next.push({ width, height, percent })
  return next
    .sort((left, right) => left.width - right.width || left.height - right.height)
    .slice(-DISPLAY_SCALE_PROFILE_LIMIT)
}
