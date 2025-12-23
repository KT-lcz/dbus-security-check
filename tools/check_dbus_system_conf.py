#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as element_tree
from typing import Any, Iterable

from _common import classify_file_not_found, dpkg_query_owners


# 基于 DBus 安全检查表的约定：
# - 扫描 system bus 配置目录下所有 *.conf（XML）
# - 本工具先实现第一个检查：定位 <policy context="default"> 下的 <allow own="...">
# - 并输出对应 conf 文件与所属 deb 包（dpkg-query -S 反查）

DEFAULT_SEARCH_DIRS = (
    "/etc/dbus-1/system.d",
    "/usr/share/dbus-1/system.d",
)

SYSTEM_COMMANDS = {
    "dpkg_query": "dpkg-query",
}


def _iter_conf_files(directories: Iterable[str]) -> tuple[list[str], list[str]]:
    files: set[str] = set()
    missing_dirs: list[str] = []

    for directory in directories:
        if not os.path.isdir(directory):
            missing_dirs.append(directory)
            continue

        for root, _, names in os.walk(directory):
            for name in names:
                if name.endswith(".conf"):
                    files.add(os.path.join(root, name))

    return sorted(files), missing_dirs


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _find_allow_own_in_default_policy(root: element_tree.Element) -> list[str]:
    owns: set[str] = set()
    for policy in root.iter():
        if _local_name(policy.tag) != "policy":
            continue
        if (policy.attrib.get("context") or "").strip() != "default":
            continue
        for allow in policy.iter():
            if _local_name(allow.tag) != "allow":
                continue
            own = (allow.attrib.get("own") or "").strip()
            if own:
                owns.add(own)
    return sorted(owns)


def _build_summary(results: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(results), "ok": 0, "error": 0, "flagged": 0, "findings": 0}
    for r in results:
        status = (r.get("status") or "").lower()
        if status == "ok":
            summary["ok"] += 1
        else:
            summary["error"] += 1

        if r.get("flagged"):
            summary["flagged"] += 1
            summary["findings"] += int(r.get("findings_count") or 0)
    return summary


def _format_list(values: list[str], *, empty: str) -> str:
    return " ".join(values) if values else empty


def _print_finding(result: dict[str, Any]) -> None:
    print(f"ConfFile: {result['conf_file']}")
    print(f"Packages: {_format_list(result.get('packages') or [], empty='(unknown)')}")
    print(f"AllowOwnInDefaultPolicy: {_format_list(result.get('allow_own_in_default_policy') or [], empty='(none)')}")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="check_dbus_system_conf",
        description="Scan DBus system bus .conf files and report <allow own> under default policy.",
    )
    parser.add_argument(
        "--etc-dir",
        default=DEFAULT_SEARCH_DIRS[0],
        help="DBus system.d directory (default: /etc/dbus-1/system.d).",
    )
    parser.add_argument(
        "--usr-dir",
        default=DEFAULT_SEARCH_DIRS[1],
        help="DBus system.d directory (default: /usr/share/dbus-1/system.d).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON to stdout (useful for CI pipelines).",
    )
    parser.add_argument(
        "--only-flagged",
        action="store_true",
        help="Only include flagged records (and errors) in JSON results; text output is already findings-only.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="dpkg-query timeout seconds (default: 5).",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    try:
        conf_files, missing_dirs = _iter_conf_files([args.etc_dir, args.usr_dir])
        if missing_dirs and not conf_files:
            raise ValueError("no .conf files found; directories not found: " + ", ".join(missing_dirs))

        owners_cache: dict[str, list[str]] = {}
        results: list[dict[str, Any]] = []
        any_error = False
        printed_findings = 0

        if missing_dirs and not args.json:
            for directory in missing_dirs:
                print(f"WARNING: directory not found: {directory}", file=sys.stderr)

        for conf_file in conf_files:
            try:
                tree = element_tree.parse(conf_file)
                allow_owns = _find_allow_own_in_default_policy(tree.getroot())

                packages: list[str] = []
                if allow_owns:
                    if conf_file not in owners_cache:
                        owners_cache[conf_file] = dpkg_query_owners(conf_file, args.timeout)
                    packages = owners_cache[conf_file]

                result = {
                    "conf_file": conf_file,
                    "packages": packages,
                    "status": "ok",
                    "flagged": bool(allow_owns),
                    "allow_own_in_default_policy": allow_owns,
                    "findings_count": len(allow_owns),
                }
                results.append(result)

                if args.json:
                    continue

                if allow_owns:
                    if printed_findings > 0:
                        print("")
                    _print_finding(result)
                    printed_findings += 1
                elif len(conf_files) == 1:
                    print(f"ConfFile: {conf_file}")
                    print("Findings: (none)")
            except FileNotFoundError:
                raise
            except subprocess.TimeoutExpired:
                any_error = True
                message = f"command timed out after {args.timeout}s"
                results.append({"conf_file": conf_file, "status": "error", "error": message})
                if not args.json:
                    print(f"ERROR: {message}", file=sys.stderr)
            except element_tree.ParseError as exc:
                any_error = True
                message = f"xml parse error: {exc}"
                results.append({"conf_file": conf_file, "status": "error", "error": message})
                if not args.json:
                    print(f"ERROR: {message}", file=sys.stderr)
            except Exception as exc:
                any_error = True
                results.append({"conf_file": conf_file, "status": "error", "error": str(exc)})
                if not args.json:
                    print(f"ERROR: {exc}", file=sys.stderr)

        summary = _build_summary(results)
        output_results = results
        if args.only_flagged:
            output_results = [
                r
                for r in results
                if r.get("status") != "ok" or bool(r.get("flagged"))
            ]

        if args.json:
            payload: dict[str, Any] = {"results": output_results, "summary": summary}
            if missing_dirs:
                payload["missing_dirs"] = missing_dirs
            print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
        elif len(conf_files) > 1:
            print("")
            print("Summary: " + " ".join(f"{k}={v}" for k, v in summary.items()))

        if any_error:
            return 1
        return 0
    except FileNotFoundError as exc:
        exit_code, message = classify_file_not_found(exc, {SYSTEM_COMMANDS["dpkg_query"]})
        print(message, file=sys.stderr)
        return exit_code
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
