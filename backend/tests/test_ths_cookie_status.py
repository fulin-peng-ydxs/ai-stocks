from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace


class _Repo:
    def __init__(self):
        self.record = {}

    def get_secret_statuses(self):
        return {"ths_board.login_cookie": "usable"}

    def get_ths_cookie_validation(self):
        return self.record

    def set_ths_cookie_validation(self, value):
        self.record = value

    def get_updated_at(self, path):
        assert path == "ths_board.login_cookie"
        return datetime.now(UTC).replace(tzinfo=None)


def test_cookie_status_is_pending_before_real_validation(monkeypatch):
    from backend.services import ths_cookie_status as module

    monkeypatch.setattr(module, "get_effective_settings", lambda: SimpleNamespace(
        ths_board=SimpleNamespace(cookie_validity_days=30)))
    monkeypatch.setattr(module, "login_cookie_with_source", lambda: ("secret", "app_config"))
    status = module.ths_cookie_status(repo=_Repo())
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
