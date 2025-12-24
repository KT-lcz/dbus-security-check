#!/usr/bin/env python3
import argparse
import hashlib
import json
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import Any, Dict, List


REQUIRED_TOP_KEYS = {"input", "summary", "access_control", "confidence"}
REQUIRED_INPUT_KEYS = {"path", "interface", "method"}


def load_prompt_template(path: Path) -> Template:
    text = path.read_text(encoding="utf-8")
    return Template(text)


def normalize_entry(entry: Dict[str, Any], index: int) -> Dict[str, str]:
    if not isinstance(entry, dict):
        raise ValueError(f"Invalid entry at index {index}: must be an object")
    path = entry.get("path") or entry.get("dbus_path") or entry.get("object_path")
    interface = entry.get("interface") or entry.get("dbus_interface")
    method = entry.get("method") or entry.get("member")
    if not path or not interface or not method:
        raise ValueError(f"Missing fields at index {index}: path/interface/method required")
    if not isinstance(path, str) or not isinstance(interface, str) or not isinstance(method, str):
        raise ValueError(f"Invalid field types at index {index}: path/interface/method must be strings")
    return {"path": path, "interface": interface, "method": method}


def load_methods_file(path: Path) -> List[Dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("Methods file is empty")
    stripped = text.lstrip()
    entries: List[Dict[str, Any]]
    # 同时支持 JSON 数组与 JSONL
    if stripped.startswith("["):
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("Methods file JSON must be an array")
        entries = data
    else:
        entries = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_no}: {exc}") from exc
    return [normalize_entry(entry, idx) for idx, entry in enumerate(entries, start=1)]


def build_method_id(entry: Dict[str, str]) -> str:
    base = f"{entry['path']}|{entry['interface']}|{entry['method']}"
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:8]
    slug = f"{entry['interface']}_{entry['method']}"
    safe = "".join(ch if ch.isalnum() else "_" for ch in slug)
    return f"{safe[:40]}_{digest}"


def run_codex(cmd: str, prompt: str, cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    args = shlex.split(cmd)
    return subprocess.run(
        args,
        input=prompt,
        text=True,
        capture_output=True,
        cwd=str(cwd),
        timeout=timeout,
        check=False,
    )


def parse_json_output(output: str) -> Dict[str, Any]:
    output = output.strip()
    if not output:
        raise ValueError("Empty codex output")
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Codex output is not valid JSON: {exc}") from exc


def validate_output(payload: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not isinstance(payload, dict):
        return ["Output must be a JSON object"]
    missing = REQUIRED_TOP_KEYS - set(payload.keys())
    if missing:
        errors.append(f"Missing top-level keys: {sorted(missing)}")
    input_obj = payload.get("input")
    if not isinstance(input_obj, dict):
        errors.append("Input must be an object")
    else:
        missing_input = REQUIRED_INPUT_KEYS - set(input_obj.keys())
        if missing_input:
            errors.append(f"Missing input keys: {sorted(missing_input)}")
    return errors


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch check DBus method access control with codex exec.")
    parser.add_argument("--methods-file", required=True, help="Path to JSON array or JSONL methods file.")
    parser.add_argument(
        "--prompt-file",
        default="prompts/dbus_method_access_control.md",
        help="Path to prompt template.",
    )
    parser.add_argument("--project-root", default=".", help="Project root for codex execution.")
    parser.add_argument("--codex-cmd", default="codex exec --skip-git-repo-check", help="Codex exec command.")
    parser.add_argument("--timeout", type=int, default=300, help="Per-method timeout in seconds.")
    parser.add_argument("--output-dir", default="out", help="Output directory.")
    args = parser.parse_args()

    methods_file = Path(args.methods_file)
    prompt_file = Path(args.prompt_file)
    project_root = Path(args.project_root)
    output_dir = Path(args.output_dir)
    per_method_dir = output_dir / "per_method"
    raw_dir = output_dir / "raw"

    try:
        methods = load_methods_file(methods_file)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not prompt_file.exists():
        print(f"ERROR: Prompt file not found: {prompt_file}", file=sys.stderr)
        return 2

    template = load_prompt_template(prompt_file)
    per_method_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    summary: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(project_root),
        "methods_file": str(methods_file),
        "prompt_file": str(prompt_file),
        "results": [],
        "errors": [],
    }

    for entry in methods:
        method_id = build_method_id(entry)
        print(f"INFO: Running codex for {entry['interface']}.{entry['method']} ({method_id})")
        prompt = template.safe_substitute(
            dbus_path=entry["path"],
            dbus_interface=entry["interface"],
            dbus_method=entry["method"],
        )
        result = run_codex(args.codex_cmd, prompt, project_root, args.timeout)
        raw_path = raw_dir / f"{method_id}.txt"
        raw_path.write_text(result.stdout + result.stderr, encoding="utf-8")

        if result.returncode != 0:
            error_msg = f"codex exec failed with code {result.returncode}"
            print(f"ERROR: {error_msg}", file=sys.stderr)
            summary["errors"].append(
                {"id": method_id, "input": entry, "error": error_msg, "raw_output": str(raw_path)}
            )
            write_json(
                per_method_dir / f"{method_id}.json",
                {"input": entry, "error": error_msg, "raw_output": str(raw_path)},
            )
            continue

        try:
            payload = parse_json_output(result.stdout)
            validation_errors = validate_output(payload)
            if validation_errors:
                raise ValueError("; ".join(validation_errors))
        except ValueError as exc:
            error_msg = str(exc)
            print(f"ERROR: {error_msg}", file=sys.stderr)
            summary["errors"].append(
                {"id": method_id, "input": entry, "error": error_msg, "raw_output": str(raw_path)}
            )
            write_json(
                per_method_dir / f"{method_id}.json",
                {"input": entry, "error": error_msg, "raw_output": str(raw_path)},
            )
            continue

        output_path = per_method_dir / f"{method_id}.json"
        write_json(output_path, payload)
        summary["results"].append(
            {"id": method_id, "input": entry, "output": str(output_path), "raw_output": str(raw_path)}
        )

    summary_path = output_dir / "summary.json"
    write_json(summary_path, summary)
    print(f"INFO: Summary written to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
