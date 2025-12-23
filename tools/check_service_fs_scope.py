#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

from _common import classify_file_not_found, parse_key_value_lines, read_non_empty_lines, sanitize_line, split_tokens, systemctl_show


# 基于 DBus 安全检查表的约定：
# - 通过 systemctl show 读取 service 的沙箱/路径相关参数，派生可读/可写范围摘要
# - 若显式使用 /var/lib /var/run /run，提示优先使用 StateDirectory=/RuntimeDirectory=

SYSTEMCTL_PROPERTIES = (
    "LoadState",
    "ProtectSystem",
    "ProtectHome",
    "PrivateTmp",
    "NoNewPrivileges",
    "ReadWritePaths",
    "ReadOnlyPaths",
    "InaccessiblePaths",
    "StateDirectory",
    "RuntimeDirectory",
)


def _parse_systemctl_show(output: str) -> dict[str, str]:
    return parse_key_value_lines(output)


def _format_list(values: list[str]) -> str:
    return " ".join(values) if values else "(none)"


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "yes", "true"}


def _normalize_protect_system(value: str) -> str:
    raw = value.strip().lower()
    if raw in {"1", "yes", "true"}:
        return "yes"
    if raw in {"0", "no", "false", ""}:
        return "no"
    if raw in {"full", "strict"}:
        return raw
    return raw


def _normalize_protect_home(value: str) -> str:
    raw = value.strip().lower()
    if raw in {"1", "yes", "true"}:
        return "yes"
    if raw in {"0", "no", "false", ""}:
        return "no"
    if raw in {"read-only", "tmpfs"}:
        return raw
    return raw


def _protect_system_read_only_roots(mode: str) -> list[str]:
    if mode == "yes":
        return ["/usr", "/boot"]
    if mode == "full":
        return ["/usr", "/boot", "/etc"]
    if mode == "strict":
        return ["/"]
    return []


def _protect_home_effect(mode: str) -> tuple[list[str], list[str], list[str]]:
    home_roots = ["/home", "/root", "/run/user"]
    if mode == "yes":
        return [], home_roots, []
    if mode == "read-only":
        return home_roots, [], []
    if mode == "tmpfs":
        return [], [], home_roots
    return [], [], []


def _load_services(service: str | None, services_file: str | None) -> list[str]:
    if service and services_file:
        raise ValueError("service and --services-file are mutually exclusive")
    if not service and not services_file:
        raise ValueError("either a service argument or --services-file is required")

    if service:
        return [sanitize_line(service)]

    services = read_non_empty_lines(services_file or "")
    if not services:
        raise ValueError("services file is empty")
    return services


def _build_summary(results: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(results), "ok": 0, "not_found": 0, "error": 0}
    for r in results:
        status = (r.get("status") or "").lower()
        if status == "ok":
            summary["ok"] += 1
        elif status == "not-found":
            summary["not_found"] += 1
        else:
            summary["error"] += 1
    return summary


def _derive_state_directory_paths(names: list[str]) -> list[str]:
    return [f"/var/lib/{name}" for name in names]


def _derive_runtime_directory_paths(names: list[str]) -> list[str]:
    return [f"/run/{name}" for name in names]


def _dedup_sorted(values: list[str]) -> list[str]:
    return sorted({v for v in values if v})


def _detect_state_runtime_hint(explicit_paths: list[str]) -> tuple[bool, list[str], str]:
    offenders: list[str] = []
    for path in explicit_paths:
        if path == "/var/lib" or path.startswith("/var/lib/"):
            offenders.append(path)
        elif path == "/var/run" or path.startswith("/var/run/"):
            offenders.append(path)
        elif path == "/run" or path.startswith("/run/"):
            offenders.append(path)
    offenders = _dedup_sorted(offenders)
    if not offenders:
        return False, [], ""
    message = "Prefer using StateDirectory=/RuntimeDirectory= instead of /var/lib /var/run /run in *Paths settings."
    return True, offenders, message


