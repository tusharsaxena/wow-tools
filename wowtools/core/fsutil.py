"""Small file-system helpers shared by core and the tools."""
from __future__ import annotations

import errno
import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path

# os.link errors meaning "this file system (or this kind of file) has no hard links", not "the target exists".
_NO_HARDLINK = {errno.EPERM, errno.EACCES, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EMLINK, errno.ENOSYS}

# Reparse tags (os.lstat(...).st_reparse_tag on Windows) of the two kinds of link: a symlink and a junction.
_LINK_TAGS = (0xA000000C, 0xA0000003)


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


def remove_quietly(path: Path) -> None:
    """Delete a file, ignoring any error (it is already gone, or cannot be removed): for clean-up of our own
    temporary or partial files, where a failure must never hide the real outcome."""
    try:
        os.remove(path)
    except OSError:
        pass


def safe_progress(progress: Callable[..., None] | None) -> Callable[..., None]:
    """Wrap a progress callback (None means no progress) so an error inside it can never disturb, stop or roll
    back the run that reports to it."""
    def report(*args, **kwargs) -> None:
        if progress is None:
            return
        try:
            progress(*args, **kwargs)
        except Exception:  # noqa: BLE001, S110 - a broken progress display must never stop a run
            pass
    return report


def is_link(entry: os.DirEntry | Path) -> bool:
    """True for a symlink or, on Windows, a junction (Python 3.10 reports a junction as a plain folder, so its
    reparse tag is checked; other reparse points such as cloud placeholders are not links). Never raises."""
    try:
        if entry.is_symlink():
            return True
        if sys.platform != "win32":
            return False
        info = entry.stat(follow_symlinks=False) if isinstance(entry, os.DirEntry) else os.lstat(entry)
        return getattr(info, "st_reparse_tag", 0) in _LINK_TAGS
    except OSError:
        return False


def is_real_dir(path: Path) -> bool:
    """True for a folder that is not itself a symlink or junction, from one lstat (never follows the last
    component). False when it is gone, a file or a link. Never raises."""
    try:
        info = os.lstat(path)
    except (OSError, ValueError):
        return False
    return stat.S_ISDIR(info.st_mode) and getattr(info, "st_reparse_tag", 0) not in _LINK_TAGS


_JUNCTION_TAG = _LINK_TAGS[1]
_VERBATIM = "\\\\?\\"  # os.readlink's prefix on a Windows junction's target


def read_link(path: Path) -> tuple[str, bool] | None:
    """(target, junction) of a symlink or a Windows junction, as os.readlink gives it (never resolved); None when
    path is not a link or cannot be read. Never raises."""
    try:
        info = os.lstat(path)
        junction = getattr(info, "st_reparse_tag", 0) == _JUNCTION_TAG
        if not (stat.S_ISLNK(info.st_mode) or junction):
            return None
        return os.fsdecode(os.readlink(path)), junction
    except (OSError, ValueError):
        return None


def make_link(target: str, path: Path, *, junction: bool) -> None:
    """Make path a link to target again (read_link's pair): a junction on Windows when it was one, else a symlink
    (to a folder when the target is one, as Windows needs to know). Raises OSError."""
    if junction and sys.platform == "win32":
        import _winapi  # Windows only
        _winapi.CreateJunction(target.removeprefix(_VERBATIM), str(path))
        return
    is_dir = junction or os.path.isdir(os.path.join(os.path.dirname(path), target))
    os.symlink(target, path, target_is_directory=is_dir)


def _unlink_link(path: Path) -> None:
    """Remove a link itself (never its target)."""
    try:
        os.unlink(path)
    except OSError:
        if sys.platform != "win32":
            raise
        os.rmdir(path)  # a junction or directory symlink is removed like a folder; its target is untouched


def _delete_entry(path: Path, *, folder: bool) -> None:
    """Remove a plain file or an empty folder, clearing a read-only flag (Windows) when that is what stops it. On
    POSIX the error is raised as it is: there a mode never blocks its own removal (the parent's does), and a chmod
    would only leave the entry write-only."""
    remover = os.rmdir if folder else os.remove
    try:
        remover(path)
    except PermissionError:
        if sys.platform != "win32":
            raise
        os.chmod(path, stat.S_IWRITE)  # a read-only file or folder on Windows
        remover(path)


def remove_tree_no_follow(path: Path) -> None:
    """Delete a folder tree. Links inside it (symlinks, junctions) are removed as links and never descended into,
    so whatever they point at is untouched; a link given as `path` is just unlinked. Raises OSError."""
    path = Path(path)
    if is_link(path):
        _unlink_link(path)
        return
    with os.scandir(path) as entries:
        children = list(entries)
    for entry in children:
        child = Path(entry.path)
        if is_link(entry):
            _unlink_link(child)
        elif entry.is_dir(follow_symlinks=False):
            remove_tree_no_follow(child)
        else:
            _delete_entry(child, folder=False)
    _delete_entry(path, folder=True)
