"""Entry point used by wow-tools.sh / wow-tools.cmd: python -m wowtools [update|--version|--help]."""
from __future__ import annotations

import sys

from wowtools.core.bootstrap import add_vendor_path, check_python


def main(argv: list[str] | None = None) -> int:
    problem = check_python()
    if problem:
        print(problem, file=sys.stderr)
        return 1
    add_vendor_path()
    from wowtools.suite import run  # everything else is imported after vendor/ is on sys.path

    return run(sys.argv[1:] if argv is None else list(argv))


if __name__ == "__main__":
    sys.exit(main())
