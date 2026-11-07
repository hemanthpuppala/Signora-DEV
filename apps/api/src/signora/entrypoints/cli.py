"""``signora`` command-line interface.

Commands are added by the tasks that need them; each one loads settings first so configuration
errors stop the command with the full list of problems.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from signora.kernel.config import ConfigError, get_settings
from signora.kernel.migrations import upgrade_to_head


def _migrate(_: argparse.Namespace) -> int:
    upgrade_to_head(get_settings().db)
    sys.stderr.write("database migrated to head\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="signora", description="Signora operations")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply database migrations up to the latest revision")
    return parser


_COMMANDS = {"migrate": _migrate}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _COMMANDS[args.command](args)
    except ConfigError as error:
        sys.stderr.write(f"{error}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
