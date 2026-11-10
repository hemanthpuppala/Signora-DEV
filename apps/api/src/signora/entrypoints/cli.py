"""``signora`` command-line interface.

Commands are added by the tasks that need them; each one loads settings first so configuration
errors stop the command with the full list of problems.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Sequence

from signora.kernel.config import ConfigError, get_settings
from signora.kernel.migrations import upgrade_to_head


def _migrate(_: argparse.Namespace) -> int:
    upgrade_to_head(get_settings().db)
    sys.stderr.write("database migrated to head\n")
    return 0


def _api(args: argparse.Namespace) -> int:
    import uvicorn  # imported lazily: other commands do not need the server

    get_settings()  # fail fast, with every configuration problem listed, before binding a port
    uvicorn.run(
        "signora.entrypoints.api:app_factory",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        access_log=False,  # our middleware logs requests with route templates
        log_config=None,  # logging is configured by the app factory
        proxy_headers=False,  # proxy headers are handled by RequestContextMiddleware
        server_header=False,
    )
    return 0


def _worker(_: argparse.Namespace) -> int:
    from signora.entrypoints.worker import run_worker

    return run_worker()


def _audit_verify(args: argparse.Namespace) -> int:
    import json

    from signora.kernel.db import Database, create_db_engine
    from signora.modules.audit import verify

    expected = None
    if args.expect_seq is not None or args.expect_hash is not None:
        if args.expect_seq is None or args.expect_hash is None:
            sys.stderr.write("--expect-seq and --expect-hash must be given together\n")
            return 2
        expected = (args.expect_seq, bytes.fromhex(args.expect_hash))
    engine = create_db_engine(get_settings().db, pool_size=1)
    try:
        with Database(engine).unit_of_work() as uow:
            result = verify(uow.session, args.chain_id, expected_head=expected)
    finally:
        engine.dispose()
    report = {
        "ok": result.ok,
        "entries_checked": result.entries_checked,
        "head_seq": result.head_seq,
        "head_hash": result.head_hash.hex(),
        "failed_seq": result.failed_seq,
        "reason": result.reason,
    }
    sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0 if result.ok else 1


def _measure_text_sizes(args: argparse.Namespace) -> int:
    """Measure the text sizes of versions approved before they were measured (Phase 7b)."""
    from signora.kernel.blobstore import blob_store_from_settings
    from signora.kernel.db import Database, create_db_engine
    from signora.modules.review import measure_unmeasured

    settings = get_settings()
    engine = create_db_engine(settings.db, pool_size=1)
    try:
        with Database(engine).unit_of_work() as uow:
            done = measure_unmeasured(
                uow.session, blob_store_from_settings(settings.blob_store), args.workspace
            )
    finally:
        engine.dispose()
    sys.stdout.write(f"measured {done.measured} approved versions\n")
    for version_id in done.failed:
        sys.stdout.write(f"could not measure version {version_id} (see the log)\n")
    return 1 if done.failed else 0


def _openapi(args: argparse.Namespace) -> int:
    import json
    from pathlib import Path

    from signora.entrypoints.api import create_app

    document = create_app(get_settings()).openapi()
    rendered = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="signora", description="Signora operations")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply database migrations up to the latest revision")
    api = commands.add_parser("api", help="run the HTTP API server")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8100)
    api.add_argument("--reload", action="store_true", help="reload on code changes (development)")
    commands.add_parser("worker", help="run the background job worker")
    measure_cmd = commands.add_parser(
        "measure-text-sizes",
        help="measure the text beside each place of versions approved before sizes were kept",
    )
    measure_cmd.add_argument("--workspace", type=uuid.UUID, help="only this company's versions")
    openapi = commands.add_parser("openapi", help="write the OpenAPI document (deterministic)")
    openapi.add_argument("--output", help="file to write (default: stdout)")
    audit = commands.add_parser("audit", help="audit log operations")
    audit_commands = audit.add_subparsers(dest="audit_command", required=True)
    verify_cmd = audit_commands.add_parser("verify", help="verify one hash chain")
    verify_cmd.add_argument(
        "chain_id", type=uuid.UUID, help="envelope id, workspace id, or the system chain id"
    )
    verify_cmd.add_argument("--expect-seq", type=int, help="anchored head sequence number")
    verify_cmd.add_argument("--expect-hash", help="anchored head hash (hex)")
    return parser


_COMMANDS = {
    "migrate": _migrate,
    "api": _api,
    "worker": _worker,
    "measure-text-sizes": _measure_text_sizes,
    "openapi": _openapi,
    "audit": _audit_verify,  # the only audit subcommand
}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _COMMANDS[args.command](args)
    except ConfigError as error:
        sys.stderr.write(f"{error}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
