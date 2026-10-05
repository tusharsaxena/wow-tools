## (a) Corrections to the agent reports

1. **ConfirmScreen call-site count.** `common-library` counts "12 `default_yes` uses, only 1 True". The real numbers are:
   - 8 explicit `default_yes=` arguments:
     - `wtf_cleaner/review_screen.py:646` (dry_run) and `:784` (False)
     - `screenshot_organizer/review_screen.py:512` (dry_run) and `:604` (False)
     - `interface_backup/review_screen.py:652` (True), `:785` (False) and `:850` (False)
     - `ace3_profile_manager/review_screen.py:1240` (dry_run)
   - 4 Ace3 sites that take the implicit `False`: `:371`, `:1060`, `:1134`, `:1357`, `:1485`. That is 5 sites, so 13 call sites in total.
   - The `buttons-colors-confirm` table is the accurate one.
2. **Ace3 select none.** `action_select_none` is at `ace3_profile_manager/review_screen.py:751-754` and runs `self.ticked.clear()`. Confirmed: it clears hidden ticks too, while select all ticks only visible keys. The inconsistency is real and not just a theory.
3. **"No disclaimer exists" is incomplete.** `LICENSE` is MIT, so the as-is / no-warranty language already exists legally. Neither README nor any doc has a user-facing "use at your own risk" line (grep for `warrant|own risk|as is` finds none). The new menu text should agree with the MIT warranty clause, and README should get the same text.
4. **The README version history contradicts "no release exists".** `README.md:262` lists `1.0.0 | 2026-10-04 | First release`, yet `git tag` is empty and no GitHub release exists. The "Unreleased" row (`:261`) already holds Interface Backup, Ace3 and the shared settings. So the changelog has two sources today (README table and `__version__`). That needs one decision, not two separate ones.
5. **Updater shipping is confirmed.** `_shipped_names` (`core/updater.py:~350`) ships the root `*.md` files, so a root `CHANGELOG.md` reaches zip installs. A `docs/CHANGELOG.md` also ships, because `docs` is in `MANAGED_DIRS` at `:158`. A runtime parser can read either. There is no `export-ignore` hit in `.gitattributes`, so `git archive` includes it.
6. **Ace3 key shadowing.** The `u` binding (unlock, `ace3_profile_manager/review_screen.py:219`) shadows the app-level `u` (update), so "press u to update" is wrong on that screen. It is invisible today only because BrandBar is hidden (see b1). This matters once BrandBar is fixed.

## (b) Additional findings and risks

1. **BrandBar fix ripples across 19 screens.** Once BrandBar is visible it takes 1 row on every screen. Ace3 review is pinned by `assert_ace_tree_pane_rows` (tree at least 12 rows at 120x30, guide at most 2, action bar at most 3), so it could fail.
   - Option: render the version and update text inside a custom Footer subclass in the same single row. Textual's `Footer` is a horizontal grid of keys, so a right-aligned label could share that row without adding a row.
   - Either way, the menu "version under the logo" must not rely on BrandBar.
2. **Filtering in the three "unchecked" tools can act on files the user cannot see. This is the biggest safety risk in the request.**
   - WTF, Shots and IB default to everything ticked (`unchecked` set). If a filter hides items, those items stay ticked, so Clean or Organize would delete or move files that are not on screen.
   - Ace3 has the same issue the other way round: hidden ticks survive `a` from an earlier filter.
   - The plan needs a rule (see Q4). The summary line, which starts "Selected: …", and the ConfirmScreen body should state the hidden-but-selected count whatever the rule is.
3. **Default Yes plus single-key run starts means one key and Enter can delete.**
   - `w` (WTF Clean, Ace3 Apply), `o` (Organize) and the restore keys each open the confirm. With focus on Yes, Enter or Space completes a delete or overwrite.
   - Under WSL / Windows Terminal, key repeat on Enter from the previous screen is a real hazard.
   - Mitigations that keep "default Yes":
     - colour the Yes button by action kind (red for destructive);
     - keep `y` as an explicit key;
     - ignore Enter for about 250 ms after mount.
   - Pinned by about 12 tests (`test_wtf_app.py:669/677/692/1628`, `test_ace_app.py:1278`, `test_interface_backup_app.py:764-765/780/977/1085/1176/1484`) and by the docs: `adding-a-tool.md:31/46`, `architecture.md:388/561/593/633/637-638`, the 4 tool guides, and the `test_docs.py` needles.
4. **Non-ConfirmScreen two-choice dialogs.**
   - WTF `RecoveryScreen` (`wtf_cleaner/review_screen.py:60-93`) has no bindings at all: no Esc, no y/n. "Default yes" has no clear meaning there.
   - `UpdateScreen` has only Esc.
   - `LockScreen` focuses Quit unless the lock is stale. Defaulting to Override would be a safety regression: it bypasses the single-instance lock.
   - Recommend scoping "default yes" to `ConfirmScreen` only and leaving LockScreen as it is.
