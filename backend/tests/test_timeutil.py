"""业务墙上时间与日期解析契约，不依赖运行主机的本地时区。"""

from datetime import UTC, date, datetime

import pytest

from backend.common import timeutil


def test_shanghai_wall_time_crosses_utc_midnight_without_changing_timestamp_format(monkeypatch):
    instant = datetime(2026, 11, 14, 17, 30, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is timeutil.SHANGHAI
            return instant.astimezone(tz)

    monkeypatch.setattr(timeutil, "datetime", Clock)
    value = timeutil.shanghai_now_naive()
    assert value.isoformat() == "2026-11-15T01:30:00"
    assert value.tzinfo is None


@pytest.mark.parametrize("value", ["20240229", "2024-02-29", date(2024, 2, 29),
    datetime(2024, 2, 29, 23, tzinfo=UTC)])
def test_date_parser_preserves_calendar_date_for_supported_inputs(value):
    assert timeutil.to_date(value) == date(2024, 2, 29)


@pytest.mark.parametrize("value", ["20230229", "2024-13-01", "not-a-date"])
def test_date_parser_rejects_invalid_calendar_dates(value):
    with pytest.raises(ValueError):
        timeutil.to_date(value)
