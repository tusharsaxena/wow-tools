"""Small file-system helpers shared by core and the tools."""
from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    """Write text to path so a reader (or the next start, after a crash) sees either the old file or the new one,
    never a truncated mix: write <name>.partial next to it, then os.replace it over the target. If the write or
    the replace fails, the original file is untouched and the partial is removed."""
    path = Path(path)
    partial = path.with_name(path.name + ".partial")
    try:
        with partial.open("w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(partial, path)
    except BaseException:
        try:
            partial.unlink()
        except OSError:
            pass
        raise
