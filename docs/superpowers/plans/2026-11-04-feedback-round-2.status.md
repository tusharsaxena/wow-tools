# Feedback round 2: status

Branch `feat/config-editor-feedback-1`. Plan `2026-11-04-feedback-round-2.md`. Resume at the first row not `done`.

| Task | What | Status | Commit | Notes |
|---|---|---|---|---|
| G0 | re-sort the 250 "other" CVars (workflow pass, data handed to G2) | done | (this commit) | the 250: debug 92, game state 82, system 43, graphics 20, interface 9, network 3, other 1 (`repositionfrequency`); written into cvar_categories.json by G2 |
| G1 | shared column and count helpers, two standards | done | (this commit) | 16 new tests in tests/test_ui_columns.py + test_structure::test_tree_label_helpers_live_in_ui; CE ops column tests on the shared fit. Gate: run_tests --all 2365 tests, WSL OK (10 skipped), Windows OK (86 skipped); ruff clean; gen_event_docs --check OK |
| G2 | Config Editor R1, R2, R3, R5, R6 | done | (this commit) | 6 new tests (5 in test_config_editor_app: node counts, flavor counts, dropdown counts, not-set colour, help colours; test_kb::test_other_is_kept_to_a_handful), group lists / help styles / tree labels updated in test_config_editor_app, test_config_editor_ops, test_kb. Stale screenshots: config-editor/browse.png, recommend.png. Gate: run_tests --all 2371 tests, WSL OK (10 skipped) every run; Windows OK (86 skipped) on the --windows rerun, its --all runs each had one environmental error in an untouched test (WinError 10055 socket-buffer twice, as in T5/T6; one test_suite lock-timing KeyError under the doubled load); ruff clean; gen_event_docs --check OK. Review fixes (fix: G2 review fixes): kb/README.md cvars section lists the eleven groups; config-editor.md tree-count wording matches G2e (0 items included); docs only, gate run_tests --all 2371 WSL OK / Windows OK, ruff clean, gen_event_docs OK |
| G3 | WTF Cleaner counts + columns | done | (this commit) | 7 new tests (test_ui_columns::test_a_rich_cell_keeps_its_own_colours; 6 in test_wtf_app NodeCountsAndColumnsTest: group counts, counts follow the search, blacklisted not counted, aligned addon and file columns, long name cut to the pane at 120x30 and 80x24, flavor counts); no existing test changed. Stale screenshots: wtf-cleaner/review.png (also in README.md). Review fixes (fix: G3 review fixes, G3h/G3i): +1 test (test_a_group_of_blacklisted_rows_only_counts_zero), test_a_long_name_is_cut_to_fit_the_pane checks group rows too, test_flavor_with_nothing_to_clean_says_so changed (flavor `0 items`). Gate after the fixes: run_tests --all 2379 tests, WSL OK, Windows OK (86 skipped); ruff clean; gen_event_docs --check OK. Gate before the fixes: run_tests --all 2378 tests, WSL OK (10 skipped), Windows OK (86 skipped); ruff clean; gen_event_docs --check OK |
| G4 | Screenshot Organizer counts + columns | done | (this commit) | 5 new tests in test_screenshot_organizer_app (every node counts the screenshots below it, counts follow the filter, conflicts and duplicates are aligned columns, rows cut to fit the pane at 120x30 and 80x24, copy mode flavor counts its filed copies); 3 existing assertions updated to the new labels (`Skipped  2 items`, `Already filed  4 items`, flavor `4 items`), none loosened. Stale screenshots: screenshot-organizer/review.png (also in README.md). Gate: run_tests --all 2384 tests, WSL OK (10 skipped), Windows OK (86 skipped); ruff clean; gen_event_docs --check OK. Review fixes (fix: G4 review fixes, G4r): +1 test (test_conflict_and_skipped_counts_follow_the_filter: `notes` keeps 1 of 2 Skipped, `080119` 1 of 2 Conflicts); assert_counts checks Conflicts and Skipped against the rows the tree shows under them, no longer the unfiltered total. The 80-column file-row finding is flagged for the user (G4r below), code unchanged. Gate after the fixes: run_tests --all 2385 tests, WSL OK (10 skipped), Windows OK (86 skipped); ruff clean; gen_event_docs --check OK |
| G5 | Interface Backup counts + columns | done | (this commit) | 5 new tests in test_interface_backup_app (every node counts the backups below it, backup counts follow the filter, flavor/part/backup rows are aligned columns, review rows cut to fit the pane at 120x30 and 80x24 with the count kept, restore tree counts and columns incl. filter and 80x24); report tests moved to the new cell helpers (part_cells, flavor_cells, held_cells, backup_cells, backups_note, WARNINGS_NOTE). 11 existing app tests updated to the new labels (`Backups  N items`, `Links  1 item`, `⚠ Scan warnings  3 items`, `Will be removed  N items`, group rows `WeakAuras  2 items  Interface/AddOns`, backup rows date-first, the no-data reason without `nothing to back up:`), none loosened; test_backup_and_its_safety_zip_differ_at_base checks `last …` only when it fits at BASE (dropped on Windows, where sizes are known: the first gate run caught it). Stale screenshots: interface-backup/review.png (also in README.md), restore-screen.png. Gate: run_tests --all 2390 tests, WSL OK (10 skipped), Windows OK (86 skipped); ruff clean; gen_event_docs --check OK. Review fixes (fix: G5 review fixes, G5r): a flavor's last backup is cut to its date before it is dropped; a backup row takes a narrower form at 80 columns (no year, no seconds, safety marked S) instead of cutting its date in the middle and dropping its kind. +1 test (FlavorRowFitTest), test_backup_and_its_safety_zip_differ_at_base checks the date unconditionally and the 80-column rows, the report test covers the forms. Gate after the fixes: run_tests --all 2391 tests, WSL OK (10 skipped), Windows OK (86 skipped); ruff clean; gen_event_docs --check OK |
| G6 | Ace3 Profile Manager counts + columns | done | (this commit) | 8 new tests: 7 in test_ace_app NodeCountsAndColumnsTest (every node counts the profiles below it, counts follow the filter and the Show boxes, a pending delete is still counted, By character counts its addon rows incl. under a filter, sibling rows are aligned columns in both views, rows fit the pane at 120x30 and 80x24 with no trailing padding, the blacklist tree counts its addons incl. under a filter) and test_ui_columns::test_the_count_is_kept_by_cutting_the_name (fit_keeping_count moved to ui/columns, G6c). Existing tests updated to the new labels, none loosened: test_ace_report (3 `label` assertions now `cells`, +2 checks), test_ace_app ReviewTest (`Default  3 characters  Default`, `Gone - Realm1 +no character folder`, `KickCD +Default`; the locked deleted/removed rows check the mark behind the alignment pad), test_interface_backup_app FlavorRowFitTest (calls ui/columns' copy), test_structure (pins fit_keeping_count). Stale screenshots: ace3-profile-manager/review.png (also in README.md), review-by-character.png. Gate: run_tests --all 2399 tests, WSL OK (10 skipped), Windows OK (86 skipped); ruff clean; gen_event_docs --check OK. Review fixes (fix: G6 review fixes, G6r): a profile row's `N characters` counts the characters the tree shows under it (search, Leftover characters), not every character of the database; +1 test (test_a_profile_counts_the_characters_it_shows: `mierin` and Leftover characters off, every profile's count matches its visible live children); the user guide says so. Gate after the fixes: run_tests --all 2400 tests, WSL OK (10 skipped), Windows OK (86 skipped); ruff clean; gen_event_docs --check OK |
| G7 | Saved Variables Browser counts + columns | todo | | |
| G8 | Config Copier counts + columns | todo | | |
| G9 | Macro Editor counts + columns | todo | | |
| G10 | CHANGELOG, whole-branch review, push, CI | todo | | |

## Decisions taken during the build

- G1a: the whole of R4's helper sits in `wowtools/ui/columns.py` as the plan names it (pure, Rich only, no Textual),
  so a tool's `report.py` (STD-1.7: no `wowtools.ui` import) keeps only its cells and plain constants and the
  screen fits and draws; the Config Editor's layout is `review_screen.CVAR_COLUMNS` built from report's
  `COLUMN_CAPS` / `COLUMN_MINIMUMS` / `DROP_ORDER` (now `(2, 4, 1, 3)`, the leading `None` step is the helper's own).
- G1b: the layout is a `ColumnLayout(caps, minimums, shrink, drop)` NamedTuple: shrink stages of free-text columns,
  a drop order, and past it the helper always falls back to the first column (the name) alone cut to the room, so
  a tool whose drop order leaves status columns still fits. The CE behaviour (CF2, FB2r) is unchanged, pinned by
  its existing tests.
- G1c: the shared middle cut is `cut_middle` (cell-aware), not `cut_name`: the Macro Editor's `ops.cut_name` (a
  macro name cut to the game's limit) is a different thing and keeps its name; the structure test pins both.
- G1d: the count helper is its own module, `wowtools/ui/counts.py` (`count_text`, `with_count`, `COUNT_STYLE` dim,
  `COUNT_GAP` two spaces: the WTF Cleaner's look). The WTF Cleaner's group label already moves onto `with_count`
  here, so there is never a second copy; G3 still owns its counts and columns.
- G1e: the two rules are STD-7.27 (leaf counts) and STD-7.28 (node columns), enforced now by the helper and
  structure tests and, as G2-G9 land, by each tool's app test (the rule text names them).
- G2a: the console category `debug` now maps to the debug group in `core.kb.category_group` (only a CVar a newer
  dump adds and `cvar_categories.json` doesn't list reaches the rules); `gm`, `console` and the rest stay "other".
- G2b: the three new groups' colours take hues the first eight left free: game state teal `#4FD6BE`, debug orange
  `#FF9E64`, system periwinkle `#9D9DFF` (each over 8:1 on the background).
- G2c: R3 is `ui/theme.NOT_SET_COLOUR` `#5F6B7B` (3.7:1, against about 6.4:1 for Textual's dim of the foreground)
  on the name, value and default of a row the file doesn't set; its state and category keep their CF3 colours, and
  a set row of a read-only file stays dim.
- G2d: R1's gold title (`HELP_TITLE`, bold `TITLE_GOLD`) is on a file's panel too; `HELP_LABEL` is the review
  trees' `ACCENT` (bold cyan) on every label, the bullets' source names and the file panel's included.
- G2e: R2's leaf is a CVar row as `rows_for` shows it. The root (the scope label) counts too; the count comes after
  the whole label (after a file's `✎ N` / `no file` note); a file or a character shows one only when it has rows,
  an account, realm, flavor and the root always (an account with no files and no characters says `0 items`).
- G2f: R5's counts are worked out in the same pass as R2 (`_count_rows`, once per rebuild: one extra `ops.rows`
  per file, every category at once) across the review's flavors, and put in the select with `set_options` under
  `prevent(Select.Changed)` so the pick stays and no second rebuild runs; the prompt reads `All categories (N items)`.
- G2g: no CHANGELOG line: the Config Editor is unreleased and its `[Unreleased]` Added line covers it; G10 adds the
  suite-wide counts and columns line.
- G3a: the WTF Cleaner's leaf is a cleanable addon entry (a `ProposalItem`); a blacklisted row is shown but not
  counted (it is never cleaned, as the group's tick mark already left it out). An addon row is the leaf itself: its
  files are its `files` column, not an R2 count.
- G3b: under a search a group counts the entries with a file `filter_keys` shows, the same test `ModelFilter` uses
  to keep an addon row (its addon, a file or a group above it matches), so the count is what the tree shows.
- G3c: a group with no cleanable entries at all keeps "nothing to clean" in the count's place (the guide and two
  tests name it); a group with entries none of which the search shows says `0 items`.
- G3d: columns: an addon row is name · reasons · files · size · age, a file row name · size · age (the ` · `
  separators are gone). Caps 40 / 48 for the name and reasons (56 for a file name), minimums 12 / 13; the reasons
  give way first, then the name (cut in its middle); files, size and age are never cut, dropped age, files, size
  (a file row: age). A blacklisted row now shows the age column too, so it aligns with its cleanable siblings.
- G3e: `ui/columns` takes a Rich `Text` cell as well as a string (`natural_widths` measures it, `column_text` keeps
  its spans over the column's style and cuts it at its end), so the reasons keep a colour per criterion.
- G3f: the natural widths are worked out over the sibling rows the search keeps, once per rebuild (`_add_node`),
  with the ages as of that rebuild; `_fit_rows` refits on a resize and after a rebuild made before the tree was
  laid out (the tree is hidden during the scan).
- G3g: no CHANGELOG line here (G10 adds the suite-wide one).
- G3h (review fix, replaces G3c): a group with rows below it but no cleanable entry (only blacklisted rows, or a
  flavor whose accounts have nothing to clean) counts `0 items` (STD-7.27); only a group with no rows at all keeps
  "nothing to clean". `test_flavor_with_nothing_to_clean_says_so` now checks `0 items` on the flavor and "nothing
  to clean" on its accounts.
- G3i (review fix): a group's name is cut in its middle so its count fits the pane (at 80 columns the 28-cell pane
  cut `account-wide  7 items` to `account-wide  7 `); `_fit_rows` refits group rows on a resize too, and the
  long-name test checks every row's width at 120 and 80 columns.
- G4a: the Screenshot Organizer's leaf is a screenshot the run can file: a `ShotItem` to file or already filed
  (`FlavorPlan.selectable`). The root and a flavor count both kinds, a year, a month and a day the ones to file,
  Already filed its own. The tick keys are unchanged (a flavor still ticks only what is to file).
- G4b: Conflicts and Skipped are read-only and never filed, so they are left out of the flavor's and the root's
  count (as G3a leaves blacklisted rows out); they have children, so each counts its own rows (STD-7.27).
- G4c: the count comes straight after a group's name, before its note (Already filed, Conflicts, Skipped: `Conflicts
  2 items  a different file with the same name is already filed`), so a long note never pushes it off the pane; the
  old `(N)` and `N shots` are gone. A flavor with no rows at all keeps its reason in the count's place; one with only
  already-filed, conflict or skipped rows shows its count (`0 items` when only conflicts or skipped, as G3h) with no
  tick mark.
- G4d: columns: a file row is name · `possible duplicate` (or nothing), a conflict row name · `→ <target folder>`
  (dim). Caps 48 for the name, minimums 12 (target 12); the target gives way first, then the name, both cut in
  their middle (a path keeps its date folders); the note is never cut. A skipped row is its name only (not a column
  row). At 80 columns a day's files sit 20 cells deep in the 28-cell tree pane, so the shared fit cuts the name to
  the few cells left (STD-7.28: a row always fits); the year, month and day rows (a name and a count, not column
  rows) scroll sideways there.
- G4e: counts are worked out once per rebuild (`_count_leaves`, one pass over the plan, the filter's model nodes),
  so a tick only relabels; natural widths are worked out once per day as its files load and once per Conflicts
  node, and `_fit_rows` refits on a resize (Review Focus 5).
- G4f: no CHANGELOG line here (G10 adds the suite-wide one).
- G4r (review fix): the counts of Conflicts and Skipped under an active filter are now tested (the filtered branches
  of `_count_leaves` for `conflict` / `skip` were never run by a test before); a mutation that ignores the filter
  for skipped rows fails the new test.
- G4r (review finding flagged for the user, not fixed): at 80 columns every screenshot file row reads `✔ Wo…g`
  (confirmed: the 28-cell pane less its scrollbar, the day's 20 cells of guides and the 2-cell tick leave 4 cells,
  so `fit_columns` cuts the name to 4, below its 12-cell minimum). No cut keeps files apart in 4 cells (a tail
  cut gives `…jpg`, stripping `WoWScrnShot_` gives `07…g`), so the readable fix is to keep the name's minimum
  and let the row scroll (the spec's builder note: "a row may scroll"), and that breaks STD-7.28's MUST "a row
  always fits, at 80 columns too". The spec and the standard disagree here, so the user chooses: (a) a documented
  STD-7.28 deviation for the Screenshot Organizer's file rows, (b) amend STD-7.28 suite-wide so a name never goes
  below its minimum and the row scrolls past it (this would touch `fit_columns`, so every tool), or (c) keep it as
  is (at 120x30 the rows read fine). Until then no TINY "sibling rows are distinct" assertion is added, because it
  would fail.
- G5a: the Interface Backup review's leaf is a backup zip (a safety zip included: both are listed and restorable).
  The root, a flavor and its Backups count the zips the filter shows (before Backups is opened too); Links and Scan
  warnings are not backups, so each counts its own lines and is left out of the flavor's count (as G4b). A Backups
  node with no zips stays a leaf, `Backups  none yet`, with no count. The old `(N)` / `(N + M safety)` titles are
  gone; the safety zips are named in the Backups note (`incl. 1 safety · highlight one, then Restore`).
- G5b: the restore screen's tree counts too (STD-7.27 covers every tree of the tool): its leaf is a path the
  restore touches (a file, a link, a place that could not be read). The root, each effect and each folder group
  end with theirs, as the filter shows them (a group's old `· N files` ignored the filter); the notes (low space,
  nothing lost) are not counted, and the root has no count while the tree holds only a message (loading, blocked,
  nothing ticked).
- G5c: a flavor row is name · count · files · size · last backup, the count a column of its own right after the
  name so it lines up down the flavors; `N backups, last …` gave way to the count and `last …` (safety zips apart,
  as before; the picker's note is unchanged). A flavor with nothing to back up keeps the name and count columns and
  its reason after them, now the reason alone (`no Interface or WTF folder`, `WTF is a link (not followed)`): with
  the count, `nothing to back up: …` no longer fit whole at 120x30, and the missing tick already says it.
- G5d: columns are dropped before a name is cut (flavor: last backup, size, files; part: size, files; backup:
  parts, size, kind), every layout has `shrink=()`; `_fit_keeping_count` refits with the name shrinkable (cut in its
  middle, minimum 6) only when the shared fit would otherwise leave the name alone and lose the count. The root is
  scope · count · files · size on the same rule.
- G5e: a backup row is date and time · kind · parts · size: the date first because column 0 is the one the shared
  fit never drops and it is what tells two zips apart (a zip and its safety zip are seconds apart); at 80 columns
  the date alone shows, cut in its middle, and the bottom line names the highlighted zip in full as before. The
  parts column fills in from the worker, so the group's natural widths are worked out again and its rows relabelled
  when a zip's parts arrive.
- G5f: a part row is name · files · size (`missing` / `link, skipped` in the files column); a restore folder group is
  name · count · parent folder (`GROUP_COLUMNS`: the folder gives way first, then the name, both cut in their middle;
  the folder is dropped before the count).
- G5g: `tree_room` (the cells a row may take behind its guides, toggle and tick) lives in `restore_screen.py` and
  the review imports it (the tool's two screens share one copy; review_screen already imports restore_screen). The
  WTF Cleaner and the Screenshot Organizer each keep their own `_row_room`; a shared one in `ui/` is a candidate for
  the G10 whole-branch review.
- G5h: no CHANGELOG line here (G10 adds the suite-wide one).
- G5r (review fix): at 120x30 with the sizes known (Windows) a flavor row has 58 cells and `last …` (24) was
  dropped whole on every real install. `FLAVOR_COLUMNS` now has the last backup as a shrink stage (cut at its end,
  minimum 16: `last 2026-10-04…`), so the date stays; it is dropped only below that. `_fit_keeping_count` keeps the
  layout's stages ahead of the name's. Tested in FlavorRowFitTest (58 and 52 cells) and, unconditionally now, in
  test_backup_and_its_safety_zip_differ_at_base. Supersedes G5d for the last-backup column.
- G5r (review fix): at 80 columns a backup row (14 cells) read `2026-11…:58:19`: the day, the hour and the kind
  gone. A backup row now has four forms (`report.backup_cells(form=…)`, `BACKUP_FORMS`): the whole date, no year
  (`11-04 22:58:19`), no seconds (`11-04 22:58`), then a safety zip marked `S` (`SAFETY_MARK`) in place of its kind;
  `_row_label` takes the widest form that keeps the date whole and the kind (when the group holds a safety zip),
  so at 80 columns the rows read `11-04 22:58` / `11-04 22:58 S`. The guide says so; the bottom line still names
  the zip in full. Supersedes the 80-column half of G5e. The user guide's "its line starts with **safety**"
  (stale since G5e put the date first) now says "its line says **safety**".
- G6a: the Ace3 Profile Manager's leaf is a profile row By addon (`profile`, and a pending delete `deleted`: a row
  of its addon until Apply, so it is counted) and a character's addon row By character (`pair`, and a `removed`
  one); a locked (blacklisted) addon's rows are counted too (they are shown and `u` unlocks them, unlike the WTF
  Cleaner's never-cleaned blacklisted rows, G3a). A profile row is a leaf itself: its characters are its
  `N characters` column, not an R2 count (as G3a's addon row and its files).
- G6b: the root, a flavor, an account, a database and (By character) a character end with their count; an addon
  has it as a column right after its name (it lines up down the account); an account with no Ace3 data keeps its
  `no Ace3 data` note in its place; `⚠ Scan warnings` counts its own lines (the old `(N)` is gone) and is left out
  of the root's count (as G5a). Counted in `TreeBuilder._count` after the build, so it is exactly what the Show
  boxes and the filter left (every node is built up front: nothing loads on expand). The blacklist screen's root
  and flavors count the addons they show (a flavor with no Ace3 data has none: its note is not shown); its
  `(not found)` stays a suffix (a name and a note, not a column row).
- G6c: G5's `_fit_keeping_count` moved, unchanged, to `ui/columns.fit_keeping_count` (the Ace3 addon and character
  rows need it too: one copy, STD-2.2); the Interface Backup imports it, its FlavorRowFitTest calls it there, a
  test in test_ui_columns covers it and test_structure pins it to columns.py.
- G6d: columns (`tree_view.LAYOUTS`): addon name · count · its character (a per-character file; was `(…)` after the
  name) · blacklisted / unlocked; profile name · characters · tags; a character under a profile name · tags; By
  character a character name · count · no character folder, and its addon row addon · profile · tags (was
  `Addon: Profile · tags`). The ` · ` separators are gone; a row's tags share one column joined by `, `
  (`report.TAG_SEPARATOR`; `ProfileRow.cells` / `CharRow.cells` / `pair_cells` replace the `label` strings). The
  tags and the character give way first, then the name (cut in its middle); a count or a status is never cut, only
  dropped. A profile row with no characters (it cannot open) beside one that can is padded two spaces where the ▶
  is, so the columns line up; a row's trailing empty cells leave no padding.
- G6e: at 80 columns the tree pane is 26 cells wide behind its scrollbar, so the deepest rows (a character under a
  profile under a database: 24 cells of guides) have one cell or none left and are cut to `…` (the shared fit:
  STD-7.28 "a row always fits"); an addon's or a character's count is dropped there when the name's minimum and
  the count do not fit (the name is kept). This is the G4r finding again (spec "a row may scroll" against
  STD-7.28): flagged for the user with it, code follows the standard as G3-G5 do; at 120x30 every row reads in
  full. The fit test skips rows whose guides and mark already fill the pane.
- G6f: counts and natural widths are worked out once per build (a few hundred nodes); a tick relabels its branch as
  before; `_fit_rows` relabels the tree only when its width changed (a resize, or a build before the tree was laid
  out).
- G6g: no CHANGELOG line here (G10 adds the suite-wide one).
- G6r (review fix): a profile row's `N characters` was worked out from every live character of the database,
  not from the characters the tree shows under it, so under a search (`mierin`: `3 characters` over one row) or with
  Leftover characters off (`3 characters` over two) it disagreed with its children. `ProfileRow.shown_cells(chars)`
  now counts the shown non-removed characters (STD-7.27: the count is of what the tree shows); the user guide says so.
