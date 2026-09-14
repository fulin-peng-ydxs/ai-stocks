"""自动界面比例系统配置边界：不初始化或访问 PG/DuckDB。"""

import pytest

from backend.storage.app_config import ConfigValidationError, _coerce, get_field_meta
from backend.storage.layout_config import LayoutConfigValidationError, normalize_preset_override

PATH = "ui.display.auto_scale_exponent"
LEGACY_PATH = "responsiveDefaults.autoScaleResponsiveExponent"


@pytest.mark.parametrize("value", [0, 0.08, 0.10, 0.25, 1])
def test_scale_exponent_system_config_round_trip(value):
    field = get_field_meta(PATH)
    assert field is not None
    assert _coerce(field, value) == value


@pytest.mark.parametrize("value", [None, True, "bad", -0.01, 1.01, float("nan"), float("inf")])
def test_invalid_scale_exponent_rejected(value):
    field = get_field_meta(PATH)
    assert field is not None
    with pytest.raises(ConfigValidationError):
        _coerce(field, value)


def test_visual_preset_rejects_legacy_scale_exponent():
    with pytest.raises(LayoutConfigValidationError, match="视觉预设不支持"):
        normalize_preset_override({"values": {LEGACY_PATH: 0.1}})


def test_public_appearance_reads_scale_from_system_config(monkeypatch):
    from types import SimpleNamespace

    from backend.services.auth_service import AuthService
    from backend.storage.app_config import AppConfigRepo
    from backend.storage.layout_config import LayoutConfigRepo

    monkeypatch.setattr(LayoutConfigRepo, "__init__", lambda self: None)
    monkeypatch.setattr(LayoutConfigRepo, "list_presets", lambda self: [{
        "key": "custom",
        "name": "Custom",
        "config": {"values": {"tokens.light.primary": "#123456"}},
    }])
    monkeypatch.setattr(AppConfigRepo, "__init__", lambda self: None)
    monkeypatch.setattr(AppConfigRepo, "get_overrides", lambda self: {PATH: 0.25})
    service = object.__new__(AuthService)
    service.cfg = SimpleNamespace(
        require_email_code=False,
        login_captcha_enabled=False,
        captcha_after_fails=3,
    )
    public = service.public_config()
    assert public["auto_scale_exponent"] == 0.25
    assert public["appearance_presets"][0]["config"]["values"] == {
        "tokens.light.primary": "#123456"
    }
