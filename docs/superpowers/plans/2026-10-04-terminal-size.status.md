# Feedback round 2 (terminal size) — status ledger

Plan: `2026-10-04-terminal-size.md`. Spec: `../specs/2026-10-04-ace-profiles-design.md` (Addendum B).
Branch: `feat/ace-profiles`. Resume at the first task not marked `done`. Update this file and commit it after every
task; push after the round. Never merge without the user's go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| S1 | shared sizes, tests, CSS; Ace3 headings back | done | 8c94fac | BASE/LARGE/TINY; look-and-feel at BASE + LARGE grow/popup checks + 80x24 smoke; POPUP_WIDTH; flow WrapButtonRow; View/Show headings. Suite 1024 tests, 0 failures; ruff clean. Renders in /tmp/wow-tools-shots/S1/ |
| S2 | WTF Cleaner, Screenshot Organizer, Interface Backup at 120x30 | done | 7cb47cf | Footer keys whole (palette key hidden); settings forms <= 100 cols, centred, compact checkboxes (WTF form fits at 120x30); WTF result names zips inside a Backup folder row; IB backup lines show the full date and time; 80-column tests moved to BASE. Suite 1027 tests, 0 failures; ruff clean. Renders in /tmp/wow-tools-shots/S2/ (before: S2-before/) |
| S3 | Ace3 screens at 120x30 | done | 5b86bc3 | Action bar 1 row at 160x45, 2 at 120x30 (shorter labels); guide shows pending line + hint, one row each, at 120x30; footer whole (d/p/m off it); quick actions list and 12-line target body without scrolling; result rows inside a Backup folder row; recovery path on its own line; 80x24 Ace3 tests at BASE. Suite 1031 tests, 0 failures (2 skipped); ruff clean. Renders in /tmp/wow-tools-shots/S3/ (before: S3-before/) |
| S4 | docs | todo | | |
| R | review, fixes, push | todo | | |

## Decisions taken during the build

- Task S1: `FILTERS_WIDTH` stays 50. The left pane's four action buttons take 45 columns, so it can't shrink, and at
  120x30 the restored View and Show headings and the whole hint fit, so it doesn't need to grow. The tree takes the
  rest (`1fr`, 70 columns at 120x30).
- Task S1: popup width is the shared `POPUP_WIDTH` in `ui/dialogs.py` (`width: 90; max-width: 90%`). It is used by
  ConfirmScreen, ProgressScreen, Ace3 `popup_css`, `ProfileRecoveryScreen`, WTF Cleaner's `RecoveryScreen` and
  `LockScreen`. `UpdateScreen` (76) and `UpdateProgressScreen` (64) keep their narrower widths.
- Task S1 (moved forward from S3, needed for the Review Focus 5 tests): `WrapButtonRow` was a grid with one column
  width for every button (3 rows of 3 at 120x30). It now flows the buttons in order, each as wide as its label, as
  column spans on a grid of one-cell columns, so the action bar takes 2 rows at 120x30. At 160x45 it still takes 2
  rows (6 + 2); getting to 1 row there is left to S3.
- Task S1 (moved forward from S3): the guide's rule is now `GUIDE_MAX_ROWS = 2`, replacing `GUIDE_MIN_TREE = 5`.
  With pending changes, the node hint is dropped when the guide would take more than 2 rows. To fit, `STEPS` lost
  "; Dry run (y) only checks them" (3 rows at 68 columns before), and the pending line became "…, not written yet:
  Apply (w) writes, Dry run (y) checks, Discard (⌫) drops" (one row at 160x45, so pending + hint show together
  there). At 120x30 the pending line takes 2 rows on its own, so the hint is still dropped while changes are pending.
  S3's "drop the squeeze if it no longer triggers" doesn't apply yet; changing that needs shorter texts or a wider
  tree pane. `test_ace_report` and `test_ace_app` were updated for the new texts.
- Task S1: the docs this changes were updated in the same commit (`docs/ace-profiles.md` filter names,
  `docs/architecture.md` left pane headings and `GUIDE_MAX_ROWS`). S4 still owns the rest.
- Task S1: noticed for S2/S3 in the renders. At 120x30 the Footer key list is cut off at the right edge in the
  review screens (WTF Cleaner, Ace3). Interface Backup's result screen leaves an empty band under its detail table.
- Task S2: the footer of the review screens was cut off at 120 columns (the S1 note). The command palette's
  footer key is hidden suite-wide (`Ka0sApp.CSS`, `FooterKey.-command-palette { display: none; }`); Ctrl+P still
  opens the palette, which no doc mentions. `Footer(compact=True)` was tried and rejected: keys and descriptions run
  together ("a All n None"). The Ace3 review footer is still cut at 120x30 even so (it has more keys): left to S3.
- Task S2: `settings_css` (shared, so the Ace3 settings get it too) centres the form at `FORM_WIDTH` (`width: 100%;
  max-width: 100`). The WTF Cleaner's form did not fit at 120x30 (Save below the fold); the three tools' settings
  checkboxes are now `compact=True` (one row each, no gap), as in the left panes. The Ace3 settings checkboxes are
  left to S3; `SETTINGS_FIT_TOOLS` / `FOOTER_TOOLS` in `test_look_and_feel.py` list the three tools for S3 to extend.
