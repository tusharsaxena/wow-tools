#!/usr/bin/env sh
# Ka0s WoW Tools: WTF Cleaner. Runs from any folder; needs Python 3.10+.
here="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m wowtools wtf-cleaner "$@"
