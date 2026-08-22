#!/usr/bin/env python3
"""Utilities used by the reusable pull-request review workflow."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path, PurePosixPath
from typing import Any


LOGGER = logging.getLogger("pr-code-review")
REQUIRED_REVIEW_KEYS = {"verdict", "summary", "findings"}
MAX_DIAGNOSTIC_LINES = 80


def create_schema(output: Path) -> None:
    LOGGER.info("Using built-in review schema")
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["verdict", "summary", "findings"],
        "properties": {
            "verdict": {"type": "string", "enum": ["PASS", "FAIL"]},
            "summary": {"type": "string", "minLength": 1, "maxLength": 2000},
            "findings": {
                "type": "array",
                "maxItems": 25,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["priority", "path", "line", "title", "body"],
                    "properties": {
                        "priority": {
                            "type": "string",
                            "enum": ["P0", "P1", "P2"],
                        },
                        "path": {"type": "string", "minLength": 1, "maxLength": 500},
                        "line": {"type": "integer", "minimum": 1},
                        "title": {"type": "string", "minLength": 1, "maxLength": 300},
                        "body": {"type": "string", "minLength": 1, "maxLength": 4000},
                    },
                },
            },
        },
    }
    LOGGER.info("Writing review schema to %s", output)
    output.write_text(json.dumps(schema), encoding="utf-8")
    LOGGER.info("Review schema created successfully")


def configure_antigravity(settings_file: Path) -> None:
    LOGGER.info("Configuring Antigravity settings at %s", settings_file)
    try:
        settings = json.loads(settings_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        LOGGER.info("Settings file does not exist; creating it")
        settings = {}
    if not isinstance(settings, dict):
        raise ValueError("Antigravity settings must be a JSON object")
    settings["enableTerminalSandbox"] = True
    settings["toolPermission"] = "proceed-in-sandbox"
    settings_file.write_text(json.dumps(settings), encoding="utf-8")
    LOGGER.info("Antigravity sandbox settings configured successfully")


def load_json(path: Path) -> Any:
    LOGGER.info("Loading JSON from %s", path)
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_antigravity_envelope(input_file: Path) -> None:
    LOGGER.info("Validating Antigravity CLI response envelope")
    result = load_json(input_file)
    if not isinstance(result, dict):
        raise ValueError("Antigravity result must be a JSON object")
    if result.get("status") != "SUCCESS":
        raise ValueError(result.get("error") or "Antigravity returned an unknown error")
    if not result.get("response"):
        raise ValueError("Antigravity completed without a review response")
    LOGGER.info("Antigravity CLI response envelope is valid")


def report_failure(engine: str, exit_code: int, log_file: Path) -> None:
    LOGGER.error("%s review command failed with exit code %d", engine, exit_code)
    try:
        log_text = log_file.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        LOGGER.error("Diagnostic log does not exist: %s", log_file)
        return

    normalized_log = log_text.lower()
    if engine == "codex" and (
        "refresh_token_reused" in normalized_log
        or "provided authentication token is expired" in normalized_log
    ):
        LOGGER.error(
            "Codex authentication expired and could not be refreshed. Sign in to Codex "
            "again and replace the CODEX_AUTH_JSON repository secret."
        )
    elif "401 unauthorized" in normalized_log:
        LOGGER.error(
            "%s authentication was rejected. Refresh the corresponding repository secret.",
            engine,
        )

    lines = log_text.splitlines()
    if not lines:
        LOGGER.error("Diagnostic log is empty: %s", log_file)
        return
    visible_lines = lines[-MAX_DIAGNOSTIC_LINES:]
    LOGGER.error(
        "Last %d diagnostic lines from %s%s:",
        len(visible_lines),
        log_file,
        " (truncated)" if len(lines) > len(visible_lines) else "",
    )
    for line in visible_lines:
        LOGGER.error("engine-log | %s", line)


def unwrap_review(data: Any, engine: str) -> Any:
    if engine != "antigravity" or not isinstance(data, dict) or "response" not in data:
        return data
    LOGGER.info("Extracting review from Antigravity CLI response envelope")
    response = data["response"]
    if isinstance(response, dict):
        return response
    if not isinstance(response, str):
        raise ValueError("review response must be JSON text or an object")
    response = response.strip()
    if not response:
        raise ValueError("review response is empty")
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        LOGGER.info("Response is not plain JSON; searching for one embedded review object")
        decoder = json.JSONDecoder()
        candidates = []
        for index, character in enumerate(response):
            if character != "{":
                continue
            try:
                candidate, _ = decoder.raw_decode(response, index)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and REQUIRED_REVIEW_KEYS.issubset(candidate):
                candidates.append(candidate)
        if len(candidates) != 1:
            raise ValueError("review response must contain exactly one review object")
        return candidates[0]


def validate_review(data: Any) -> dict[str, Any]:
    LOGGER.info("Validating review fields")
    if not isinstance(data, dict):
        raise ValueError("review must be an object")
    if not REQUIRED_REVIEW_KEYS.issubset(data):
        raise ValueError("review has missing keys")
    if data["verdict"] not in {"PASS", "FAIL"}:
        raise ValueError("invalid verdict")
    if not isinstance(data["summary"], str) or not data["summary"].strip():
        raise ValueError("summary must be non-empty")
    if not isinstance(data["findings"], list):
        raise ValueError("findings must be an array")
    if (data["verdict"] == "PASS") != (len(data["findings"]) == 0):
        raise ValueError("verdict and findings disagree")
    required_finding_keys = {"priority", "path", "line", "title", "body"}
    for index, item in enumerate(data["findings"], start=1):
        if not isinstance(item, dict) or not required_finding_keys.issubset(item):
            raise ValueError(f"finding {index} has missing keys")
        path = PurePosixPath(str(item["path"]))
        if path.is_absolute() or ".." in path.parts or item["priority"] not in {"P0", "P1", "P2"}:
            raise ValueError(f"finding {index} has unsafe path or priority")
        if not isinstance(item["line"], int) or item["line"] < 1:
            raise ValueError(f"finding {index} has invalid line")
        if not isinstance(item["title"], str) or not item["title"].strip():
            raise ValueError(f"finding {index} has invalid title")
        if not isinstance(item["body"], str) or not item["body"].strip():
            raise ValueError(f"finding {index} has invalid body")
    LOGGER.info("Review is valid: verdict=%s findings=%d", data["verdict"], len(data["findings"]))
    return data


def render_review(engine: str, input_file: Path, output: Path, github_output: Path) -> None:
    LOGGER.info("Rendering %s review", engine)
    data = validate_review(unwrap_review(load_json(input_file), engine))
    name = "Codex" if engine == "codex" else "Antigravity"
    icon = "✅" if data["verdict"] == "PASS" else "❌"
    lines = [
        f"## {name} pull-request review",
        "",
        f"{icon} **Verdict: {data['verdict']}**",
        "",
        data["summary"].strip(),
    ]
    for item in data["findings"]:
        lines += [
            "",
            f"### [{item['priority']}] {item['title'].strip()}",
            "",
            f"`{item['path']}:{item['line']}`",
            "",
            item["body"].strip(),
        ]
    lines += ["", f"_Generated by {name} in an ephemeral read-only GitHub Actions job._", ""]
    output.write_text("\n".join(lines), encoding="utf-8")
    with github_output.open("a", encoding="utf-8") as handle:
        handle.write(f"verdict={data['verdict']}\n")
    LOGGER.info("Rendered review to %s and recorded workflow verdict", output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    schema_parser = subparsers.add_parser("create-schema")
    schema_parser.add_argument("--output", type=Path, required=True)

    settings_parser = subparsers.add_parser("configure-antigravity")
    settings_parser.add_argument("--settings-file", type=Path, required=True)

    envelope_parser = subparsers.add_parser("validate-antigravity-envelope")
    envelope_parser.add_argument("--input", type=Path, required=True)

    failure_parser = subparsers.add_parser("report-failure")
    failure_parser.add_argument("--engine", choices=("codex", "antigravity"), required=True)
    failure_parser.add_argument("--exit-code", type=int, required=True)
    failure_parser.add_argument("--log-file", type=Path, required=True)

    render_parser = subparsers.add_parser("render")
    render_parser.add_argument("--engine", choices=("codex", "antigravity"), required=True)
    render_parser.add_argument("--input", type=Path, required=True)
    render_parser.add_argument("--output", type=Path, required=True)
    render_parser.add_argument("--github-output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        if args.command == "create-schema":
            create_schema(args.output)
        elif args.command == "configure-antigravity":
            configure_antigravity(args.settings_file)
        elif args.command == "validate-antigravity-envelope":
            validate_antigravity_envelope(args.input)
        elif args.command == "report-failure":
            report_failure(args.engine, args.exit_code, args.log_file)
        elif args.command == "render":
            render_review(args.engine, args.input, args.output, args.github_output)
    except Exception:
        LOGGER.exception("Command %s failed", args.command)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
