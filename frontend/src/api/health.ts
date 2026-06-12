import http from './client'

export interface HealthData {
  status: string
  duckdb_ok: boolean
  duckdb: string
  history_years: number
  benchmark_main: string
  top_n: number
}

export function getHealth(): Promise<HealthData> {
  return http.get('/health')
}
