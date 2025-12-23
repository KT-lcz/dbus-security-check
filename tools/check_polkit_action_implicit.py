#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any, Iterable

from _common import classify_file_not_found, dpkg_query_owners, read_non_empty_lines, run_command, sanitize_line


# 基于 DBus 安全检查表的约定：
# - 输入为 actionid 列表（按行分隔），逐个执行 `pkaction -a <actionid> -v`
# - 检查 implicit any / implicit inactive / implicit active 是否为 yes/auth_self/auth_self_keep
# - 若命中，则输出 actionid、所属包（通过定位 .policy 文件并用 dpkg-query -S 查找）以及对应字段值

SYSTEM_COMMANDS = {
    "pkaction": "pkaction",
    "dpkg_query": "dpkg-query",
}

FLAG_VALUES = {"yes", "auth_self", "auth_self_keep"}

POLICY_SEARCH_DIRS = (
    "/usr/share/polkit-1/actions",
    "/usr/local/share/polkit-1/actions",
    "/etc/polkit-1/actions",
)

ACTION_ID_RE = re.compile(r"<action\s+id\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)

def _run_command(args: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    return run_command(args, timeout_seconds)


def _is_action_not_found_message(message: str) -> bool:
    lowered = message.lower()
    return ("no action" in lowered and "id" in lowered) or ("not found" in lowered and "action" in lowered)


def _parse_pkaction_verbose(output: str) -> dict[str, str]:
    implicit: dict[str, str] = {}
    for raw in output.splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key_norm = key.strip().lower()
        value_norm = value.strip()
        if key_norm in {"implicit any", "implicit inactive", "implicit active"}:
            implicit[key_norm] = value_norm
    return implicit


def _iter_policy_files(search_dirs: Iterable[str]) -> Iterable[str]:
    for directory in search_dirs:
        if not os.path.isdir(directory):
            continue
        for root, _, files in os.walk(directory):
            for name in files:
                if name.endswith(".policy") or name.endswith(".policy.in"):
                    yield os.path.join(root, name)


def _index_policy_actions(search_dirs: Iterable[str]) -> dict[str, list[str]]:
    index: dict[str, set[str]] = {}
    for path in _iter_policy_files(search_dirs):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                content = handle.read()
        except OSError:
            continue
        for action_id in ACTION_ID_RE.findall(content):
            key = action_id.strip()
            if not key:
                continue
            index.setdefault(key, set()).add(path)
    return {k: sorted(v) for k, v in index.items()}


def _build_summary(results: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(results), "ok": 0, "not_found": 0, "error": 0, "flagged": 0}
    for r in results:
        status = (r.get("status") or "").lower()
        if status == "ok":
            summary["ok"] += 1
        elif status == "not-found":
            summary["not_found"] += 1
        else:
            summary["error"] += 1
        if r.get("flagged"):
            summary["flagged"] += 1
    return summary


def _load_action_ids(action_id: str | None, actions_file: str | None) -> list[str]:
    if action_id and actions_file:
        raise ValueError("actionid and --actions-file are mutually exclusive")
    if not action_id and not actions_file:
        raise ValueError("either an actionid argument or --actions-file is required")

    if action_id:
        return [sanitize_line(action_id)]

    action_ids = read_non_empty_lines(actions_file or "")
    if not action_ids:
        raise ValueError("actions file is empty")
    return action_ids


def _format_list(values: list[str]) -> str:
    return " ".join(values) if values else "(unknown)"


def _print_finding(result: dict[str, Any]) -> None:
    print(f"ActionId: {result['action_id']}")
    print(f"Packages: {_format_list(result.get('packages') or [])}")
    implicit = result.get("implicit") or {}
    print(f"ImplicitAny: {implicit.get('implicit any') or '(unknown)'}")
    print(f"ImplicitInactive: {implicit.get('implicit inactive') or '(unknown)'}")
    print(f"ImplicitActive: {implicit.get('implicit active') or '(unknown)'}")
    if result.get("policy_files"):
        print(f"PolicyFiles: {_format_list(result.get('policy_files') or [])}")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="check_polkit_action_implicit",
        description="Check polkit action implicit authorizations via pkaction and report risky values.",
    )
    parser.add_argument("actionid", nargs="?", help="polkit action id, e.g. org.example.foo")
    parser.add_argument(
        "--actions-file",
        help="Path to a file containing action ids (one per line).",
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
        action_ids = _load_action_ids(args.actionid, args.actions_file)
        policy_index = _index_policy_actions(POLICY_SEARCH_DIRS)
        owners_cache: dict[str, list[str]] = {}

        results: list[dict[str, Any]] = []
        any_error = False
        any_not_found = False
        any_flagged = False

        for index, action_id in enumerate(action_ids):
            if index > 0 and not args.json:
                print("")

            try:
                completed = _run_command(
                    [SYSTEM_COMMANDS["pkaction"], "-a", action_id, "-v"],
                    args.timeout,
                )
                if completed.returncode != 0:
                    message = (completed.stderr or completed.stdout or "").strip()
                    status = "not-found" if _is_action_not_found_message(message) else "error"
                    results.append({"action_id": action_id, "status": status, "error": message})
                    if status == "not-found":
                        any_not_found = True
                        if not args.json:
                            print(f"ERROR: action not found: {action_id}", file=sys.stderr)
                    else:
                        any_error = True
                        if not args.json:
                            print(f"ERROR: pkaction failed for {action_id}: {message}", file=sys.stderr)
                    continue

                implicit = _parse_pkaction_verbose(completed.stdout)
                flag_fields = {
                    k: (implicit.get(k, "").strip().lower() in FLAG_VALUES)
                    for k in ("implicit any", "implicit inactive", "implicit active")
                }
                flagged = any(flag_fields.values())

                result: dict[str, Any] = {
                    "action_id": action_id,
                    "status": "ok",
                    "implicit": implicit,
                    "flagged": flagged,
                    "flagged_fields": flag_fields,
                }

                if flagged:
                    any_flagged = True
                    policy_files = policy_index.get(action_id, [])
                    packages: set[str] = set()
                    for policy_file in policy_files:
                        if policy_file not in owners_cache:
                            owners_cache[policy_file] = dpkg_query_owners(policy_file, args.timeout)
                        packages.update(owners_cache[policy_file])
                    result["policy_files"] = policy_files
                    result["packages"] = sorted(packages)

                results.append(result)

                if args.json:
                    continue

                if flagged:
                    _print_finding(result)
                elif len(action_ids) == 1:
                    print(f"ActionId: {action_id}")
                    print("Findings: (none)")
            except FileNotFoundError:
                raise
            except subprocess.TimeoutExpired:
                any_error = True
                message = f"command timed out after {args.timeout}s"
                results.append({"action_id": action_id, "status": "error", "error": message})
                if not args.json:
                    print(f"ERROR: {message}", file=sys.stderr)
            except Exception as exc:
                any_error = True
                results.append({"action_id": action_id, "status": "error", "error": str(exc)})
                if not args.json:
                    print(f"ERROR: {exc}", file=sys.stderr)

        if args.json:
            print(json.dumps({"results": results, "summary": _build_summary(results)}, indent=2, ensure_ascii=False, sort_keys=True))
        elif len(action_ids) > 1:
            summary = _build_summary(results)
            print("")
            print("Summary: " + " ".join(f"{k}={v}" for k, v in summary.items()))

        if any_not_found:
            return 2
        if any_error:
            return 1
        if any_flagged:
            return 0
        return 0
    except FileNotFoundError as exc:
        exit_code, message = classify_file_not_found(exc, {SYSTEM_COMMANDS["pkaction"], SYSTEM_COMMANDS["dpkg_query"]})
        print(message, file=sys.stderr)
        return exit_code
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
