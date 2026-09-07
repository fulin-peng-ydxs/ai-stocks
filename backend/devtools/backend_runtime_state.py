"""受控后端启动档案。

只记录恢复后端所需的非敏感值；其余项目环境变量仅保存不可逆摘要。档案用于 E2E
临时切换服务后恢复原启动目标，不作为通用进程管理或密钥存储入口。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from backend.storage.pg_identity import pg_fingerprint

STATE_VERSION = 2
SAFE_ENV_NAMES = (
    "AI_STOCKS_ENV",
    "AI_STOCKS_E2E_WRITE",
    "AI_STOCKS_E2E_LOGIN_BYPASS",
    "AI_STOCKS_DUCKDB_READ_ONLY",
    "ENV",
)
_DIGEST_EXCLUDED_NAMES = {*SAFE_ENV_NAMES, "AI_STOCKS_ENV_FILE", "ENV"}
_FINGERPRINT_RE = re.compile(r"^[a-f0-9]{64}$")


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _other_ai_stocks_env_digests(environment: dict[str, str]) -> dict[str, str]:
    return {
        name: _digest_text(value)
        for name, value in sorted(environment.items())
        if name.startswith("AI_STOCKS_") and name not in _DIGEST_EXCLUDED_NAMES
    }


def build_runtime_state(
    *,
    mode: str,
    pid: int,
    env_file: str,
    python_command: str,
    environment: dict[str, str],
    fingerprint: str,
) -> dict[str, Any]:
    if mode not in {"dev", "prod"} or pid <= 0:
        raise RuntimeError("后端运行档案启动信息非法")
    if not python_command or "\0" in python_command or "\0" in env_file:
        raise RuntimeError("后端运行档案环境配置非法")
    if _FINGERPRINT_RE.fullmatch(fingerprint) is None:
        raise RuntimeError("后端运行档案缺少合法 PostgreSQL 指纹")
    return {
        "version": STATE_VERSION,
        "mode": mode,
        "pid": pid,
        "envFile": env_file,
        "envFileDigest": _file_digest(Path(env_file)),
        "pythonCommand": python_command,
        "pgFingerprint": fingerprint,
        "safeEnv": {name: environment.get(name) for name in SAFE_ENV_NAMES},
        "otherAiStocksEnvDigests": _other_ai_stocks_env_digests(environment),
    }


def _write_json_atomic(target: Path, payload: dict[str, Any]) -> None:
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(target)


def write_runtime_state(
    *,
    target: Path,
    mode: str,
    pid: int,
    env_file: str,
    python_command: str,
) -> None:
    payload = build_runtime_state(
        mode=mode,
        pid=pid,
        env_file=env_file,
        python_command=python_command,
        environment=dict(os.environ),
        fingerprint=pg_fingerprint(),
    )
    _write_json_atomic(target, payload)


def load_runtime_state(source: Path) -> dict[str, Any]:
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("后端运行档案结构非法")
    return data


def validate_runtime_state(data: dict[str, Any], *, expected_pid: int | None = None) -> None:
    if data.get("version") != STATE_VERSION or data.get("mode") not in {"dev", "prod"}:
        raise RuntimeError("后端运行档案结构非法")
    if expected_pid is not None and data.get("pid") != expected_pid:
        raise RuntimeError("后端运行档案与当前进程不匹配，拒绝停止现有服务")
    if _FINGERPRINT_RE.fullmatch(str(data.get("pgFingerprint", ""))) is None:
        raise RuntimeError("后端运行档案缺少合法 PostgreSQL 指纹")
    env_file = data.get("envFile")
    python_command = data.get("pythonCommand")
    if (
        not isinstance(data.get("safeEnv"), dict)
        or not isinstance(data.get("otherAiStocksEnvDigests"), dict)
        or not isinstance(env_file, str)
        or "\0" in env_file
        or not isinstance(python_command, str)
        or not python_command
        or "\0" in python_command
    ):
        raise RuntimeError("后端运行档案环境配置非法")


def snapshot_runtime_state(*, source: Path, target: Path, expected_pid: int) -> None:
    data = load_runtime_state(source)
    validate_runtime_state(data, expected_pid=expected_pid)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=True, sort_keys=True)


def build_restore_environment(
    data: dict[str, Any],
    *,
    current_environment: dict[str, str],
) -> dict[str, str]:
    validate_runtime_state(data)
    env_file = str(data["envFile"])
    if _file_digest(Path(env_file)) != data.get("envFileDigest"):
        raise RuntimeError("后端环境文件在测试期间发生变化，拒绝猜测恢复配置")
    if _other_ai_stocks_env_digests(current_environment) != data["otherAiStocksEnvDigests"]:
        raise RuntimeError("后端额外 AI_STOCKS 环境变量与测试前不一致，拒绝猜测恢复配置")

    restored = current_environment.copy()
    restored["AI_STOCKS_ENV_FILE"] = env_file
    restored["PYTHON"] = str(data["pythonCommand"])
    safe_env = data["safeEnv"]
    for name in SAFE_ENV_NAMES:
        value = safe_env.get(name)
        if value is None:
            restored.pop(name, None)
        elif isinstance(value, str) and "\0" not in value:
            restored[name] = value
        else:
            raise RuntimeError(f"后端运行档案字段 {name} 非法")
    return restored


def restore_runtime_state(*, source: Path, start_script: Path, runtime_file: Path) -> None:
    data = load_runtime_state(source)
    environment = build_restore_environment(data, current_environment=dict(os.environ))
    subprocess.run([str(start_script), str(data["mode"])], env=environment, check=True)
    restored = load_runtime_state(runtime_file)
    if restored.get("pgFingerprint") != data.get("pgFingerprint"):
        # The just-restored process points at an unexpected PG target and must not be left alive.
        subprocess.run([str(start_script), "stop", "--force"], env=environment, check=False)
        raise RuntimeError("恢复后的 PostgreSQL 指纹与测试前不一致，已停止后端")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="受控后端启动档案")
    subparsers = parser.add_subparsers(dest="action", required=True)

    write = subparsers.add_parser("write")
    write.add_argument("--target", type=Path, required=True)
    write.add_argument("--mode", choices=("dev", "prod"), required=True)
    write.add_argument("--pid", type=int, required=True)
    write.add_argument("--env-file", required=True)
    write.add_argument("--python-command", required=True)

    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--source", type=Path, required=True)
    snapshot.add_argument("--target", type=Path, required=True)
    snapshot.add_argument("--expected-pid", type=int, required=True)

    restore = subparsers.add_parser("restore")
    restore.add_argument("--source", type=Path, required=True)
    restore.add_argument("--start-script", type=Path, required=True)
    restore.add_argument("--runtime-file", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.action == "write":
            write_runtime_state(
                target=args.target,
                mode=args.mode,
                pid=args.pid,
                env_file=args.env_file,
                python_command=args.python_command,
            )
        elif args.action == "snapshot":
            snapshot_runtime_state(
                source=args.source,
                target=args.target,
                expected_pid=args.expected_pid,
            )
        else:
            restore_runtime_state(
                source=args.source,
                start_script=args.start_script,
                runtime_file=args.runtime_file,
            )
    except (OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
