from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from backend.common.timeutil import SHANGHAI


class _Repo:
    def __init__(self, saved_at=None):
        self.record = {}
        self.saved_at = saved_at or datetime.now(UTC).astimezone().replace(tzinfo=None)

    def get_secret_statuses(self):
        return {"ths_board.login_cookie": "usable"}

    def get_ths_cookie_validation(self):
        return self.record

    def set_ths_cookie_validation(self, value):
        self.record = value

    def get_updated_at(self, path):
        assert path == "ths_board.login_cookie"
        return self.saved_at


def test_cookie_status_is_pending_before_real_validation(monkeypatch):
    from backend.services import ths_cookie_status as module

    monkeypatch.setattr(module, "get_effective_settings", lambda: SimpleNamespace(
        ths_board=SimpleNamespace(cookie_validity_days=30)))
    monkeypatch.setattr(module, "login_cookie_with_source", lambda: ("secret", "app_config"))
    now = datetime(2026, 11, 12, 12, tzinfo=SHANGHAI).replace(tzinfo=None)
    monkeypatch.setattr(module, "_now_local", lambda: now)
    status = module.ths_cookie_status(repo=_Repo(saved_at=now))
    assert status["status"] == "pending"
    assert status["remaining_days"] == 30


def test_cookie_real_validation_records_valid_and_invalid(monkeypatch):
    from backend.services import ths_cookie_status as module

    monkeypatch.setattr(module, "get_effective_settings", lambda: SimpleNamespace(
        ths_board=SimpleNamespace(cookie_validity_days=30)))
    monkeypatch.setattr(module, "login_cookie_with_source", lambda: ("secret", "app_config"))
    repo = _Repo()

    class _Source:
        valid = True

        def __init__(self, **kwargs):
            pass

        def validate_login_cookie(self):
            return self.valid

    monkeypatch.setattr(module, "ThsBoardSource", _Source)
    assert module.ths_cookie_status(validate=True, repo=repo)["status"] == "valid"
    _Source.valid = False
    assert module.ths_cookie_status(validate=True, repo=repo)["status"] == "invalid"


def test_login_wall_for_other_cookie_preserves_current_validation(monkeypatch):
    from backend.services import ths_cookie_status as module

    repo = _Repo()
    valid = {"fingerprint": module._fingerprint("current"), "result": "valid"}
    repo.record = valid.copy()
    monkeypatch.setattr(module, "AppConfigRepo", lambda: repo)
    monkeypatch.setattr(module, "login_cookie_with_source", lambda: ("current", "app_config"))
    module.mark_ths_cookie_invalid("old-instance")
    assert repo.record == valid
    module.mark_ths_cookie_invalid("current")
    assert repo.record["result"] == "invalid"
    assert repo.record["fingerprint"] == valid["fingerprint"]


def test_late_validation_does_not_overwrite_new_cookie_status(monkeypatch):
    from backend.services import ths_cookie_status as module

    monkeypatch.setattr(module, "get_effective_settings", lambda: SimpleNamespace(
        ths_board=SimpleNamespace(cookie_validity_days=30)))
    cookie = ["old"]
    monkeypatch.setattr(module, "login_cookie_with_source", lambda: (cookie[0], "app_config"))
    repo = _Repo()
    current = {"fingerprint": module._fingerprint("new"), "result": "valid",
               "checked_at": datetime.now(UTC).replace(tzinfo=None).isoformat()}

    class Source:
        def __init__(self, **kwargs):
            pass

        def validate_login_cookie(self):
            cookie[0] = "new"
            repo.record = current.copy()
            return False

    monkeypatch.setattr(module, "ThsBoardSource", Source)
    assert module.ths_cookie_status(validate=True, repo=repo)["status"] == "valid"
    assert repo.record == current
