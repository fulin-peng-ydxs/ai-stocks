"""平台敏感配置的应用层加密。

数据库只保存带版本前缀的 Fernet 密文；主密钥只从环境变量或受控文件读取，不进入 YAML、
数据库或代码。Fernet 同时提供机密性与完整性校验，解密失败时必须 fail-closed。
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

ENCRYPTED_VALUE_PREFIX = "enc:v1:"
_KEY_ENV = "AI_STOCKS_CONFIG_ENCRYPTION_KEY"
_KEY_FILE_ENV = "AI_STOCKS_CONFIG_ENCRYPTION_KEY_FILE"


class ConfigEncryptionError(RuntimeError):
    """敏感配置密钥缺失、格式非法或密文无法校验。"""


def _encryption_key() -> bytes:
    raw = os.environ.get(_KEY_ENV, "").strip()
    if not raw:
        key_file = os.environ.get(_KEY_FILE_ENV, "").strip()
        if key_file:
            try:
                path = Path(key_file)
                mode = stat.S_IMODE(path.stat().st_mode)
                if mode & 0o077:
                    raise ConfigEncryptionError(
                        "敏感配置密钥文件权限过宽，必须仅允许文件所有者访问（chmod 600）"
                    )
                raw = path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ConfigEncryptionError(f"无法读取敏感配置密钥文件: {exc}") from exc
    if not raw:
        raise ConfigEncryptionError(
            f"缺少 {_KEY_ENV} 或 {_KEY_FILE_ENV}，不能安全保存或读取敏感配置"
        )
    try:
        Fernet(raw.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ConfigEncryptionError("敏感配置密钥格式非法，必须是 Fernet 密钥") from exc
    return raw.encode("ascii")


def is_encrypted_config_value(value: object) -> bool:
    return isinstance(value, str) and value.startswith(ENCRYPTED_VALUE_PREFIX)


def encrypt_config_value(plaintext: str) -> str:
    """加密字符串并返回带版本前缀的可迁移密文。"""
    token = Fernet(_encryption_key()).encrypt(plaintext.encode("utf-8")).decode("ascii")
    return ENCRYPTED_VALUE_PREFIX + token


def decrypt_config_value(ciphertext: str) -> str:
    """校验并解密带版本前缀的密文；未知格式与篡改统一拒绝。"""
    if not is_encrypted_config_value(ciphertext):
        raise ConfigEncryptionError("敏感配置不是受支持的加密格式")
    token = ciphertext[len(ENCRYPTED_VALUE_PREFIX):]
    try:
        return Fernet(_encryption_key()).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise ConfigEncryptionError("敏感配置密文校验或解密失败") from exc
