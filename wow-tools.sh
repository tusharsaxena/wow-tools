#!/usr/bin/env sh
# Ka0s WoW Tools: the one way in. Opens the tool menu (or `update`). Needs Python 3.10+.
# An update may replace this file while Python runs, and sh reads a script as it goes. So everything is in main(),
# called on the last line together with the exit: the shell has parsed it all before Python starts, and reads
# nothing from the file afterwards. (No exec: the launcher stays to log Python's exit code.)
# Every launch is logged to logs/suite/launcher.log; if that folder can't be written, logging is skipped silently.
main() {
    here="$(cd "$(dirname "$0")" && pwd)"
    log="$here/logs/suite/launcher.log"
    mkdir -p "$here/logs/suite" 2>/dev/null
    logline() { { printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$*" >>"$log"; } 2>/dev/null; }
    logline "launcher.started python=python3 platform=$(uname -s 2>/dev/null) args=$*"
    # The Python check: 0 = fine, 3 = too old, anything else (127: not found) = none.
    if command -v python3 >/dev/null 2>&1; then
        python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 3)" >/dev/null 2>&1
        check=$?
    else
        check=127
    fi
    if [ "$check" -ne 0 ]; then
        if [ "$check" -eq 3 ]; then
            found="$(python3 -c "import sys; sys.stdout.write('.'.join(map(str, sys.version_info[:2])))" 2>/dev/null)"
            logline "launcher.python_too_old found=${found:-unknown} python=python3"
            echo "Ka0s WoW Tools needs Python 3.10 or newer, but \"python3\" is Python ${found:-unknown}." >&2
        else
            check=127
            logline "launcher.python_missing python=python3"
            echo "Ka0s WoW Tools needs Python 3.10 or newer, and no Python was found: \"python3\" did not run." >&2
        fi
        echo "Install it as README.md describes under \"Installing Python\", then start wow-tools again." >&2
        logline "launcher.exited code=$check"
        return "$check"
    fi
    PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}" python3 -m wowtools "$@"
    rc=$?
    logline "launcher.exited code=$rc"
    return "$rc"
}
main "$@"; exit $?
