export const DEFAULT_E2E_API_URL: string

export function e2eBackendHealthUrl(apiUrl?: string): string

export function requireE2EBackendHealth(body: unknown): string
