from __future__ import annotations

import argparse
import json
import sys

from vsa_agent.config import AppConfig
from vsa_agent.config import resolve_runtime_config
from vsa_agent.config import validate_runtime_config
from vsa_agent.live_run_validator import format_validation_result
from vsa_agent.live_run_validator import validate_live_run


def _load_config(path: str) -> AppConfig:
    return AppConfig.from_yaml(path)


def _config_print(path: str) -> int:
    runtime = resolve_runtime_config(_load_config(path))
    print(json.dumps(runtime.model_dump_redacted(), ensure_ascii=False, indent=2))
    return 0


def _config_doctor(path: str) -> int:
    diagnostics = validate_runtime_config(_load_config(path))
    if diagnostics.ok:
        print("Config OK")
        return 0

    for issue in diagnostics.issues:
        print(f"{issue.severity.upper()}: {issue.message}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vsa_agent")
    subparsers = parser.add_subparsers(dest="command")

    config_parser = subparsers.add_parser("config")
    config_subparsers = config_parser.add_subparsers(dest="config_command")

    print_parser = config_subparsers.add_parser("print")
    print_parser.add_argument("--config", default="config.yaml")

    doctor_parser = config_subparsers.add_parser("doctor")
    doctor_parser.add_argument("--config", default="config.yaml")

    validate_run_parser = subparsers.add_parser("validate-run")
    validate_run_parser.add_argument("run_dir")

    args = parser.parse_args(argv)
    if args.command == "config" and args.config_command == "print":
        return _config_print(args.config)
    if args.command == "config" and args.config_command == "doctor":
        return _config_doctor(args.config)
    if args.command == "validate-run":
        result = validate_live_run(args.run_dir)
        print(format_validation_result(result))
        return 0 if result.ok else 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
