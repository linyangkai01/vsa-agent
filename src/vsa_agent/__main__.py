from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

from vsa_agent.archive.ingest import ingest_live_run
from vsa_agent.archive.search import LocalArchiveSearchStore
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


def _archive_ingest(run_dir: str, index_path: str) -> int:
    try:
        record = ingest_live_run(run_dir, index_path)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "records_written": 1,
                "index_path": index_path,
                "record_id": record.record_id,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _archive_search(query: str, index_path: str, top_k: int) -> int:
    if not Path(index_path).exists():
        print(f"ERROR: Archive index not found: {index_path}", file=sys.stderr)
        return 1

    async def _run() -> dict:
        output = await LocalArchiveSearchStore(index_path).search(query=query, top_k=top_k)
        return output.model_dump()

    try:
        print(json.dumps(asyncio.run(_run()), ensure_ascii=False))
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vsa_agent")
    subparsers = parser.add_subparsers(dest="command")

    config_parser = subparsers.add_parser("config")
    config_subparsers = config_parser.add_subparsers(dest="config_command")

    print_parser = config_subparsers.add_parser("print")
    print_parser.add_argument("--config", default="config.yaml")

    doctor_parser = config_subparsers.add_parser("doctor")
    doctor_parser.add_argument("--config", default="config.yaml")

    archive_parser = subparsers.add_parser("archive")
    archive_subparsers = archive_parser.add_subparsers(dest="archive_command")

    archive_ingest_parser = archive_subparsers.add_parser("ingest")
    archive_ingest_parser.add_argument("run_dir")
    archive_ingest_parser.add_argument("--index", default="artifacts/video-archive/index.jsonl")

    archive_search_parser = archive_subparsers.add_parser("search")
    archive_search_parser.add_argument("query")
    archive_search_parser.add_argument("--index", default="artifacts/video-archive/index.jsonl")
    archive_search_parser.add_argument("--top-k", type=int, default=5)

    validate_run_parser = subparsers.add_parser("validate-run")
    validate_run_parser.add_argument("run_dir")

    args = parser.parse_args(argv)
    if args.command == "config" and args.config_command == "print":
        return _config_print(args.config)
    if args.command == "config" and args.config_command == "doctor":
        return _config_doctor(args.config)
    if args.command == "archive" and args.archive_command == "ingest":
        return _archive_ingest(args.run_dir, args.index)
    if args.command == "archive" and args.archive_command == "search":
        return _archive_search(args.query, args.index, args.top_k)
    if args.command == "validate-run":
        result = validate_live_run(args.run_dir)
        print(format_validation_result(result))
        return 0 if result.ok else 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
