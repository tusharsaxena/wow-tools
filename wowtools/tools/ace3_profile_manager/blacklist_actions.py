"""The Ace3 review's blacklist (spec B1; F-007, decision R5), mixed into ProfileReviewScreen before the shared
BlacklistAction: its hooks for `b` (the highlighted addon on or off the tool's blacklist), the blacklist screen, Unlock
(u: a blacklisted addon of one flavor unlocked for this session) and dropping a locked addon's pending changes and
ticks. The screen supplies `cfg`, `tool_cfg`, `flavors`, `settings`, `scan`, `staging`, `ticked`, `unlocked`, `idle`,
locked(), _blacklisted(), wow_folder_changed(), refresh_view() and _schedule_rebuild()."""
from __future__ import annotations

from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from wowtools.core.blacklist import Pair, format_blacklist, toggle_pair
from wowtools.core.events import log_event
from wowtools.core.install import WowInstall
from wowtools.core.svfiles import SvFile
from wowtools.tools.ace3_profile_manager.blacklist_screen import BlacklistScreen
from wowtools.tools.ace3_profile_manager.ops import DbKey, Staging
from wowtools.tools.ace3_profile_manager.settings import load_settings, save_settings
from wowtools.ui.review import BLACKLIST_NO_TARGET

__all__ = ["ProfileBlacklistActions"]


class ProfileBlacklistActions:
    """The tool's blacklist hooks and actions on the review."""

    staging: Staging | None
    ticked: set[tuple]

    def _file_of(self, node: TreeNode | None) -> SvFile | None:
        """The SavedVariables file (flavor and addon) of this addon node, or of the addon it is in (None above
        one)."""
        while node is not None and node.data is not None:
            data = node.data
            if data[0] == "addon":
                return data[1].file
            if len(data) > 1 and isinstance(data[1], DbKey) and self.staging is not None:
                return self.staging.state(data[1]).file
            node = node.parent
        return None

    def _file_at_cursor(self) -> SvFile | None:
        """The SavedVariables file (flavor and addon) of the highlighted addon, or of what is highlighted in one."""
        file = self._file_of(self.query_one("#profiles", Tree).cursor_node)
        if file is None:
            self.notify(BLACKLIST_NO_TARGET)
        return file

    def _flavor_folders(self) -> list[str]:
        """Every flavor folder of the install (a wildcard pair taken off in one flavor stays in the others)."""
        try:
            folders = [f.folder for f in WowInstall(self.cfg.wow_path).flavors()] if self.cfg.wow_path else []
        except OSError:
            folders = []
        return folders or [f.folder for f in self.flavors]

    # b (BlacklistAction): the highlighted addon in its flavor, on or off the tool's blacklist
    def blacklist_ready(self) -> bool:
        return self.idle and self.scan is not None

    def blacklist_target(self, node: TreeNode | None) -> tuple[str, str] | None:
        file = self._file_of(node)
        return None if file is None else (file.flavor.folder, file.addon)

    def toggle_blacklist(self, flavor: str, addon: str) -> bool:
        self.settings = load_settings(self.tool_cfg)
        self.settings.blacklist, listed = toggle_pair(self.settings.blacklist, flavor, addon, self._flavor_folders())
        save_settings(self.tool_cfg, self.settings, source="review")
        log_event("ace.blacklist_changed", flavor=flavor, addon=addon, blacklisted=listed)
        return listed

    def blacklist_changed(self) -> None:
        self._drop_locked()
        self._schedule_rebuild()

    def action_edit_blacklist(self) -> None:
        """The blacklist tree for the reviewed flavors; what it saves is written at once."""
        if not self.idle or self.wow_folder_changed():
            return
        self.settings = load_settings(self.tool_cfg)
        self.app.push_screen(BlacklistScreen(self.cfg, self.flavors, self.settings.blacklist),
                             self._blacklist_edited)

    def _blacklist_edited(self, pairs: list[Pair] | None) -> None:
        if pairs is None:
            return
        self.settings = load_settings(self.tool_cfg)
        self.settings.blacklist = pairs
        save_settings(self.tool_cfg, self.settings, source="review")
        log_event("ace.blacklist_changed", pairs=format_blacklist(pairs))
        self.notify("Blacklist saved.")
        self._drop_locked()
        self._schedule_rebuild()

    def action_unlock(self) -> None:
        if not self.idle or self.scan is None:
            return
        file = self._file_at_cursor()
        if file is None:
            return
        flavor, addon = file.flavor.folder, file.addon
        if not self._blacklisted(flavor, addon):
            self.notify(f"{addon} is not blacklisted.")
            return
        pair = (flavor.casefold(), addon.casefold())
        unlocked = pair not in self.unlocked
        if unlocked:
            self.unlocked.add(pair)
        else:
            self.unlocked.discard(pair)
        log_event("ace.unlocked", flavor=flavor, addon=addon, unlocked=unlocked)
        self.notify(f"{addon} is {'unlocked for this session' if unlocked else 'locked again'}.")
        self._drop_locked()
        self._schedule_rebuild()

    def _drop_locked(self) -> bool:
        """A blacklisted (locked) addon is never changed: drop its pending changes and its ticks, and say so.
        True when something was dropped."""
        if self.staging is None:
            return False
        files = {k: self.staging.state(k[1]).file for k in self.ticked}
        locked = {k for k, f in files.items() if self.locked(f.flavor.folder, f.addon)}
        self.ticked -= locked
        dropped = self.staging.drop_locked()
        if dropped:
            self.notify(f"Dropped the pending changes of {', '.join(dropped)}: blacklisted addons are never "
                        "changed.", title="Blacklisted", severity="warning", timeout=10)
        return bool(dropped or locked)

    def _reload_settings(self) -> None:
        """Read the settings again (changed with `s`): a newly blacklisted addon loses its pending changes."""
        self.settings = load_settings(self.tool_cfg)
        if self._drop_locked() and self.is_attached:
            self.refresh_view()
