#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any


# 基于 DBus 安全检查表的约定：
# - User 为空时认为是 root，此时以 CapabilityBoundingSet 作为“实际 Cap”
# - User 非空时以 AmbientCapabilities 作为“实际 Cap”
EXIT_CAP_MISMATCH = 3

SYSTEMCTL_PROPERTIES = (
    "LoadState",
    "User",
    "Group",
    "SupplementaryGroups",
    "CapabilityBoundingSet",
    "AmbientCapabilities",
)

_ZERO_WIDTH_TRANSLATION = str.maketrans(
    "",
    "",
    "\ufeff\u200b\u200c\u200d\u2060",
)


def _split_tokens(value: str) -> list[str]:
    value = value.strip()
    if not value:
        return []
    return [token for token in value.split() if token]


def _sanitize_line(raw: str) -> str:
    return raw.strip().translate(_ZERO_WIDTH_TRANSLATION)


def _read_non_empty_lines(path: str) -> list[str]:
    items: list[str] = []
    with open(path, "r", encoding="utf-8-sig") as handle:
        for raw in handle:
            line = _sanitize_line(raw)
            if not line or line.startswith("#"):
                continue
            items.append(line)
    return items


def _normalize_cap_token(token: str) -> str:
    return token.strip().lower()


def _normalize_cap_list(tokens: list[str]) -> list[str]:
    normalized = [_normalize_cap_token(t) for t in tokens if t.strip()]
    return sorted({t for t in normalized if t})