- Task S2: the WTF Cleaner result named its zips and run journal by whole path, cut at 120 columns. It now shows
  `cleaned/<name>` and `backup/<name>` plus a "Backup folder" row, and the journal by name (as Interface Backup's
  result does). That made a one-flavor clean's summary 10 rows, one more than fits under the 50% cap at 120x30, so
  `result_css` caps the summary at 60% instead (shared; the other tools' summaries are shorter).
- Task S2: tests moved to BASE and renamed: WTF / SO / IB `test_settings_labels_wrap_at_base`, IB
  `test_review_actions_fit_at_base`, `test_review_tree_shows_links_and_leftovers_at_base`,
  `test_restore_screens_fit_at_base`, `test_restore_tree_names_groups_at_base` (kept: the group name first, the
  whole root and the unclipped hint still mean something at BASE), `test_restore_confirm_fits_at_base_with_long_warnings`
  and `test_backup_and_its_safety_zip_differ_at_base` (now also checks each line shows the whole date and time). None
  was removed. `test_ui_base`'s 80x24 tests are not tool tests and stay (crash logging; ↓ reaching every field of the
  general setup form at 80x24 is a TINY reachability guard).
- Task S2: seen in the renders and left as they are: tree lines longer than the tree pane (WTF "not scanned: No
  addons found in <path>", deep "Older than max age" lines with long addon names, IB "Retail PTR nothing to back up:
  ... · no backups yet") end at the pane's edge but the tree scrolls sideways; the WTF result's Reasons column and
  the Screenshot Organizer's Target column (an absolute path) scroll sideways in their tables (putting Reason
  before Target would leave Target ~25 columns whenever a row has a reason); Interface Backup's result leaves blank
  rows under a short detail table (the table takes the rest of the height, buttons stay at the bottom as on every
  result screen). A multi-flavor real clean shows "Run journal" both on top and in the flavor's block (as before).
- Task S3: the action bar's labels are shorter than the spec's (feedback round 1, item 5): "Delete (d)", "Assign
  (p)" and "Leftovers (o)" instead of "Delete profile (d)", "Assign profile (p)" and "Remove leftovers (o)". At
  160x45 the bar has 108 columns; the eight buttons took 128 (label + 2 padding + 1 gap each). Dropping "profile"
  twice still left 112, and no padding or gap change closes the rest without merging the grey buttons into one bar,
  so a third label had to shrink. The More menu still says "Remove leftover characters (o)". `docs/ace-profiles.md`
  and `docs/architecture.md` were updated in the same commit; the spec keeps its original labels as history.
- Task S3: the guide's texts were shortened so each takes one row at 120x30 (68 columns, with a name of up to 16
  characters, `test_guide_lines_fit_one_row_of_the_tree_pane_at_base`): the pending line is "N pending changes, not
  written yet: w apply · y dry run · ⌫ discard" (the file count is on the bottom line; `guidance()` lost its
  `pending_files` argument), the profile hint is the spec's `Profile "Healer": Delete, Rename or Copy it`, the
  locked hint "ElvUI is blacklisted: u unlocks it for this session". The squeeze (GUIDE_MAX_ROWS) stays: it no
  longer triggers for ordinary names, but a long profile, character or addon name, or 100+ pending changes, still
  makes the guide wrap, and the plan's condition for dropping it ("if it no longer triggers") is not met.
- Task S3: the review footer was still cut at 120 columns (it lost "q Quit" and "s Settings"). `d`, `p` and `m` are
  no longer in the footer (show=False): each is on an action bar button with its key, and in the left pane's hint.
  `SETTINGS_FIT_TOOLS` / `FOOTER_TOOLS` are gone: those checks run for every tool. The Ace3 settings form has no
  checkboxes; it already fit at 120x30.
- Task S3: popups. The quick actions list (`max-height` is now its 12 actions + 2) showed 10 of 12 actions; the target
  popup's body (`40vh`, was `35vh`) cut the last line of a 10-addon delete at 120x30. The recovery popup puts the zip
  path on a line of its own; a path with a space ("World of Warcraft") still wraps at that space when it is longer
  than the popup (84 columns), which was left as it is.
- Task S3: the Ace3 result screens named whole paths (WTF backup, Original files, Journal), cut at 120 columns. As in
  the WTF Cleaner (S2): a "Backup folder" row, then `snapshots/<name>`, `edited/<name>` and `journal/<name>`
  (`report.in_backup_folder`; a file outside the backup folder, such as the journal when the backup folder is set
  elsewhere, keeps its whole path).
- Task S3: tests moved to BASE and renamed: `test_recovery_popup_fits_at_base` (now also checks the path's own
  line), `test_popups_fit_at_base`, blacklist `test_fits_at_base`. None was removed. Seen in the renders and left as
  they are: tree lines longer than the tree pane at 120x30 (for example "Default copy · 0 characters · copy of
  Default · unused") end at the pane's edge and the tree scrolls sideways, as S2 left them; the result screens leave
  blank rows under a short detail table; the left pane's hint takes 5 rows at 120x30 and still fits.