def _build_result(service: str, kv: dict[str, str]) -> dict[str, Any]:
    load_state = (kv.get("LoadState") or "").strip()

    protect_system = _normalize_protect_system(kv.get("ProtectSystem") or "")
    protect_home = _normalize_protect_home(kv.get("ProtectHome") or "")
    private_tmp = _parse_bool(kv.get("PrivateTmp") or "")
    no_new_privileges = _parse_bool(kv.get("NoNewPrivileges") or "")

    read_write_paths = split_tokens(kv.get("ReadWritePaths") or "")
    read_only_paths = split_tokens(kv.get("ReadOnlyPaths") or "")
    inaccessible_paths = split_tokens(kv.get("InaccessiblePaths") or "")

    state_directory_names = split_tokens(kv.get("StateDirectory") or "")
    runtime_directory_names = split_tokens(kv.get("RuntimeDirectory") or "")
    state_directory_paths = _derive_state_directory_paths(state_directory_names)
    runtime_directory_paths = _derive_runtime_directory_paths(runtime_directory_names)

    ps_read_only_roots = _protect_system_read_only_roots(protect_system)
    ph_read_only_roots, ph_inaccessible_roots, ph_tmpfs_roots = _protect_home_effect(protect_home)

    effective_read_only_paths = _dedup_sorted(ps_read_only_roots + ph_read_only_roots + read_only_paths)
    effective_inaccessible_paths = _dedup_sorted(ph_inaccessible_roots + inaccessible_paths)

    explicit_writable_paths = _dedup_sorted(read_write_paths + state_directory_paths + runtime_directory_paths)

    hint_triggered, hint_paths, hint_message = _detect_state_runtime_hint(
        read_write_paths + read_only_paths + inaccessible_paths,
    )

    read_scope: dict[str, Any]
    if effective_inaccessible_paths:
        read_scope = {"mode": "all_except", "except": effective_inaccessible_paths}
    else:
        read_scope = {"mode": "all"}

    write_scope: dict[str, Any]
    if protect_system == "strict":
        write_scope = {
            "mode": "only",
            "paths": explicit_writable_paths,
            "read_only_roots": effective_read_only_paths,
            "inaccessible_paths": effective_inaccessible_paths,
        }
    else:
        write_scope = {
            "mode": "all_except",
            "read_only_roots": effective_read_only_paths,
            "inaccessible_paths": effective_inaccessible_paths,
            "writable_exceptions": explicit_writable_paths,
        }

    status = "ok"
    if load_state.lower() == "not-found":
        status = "not-found"

    return {
        "service": service,
        "load_state": load_state,
        "status": status,
        "protect_system": protect_system,
        "protect_home": protect_home,
        "private_tmp": private_tmp,
        "no_new_privileges": no_new_privileges,
        "read_write_paths": _dedup_sorted(read_write_paths),
        "read_only_paths": _dedup_sorted(read_only_paths),
        "inaccessible_paths": _dedup_sorted(inaccessible_paths),
        "state_directory": _dedup_sorted(state_directory_names),
        "runtime_directory": _dedup_sorted(runtime_directory_names),
        "state_directory_paths": _dedup_sorted(state_directory_paths),
        "runtime_directory_paths": _dedup_sorted(runtime_directory_paths),
        "protect_system_read_only_roots": _dedup_sorted(ps_read_only_roots),
        "protect_home_read_only_roots": _dedup_sorted(ph_read_only_roots),
        "protect_home_inaccessible_roots": _dedup_sorted(ph_inaccessible_roots),
        "protect_home_tmpfs_roots": _dedup_sorted(ph_tmpfs_roots),
        "read_scope": read_scope,
        "write_scope": write_scope,
        "prefer_state_runtime_directory_hint": {
            "triggered": hint_triggered,
            "paths": hint_paths,
            "message": hint_message,
        },
        "note": "Scope is derived from a subset of sandboxing directives; consider reviewing unit files for additional restrictions.",
    }


