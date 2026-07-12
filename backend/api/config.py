"""YAML 基线配置读取 / reload API。

- GET  /api/config         查看 `get_settings()` 的 YAML-only 基线配置。
- POST /api/config/reload  改完 config/settings.yaml 后清缓存重载。

Web 系统设置写 PostgreSQL app_config 覆盖层，入口在 /api/data/settings；环境变量、
变量文件和配置覆盖层完整口径见 agent-works/architecture/environment-configuration.md。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.response import ApiResponse, ok
from backend.auth.deps import require_system_perm
from backend.config import get_settings, reload_settings
from backend.config.settings import _config_path

router = APIRouter(prefix="/api", tags=["config"])


# 平台配置全量读：仅系统管理员（配置管理菜单 system-only；避免向普通租户泄露平台参数）。
# stage4·T5：叠加精确码 config:view（require_system_perm = 硬 system 守卫 + 扫描元数据，非 system 恒 403）。
@router.get("/config", response_model=ApiResponse,
            dependencies=[Depends(require_system_perm("config:view"))])
def get_config() -> ApiResponse:
    s = get_settings()
    return ok({"path": str(_config_path()), "config": s.model_dump()})


@router.post("/config/reload", response_model=ApiResponse,
             dependencies=[Depends(require_system_perm("config:reload"))])
def reload_config() -> ApiResponse:
    s = reload_settings()
    return ok({"path": str(_config_path()), "config": s.model_dump()},
              msg="配置已重载，即时生效")
