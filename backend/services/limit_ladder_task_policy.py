"""天梯等待策略：统一期限、过期判断及业务原因码，不持有进程内排队状态。"""

from datetime import UTC, datetime, timedelta

import pandas as pd

from backend.common.exceptions import ConflictError
from backend.config import get_settings

QUEUE_TIMEOUT_REASON = "limit_ladder_queue_timeout"


class LimitLadderQueueTimeoutError(ConflictError):
    """等待请求已过期，禁止在释放写槽位后迟到执行。"""


def queue_timeout_seconds() -> int:
    """采用 YAML 启动基线；与共享写准入使用完全相同的等待期限。"""
    return get_settings().limit_ladder.queue_timeout_sec


def queue_deadline(created_at) -> datetime:
    """以首次请求时间计算绝对期限，轮询、重试与服务重启均不续期。"""
    stamp = pd.Timestamp(created_at)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    return stamp.to_pydatetime() + timedelta(seconds=queue_timeout_seconds())


def check_queue_deadline(value: str | None, *, now: datetime | None = None) -> None:
    """只在运行态创建锁内调用；已存在的幂等运行任务应先复用。"""
    if value and (now or datetime.now(UTC)) >= datetime.fromisoformat(value):
        raise LimitLadderQueueTimeoutError("天梯排队等待已超时，请重新排队")
