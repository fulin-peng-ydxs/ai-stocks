export const MASTER_DETAIL_PROFILE_MATCH_TOLERANCE = 0.15
export const MASTER_DETAIL_PROFILE_MERGE_TOLERANCE = 0.05

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
    if (width === undefined || width <= 0 || ratio === undefined || ratio < 30 || ratio > 70) return []
    return [{ width, ratio }]
  })
  return {
    profiles: [...new Map(profiles.map((profile) => [profile.width, profile])).values()]
      .sort((left, right) => left.width - right.width),
  }
}

function relativeDistance(currentWidth: number, profileWidth: number): number {
  return Math.abs(currentWidth - profileWidth) / profileWidth
}

export function closestMasterDetailRatioProfile(
  value: unknown,
  currentWidth: number,
  tolerance = MASTER_DETAIL_PROFILE_MATCH_TOLERANCE,
): MasterDetailRatioProfile | undefined {
  if (!Number.isFinite(currentWidth) || currentWidth <= 0) return undefined
  return normalizeMasterDetailRatioProfiles(value).profiles
    .map((profile) => ({ profile, distance: relativeDistance(currentWidth, profile.width) }))
    .filter((candidate) => candidate.distance <= tolerance)
    .sort((left, right) => left.distance - right.distance || left.profile.width - right.profile.width)[0]?.profile
}

export function upsertMasterDetailRatioProfile(
  value: unknown,
  sample: MasterDetailRatioSample,
): MasterDetailRatioProfilesConfig {
  const normalized = normalizeMasterDetailRatioProfiles(value)
  const width = finiteRounded(sample.width)
  const ratio = finiteRounded(sample.ratio)
  if (width === undefined || width <= 0 || ratio === undefined || ratio < 30 || ratio > 70) return normalized
  const nearest = normalized.profiles
    .map((profile, index) => ({ index, distance: relativeDistance(width, profile.width) }))
    .sort((left, right) => left.distance - right.distance)[0]
  const profiles = [...normalized.profiles]
  if (nearest && nearest.distance <= MASTER_DETAIL_PROFILE_MERGE_TOLERANCE) {
    profiles.splice(nearest.index, 1, { width, ratio })
  } else {
    profiles.push({ width, ratio })
  }
  return { profiles: profiles.sort((left, right) => left.width - right.width) }
}
