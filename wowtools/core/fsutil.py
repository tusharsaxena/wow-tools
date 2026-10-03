"""Small file-system helpers shared by core and the tools."""
from __future__ import annotations

import errno
import os
from pathlib import Path

# os.link errors meaning "this file system (or this kind of file) has no hard links", not "the target exists".
_NO_HARDLINK = {errno.EPERM, errno.EACCES, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EMLINK, errno.ENOSYS}


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


def rename_no_replace(src: Path, dst: Path) -> None:
    """Rename src to dst, refusing (FileExistsError) if dst exists, with no window in between where a file that
    appears at dst would be replaced.

    Windows' rename already refuses an existing target. On POSIX (Linux, macOS, WSL drives) os.rename silently
    replaces it, so the file is hard-linked to dst first (the kernel refuses an existing dst atomically) and then
    unlinked from src. Where hard links are not supported the fallback is a last check plus rename (best effort).
    A cross-device rename raises OSError(EXDEV), as os.rename does, so callers can copy instead."""
    src, dst = Path(src), Path(dst)
    if os.name == "nt":
        os.rename(src, dst)
        return
    try:
        os.link(src, dst, follow_symlinks=False)
    except FileExistsError:
        raise
    except (NotImplementedError, OSError) as exc:
        if isinstance(exc, OSError) and exc.errno not in _NO_HARDLINK:
            raise  # ENOENT, EXDEV, ...
        if not os.path.lexists(src):
            raise FileNotFoundError(errno.ENOENT, "no such file", str(src)) from exc
        if os.path.lexists(dst):
            raise FileExistsError(errno.EEXIST, "target exists", str(dst)) from exc
        os.rename(src, dst)
        return
    try:
        os.unlink(src)
    except OSError:
        try:
            os.unlink(dst)  # back to how it was: only the source name
        except OSError:
            pass
        raise


def free_name(folder: Path, stem: str, suffix: str) -> Path:
    """folder/<stem><suffix>, or <stem>-2<suffix>, <stem>-3<suffix>, ... when that name is taken. Used for
    timestamped names (backups, journals) so two runs in the same second never share a file."""
    path = folder / f"{stem}{suffix}"
    n = 2
    while os.path.lexists(path):
        path = folder / f"{stem}-{n}{suffix}"
        n += 1
    return path
