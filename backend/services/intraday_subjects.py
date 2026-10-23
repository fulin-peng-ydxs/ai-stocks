"""股票与市场指数共用分时流程；类型、交易时点和来源策略在这里区分。"""

from backend.services.market_benchmark import BENCHMARK_NAMES

# 同花顺指数使用独立标识，不能把沪市 000xxx 当作深市同号股票。
THS_INDEX_SYMBOLS = {
    "000001.SH": "1A0001",
    "000300.SH": "1B0300",
    "000905.SH": "1B0905",
    "000688.SH": "1B0688",
    "399001.SZ": "399001",
    "399006.SZ": "399006",
}


def is_index(code: str | None) -> bool:
    # 这里只判别代码类型；是否启用由任务入口的配置清单校验，避免逐分钟访问 PG 配置。
    return bool(
        code
        and (
            code in BENCHMARK_NAMES
            or (code.endswith(".SH") and code.startswith("000"))
            or (code.endswith(".SZ") and code.startswith("399"))
        )
    )


def providers_for(code: str | None, allow_fallback: bool = False) -> tuple[str, ...]:
    if is_index(code):
        return ("ths", "sina", "eastmoney") if allow_fallback else ("ths",)
    return ("sina", "ths", "eastmoney") if allow_fallback else ("sina",)
