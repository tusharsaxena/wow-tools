"""Entry point used by wow-tools.sh / wow-tools.cmd: python -m wowtools [update|--version|--help]."""
from __future__ import annotations

import sys

from wowtools.core.bootstrap import add_vendor_path, check_python, log_bootstrap_failure


def _event_log_open() -> bool:
    """True once suite.run() has opened the event log (from then on failures are logged there, not here)."""
    events = sys.modules.get("wowtools.core.events")
    return events is not None and events.get_event_log().log_dir is not None


def main(argv: list[str] | None = None) -> int:
    try:
        problem = check_python()
        if problem:
            print(problem, file=sys.stderr)
            log_bootstrap_failure("python_check", problem)
            return 1
        add_vendor_path()
        from wowtools.suite import run  # everything else is imported after vendor/ is on sys.path

        return run(sys.argv[1:] if argv is None else list(argv))
    except Exception as exc:
        # LN5: before the event log opens, nothing else would record this (Ctrl+C and SystemExit are not failures).
        if not _event_log_open():
            log_bootstrap_failure("startup", exc)
        raise


if __name__ == "__main__":
    sys.exit(main())
