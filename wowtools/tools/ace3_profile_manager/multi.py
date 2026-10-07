"""Apply over one or several flavors with one journal for the whole run (spec §9): the shared driver
(core/sv_apply.apply_flavors) with this tool's apply_flavor. UI-free."""
from __future__ import annotations

from wowtools.core import sv_apply
from wowtools.core.install import Flavor
from wowtools.core.sv_apply import FlavorRun, MultiApplyResult, WowRunning, prune_edited_zips
from wowtools.tools.ace3_profile_manager.editor import apply_flavor
from wowtools.tools.ace3_profile_manager.events import SV_TOOL
from wowtools.tools.ace3_profile_manager.ops import DbState

__all__ = ["FlavorRun", "MultiApplyResult", "WowRunning", "apply_flavors", "prune_edited_zips"]


def apply_flavors(plan: list[tuple[Flavor, list[DbState]]], **options) -> MultiApplyResult:
    """core/sv_apply.apply_flavors's options (root, journal_dir, keep_journals, keep_snapshots, dry_run, account,
    wow_check, now, progress). apply_flavor is looked up per call, so a test can patch it here."""
    return sv_apply.apply_flavors(SV_TOOL, plan, lambda flavor, states, **kw: apply_flavor(flavor, states, **kw),
                                  **options)
