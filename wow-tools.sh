#!/usr/bin/env sh
# Ka0s WoW Tools: tool menu, `update`, or any tool by name. Needs Python 3.10+.
here="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m wowtools "$@"
