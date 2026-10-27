"""请求策略快照：Redis 版本通知加有界轮询恢复；保留最近有效值并显式报告异常。"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from uuid import uuid4

from backend.common.exceptions import ConfigError
from backend.common.logging import get_logger

log = get_logger("config.request_snapshot")

VERSION_KEY = "market:request-config:version:v1"
_lock = threading.RLock()
_settings = None
_status = {"version": "", "degraded": False}
_checked = 0.0
_loaded = 0.0
_notification = None


def _redis():
    from backend.storage import get_redis_client

    return get_redis_client().client


def invalidate_request_settings():
    """写入成功后通知；通知失败仍在五秒内轮询恢复，不回滚已提交配置。"""
    global _loaded, _checked
    with _lock:
        _loaded = _checked = 0.0
    try:
        _redis().set(VERSION_KEY, uuid4().hex)
    except Exception:  # noqa: BLE001 -- 通知失败由有界轮询恢复
        log.warning("请求配置版本通知失败，将通过周期校验恢复")


def request_settings_status():
    with _lock:
        return dict(_status)


def get_request_settings():
    global _settings, _checked, _loaded, _notification
    now = time.monotonic()
    with _lock:
        if _settings is not None and now - _checked < 1:
            return _settings
        _checked = now
        notification_failed = False
        try:
            notification = _redis().get(VERSION_KEY)
        except Exception:  # noqa: BLE001 -- 留存最近有效快照并显式标记
            notification, notification_failed = _notification, True
        if _settings is not None and notification == _notification and now - _loaded < 5:
            _status["degraded"] = notification_failed
            return _settings
        try:
            from backend.config.settings import Settings, _raw_yaml
            from backend.storage.app_config import AppConfigRepo, apply_overrides

            base = _raw_yaml()
            settings = Settings.model_validate(
                apply_overrides(base, AppConfigRepo().get_overrides())
            )
            # 版本只由请求策略决定，不对 Cookie、密钥或其它敏感配置计算可见摘要。
            data = {
                "datasource": settings.datasource.model_dump(),
                "intraday": settings.intraday.model_dump(),
                "ths_board": settings.ths_board.model_dump(exclude={"login_cookie"}),
            }
            version = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]
        except Exception as exc:
            _status["degraded"] = True
            if _settings is None:
                raise ConfigError("无法加载有效请求配置，已停止外部请求") from exc
            return _settings
        _settings, _notification, _loaded = settings, notification, now
        _status.update(version=version, degraded=notification_failed)
        return settings
