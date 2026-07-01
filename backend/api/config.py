"""配置读取 / 即时生效 API（T-M7-3，A-09 改参不改码）。

- GET  /api/config         查看当前全部配置（含派生路径）。
- POST /api/config/reload  改完 config/settings.yaml 后重载 → 即时生效（不重启服务）。

设计：采用"编辑 YAML + 重载"而非 Web 表单回写，**保留 settings.yaml 里成段的中文注释**
（注释是重要文档，程序化 dump 会丢失）。前端展示关键可调参数 + 一键重载。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.response import ApiResponse, ok
from backend.auth.deps import require_system
from backend.config import get_settings, reload_settings
from backend.config.settings import _config_path

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config", response_model=ApiResponse)
def get_config() -> ApiResponse:
    s = get_settings()
    return ok({"path": str(_config_path()), "config": s.model_dump()})


@router.post("/config/reload", response_model=ApiResponse, dependencies=[Depends(require_system)])
def reload_config() -> ApiResponse:
    s = reload_settings()
    return ok({"path": str(_config_path()), "config": s.model_dump()},
              msg="配置已重载，即时生效")
