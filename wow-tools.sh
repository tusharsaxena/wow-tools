#!/usr/bin/env sh
# Ka0s WoW Tools: the one way in. Opens the tool menu (or `update`). Needs Python 3.10+.
here="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m wowtools "$@"
