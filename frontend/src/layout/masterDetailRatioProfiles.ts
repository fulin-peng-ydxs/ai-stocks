import {
  closestSizeProfile,
  SIZE_PROFILE_MATCH_TOLERANCE,
  SIZE_PROFILE_MERGE_TOLERANCE,
  sizeProfileDistance,
} from './sizeProfileMatching'

export const MASTER_DETAIL_PROFILE_MATCH_TOLERANCE = SIZE_PROFILE_MATCH_TOLERANCE
export const MASTER_DETAIL_PROFILE_MERGE_TOLERANCE = SIZE_PROFILE_MERGE_TOLERANCE
export const MASTER_DETAIL_RATIO_MIN = 30
export const MASTER_DETAIL_RATIO_MAX = 70
export const MASTER_DETAIL_RATIO_DEFAULT = 45

export interface MasterDetailRatioProfile {
  width: number
  ratio: number
}

export interface MasterDetailRatioProfilesConfig {
  profiles: MasterDetailRatioProfile[]
}

export interface MasterDetailRatioSample {
  width: number
  ratio: number
}

function finiteRounded(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? Math.round(value) : undefined
}

export function normalizeMasterDetailRatioProfiles(value: unknown): MasterDetailRatioProfilesConfig {
  const raw = value && typeof value === 'object' && Array.isArray((value as { profiles?: unknown }).profiles)
    ? (value as { profiles: unknown[] }).profiles
    : []
  const profiles = raw.flatMap((item) => {
    if (!item || typeof item !== 'object') return []
    const width = finiteRounded((item as { width?: unknown }).width)
    const ratio = finiteRounded((item as { ratio?: unknown }).ratio)
    if (
      width === undefined
      || width <= 0
      || ratio === undefined
      || ratio < MASTER_DETAIL_RATIO_MIN
      || ratio > MASTER_DETAIL_RATIO_MAX
    ) return []
    return [{ width, ratio }]
  })
  return {
    profiles: [...new Map(profiles.map((profile) => [profile.width, profile])).values()]
      .sort((left, right) => left.width - right.width),
  }
}

export function closestMasterDetailRatioProfile(
  value: unknown,
  currentWidth: number,
  tolerance = MASTER_DETAIL_PROFILE_MATCH_TOLERANCE,
): MasterDetailRatioProfile | undefined {
  if (!Number.isFinite(currentWidth) || currentWidth <= 0) return undefined
  return closestSizeProfile(
    normalizeMasterDetailRatioProfiles(value).profiles,
    { width: currentWidth },
    tolerance,
  )
}

export function upsertMasterDetailRatioProfile(
  value: unknown,
  sample: MasterDetailRatioSample,
): MasterDetailRatioProfilesConfig {
  const normalized = normalizeMasterDetailRatioProfiles(value)
  const width = finiteRounded(sample.width)
  const ratio = finiteRounded(sample.ratio)
  if (
    width === undefined
    || width <= 0
    || ratio === undefined
    || ratio < MASTER_DETAIL_RATIO_MIN
    || ratio > MASTER_DETAIL_RATIO_MAX
  ) return normalized
  const nearest = normalized.profiles
    .map((profile, index) => ({ index, distance: sizeProfileDistance({ width }, profile) }))
    .sort((left, right) => left.distance - right.distance)[0]
  const profiles = [...normalized.profiles]
  if (nearest && nearest.distance <= MASTER_DETAIL_PROFILE_MERGE_TOLERANCE) {
    profiles.splice(nearest.index, 1, { width, ratio })
  } else {
    profiles.push({ width, ratio })
  }
  return { profiles: profiles.sort((left, right) => left.width - right.width) }
}
