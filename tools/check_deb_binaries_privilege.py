#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from typing import Any, Iterable

from _common import classify_file_not_found, read_non_empty_lines, run_command, sanitize_line


# 基于 DBus 安全检查表的约定：
# - 输入为 deb 包名列表（按行分隔），通过 dpkg-query 列出包内文件
# - 过滤出可执行的常规文件（含符号链接指向的可执行文件）
# - 对可执行文件检查：
#   - file capabilities（getcap）
#   - setuid/setgid（S 位）
# - 最终仅输出“存在 capabilities 或 S 位”的二进制及其所属包

SYSTEM_COMMANDS = {
    "dpkg_query": "dpkg-query",
    "getcap": "getcap",
}

def _run_command(args: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    return run_command(args, timeout_seconds)


def _is_pkg_not_installed_message(message: str) -> bool:
    lowered = message.lower()
    return "is not installed" in lowered or "no packages found" in lowered


def _list_installed_files(package: str, timeout_seconds: float) -> list[str] | None:
    completed = _run_command([SYSTEM_COMMANDS["dpkg_query"], "-L", package], timeout_seconds)
    if completed.returncode == 0:
        return [line.strip() for line in completed.stdout.splitlines() if line.strip()]

    message = (completed.stderr or completed.stdout or "").strip()
    if _is_pkg_not_installed_message(message):
        return None
    raise RuntimeError(message or "dpkg-query -L failed")


def _is_executable_regular_file(path: str) -> bool:
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(st.st_mode):
        return False
    return bool(st.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def _parse_getcap_output(stdout: str) -> dict[str, str]:
    caps: dict[str, str] = {}
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        if " = " in line:
            path, cap_value = line.split(" = ", 1)
            caps[path.strip()] = cap_value.strip()
            continue

        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        path, cap_value = parts
        caps[path.strip()] = cap_value.strip()
    return caps


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(values), size):
        yield values[i : i + size]


def _get_file_caps(paths: list[str], timeout_seconds: float) -> dict[str, str]:
    if not paths:
        return {}

    caps: dict[str, str] = {}
    for group in _chunks(paths, 200):
        completed = _run_command([SYSTEM_COMMANDS["getcap"], *group], timeout_seconds)
        if completed.returncode != 0:
            message = (completed.stderr or "").strip()
            raise RuntimeError(message or "getcap failed")
        caps.update(_parse_getcap_output(completed.stdout))
    return caps


def _mode_octal(mode: int) -> str:
    return f"0o{mode & 0o7777:04o}"


def _build_summary(results: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "total": len(results),
        "ok": 0,
        "mismatch": 0,
        "not_found": 0,
        "error": 0,
        "binaries_scanned": 0,
        "findings": 0,
        "findings_with_caps": 0,
        "findings_with_setuid": 0,
        "findings_with_setgid": 0,
    }

    for r in results:
        status = (r.get("status") or "").lower()
        if status == "ok":
            summary["ok"] += 1
        elif status == "not-found":
            summary["not_found"] += 1
        elif status == "mismatch":
            summary["mismatch"] += 1
        else:
            summary["error"] += 1

        summary["binaries_scanned"] += int(r.get("binaries_scanned") or 0)
        summary["findings"] += int(r.get("findings_count") or 0)
        summary["findings_with_caps"] += int(r.get("findings_with_caps") or 0)
        summary["findings_with_setuid"] += int(r.get("findings_with_setuid") or 0)
        summary["findings_with_setgid"] += int(r.get("findings_with_setgid") or 0)

    return summary


def _load_packages(package: str | None, packages_file: str | None) -> list[str]:
    if package and packages_file:
        raise ValueError("package and --packages-file are mutually exclusive")
    if not package and not packages_file:
        raise ValueError("either a package argument or --packages-file is required")

    if package:
        return [sanitize_line(package)]

    packages = read_non_empty_lines(packages_file or "")
    if not packages:
        raise ValueError("packages file is empty")
    return packages


def _format_list(values: list[str]) -> str:
    return " ".join(values) if values else "(none)"


def _print_findings(package: str, findings: list[dict[str, Any]]) -> None:
    print(f"Package: {package}")
    for finding in findings:
        caps = finding.get("capabilities") or "(none)"
        setuid = "yes" if finding.get("setuid") else "no"
        setgid = "yes" if finding.get("setgid") else "no"
        print(
            "Binary: "
            + finding["path"]
            + f" | Capabilities: {caps}"
            + f" | Setuid: {setuid}"
            + f" | Setgid: {setgid}"
            + f" | Mode: {finding.get('mode_octal')}",
        )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="check_deb_binaries_privilege",
        description="Scan installed Debian packages for executable files with capabilities or setuid/setgid bits.",
    )
    parser.add_argument("package", nargs="?", help="Debian package name (must be installed).")
    parser.add_argument(
        "--packages-file",
        help="Path to a file containing Debian package names (one per line).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON to stdout (useful for CI pipelines).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Command timeout seconds (default: 10).",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    try:
        packages = _load_packages(args.package, args.packages_file)
        results: list[dict[str, Any]] = []

        any_error = False
        any_not_found = False

        for package in packages:
            try:
                files = _list_installed_files(package, args.timeout)
                if files is None:
                    results.append({"package": package, "status": "not-found"})
                    any_not_found = True
                    if not args.json:
                        print(f"ERROR: package not installed: {package}", file=sys.stderr)
                    continue

                binaries = [p for p in files if _is_executable_regular_file(p)]
                caps_map = _get_file_caps(binaries, args.timeout)

                findings: list[dict[str, Any]] = []
                findings_with_caps = 0
                findings_with_setuid = 0
                findings_with_setgid = 0

                for path in binaries:
                    try:
                        st = os.stat(path)
                    except FileNotFoundError:
                        continue
                    setuid = bool(st.st_mode & stat.S_ISUID)
                    setgid = bool(st.st_mode & stat.S_ISGID)
                    cap_value = caps_map.get(path)

                    if cap_value or setuid or setgid:
                        findings.append(
                            {
                                "path": path,
                                "capabilities": cap_value,
                                "setuid": setuid,
                                "setgid": setgid,
                                "mode_octal": _mode_octal(st.st_mode),
                            },
                        )
                        if cap_value:
                            findings_with_caps += 1
                        if setuid:
                            findings_with_setuid += 1
                        if setgid:
                            findings_with_setgid += 1

                result = {
                    "package": package,
                    "status": "ok",
                    "binaries_scanned": len(binaries),
                    "findings": findings,
                    "findings_count": len(findings),
                    "findings_with_caps": findings_with_caps,
                    "findings_with_setuid": findings_with_setuid,
                    "findings_with_setgid": findings_with_setgid,
                }
                results.append(result)

                if args.json:
                    continue

                if findings:
                    _print_findings(package, findings)
                    print("")
                elif len(packages) == 1:
                    print(f"Package: {package}")
                    print("Findings: (none)")
            except FileNotFoundError:
                raise
            except subprocess.TimeoutExpired:
                any_error = True
                error_message = f"command timed out after {args.timeout}s"
                results.append({"package": package, "status": "error", "error": error_message})
                if not args.json:
                    print(f"ERROR: {error_message}", file=sys.stderr)
            except Exception as exc:
                any_error = True
                results.append({"package": package, "status": "error", "error": str(exc)})
                if not args.json:
                    print(f"ERROR: {exc}", file=sys.stderr)

        summary = _build_summary(results)

        if args.json:
            print(json.dumps({"results": results, "summary": summary}, indent=2, ensure_ascii=False, sort_keys=True))
        elif len(packages) > 1:
            print("Summary: " + " ".join(f"{k}={v}" for k, v in summary.items()))

        if any_not_found:
            return 2
        if any_error:
            return 1
        return 0
    except FileNotFoundError as exc:
        exit_code, message = classify_file_not_found(exc, {SYSTEM_COMMANDS["dpkg_query"], SYSTEM_COMMANDS["getcap"]})
        print(message, file=sys.stderr)
        return exit_code
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