def _print_text_report(result: dict[str, Any]) -> None:
    print(f"Service: {result['service']}")
    if result.get("load_state"):
        print(f"LoadState: {result['load_state']}")
    print(f"Status: {result.get('status')}")
    print(f"NoNewPrivileges: {'yes' if result.get('no_new_privileges') else 'no'}")
    print(f"ProtectSystem: {result.get('protect_system')}")
    print(f"ProtectHome: {result.get('protect_home')}")
    print(f"PrivateTmp: {'yes' if result.get('private_tmp') else 'no'}")

    print(f"ReadWritePaths: {_format_list(result.get('read_write_paths') or [])}")
    print(f"ReadOnlyPaths: {_format_list(result.get('read_only_paths') or [])}")
    print(f"InaccessiblePaths: {_format_list(result.get('inaccessible_paths') or [])}")

    print(f"StateDirectory: {_format_list(result.get('state_directory') or [])}")
    print(f"StateDirectoryPaths: {_format_list(result.get('state_directory_paths') or [])}")
    print(f"RuntimeDirectory: {_format_list(result.get('runtime_directory') or [])}")
    print(f"RuntimeDirectoryPaths: {_format_list(result.get('runtime_directory_paths') or [])}")

    read_scope = result.get("read_scope") or {}
    if read_scope.get("mode") == "all_except":
        print(f"ReadableScope: All except {_format_list(read_scope.get('except') or [])}")
    else:
        print("ReadableScope: All")

    write_scope = result.get("write_scope") or {}
    if write_scope.get("mode") == "only":
        print(f"WritableScope: Only {_format_list(write_scope.get('paths') or [])}")
    else:
        print(
            "WritableScope: All except read-only roots "
            + _format_list(write_scope.get("read_only_roots") or [])
            + " and inaccessible paths "
            + _format_list(write_scope.get("inaccessible_paths") or [])
            + "; writable exceptions "
            + _format_list(write_scope.get("writable_exceptions") or []),
        )

    hint = result.get("prefer_state_runtime_directory_hint") or {}
    if hint.get("triggered"):
        print("HintPreferStateRuntimeDirectory: yes")
        print(f"HintPaths: {_format_list(hint.get('paths') or [])}")
        if hint.get("message"):
            print(f"HintMessage: {hint['message']}")
    else:
        print("HintPreferStateRuntimeDirectory: no")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="check_service_fs_scope",
        description="Check systemd services' filesystem sandbox settings via systemctl show.",
    )
    parser.add_argument("service", nargs="?", help="systemd unit name, e.g. dbus.service or ssh.service")
    parser.add_argument(
        "--services-file",
        help="Path to a file containing unit names (one per line).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON to stdout (useful for CI pipelines).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="systemctl timeout seconds (default: 5).",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    try:
        services = _load_services(args.service, args.services_file)

        results: list[dict[str, Any]] = []
        any_error = False
        any_not_found = False

        for index, service in enumerate(services):
            if index > 0 and not args.json:
                print("")

            try:
                output = systemctl_show(service, SYSTEMCTL_PROPERTIES, args.timeout)
                kv = _parse_systemctl_show(output)
                result = _build_result(service, kv)
                results.append(result)

                if result.get("status") == "not-found":
                    any_not_found = True

                if args.json:
                    continue

                _print_text_report(result)
                if result.get("status") == "not-found":
                    print(f"ERROR: service not found: {service}", file=sys.stderr)
            except FileNotFoundError:
                raise
            except subprocess.TimeoutExpired:
                any_error = True
                error_result = {"service": service, "status": "error", "error": f"systemctl timed out after {args.timeout}s"}
                results.append(error_result)
                if not args.json:
                    print(f"ERROR: {error_result['error']}", file=sys.stderr)
            except Exception as exc:
                any_error = True
                error_result = {"service": service, "status": "error", "error": str(exc)}
                results.append(error_result)
                if not args.json:
                    print(f"ERROR: {error_result['error']}", file=sys.stderr)

        if args.json:
            payload = {"results": results, "summary": _build_summary(results)}
            print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
        elif len(services) > 1:
            summary = _build_summary(results)
            print("")
            print("Summary: " + " ".join(f"{k}={v}" for k, v in summary.items()))

        if any_not_found:
            return 2
        if any_error:
            return 1
        return 0
    except FileNotFoundError as exc:
        exit_code, message = classify_file_not_found(exc, {"systemctl"})
        print(message, file=sys.stderr)
        return exit_code
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
