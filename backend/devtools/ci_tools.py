"""CI 二进制工具的固定版本、官方校验下载与本地缓存。"""

import hashlib
import io
import os
import platform
import subprocess
import tarfile
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
TOOLS = {
    "actionlint": ("rhysd/actionlint", "1.7.12", "-version"),
    "gitleaks": ("gitleaks/gitleaks", "8.30.1", "version"),
}


def release_executable(tool: str) -> Path:
    """只安装登记的官方工具，验证归档，只提取预期常规文件并原子替换。"""
    repository, version, version_flag = TOOLS[tool]
    system = {"Darwin": "darwin", "Linux": "linux"}.get(platform.system())
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64"}.get(platform.machine())
    if system is None or arch is None:
        raise RuntimeError(f"{tool} 门禁支持 Linux/macOS 的 amd64/arm64 环境")
    asset_arch = "x64" if tool == "gitleaks" and arch == "amd64" else arch
    folder = ROOT / ".local/ci-tools" / tool / version / f"{system}-{arch}"
    binary = folder / tool
    if not binary.is_file():
        name = f"{tool}_{version}_{system}_{asset_arch}.tar.gz"
        base = f"https://github.com/{repository}/releases/download/v{version}"
        with urlopen(f"{base}/{tool}_{version}_checksums.txt", timeout=60) as response:
            checksums = dict(line.split()[::-1] for line in response.read().decode().splitlines())
        with urlopen(f"{base}/{name}", timeout=60) as response:
            archive = response.read()
        if hashlib.sha256(archive).hexdigest() != checksums.get(name):
            raise RuntimeError(f"{tool} 下载校验和不匹配，拒绝执行")
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
            member = package.getmember(tool)
            if not member.isfile():
                raise RuntimeError(f"{tool} 归档中的可执行文件类型非法")
            contents = package.extractfile(member).read()
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / f"{tool}-{uuid4().hex}.tmp"
        try:
            temporary.write_bytes(contents)
            temporary.chmod(0o755)
            os.replace(temporary, binary)
        finally:
            temporary.unlink(missing_ok=True)
    actual = subprocess.check_output([str(binary), version_flag], text=True, timeout=10)
    if actual.splitlines()[0].strip() != version:
        raise RuntimeError(f"{tool} 缓存版本不匹配，请移除该版本工具缓存后重试")
    return binary
