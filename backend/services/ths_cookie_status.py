"""同花顺登录 Cookie 的脱敏期限状态与真实登录态校验。"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from backend.common.exceptions import DataSourceError
from backend.common.logging import get_logger
from backend.config import get_effective_settings
from backend.datasource.ths_board import ThsBoardSource, login_cookie_with_source
from backend.storage.app_config import (
    SECRET_STATUS_UNAVAILABLE,
    AppConfigRepo,
)

_COOKIE_PATH = "ths_board.login_cookie"
log = get_logger("services.ths_cookie_status")


def _now_local() -> datetime:
    return datetime.now(UTC).astimezone().replace(tzinfo=None)


def _fingerprint(cookie: str) -> str:
    return hashlib.sha256(cookie.encode("utf-8")).hexdigest()


def _as_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=None)
    except ValueError:
        return None


def ths_cookie_status(*, validate: bool = False, repo: AppConfigRepo | None = None) -> dict:
    """返回不含凭证明文的状态；validate=True 时访问同花顺登录深页并持久化结果。"""
    repo = repo or AppConfigRepo()
    validity_days = int(get_effective_settings().ths_board.cookie_validity_days)
    secret_status = repo.get_secret_statuses().get(_COOKIE_PATH, "unset")
    cookie, source = login_cookie_with_source()
    if not cookie:
        status = "unavailable" if secret_status == SECRET_STATUS_UNAVAILABLE else "unset"
        return {
            "status": status,
            "source": None,
            "validity_days": validity_days,
            "saved_at": None,
            "checked_at": None,
            "expires_at": None,
            "remaining_days": None,
        }

    fingerprint = _fingerprint(cookie)
    record = repo.get_ths_cookie_validation()
    if record.get("fingerprint") != fingerprint:
        record = {}

    if validate:
        checked_at = _now_local()
        try:
            valid = ThsBoardSource(login_cookie=cookie).validate_login_cookie()
        except DataSourceError:  # 网络/反爬异常不能等价为凭证失效
            record = {
                "fingerprint": fingerprint,
                "result": "check_failed",
                "checked_at": checked_at.isoformat(timespec="seconds"),
            }
        else:
            record = {
                "fingerprint": fingerprint,
                "result": "valid" if valid else "invalid",
                "checked_at": checked_at.isoformat(timespec="seconds"),
            }
        repo.set_ths_cookie_validation(record)

    saved_at = _as_datetime(repo.get_updated_at(_COOKIE_PATH)) if source == "app_config" else None
    checked_at = _as_datetime(record.get("checked_at"))
    result = record.get("result")
    # 页面配置有可靠保存时间；外部环境/文件没有，不能伪造到期日。
    base_at = (checked_at if result == "valid" else saved_at) if source == "app_config" else None
    expires_at = base_at + timedelta(days=validity_days) if base_at else None
    remaining_days = None
    if expires_at:
        remaining_days = max(0, (expires_at.date() - _now_local().date()).days)

    if result == "invalid":
        status = "invalid"
    elif expires_at and expires_at <= _now_local():
        status = "expired"
    elif result == "check_failed":
        status = "check_failed"
    elif remaining_days is not None and remaining_days <= min(3, max(1, validity_days - 1)):
        status = "expiring"
    elif result == "valid":
        status = "valid"
    elif base_at:
        status = "pending"
    else:
        status = "unknown"

    return {
        "status": status,
        "source": source,
        "validity_days": validity_days,
        "saved_at": saved_at.isoformat(timespec="seconds") if saved_at else None,
        "checked_at": checked_at.isoformat(timespec="seconds") if checked_at else None,
        "expires_at": expires_at.isoformat(timespec="seconds") if expires_at else None,
        "remaining_days": remaining_days,
    }


def mark_ths_cookie_invalid(cookie: str) -> None:
    """采集明确命中登录墙时记录失效；失败不影响采集本身的降级流程。"""
    try:
        AppConfigRepo().set_ths_cookie_validation({
            "fingerprint": _fingerprint(cookie),
            "result": "invalid",
            "checked_at": _now_local().isoformat(timespec="seconds"),
        })
    except Exception as exc:  # noqa: BLE001 -- 状态旁路不得中断正常采集
        log.warning("同花顺 Cookie 失效状态写入失败: %s", exc)


__all__ = ["mark_ths_cookie_invalid", "ths_cookie_status"]
