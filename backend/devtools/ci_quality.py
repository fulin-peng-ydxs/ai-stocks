"""常用静态门禁：使用固定 Ruff 与校验安装的 actionlint，不需要业务存储。"""

import hashlib
import io
import os
import platform
import subprocess
import sys
import tarfile
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
ACTIONLINT_VERSION = "1.7.12"


def actionlint_executable() -> Path:
    """从官方固定版本安装工具；验证归档校验和，只提取预期的可执行文件。"""
    system = {"Darwin": "darwin", "Linux": "linux"}.get(platform.system())
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64"}.get(platform.machine())
    if system is None or arch is None:
        raise RuntimeError("actionlint 门禁支持 Linux/macOS 的 amd64/arm64 环境")
    folder = ROOT / ".local/ci-tools/actionlint" / ACTIONLINT_VERSION / f"{system}-{arch}"
    binary = folder / "actionlint"
    if not binary.is_file():
        name = f"actionlint_{ACTIONLINT_VERSION}_{system}_{arch}.tar.gz"
        base = f"https://github.com/rhysd/actionlint/releases/download/v{ACTIONLINT_VERSION}"
        with urlopen(
            f"{base}/actionlint_{ACTIONLINT_VERSION}_checksums.txt", timeout=60
        ) as response:
            checksums = dict(line.split()[::-1] for line in response.read().decode().splitlines())
        with urlopen(f"{base}/{name}", timeout=60) as response:
            archive = response.read()
        if hashlib.sha256(archive).hexdigest() != checksums.get(name):
            raise RuntimeError("actionlint 下载校验和不匹配，拒绝执行")
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
            member = package.getmember("actionlint")
            if not member.isfile():
                raise RuntimeError("actionlint 归档中的可执行文件类型非法")
            contents = package.extractfile(member).read()
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / f"actionlint-{uuid4().hex}.tmp"
        try:
            temporary.write_bytes(contents)
            temporary.chmod(0o755)
            os.replace(temporary, binary)
        finally:
            temporary.unlink(missing_ok=True)
    version = subprocess.check_output([str(binary), "-version"], text=True, timeout=10)
    if version.splitlines()[0].strip() != ACTIONLINT_VERSION:
        raise RuntimeError("actionlint 缓存版本不匹配，请移除该版本工具缓存后重试")
    return binary


def run_quality() -> int:
    """完整扫描后端与所有 workflow；工具不可用或任一检查失败均返回失败。"""
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "backend"], cwd=ROOT, check=False,
    )
    if result.returncode:
        return result.returncode
    workflows = sorted((ROOT / ".github/workflows").glob("*.y*ml"))
    if not workflows:
        raise RuntimeError("workflow 集合为空，不能把未检查当作成功")
    # 仅做 actionlint 的工作流语法与表达式检查；不隐式依赖可选的 ShellCheck/Pyflakes。
    return subprocess.run(
        [str(actionlint_executable()), "-shellcheck=", "-pyflakes=", *map(str, workflows)],
        cwd=ROOT,
        check=False,
    ).returncode
