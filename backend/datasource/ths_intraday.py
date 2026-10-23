"""同花顺年度 1 分钟原始行情；年度路径只表示请求年份，不保证覆盖全年。"""

from __future__ import annotations

import json
import re

import pandas as pd
import requests


def fetch_ths_minutes(code: str, year: int, *, timeout: float) -> pd.DataFrame:
    """读取完整年度响应，避免 last10000 把首日截断；不补造缺失量价。"""
    code6 = code.split(".")[0]
    if not re.fullmatch(r"\d{6}", code6):
        raise ValueError("同花顺分钟请求须使用六位股票代码")
    from backend.services.intraday_subjects import THS_INDEX_SYMBOLS, is_index

    if is_index(code):
        if code not in THS_INDEX_SYMBOLS:
            raise ValueError(f"同花顺尚未登记该指数的分钟标识：{code}")
        code6 = THS_INDEX_SYMBOLS[code]
    callback = f"quotebridge_v6_line_hs_{code6}_60_{year}"
    response = requests.get(
        f"https://d.10jqka.com.cn/v6/line/hs_{code6}/60/{year}.js",
        timeout=timeout,
        # 部分标的对缺少浏览器标识/股票页来源的请求返回空 404，不能据此判定无数据。
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": f"https://stockpage.10jqka.com.cn/{code6}/",
        },
    )
    response.raise_for_status()
    match = re.fullmatch(re.escape(callback) + r"\((.*)\);?", response.text.strip(), re.S)
    if match is None:
        raise ValueError("同花顺分钟响应标的、周期或年份与请求不符")
    payload = json.loads(match[1])
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), str):
        raise ValueError("同花顺分钟响应缺少 data 字段")
    rows = []
    for record in payload["data"].split(";"):
        if not record:
            continue
        fields = record.split(",")
        if len(fields) < 7 or not re.fullmatch(r"\d{12}", fields[0]):
            raise ValueError("同花顺分钟记录格式异常")
        if int(fields[0][:4]) != year:
            raise ValueError("同花顺分钟记录超出请求年份")
        rows.append(fields[:7])
    # 实测原始顺序为时间、开高低收、股、元；统一成交量为手，保留小数手。
    frame = pd.DataFrame(rows, columns=[
        "timestamp", "open", "high", "low", "close", "volume", "amount",
    ])
    frame["timestamp"] = pd.to_datetime(frame.timestamp, format="%Y%m%d%H%M", errors="coerce")
    for field in frame.columns[1:]:
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    frame["volume"] /= 100
    frame.attrs["request_years"] = [year]
    return frame
