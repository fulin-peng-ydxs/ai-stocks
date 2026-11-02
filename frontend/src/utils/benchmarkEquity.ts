import { getSectorBenchmarkBars, type SectorBar } from '@/api/sectors'

export interface BenchmarkEquity {
  code: string
  name: string
  equity: (number | null)[]
}

/** 把指数 bars 归一成资金净值曲线（与回测引擎 init_cap × close/基准 同口径）；无有效基准收盘返回全 null。 */
export function normalizeBenchmarkEquity(bars: SectorBar[], initCap: number): (number | null)[] {
  const base = bars.find((b) => Number.isFinite(b.close) && b.close !== 0)?.close
  if (base == null || base === 0) return bars.map(() => null)
  return bars.map((b) =>
    Number.isFinite(b.close) && b.close !== 0 ? initCap * (b.close / base) : null,
  )
}

/** 拉取所选指数区间行情并归一成净值曲线；code 为空 / 接口失败 / 无行情时返回 null（父页回退默认基准线）。 */
export async function fetchBenchmarkEquity(
  code: string,
  start: string,
  end: string,
  initCap: number,
): Promise<BenchmarkEquity | null> {
  if (!code) return null
  try {
    const res = await getSectorBenchmarkBars(code, start, end)
    if (!res.list.length) return null
    return { code: res.index_code, name: res.name, equity: normalizeBenchmarkEquity(res.list, initCap) }
  } catch {
    return null
  }
}