def _parse_systemctl_show(output: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value
    return result


def _run_systemctl_show(service: str, timeout_seconds: float) -> str:
    args = ["systemctl", "--no-pager", "show", service]
    for prop in SYSTEMCTL_PROPERTIES:
        args.append(f"--property={prop}")

    env = os.environ.copy()
    env.setdefault("SYSTEMD_COLORS", "0")
    env.setdefault("SYSTEMD_PAGER", "")

    completed = subprocess.run(
        args,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_seconds,
        env=env,
    )

    if completed.returncode != 0:
        if (completed.stdout or "").strip():
            return completed.stdout
        message = (completed.stderr or "").strip() or "systemctl show failed"
        raise RuntimeError(message)

    return completed.stdout


def _build_result(service: str, kv: dict[str, str]) -> dict[str, Any]:
    load_state = (kv.get("LoadState") or "").strip()

    user_field = kv.get("User") or ""
    user = user_field.strip() or "root"
    is_root = (not user_field.strip()) or user.lower() == "root"

    group = (kv.get("Group") or "").strip()
    supplementary_groups = _split_tokens(kv.get("SupplementaryGroups") or "")
    groups = sorted({g for g in ([group] if group else []) + supplementary_groups})

    capability_bounding_set = _split_tokens(kv.get("CapabilityBoundingSet") or "")
    ambient_capabilities = _split_tokens(kv.get("AmbientCapabilities") or "")

    if is_root:
        effective_capabilities = capability_bounding_set
        rule = "root->CapabilityBoundingSet"
    else:
        effective_capabilities = ambient_capabilities
        rule = "non-root->AmbientCapabilities"

    return {
        "service": service,
        "load_state": load_state,
        "user": user,
        "group": group,
        "supplementary_groups": supplementary_groups,
        "groups": groups,
        "capability_bounding_set": capability_bounding_set,
        "ambient_capabilities": ambient_capabilities,
        "effective_capabilities": effective_capabilities,
        "rule": rule,
    }


def _format_list(values: list[str]) -> str:
    return " ".join(values) if values else "(none)"


def _print_text_report(result: dict[str, Any]) -> None:
    print(f"Service: {result['service']}")
    if result.get("load_state"):
        print(f"LoadState: {result['load_state']}")
    print(f"User: {result['user']}")
    print(f"Group: {result.get('group') or '(none)'}")
    print(f"SupplementaryGroups: {_format_list(result.get('supplementary_groups') or [])}")
    print(f"Groups: {_format_list(result.get('groups') or [])}")
    print(f"CapabilityBoundingSet: {_format_list(result.get('capability_bounding_set') or [])}")
    print(f"AmbientCapabilities: {_format_list(result.get('ambient_capabilities') or [])}")
    print(f"EffectiveCapabilities: {_format_list(result.get('effective_capabilities') or [])}")
    print(f"Rule: {result['rule']}")

    if "expected_capabilities" in result:
        print(f"ExpectedCapabilities: {_format_list(result.get('expected_capabilities') or [])}")
        print(f"MatchExpected: {bool(result.get('match_expected'))}")
        if result.get("missing_capabilities"):
            print(f"MissingCapabilities: {_format_list(result.get('missing_capabilities') or [])}")
        if result.get("unexpected_capabilities"):
            print(f"UnexpectedCapabilities: {_format_list(result.get('unexpected_capabilities') or [])}")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="check_service_cap",
        description="Check systemd services' User/Group/Capabilities via systemctl show.",
    )
    parser.add_argument("service", nargs="?", help="systemd unit name, e.g. dbus.service or ssh.service")
    parser.add_argument(
        "--services-file",
        help="Path to a file containing unit names (one per line).",
    )
    parser.add_argument(
        "--expected-caps",
        help="Path to a file containing expected effective capability tokens (one per line).",
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

def _compare_effective_caps(actual_caps: list[str], expected_caps: list[str]) -> tuple[bool, list[str], list[str]]:
    actual_set = set(_normalize_cap_list(actual_caps))
    expected_set = set(_normalize_cap_list(expected_caps))
    missing = sorted(expected_set - actual_set)
    unexpected = sorted(actual_set - expected_set)
    return (not missing and not unexpected), missing, unexpected


def _load_expected_caps(path: str | None) -> list[str] | None:
    if not path:
        return None
    lines = _read_non_empty_lines(path)
    tokens: list[str] = []
    for line in lines:
        tokens.extend(_split_tokens(line))
    return _normalize_cap_list(tokens)


def _load_services(service: str | None, services_file: str | None) -> list[str]:
    if service and services_file:
        raise ValueError("service and --services-file are mutually exclusive")
    if not service and not services_file:
        raise ValueError("either a service argument or --services-file is required")

    if service:
        return [_sanitize_line(service)]

    services = _read_non_empty_lines(services_file or "")
    if not services:
        raise ValueError("services file is empty")
    return services


def _build_summary(results: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(results), "ok": 0, "mismatch": 0, "not_found": 0, "error": 0}
    for r in results:
        status = (r.get("status") or "").lower()
        if status == "ok":
            summary["ok"] += 1
        elif status == "mismatch":
            summary["mismatch"] += 1
        elif status == "not-found":
            summary["not_found"] += 1
        else:
            summary["error"] += 1
    return summary


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    try:
        services = _load_services(args.service, args.services_file)
        expected_caps = _load_expected_caps(args.expected_caps)

        results: list[dict[str, Any]] = []
        any_error = False
        any_not_found = False
        any_mismatch = False

        for index, service in enumerate(services):
            if index > 0 and not args.json:
                print("")

            try:
                output = _run_systemctl_show(service, args.timeout)
                kv = _parse_systemctl_show(output)
                result = _build_result(service, kv)

                load_state = (result.get("load_state") or "").lower()
                if load_state == "not-found":
                    result["status"] = "not-found"
                    any_not_found = True
                else:
                    result["status"] = "ok"

                if expected_caps is not None and result.get("status") == "ok":
                    match, missing, unexpected = _compare_effective_caps(
                        result.get("effective_capabilities") or [],
                        expected_caps,
                    )
                    result["expected_capabilities"] = expected_caps
                    result["match_expected"] = match
                    result["missing_capabilities"] = missing
                    result["unexpected_capabilities"] = unexpected
                    if not match:
                        result["status"] = "mismatch"
                        any_mismatch = True

                results.append(result)

                if args.json:
                    continue

                _print_text_report(result)
                if result.get("status") == "not-found":
                    print(f"ERROR: service not found: {service}", file=sys.stderr)
                elif result.get("status") == "mismatch":
                    print(f"ERROR: capabilities mismatch: {service}", file=sys.stderr)
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
            print(
                "Summary: "
                + " ".join(f"{k}={v}" for k, v in summary.items()),
            )

        if any_mismatch:
            return EXIT_CAP_MISMATCH
        if any_not_found:
            return 2
        if any_error:
            return 1
        return 0
    except FileNotFoundError:
        print("ERROR: systemctl not found in PATH", file=sys.stderr)
        return 127
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
