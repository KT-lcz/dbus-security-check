#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections import deque
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as element_tree
from typing import Any, Iterable

from _common import classify_file_not_found, dpkg_query_owners, read_non_empty_lines, run_command


# 基于 DBus 安全检查表的约定：
# - 扫描 system bus 配置目录下所有 *.conf（XML）
# - 功能 1：定位 <policy context="default"> 下的 <allow own="...">，输出 conf 文件与所属 deb 包（dpkg-query -S 反查）
# - 功能 2：读取 system bus service（bus name）列表，识别 allow own 允许 root 的 service：
#          枚举该 service 的所有 method，并剔除 default policy 中 deny 管控的 method，输出残留 method 与所属 deb 包

DEFAULT_SEARCH_DIRS = (
    "/etc/dbus-1/system.d",
    "/usr/share/dbus-1/system.d",
)

SYSTEM_COMMANDS = {
    "busctl": "busctl",
    "dpkg_query": "dpkg-query",
}

EXCLUDED_METHOD_INTERFACES = {
    "org.freedesktop.DBus.Introspectable",
    "org.freedesktop.DBus.Properties",
    "org.freedesktop.DBus.Peer",
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


def _scan_conf_file(
    conf_file: str,
    allow_own_index: dict[str, list[dict[str, Any]]],
    default_deny_index: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    tree = element_tree.parse(conf_file)
    root = tree.getroot()

    default_allow_owns: set[str] = set()

    for policy in root.iter():
        if _local_name(policy.tag) != "policy":
            continue

        policy_user = (policy.attrib.get("user") or "").strip() or None
        policy_group = (policy.attrib.get("group") or "").strip() or None
        policy_context = (policy.attrib.get("context") or "").strip() or None

        for child in list(policy):
            tag = _local_name(child.tag)
            if tag == "allow":
                own = (child.attrib.get("own") or "").strip()
                if not own:
                    continue
                allow_own_index.setdefault(own, []).append(
                    {
                        "conf_file": conf_file,
                        "policy_user": policy_user,
                        "policy_group": policy_group,
                        "policy_context": policy_context,
                    },
                )
                if policy_context == "default":
                    default_allow_owns.add(own)
            elif tag == "deny":
                if policy_context != "default":
                    continue
                send_destination = (child.attrib.get("send_destination") or "").strip()
                if not send_destination:
                    continue
                default_deny_index.setdefault(send_destination, []).append(
                    {
                        "conf_file": conf_file,
                        "send_destination": send_destination,
                        "send_type": (child.attrib.get("send_type") or "").strip() or None,
                        "send_path": (child.attrib.get("send_path") or "").strip() or None,
                        "send_path_prefix": (child.attrib.get("send_path_prefix") or "").strip() or None,
                        "send_interface": (child.attrib.get("send_interface") or "").strip() or None,
                        "send_member": (child.attrib.get("send_member") or "").strip() or None,
                    },
                )

    return {
        "conf_file": conf_file,
        "status": "ok",
        "flagged": bool(default_allow_owns),
        "allow_own_in_default_policy": sorted(default_allow_owns),
        "findings_count": len(default_allow_owns),
        "packages": [],
    }


def _build_conf_summary(results: list[dict[str, Any]]) -> dict[str, int]:
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


def _print_conf_finding(result: dict[str, Any]) -> None:
    print(f"ConfFile: {result['conf_file']}")
    print(f"Packages: {_format_list(result.get('packages') or [], empty='(unknown)')}")
    print(f"AllowOwnInDefaultPolicy: {_format_list(result.get('allow_own_in_default_policy') or [], empty='(none)')}")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="check_dbus_system_conf",
        description="Scan DBus system bus .conf files and report risky patterns (default allow-own; or root-owned service methods not denied in default policy).",
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
        "--services-file",
        help="Path to a file containing D-Bus bus names (one per line). Enables root service method report mode.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON to stdout (useful for CI pipelines).",
    )
    parser.add_argument(
        "--only-flagged",
        action="store_true",
        help="Only include flagged records (and errors) in JSON results.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Command timeout seconds (default: 5).",
    )
    return parser.parse_args(argv)


def _is_root_service(entries: list[dict[str, Any]]) -> bool:
    return any((e.get("policy_user") or "").lower() == "root" for e in entries)


def _join_object_path(parent: str, child: str) -> str:
    child = child.strip()
    if not child:
        return parent
    if child.startswith("/"):
        return child
    if parent == "/":
        return "/" + child.lstrip("/")
    return parent.rstrip("/") + "/" + child.lstrip("/")


def _matches_default_deny(rule: dict[str, Any], service: str, path: str, interface: str, method: str) -> bool:
    if (rule.get("send_destination") or "") != service:
        return False

    send_type = (rule.get("send_type") or "").strip().lower()
    if send_type and send_type != "method_call":
        return False

    rule_path = rule.get("send_path")
    if rule_path and rule_path != path:
        return False

    rule_prefix = rule.get("send_path_prefix")
    if rule_prefix:
        prefix = rule_prefix.rstrip("/")
        if path != prefix and not path.startswith(prefix + "/"):
            return False

    rule_interface = rule.get("send_interface")
    if rule_interface and rule_interface != interface:
        return False

    rule_member = rule.get("send_member")
    if rule_member and rule_member != method:
        return False

    return True


def _busctl_introspect_xml(service: str, object_path: str, timeout_seconds: float) -> str:
    args = [
        SYSTEM_COMMANDS["busctl"],
        "--system",
        "--no-pager",
        "--no-legend",
        "--xml-interface",
        "--auto-start=yes",
        f"--timeout={timeout_seconds}",
        "introspect",
        service,
        object_path,
    ]
    completed = run_command(args, timeout_seconds)
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip() or "busctl introspect failed"
        raise RuntimeError(message)
    return completed.stdout


def _collect_methods_not_denied(
    service: str,
    deny_rules: list[dict[str, Any]],
    timeout_seconds: float,
) -> tuple[dict[str, dict[str, list[str]]], dict[str, int], list[dict[str, str]]]:
    queue: deque[str] = deque(["/"])
    visited: set[str] = set()
    methods_tree: dict[str, dict[str, list[str]]] = {}

    total_methods = 0
    denied_methods = 0
    remaining_methods = 0
    errors: list[dict[str, str]] = []

    while queue:
        object_path = queue.popleft()
        if object_path in visited:
            continue
        visited.add(object_path)

        try:
            xml_text = _busctl_introspect_xml(service, object_path, timeout_seconds)
            node = element_tree.fromstring(xml_text)
        except element_tree.ParseError as exc:
            errors.append({"object_path": object_path, "error": f"introspection xml parse error: {exc}"})
            continue
        except FileNotFoundError:
            raise
        except Exception as exc:
            errors.append({"object_path": object_path, "error": str(exc)})
            continue

        for child in node:
            tag = _local_name(child.tag)
            if tag == "node":
                name = (child.attrib.get("name") or "").strip()
                if not name:
                    continue
                queue.append(_join_object_path(object_path, name))
                continue
            if tag != "interface":
                continue

            interface_name = (child.attrib.get("name") or "").strip()
            if not interface_name:
                continue
            if interface_name in EXCLUDED_METHOD_INTERFACES:
                continue

            for member in child:
                if _local_name(member.tag) != "method":
                    continue
                method_name = (member.attrib.get("name") or "").strip()
                if not method_name:
                    continue

                total_methods += 1
                if any(_matches_default_deny(r, service, object_path, interface_name, method_name) for r in deny_rules):
                    denied_methods += 1
                    continue

                remaining_methods += 1
                methods_tree.setdefault(object_path, {}).setdefault(interface_name, []).append(method_name)

    for object_path, interfaces in methods_tree.items():
        for interface_name, methods in interfaces.items():
            interfaces[interface_name] = sorted(set(methods))
        methods_tree[object_path] = {k: interfaces[k] for k in sorted(interfaces)}

    stats = {
        "object_paths_scanned": len(visited),
        "methods_total": total_methods,
        "methods_denied_by_default_policy": denied_methods,
        "methods_remaining": remaining_methods,
        "deny_rules_count": len(deny_rules),
    }
    return methods_tree, stats, errors


def _build_service_summary(results: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(results), "ok": 0, "uncontrolled": 0, "not_found": 0, "not_root": 0, "error": 0, "flagged": 0}
    for r in results:
        status = (r.get("status") or "").lower()
        if status == "ok":
            summary["ok"] += 1
        elif status == "uncontrolled":
            summary["uncontrolled"] += 1
        elif status == "not-found":
            summary["not_found"] += 1
        elif status == "not-root":
            summary["not_root"] += 1
        else:
            summary["error"] += 1
        if r.get("flagged"):
            summary["flagged"] += 1
    return summary


def _print_service_finding(result: dict[str, Any]) -> None:
    print(f"Service: {result['service']}")
    print(f"Status: {result.get('status') or '(unknown)'}")
    print(f"Packages: {_format_list(result.get('packages') or [], empty='(unknown)')}")
    if result.get("conf_files"):
        print(f"ConfFiles: {_format_list(result.get('conf_files') or [], empty='(unknown)')}")
    if result.get("stats"):
        stats = result.get("stats") or {}
        print(
            "Stats: "
            + " ".join(
                f"{k}={v}"
                for k, v in stats.items()
            ),
        )

    if result.get("errors"):
        first = (result.get("errors") or [{}])[0] or {}
        message = (first.get("error") or "").strip()
        if message:
            print(f"Error: {message}")

    methods = result.get("methods") or {}
    if not methods:
        print("Findings: (none)")
        return

    for object_path in sorted(methods):
        print(f"ObjectPath: {object_path}")
        interfaces = methods.get(object_path) or {}
        for interface_name in sorted(interfaces):
            print(f"  Interface: {interface_name}")
            for method_name in interfaces.get(interface_name) or []:
                print(f"    Method: {method_name}")


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    try:
        conf_files, missing_dirs = _iter_conf_files([args.etc_dir, args.usr_dir])
        if missing_dirs and not conf_files:
            raise ValueError("no .conf files found; directories not found: " + ", ".join(missing_dirs))

        owners_cache: dict[str, list[str]] = {}
        conf_results: list[dict[str, Any]] = []
        allow_own_index: dict[str, list[dict[str, Any]]] = {}
        default_deny_index: dict[str, list[dict[str, Any]]] = {}
        any_error = False
        printed_findings = 0

        if missing_dirs and not args.json:
            for directory in missing_dirs:
                print(f"WARNING: directory not found: {directory}", file=sys.stderr)

        for conf_file in conf_files:
            try:
                conf_results.append(_scan_conf_file(conf_file, allow_own_index, default_deny_index))
            except FileNotFoundError:
                raise
            except subprocess.TimeoutExpired:
                any_error = True
                message = f"command timed out after {args.timeout}s"
                conf_results.append({"conf_file": conf_file, "status": "error", "error": message, "packages": []})
                if not args.json and not args.services_file:
                    print(f"ERROR: {message}", file=sys.stderr)
            except element_tree.ParseError as exc:
                any_error = True
                message = f"xml parse error: {exc}"
                conf_results.append({"conf_file": conf_file, "status": "error", "error": message, "packages": []})
                if not args.json and not args.services_file:
                    print(f"ERROR: {message}", file=sys.stderr)
            except Exception as exc:
                any_error = True
                conf_results.append({"conf_file": conf_file, "status": "error", "error": str(exc), "packages": []})
                if not args.json and not args.services_file:
                    print(f"ERROR: {exc}", file=sys.stderr)

        # 模式 2：基于 services 列表输出 root service 的未被 deny 覆盖的 method
        if args.services_file:
            services = read_non_empty_lines(args.services_file)
            if not services:
                raise ValueError("services file is empty")

            service_results: list[dict[str, Any]] = []
            any_not_found = False

            for service in services:
                entries = allow_own_index.get(service) or []
                conf_files_for_service = sorted({e.get("conf_file") for e in entries if e.get("conf_file")})

                if not entries:
                    any_not_found = True
                    service_results.append({"service": service, "status": "not-found", "flagged": False})
                    continue

                if not _is_root_service(entries):
                    service_results.append(
                        {
                            "service": service,
                            "status": "not-root",
                            "flagged": False,
                            "conf_files": conf_files_for_service,
                            "packages": [],
                        },
                    )
                    continue

                packages: set[str] = set()
                for conf_file in conf_files_for_service:
                    if conf_file not in owners_cache:
                        owners_cache[conf_file] = dpkg_query_owners(conf_file, args.timeout)
                    packages.update(owners_cache[conf_file])

                deny_rules = default_deny_index.get(service) or []
                methods, stats, errors = _collect_methods_not_denied(service, deny_rules, args.timeout)
                flagged = bool(methods)
                if errors:
                    any_error = True
                status = "error" if errors else ("uncontrolled" if flagged else "ok")

                service_results.append(
                    {
                        "service": service,
                        "status": status,
                        "flagged": flagged,
                        "conf_files": conf_files_for_service,
                        "packages": sorted(packages),
                        "methods": methods,
                        "stats": stats,
                        "errors": errors,
                    },
                )

            summary = _build_service_summary(service_results)
            output_results = service_results
            if args.only_flagged:
                output_results = [
                    r
                    for r in service_results
                    if r.get("status") in {"error", "not-found"} or bool(r.get("flagged"))
                ]

            if args.json:
                payload: dict[str, Any] = {"results": output_results, "summary": summary}
                if missing_dirs:
                    payload["missing_dirs"] = missing_dirs
                print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                printed = 0
                for r in service_results:
                    if printed > 0:
                        print("")
                    _print_service_finding(r)
                    printed += 1

                if len(services) > 1:
                    print("")
                    print("Summary: " + " ".join(f"{k}={v}" for k, v in summary.items()))

            if any_not_found:
                return 2
            if any_error:
                return 1
            return 0

        # 模式 1：输出 default policy 下 allow own
        for r in conf_results:
            if (r.get("status") or "").lower() != "ok":
                continue
            allow_owns = r.get("allow_own_in_default_policy") or []
            if not allow_owns:
                continue
            conf_file = r.get("conf_file") or ""
            if conf_file and conf_file not in owners_cache:
                owners_cache[conf_file] = dpkg_query_owners(conf_file, args.timeout)
            r["packages"] = owners_cache.get(conf_file) or []

        summary = _build_conf_summary(conf_results)
        output_results = conf_results
        if args.only_flagged:
            output_results = [
                r
                for r in conf_results
                if r.get("status") != "ok" or bool(r.get("flagged"))
            ]

        if args.json:
            payload: dict[str, Any] = {"results": output_results, "summary": summary}
            if missing_dirs:
                payload["missing_dirs"] = missing_dirs
            print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
        else:
            for r in conf_results:
                if (r.get("status") or "").lower() != "ok":
                    continue
                allow_owns = r.get("allow_own_in_default_policy") or []
                if not allow_owns:
                    continue
                if printed_findings > 0:
                    print("")
                _print_conf_finding(r)
                printed_findings += 1

            if len(conf_files) > 1:
                print("")
                print("Summary: " + " ".join(f"{k}={v}" for k, v in summary.items()))
            elif len(conf_files) == 1 and printed_findings == 0:
                print(f"ConfFile: {conf_files[0]}")
                print("Findings: (none)")

        if any_error:
            return 1
        return 0
    except FileNotFoundError as exc:
        exit_code, message = classify_file_not_found(exc, {SYSTEM_COMMANDS["dpkg_query"], SYSTEM_COMMANDS["busctl"]})
        print(message, file=sys.stderr)
        return exit_code
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
