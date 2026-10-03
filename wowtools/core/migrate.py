"""Start-up migrations for renamed tools: carry a tool's config file and folders over to its new name.

A rename is one ToolRename line in wowtools.tools.RENAMED_TOOLS. suite.run() applies every line at start-up:

- config/<old>.cfg becomes config/<new>.cfg, with the tool's section renamed (migrate_tool_config);
- logs/<old>/ becomes logs/<new>/, and <WoW folder>/wow-tools/<old>/ becomes .../<new>/ (merge_folder).

Nothing is ever overwritten. A folder whose new name does not exist yet is simply renamed. When both exist, the
entries that do not clash are moved into the new folder (sub-folders are merged the same way), clashing entries
are left where they are, and the old folder is removed only if it ends up empty.
"""
from __future__ import annotations

import configparser
import io
import os
from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core.config import Config, tool_config_path
from wowtools.core.fsutil import atomic_write_text

WOW_TOOLS_DIR = "wow-tools"  # <WoW folder>/wow-tools/<tool>/: where tools keep their data next to the game


@dataclass(frozen=True)
class ToolRename:
    old: str           # old tool name: config/<old>.cfg, logs/<old>/, <WoW>/wow-tools/<old>/
    new: str           # new tool name
    old_section: str   # the tool's section in config/<old>.cfg
    new_section: str   # its section in config/<new>.cfg


@dataclass
class FolderMerge:
    """What merge_folder did. `renamed` means the old folder was renamed whole (the new one did not exist)."""
    old: Path
    new: Path
    renamed: bool = False
    moved: list[str] = field(default_factory=list)     # entries moved into the new folder, relative to it
    clashes: list[str] = field(default_factory=list)   # entries left in the old folder: the new one has them
    errors: list[str] = field(default_factory=list)    # "<entry>: <error>" for moves that failed
    old_removed: bool = False

    @property
    def changed(self) -> bool:
        return self.renamed or bool(self.moved)


@dataclass
class ConfigMigration:
    """What migrate_tool_config did."""
    old: Path
    new: Path
    merged: bool                                       # the new file already existed; missing keys were added
    added: list[str] = field(default_factory=list)     # "section.key" entries carried over
    kept_old: Path | None = None                       # where the old file was kept (some values differed)


def merge_folder(old: Path, new: Path) -> FolderMerge | None:
    """Move old/ to new/ without overwriting anything. None when old/ is not a folder (nothing to do)."""
    if not old.is_dir():
        return None
    result = FolderMerge(old, new)
    if not os.path.lexists(new):
        new.parent.mkdir(parents=True, exist_ok=True)
        os.rename(old, new)
        result.renamed = result.old_removed = True
        return result
    if not new.is_dir():
        result.clashes.append(".")
        return result
    _merge_into(old, new, "", result)
    result.old_removed = _remove_if_empty(old)
    return result


def _merge_into(old: Path, new: Path, prefix: str, result: FolderMerge) -> None:
    with os.scandir(old) as entries:
        names = sorted((entry.name, entry.is_dir(follow_symlinks=False)) for entry in entries)
    for name, is_dir in names:
        rel = prefix + name
        source, target = old / name, new / name
        if not os.path.lexists(target):
            try:
                os.rename(source, target)
            except OSError as exc:
                result.errors.append(f"{rel}: {exc}")
            else:
                result.moved.append(rel)
        elif is_dir and target.is_dir() and not target.is_symlink():
            _merge_into(source, target, rel + "/", result)
            _remove_if_empty(source)
        else:
            result.clashes.append(rel)


def _remove_if_empty(folder: Path) -> bool:
    try:
        folder.rmdir()
    except OSError:
        return False
    return True


def migrate_tool_config(config_dir: Path, rename: ToolRename) -> ConfigMigration | None:
    """config/<old>.cfg -> config/<new>.cfg with [old_section] renamed [new_section]; other sections keep their
    names. None when there is no old file.

    If the new file does not exist, it is written with everything from the old one and the old file is removed.
    If it does exist, only the keys it lacks are added (its own values win). The old file is then removed when
    every one of its values is in the new file, and otherwise kept as <old>.cfg.migrated (or .migrated-2, ...),
    so nothing is lost. Raises ConfigError if a file cannot be read, OSError if the new file cannot be written
    (the old one is then left alone)."""
    old = tool_config_path(rename.old, config_dir)
    new = tool_config_path(rename.new, config_dir)
    if not old.is_file():
        return None
    source = Config(old).load()._parser
    target_cfg = Config(new).load()
    merged = target_cfg.exists
    target = target_cfg._parser
    result = ConfigMigration(old, new, merged)
    differs = False
    for section in source.sections():
        new_section = rename.new_section if section == rename.old_section else section
        if not target.has_section(new_section):
            target.add_section(new_section)
        for key, value in source.items(section, raw=True):
            if not target.has_option(new_section, key):
                target.set(new_section, key, value)
                result.added.append(f"{new_section}.{key}")
            elif target.get(new_section, key, raw=True) != value:
                differs = True
    if result.added or not merged:
        _write(new, target)
    if differs:
        result.kept_old = _free_name(old.with_name(old.name + ".migrated"))
        os.rename(old, result.kept_old)
    else:
        old.unlink()
    return result


def _write(path: Path, parser: configparser.ConfigParser) -> None:
    buffer = io.StringIO()
    parser.write(buffer)
    atomic_write_text(path, buffer.getvalue())


def _free_name(path: Path) -> Path:
    candidate, n = path, 1
    while os.path.lexists(candidate):
        n += 1
        candidate = path.with_name(f"{path.name}-{n}")
    return candidate


def tool_folder_pairs(rename: ToolRename, log_dir: Path | None, wow_path: Path | None) -> list[tuple[Path, Path]]:
    """The (old, new) folders a rename moves: logs/<tool>/ and <WoW>/wow-tools/<tool>/ (when those are known)."""
    pairs = []
    if log_dir is not None:
        pairs.append((log_dir / rename.old, log_dir / rename.new))
    if wow_path is not None:
        pairs.append((wow_path / WOW_TOOLS_DIR / rename.old, wow_path / WOW_TOOLS_DIR / rename.new))
    return pairs
