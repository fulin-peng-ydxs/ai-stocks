export function normalizeAllSelectedFilter(
  value: string[] | string,
  allowedValues: readonly string[],
): string[] {
  const requested = new Set(Array.isArray(value) ? value : [value])
  const selected = allowedValues.filter((item) => requested.has(item))
  return selected.length === 0 || selected.length === allowedValues.length
    ? [...allowedValues]
    : selected
}

export function isAllSelectedFilter(
  value: readonly string[],
  allowedValues: readonly string[],
): boolean {
  if (value.length !== allowedValues.length) return false
  const selected = new Set(value)
  return allowedValues.every((item) => selected.has(item))
}