5. **Shared filter infrastructure gaps.**
   - Every review screen's `space` is `priority=True` (`wtf:107`, `shots:120`, `ib:174`, `ace:204`, `blacklist:58`), but only Ace3 passes Space through to a focused `Input`. A shared filter needs the passthrough in the shared toggle.
   - Esc today means "back to flavors". With focus in the filter, Esc must first return to the tree (and probably clear the filter). Otherwise a stray Esc throws away a review, and on Ace3, pending changes too. Ace3's `action_back` is the model.
   - Ace3's `backspace` → discard (`:217`) is non-priority, so an Input swallows it first. Keep it that way. A priority binding would break typing.
   - Lazily loaded children (Shots day and filed nodes, IB links, warnings and backups, Restore groups) mean matching must run on model data: `_items_by_key` in Shots, scan data in IB.
6. **`s` (settings) from the new changelog screen.** `WowToolsApp.action_settings` (`suite_app.py:182`) is app-level, so it fires on a changelog screen pushed over the menu. It would open general settings on top of the changelog. That is harmless but odd. Either bind the changelog only on `ToolMenuScreen` and have `action_settings` refuse when `screen` is not the menu, or accept it.
7. **Parallelism inside Textual's worker model.**
   - Keep one `run_worker(thread=True, exclusive=True, group=…)` per job, and run a `ThreadPoolExecutor(max_workers=cfg.parallelism)` inside it, wrapped in a single `activity.running()` so `wait_idle` at quit (`suite.py:103-106`, 600 s) still covers every thread.
   - Thread workers cannot be cancelled by Textual. `exclusive=True` only flags the old worker. So any "stop siblings on failure" needs its own `threading.Event`.
   - `call_from_thread` blocks (`vendor/textual/app.py:1833`). N pool threads reporting per file serialise on the UI loop, so progress must be aggregated under a lock and pushed on a timer or throttle.
   - `ThrottledProgress` (`interface_backup/review_screen.py:55-90`) is not thread-safe.
   - `JournalWriter` (`core/journal.py:58-115`) has no lock.
8. **Hard blockers to parallel apply.**
   - The singleton crash markers: WTF `clean-in-progress.json` (`safety.py:26`, used by `cleaner.py:162-194`) and Ace3 `edit-in-progress.json` (`editor.py:36`).
   - The single-marker recovery screens.
   - Safe first scope: Interface Backup `back_up_all` (`backup.py:238`, no journal, per-flavor failure already isolated) and the read-only per-flavor scans (`wtf_cleaner/multi.py:32`, `interface_backup/scanner.py:144`, the Shots and IB picker-count workers).
   - Ace3 undo snapshots (`ace3_profile_manager/undo.py:174-175`) are a secondary candidate.
   - Ace3 scan is CPU-bound Lua parsing under the GIL, so threads give little there.
9. **Fixed-size progress popup.**
   - Textual's inner `Bar` is fixed `width: 32` (`vendor/textual/widgets/_progress_bar.py`), so the box looks half-empty unless CSS overrides `ProgressBar Bar { width: 1fr; }`.
   - Fixed height needs `height:` on the box plus a `height: 1` stage line with `text-overflow: ellipsis` / `overflow: hidden`. Otherwise the title wraps at 80x24.
   - A per-unit layout needs a fixed number of rows equal to `min(parallelism, units)`. Sizing the box to the configured maximum avoids resizing.
   - `test_popups_keep_a_readable_width_at_large` (`test_look_and_feel.py:461`) checks width only. A height test should be added.
   - At 80x24 a popup with N rows (N up to about 4) must still fit inside 24 rows.
10. **Button colours.**
    - Textual has 5 variants, and `simulate` and `confirm` are both `primary`.
    - WTF `CRITERION_COLORS` already uses red, orange, yellow and purple for meanings on the same review screen, so new button hues must not reuse orange or purple there.
    - Tests pin variants, not colours (`test_look_and_feel.py:89`, `test_ace_app.py:999`, `test_wtf_app.py:430-432/1609`, IB `:282-287/773/1427-1428`, `test_screenshot_organizer_app.py:499-507`). Keeping the closest variant and adding a `-act-<kind>` class keeps most of them passing.
    - `test_structure.test_literals_are_defined_once` forbids `#4CC38A` as a literal, so new hexes should be theme variables (`Theme(variables=…)` in `ui/theme.py`).
