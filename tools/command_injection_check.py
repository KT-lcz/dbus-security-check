#!/usr/bin/env python3
import argparse
import json
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import Any, Dict, List


CHECK_TYPE_CONFIG = {
    "command_injection": {
        "prompt_file": "prompts/command_injection_check.md",
        "required_keys": {
            "check_type",
            "summary",
            "explicit_shell_exec",
            "implicit_shell_exec",
            "confidence",
        },
    }
}


def load_prompt_template(path: Path) -> Template:
    text = path.read_text(encoding="utf-8")
    return Template(text)


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


def validate_output(payload: Dict[str, Any], check_type: str) -> List[str]:
    errors: List[str] = []
    if not isinstance(payload, dict):
        return ["Output must be a JSON object"]
    missing = CHECK_TYPE_CONFIG[check_type]["required_keys"] - set(payload.keys())
    if missing:
        errors.append(f"Missing top-level keys: {sorted(missing)}")
    if payload.get("check_type") not in (check_type, "unknown"):
        errors.append("check_type mismatch")
    return errors


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run static code checks with codex exec.")
    parser.add_argument("--project-root", required=True, help="Path to the target project root.")
    parser.add_argument(
        "--check-type",
        required=True,
        choices=sorted(CHECK_TYPE_CONFIG.keys()),
        help="Check type to run.",
    )
    parser.add_argument("--codex-cmd", default="codex exec --skip-git-repo-check", help="Codex exec command.")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout in seconds.")
    parser.add_argument("--output-dir", default="out", help="Output directory.")
    parser.add_argument("--prompt-file", default=None, help="Override prompt template path.")
    args = parser.parse_args()

    project_root = Path(args.project_root)
    if not project_root.exists():
        print(f"ERROR: Project root not found: {project_root}", file=sys.stderr)
        return 2

    prompt_file = Path(args.prompt_file) if args.prompt_file else Path(
        CHECK_TYPE_CONFIG[args.check_type]["prompt_file"]
    )
    if not prompt_file.exists():
        print(f"ERROR: Prompt file not found: {prompt_file}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir) / args.check_type
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "raw.txt"
    result_path = output_dir / "result.json"
    meta_path = output_dir / "meta.json"

    template = load_prompt_template(prompt_file)
    prompt = template.safe_substitute()
    result = run_codex(args.codex_cmd, prompt, project_root, args.timeout)
    raw_path.write_text(result.stdout + result.stderr, encoding="utf-8")

    if result.returncode != 0:
        error_msg = f"codex exec failed with code {result.returncode}"
        print(f"ERROR: {error_msg}", file=sys.stderr)
        write_json(result_path, {"check_type": args.check_type, "error": error_msg, "raw_output": str(raw_path)})
        write_json(
            meta_path,
            {
                "check_type": args.check_type,
                "project_root": str(project_root),
                "prompt_file": str(prompt_file),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "status": "error",
            },
        )
        return 1

    try:
        payload = parse_json_output(result.stdout)
        validation_errors = validate_output(payload, args.check_type)
        if validation_errors:
            raise ValueError("; ".join(validation_errors))
    except ValueError as exc:
        error_msg = str(exc)
        print(f"ERROR: {error_msg}", file=sys.stderr)
        write_json(result_path, {"check_type": args.check_type, "error": error_msg, "raw_output": str(raw_path)})
        write_json(
            meta_path,
            {
                "check_type": args.check_type,
                "project_root": str(project_root),
                "prompt_file": str(prompt_file),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "status": "invalid_output",
            },
        )
        return 1

    write_json(result_path, payload)
    write_json(
        meta_path,
        {
            "check_type": args.check_type,
            "project_root": str(project_root),
            "prompt_file": str(prompt_file),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "ok",
            "result": str(result_path),
            "raw_output": str(raw_path),
        },
    )
    print(f"INFO: Result written to {result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
