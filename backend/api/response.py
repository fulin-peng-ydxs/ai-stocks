"""统一响应封装（SDD §12：返回 {code, msg, data}）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    code: int = 0
    msg: str = "ok"
    data: Any = None


def ok(data: Any = None, msg: str = "ok") -> ApiResponse:
    return ApiResponse(code=0, msg=msg, data=data)


def err(code: int, msg: str, data: Any = None) -> ApiResponse:
    return ApiResponse(code=code, msg=msg, data=data)