11. **Shared library enforcement gaps.**
    - No test enforces "core never imports textual". Add an AST test.
    - The `ConfirmScreen` re-export at `wtf_cleaner/review_screen.py:43-44` was kept "for one release", and README claims 1.0.0 shipped. It can go with the dead code, together with the assertion at `test_structure.py:63`.
12. **Dead code: confirmed.**
    - `safety.py:29` is the only user of `re`, so remove `import re` at `:13` too.
    - `InstallError` has zero code references.
    - Pin both in `test_structure.test_dead_code_is_gone`.
13. **Docs drift to fold in.**
    - CLAUDE.md says the test suite takes "~10s"; the measured run was about 52 s on WSL `/mnt/d` with 16 shards.
    - The README key table (`:107-122`) needs `/`, `a`/`n` within a filter, and `c` on the menu.
    - `releasing.md` needs a changelog step between bumping `__version__` and the release commit, so the entry is inside the tagged archive.
    - `build_release.py` can refuse a tag with no entry.
14. **Menu at 80x24 already scrolls** (`max_scroll_y` is 3). There is no menu look-and-feel test; add one at BASE (version visible, disclaimer visible, footer keys whole) and at TINY (still usable).

## (c) Product-owner questions (each with a recommended default)

1. **Changelog source and first entries.** One `CHANGELOG.md` (Keep a Changelog, parsed in `core/`) that replaces the README "Version History" table. README would then link to it.
   - Recommended default: yes. Entries "1.0.0 (2026-10-04)" and "Unreleased" (shown in the app). Tag `v1.0.0` retroactively on the commit README names, and ship this work as 1.1.0.
   - Enforce with a test (`__version__` has an entry) and a check in `build_release.py`.
2. **Default Yes on destructive confirms (Clean, Apply, Restore, Undo, Discard).**
   - Recommended default: Yes everywhere in `ConfirmScreen` as requested, made safer by colouring Yes by action kind (red for destructive) plus an Enter debounce of about 250 ms after the popup opens.
   - Keep the button order Yes, No. Exclude `LockScreen`, which keeps Quit unless the lock is stale.
3. **Disclaimer form.**
   - Recommended default: an always-visible, muted, 1-2 line "Terms" text docked at the bottom of the tool menu (it would shrink the tool list at 80x24 instead of scrolling off), with the same wording in README.
   - No click-through acknowledgement. Optionally add a one-time acceptance on the first-run setup, stored as `[general] accepted_terms`. Is that wanted?
4. **Selections hidden by a filter.**
   - Recommended default: the filter is a view only.
     - `a` and `n` act on visible matches only (Ace3's select none changes to match).
     - Hidden selections still count toward the run.
     - The summary and the confirm both say "N selected items are hidden by the filter".
   - Alternative: the run acts on visible items only.
5. **Shared filter keys and scope.**
   - Recommended default: `/` focuses a left-pane "Filter" Input on every tickable tree screen: WTF, Shots, IB review, Ace3 review (reuse `#search`) and Blacklist.
   - `a` and `n` stay select all and none.
   - Esc in the Input clears it and returns to the tree; Esc on the tree leaves as today.
   - Case-insensitive substring match on leaf and group labels, auto-expanding matches.
   - The Restore screen and popup detail trees are left out (read-only).
   - Is the WTF text filter applied on top of the existing criteria? Recommended: yes.
6. **Parallelism scope and setting.**
   - Recommended default: `[general] parallelism`, default 2, range 1-8, edited on the setup screen.
   - Applies only to Interface Backup `back_up_all` and the read-only per-flavor scans in the first pass.
   - WTF Clean and Ace3 Apply stay serial: they have singleton crash markers and stop-on-first-failure semantics.
   - Document that slow disks (HDD, WSL `/mnt`) should use 1.
7. **Progress popup design.**
   - Recommended default: fixed width (90, or 90%) and fixed height for every tool. It holds an overall bar ("2 of 5 flavors"), one row per running unit (label, stage, bar) up to `parallelism`, and a 1-line truncated detail line.
   - Serial runs use the same box with one row.
   - Cancellation is out of scope.
8. **Button colour palette.**
   - Recommended default: action kinds coloured with new theme variables, layered on the closest Textual variant:
     | Kind | Colour |
     |---|---|
     | destructive | red |
     | write / overwrite (Restore, Organize, Update now) | amber |
     | create-safe (Back up) | green |
     | revert | violet |
     | simulate | cyan |
     | confirm / save | blue |
     | navigate | grey |
     | cancel | dim grey |
   - Ace3 Apply is red. Staging buttons use a dimmer shade of the colour of the action they stage.
   - Avoid clashes with the WTF criterion colours on that screen. Is a 7-8 colour palette acceptable, or should it stay within the current 5?