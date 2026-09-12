export const SIZE_PROFILE_MATCH_TOLERANCE = 0.15
export const SIZE_PROFILE_MERGE_TOLERANCE = 0.05

export interface SizeProfileDimensions {
  width: number
  height?: number
}

function relativeDistance(current: number, saved: number): number {
  return Math.abs(current - saved) / saved
}

export function sizeProfileDistance(
  current: SizeProfileDimensions,
  saved: SizeProfileDimensions,
): number {
  const distances = [relativeDistance(current.width, saved.width)]
  if (current.height !== undefined && saved.height !== undefined) {
    distances.push(relativeDistance(current.height, saved.height))
  }
  return Math.sqrt(distances.reduce((sum, value) => sum + value ** 2, 0) / distances.length)
}

export function sizeProfileWithinTolerance(
  current: SizeProfileDimensions,
  saved: SizeProfileDimensions,
  tolerance: number,
): boolean {
  if (relativeDistance(current.width, saved.width) > tolerance) return false
  return current.height === undefined
    || saved.height === undefined
    || relativeDistance(current.height, saved.height) <= tolerance
}

export function closestSizeProfile<T extends SizeProfileDimensions>(
  profiles: T[],
  current: SizeProfileDimensions,
  tolerance = SIZE_PROFILE_MATCH_TOLERANCE,
): T | undefined {
  if (!Number.isFinite(current.width) || current.width <= 0) return undefined
  if (current.height !== undefined && (!Number.isFinite(current.height) || current.height <= 0)) {
    return undefined
  }
  return profiles
    .map((profile) => ({ profile, distance: sizeProfileDistance(current, profile) }))
    .filter(({ profile }) => sizeProfileWithinTolerance(current, profile, tolerance))
    .sort((left, right) => (
      left.distance - right.distance
      || left.profile.width - right.profile.width
      || (left.profile.height ?? 0) - (right.profile.height ?? 0)
    ))[0]?.profile
}
