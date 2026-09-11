"""缩放预设纯校验测试：不初始化或访问 PG/DuckDB。"""

import pytest

from backend.storage.layout_config import LayoutConfigValidationError, normalize_preset_override

PATH = "responsiveDefaults.autoScaleResponsiveExponent"


@pytest.mark.parametrize("value", [0, 0.08, 0.10, 0.25, 1])
def test_scale_exponent_round_trip(value):
    config = normalize_preset_override({"values": {PATH: value}})
    assert config["values"][PATH] == value
    assert normalize_preset_override(config) == config


@pytest.mark.parametrize("value", [None, True, "0.1", -0.01, 1.01, float("nan"), float("inf")])
def test_invalid_scale_exponent_rejected(value):
    with pytest.raises(LayoutConfigValidationError):
        normalize_preset_override({"values": {PATH: value}})


def test_legacy_preset_does_not_require_scale_exponent():
    assert normalize_preset_override({"values": {}})["values"] == {}


def test_public_appearance_includes_scale_but_not_other_layout_fields(monkeypatch):
    from types import SimpleNamespace
    from backend.services.auth_service import AuthService
    from backend.storage.layout_config import LayoutConfigRepo

    monkeypatch.setattr(LayoutConfigRepo, "__init__", lambda self: None)
    monkeypatch.setattr(LayoutConfigRepo, "list_presets", lambda self: [{
        "key": "custom", "name": "Custom", "config": {"values": {
            PATH: 0.25, "responsiveDefaults.reflowBreakpoint": 1024,
            "componentDefaults.drawerSize": "lg", "tokens.light.primary": "#123456",
        }},
    }])
    service = object.__new__(AuthService)
    service.cfg = SimpleNamespace(require_email_code=False, login_captcha_enabled=False,
                                  captcha_after_fails=3)
    values = service.public_config()["appearance_presets"][0]["config"]["values"]
    assert values == {PATH: 0.25, "tokens.light.primary": "#123456"}
