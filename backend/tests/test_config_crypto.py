"""平台敏感配置加密边界。"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from backend.security.config_crypto import (
    ConfigEncryptionError,
    decrypt_config_value,
    encrypt_config_value,
    is_encrypted_config_value,
)


def test_config_secret_round_trip_and_random_nonce(monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("AI_STOCKS_CONFIG_ENCRYPTION_KEY", key)
    plaintext = "user=test; ticket=never-store-plaintext"

    first = encrypt_config_value(plaintext)
    second = encrypt_config_value(plaintext)

    assert first != second
    assert is_encrypted_config_value(first)
    assert plaintext not in first
    assert decrypt_config_value(first) == plaintext


def test_config_secret_reads_key_file(monkeypatch, tmp_path):
    key_file = tmp_path / "config.key"
    key_file.write_text(Fernet.generate_key().decode("ascii"), encoding="utf-8")
    key_file.chmod(0o600)
    monkeypatch.delenv("AI_STOCKS_CONFIG_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("AI_STOCKS_CONFIG_ENCRYPTION_KEY_FILE", str(key_file))

    encrypted = encrypt_config_value("cookie-from-page")

    assert decrypt_config_value(encrypted) == "cookie-from-page"


def test_config_secret_rejects_overexposed_key_file(monkeypatch, tmp_path):
    key_file = tmp_path / "config.key"
    key_file.write_text(Fernet.generate_key().decode("ascii"), encoding="utf-8")
    key_file.chmod(0o644)
    monkeypatch.delenv("AI_STOCKS_CONFIG_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("AI_STOCKS_CONFIG_ENCRYPTION_KEY_FILE", str(key_file))

    with pytest.raises(ConfigEncryptionError, match="权限过宽"):
        encrypt_config_value("plaintext")


def test_config_secret_fails_closed_without_key_or_after_tamper(monkeypatch):
    monkeypatch.delenv("AI_STOCKS_CONFIG_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("AI_STOCKS_CONFIG_ENCRYPTION_KEY_FILE", raising=False)
    with pytest.raises(ConfigEncryptionError, match="缺少"):
        encrypt_config_value("plaintext")

    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("AI_STOCKS_CONFIG_ENCRYPTION_KEY", key)
    encrypted = encrypt_config_value("plaintext")
    tampered = encrypted[:-1] + ("A" if encrypted[-1] != "A" else "B")
    with pytest.raises(ConfigEncryptionError, match="校验或解密失败"):
        decrypt_config_value(tampered)


def test_login_cookie_in_yaml_is_ignored(monkeypatch, tmp_path):
    from backend.config.settings import _raw_yaml

    config = tmp_path / "settings.yaml"
    config.write_text(
        "ths_board:\n  timeout_sec: 10\n  login_cookie: plaintext-must-be-ignored\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_STOCKS_CONFIG", str(config))

    raw = _raw_yaml()

    assert raw["ths_board"]["timeout_sec"] == 10
    assert "login_cookie" not in raw["ths_board"]
