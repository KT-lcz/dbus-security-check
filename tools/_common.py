from __future__ import annotations

import os
import subprocess
from typing import Iterable


# 公共工具函数：
# - 统一处理 UTF-8 BOM、零宽字符（避免肉眼不可见字符污染参数）
# - 统一执行外部命令
# - 统一解析 `key=value` 输出（systemctl show 等）
# - 统一区分“缺少命令”和“缺少输入文件”的错误输出/退出码
# - 统一 dpkg-query 所属包查询（dpkg-query -S）

_ZERO_WIDTH_TRANSLATION = str.maketrans(
    "",
    "",
    "\ufeff\u200b\u200c\u200d\u2060",
)


def sanitize_line(raw: str) -> str:
    return raw.strip().translate(_ZERO_WIDTH_TRANSLATION)


def read_non_empty_lines(path: str) -> list[str]:
    items: list[str] = []
    with open(path, "r", encoding="utf-8-sig") as handle:
        for raw in handle:
            line = sanitize_line(raw)
            if not line or line.startswith("#"):
                continue
            items.append(line)
    return items


def split_tokens(value: str) -> list[str]:
    value = value.strip()
    if not value:
        return []
    return [token for token in value.split() if token]


def parse_key_value_lines(output: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value
    return result


def run_command(
    args: list[str],
    timeout_seconds: float,
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_seconds,
        env=env,
    )


def systemctl_show(service: str, properties: Iterable[str], timeout_seconds: float) -> str:
    args = ["systemctl", "--no-pager", "show", service]
    for prop in properties:
        args.append(f"--property={prop}")

    env = os.environ.copy()
    env.setdefault("SYSTEMD_COLORS", "0")
    env.setdefault("SYSTEMD_PAGER", "")

    completed = run_command(args, timeout_seconds, env=env)
    if completed.returncode != 0:
        if (completed.stdout or "").strip():
            return completed.stdout
        message = (completed.stderr or "").strip() or "systemctl show failed"
        raise RuntimeError(message)
    return completed.stdout


def classify_file_not_found(exc: FileNotFoundError, known_commands: Iterable[str]) -> tuple[int, str]:
    filename = getattr(exc, "filename", "") or ""
    missing = os.path.basename(filename)
    if missing in set(known_commands):
        return 127, f"ERROR: {missing} not found in PATH"
    return 1, f"ERROR: file not found: {filename}"


def parse_dpkg_query_owner(stdout: str) -> list[str]:
    packages: set[str] = set()
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        left, _ = line.split(":", 1)
        for name in left.split(","):
            pkg = name.strip()
            if pkg:
                packages.add(pkg)
    return sorted(packages)


def dpkg_query_owners(path: str, timeout_seconds: float) -> list[str]:
    completed = run_command(["dpkg-query", "-S", path], timeout_seconds)
    if completed.returncode == 0:
        return parse_dpkg_query_owner(completed.stdout)

    message = (completed.stderr or completed.stdout or "").strip().lower()
    if "no path found" in message or "no packages found" in message:
        return []
    raise RuntimeError((completed.stderr or completed.stdout or "").strip() or "dpkg-query -S failed")
