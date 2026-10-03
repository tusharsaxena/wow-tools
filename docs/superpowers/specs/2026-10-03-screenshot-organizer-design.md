# Ka0s WoW Tools: Screenshot Organizer design

Date: 2026-10-03. Second tool in the suite. It follows `docs/adding-a-tool.md` and the conventions in
`2026-09-27-wtf-cleaner-design.md` (with Addenda A–D).

## 1. Purpose

Move (or copy) the screenshots of each WoW flavor out of `<WoW>/<flavor>/Screenshots/` and file them into
`YYYY/MM/DD` folders, separately per flavor. This replaces the old `wow_screenshot_organizer.py` script. That
script moved `WoWScrnShot_MMDDYY_HHMMSS.(jpg|png)` from `_retail_` and `_classic_` into
`<target>/<flavor folder>/YYYY/MM/DD/`. The new tool keeps that layout, so the existing archive keeps growing as
it is, and adds the suite's guard rails, TUI, logging and tests.

## 2. Decisions

| Topic | Decision |
|---|---|
| Flavor scope | The flavor picker gets an **All flavors** entry first, then each flavor. The choice is remembered. |
| Destination | Setting `dest_dir`. If it is set: `<dest>/<flavor folder>/YYYY/MM/DD/<name>`, e.g. `<dest>/_retail_/2019/07/31/WoWScrnShot_073119_232713.jpg`. If it is empty, the files are organized **in place**: `<WoW>/<flavor>/Screenshots/YYYY/MM/DD/<name>`. File names are never changed. |
| Date source | The file name only: `WoWScrnShot_MMDDYY_HHMMSS.<ext>` with ext `jpg`, `jpeg`, `png` or `tga` (any case), and year `20YY`. The date must be a real calendar date. Anything else is **skipped** ("name not recognised") and left where it is. |
| Same name at the target | Same size and SHA-256 means a **duplicate**: the source is removed, or left alone in copy mode, and counted as "already filed". Different content is a **conflict**: both files are left alone and it is reported. Nothing is ever overwritten. |
| Extras | Dry run, copy mode, and undo of the last run (via a run journal). There is **no** WoW-running check, because filing screenshots does not depend on the game. |
| Global config | `wow_path` is already shared (`[general]` in `config/wow-tools.cfg`), so no other key needs to move. |

## 3. Package layout

`wowtools/tools/screenshots/`. Tool name `screenshots`, config `config/screenshots.cfg` with section
`[screenshots]`, logs in `logs/screenshots/`. Menu entry: "Screenshot Organizer", "File screenshots into
year/month/day folders, per flavor."

| Module | Job |
|---|---|
| `__init__.py` | imports `events` |
| `events.py` | the tool's event registry (§8) |
| `naming.py` | `SHOT_RE`, `parse_shot_name(name) -> date \| None`, `day_parts(date) -> (YYYY, MM, DD)` |
| `settings.py` | `ShotSettings`, `load_settings`, `save_settings`, `target_root(flavor, settings)`, `resolve_journal_dir(wow_path)`, `validate_dest(dest, install)` |
| `planner.py` | `scan(flavors, settings, progress) -> Plan` |
| `organizer.py` | `execute(plan, *, copy, dry_run, journal_dir, keep_journals, progress) -> OrganizeResult` |
| `journal.py` | write/read/list journals, `undo(journal, progress) -> OrganizeResult`, `prune_journals` |
| `report.py` | labels, stage titles, result rows (UI-free text helpers) |
| `app.py` | (UI) `ScreenshotsFlow` (`FLOW`), `ScreenshotSettingsScreen` |
| `review_screen.py` | (UI) `ShotReviewScreen`, `ShotProgressScreen`, `ShotResultScreen` |

Everything except `app.py` and `review_screen.py` is UI-free and never imports `textual`.

## 4. Settings (`[screenshots]` in `config/screenshots.cfg`)

| Key | Default | Meaning |
|---|---|---|
| `dest_dir` | empty | The archive root. Empty means in place. Stored in Windows form (`core/paths`). |
| `copy_mode` | false | Copy instead of move. |
| `last_flavor_choice` | empty | Empty means All flavors, otherwise a flavor folder such as `_retail_`. |
| `keep_journals` | 10 | Run journals to keep (at least 1). |

Validation (`validate_dest`): if set, the destination must not be inside any flavor's `Screenshots` folder (in
place covers that case) and must not be the WoW folder itself. It need not exist yet, because it is created on
the first real run. Bad stored values fall back to defaults, as `Config` does.

Journals live in `<WoW>/wow-tools/screenshots/journal/`, beside the WTF Cleaner's output folder and never in the
screenshot destination, which may hold other programs' files (e.g. digiKam databases).

## 5. Scan and plan (`planner.py`)

`scan(flavors, settings, progress=None)` does one directory listing per `<flavor>/Screenshots` folder, of
**top-level files only**. Date folders already made in place are never descended into. A flavor without a
`Screenshots` folder contributes nothing. For every file:

- If the name does not parse, it becomes `Skipped(path, "name not recognised")`.
- Otherwise the target is `target_root(flavor) / YYYY / MM / DD / name`. If no file exists there it becomes a
  `ShotMove`. If one exists with the same size it is a candidate duplicate; if the size differs it is a conflict.
  The hash comparison runs at execute time, so the scan stays cheap.

Data:

    Plan(flavors: list[FlavorPlan], dest_dir: Path | None)
    FlavorPlan(flavor, source_dir, target_root, items: list[ShotItem], skipped: list[Skipped])
    ShotItem(src: Path, dst: Path, day: date, size: int, mtime: float, state: "new" | "maybe_duplicate" | "conflict")

Progress: `progress(current, total, label)` once per flavor folder, plus a mid-folder tick every 500 files. The
scan reads `os.scandir` entries, whose `stat` is cached on Windows, and never calls `resolve()` per file, because
`resolve()` is slow over WSL drvfs.

## 6. Execute (`organizer.py`)

`execute(items, *, copy, dry_run, journal_dir, keep_journals, progress=None, move_fn=None)` runs over the items
the user left ticked:

1. **Path guard.** `src.parent` must equal the flavor's `Screenshots` folder, and `dst` must sit lexically under
   `target_root` (with no `..` parts) as `YYYY/MM/DD/<src.name>`. The roots are resolved once per run. A failed
   guard gives a `refused` outcome; the file is not touched.
2. **Re-check.** The source must still exist with the scanned size, else the outcome is `skipped` ("changed since
   scan").
3. **Target exists.** Hash both files. If they are identical, a move deletes the source (`duplicate_removed`) and
   copy mode does nothing (`already_filed`). If they differ, the outcome is `conflict` and neither file is touched.
4. **Move.** `os.makedirs(dst.parent)`, then `os.rename(src, dst)` when on the same device (the target was checked
   absent just before). Across devices (`OSError` with `EXDEV`, or different `st_dev` on the roots), copy to
   `dst.with_name(name + ".partial")`, compare size and SHA-256 with the source, rename to `dst`, then delete the
   source. If that delete fails, the outcome is `copied_source_left`, which is a warning, not a failure. A failed
   verification deletes the partial file and gives `failed`.
5. **Copy mode** is step 4's copy path without deleting the source: `copied`.
6. **Journal.** A real run (not a dry run) opens `journal-<YYYYMMDD-HHMMSS>.jsonl` first. Line 1 is the header
   `{"version": 1, "started", "copy", "dest_dir", "suite_version", "flavors"}`. After each completed action it
   appends `{"action": moved|copied|copied_source_left|duplicate_removed, "src", "dst", "size"}` and flushes.
   The journal is accurate even after a crash. At the end it appends `{"finished": <iso>}`. The newest
   `keep_journals` are kept (`prune_journals`); undone journals count towards the limit.
7. **Dry run** walks the same checks, including hashing, and reports `would_move`, `would_copy`,
   `would_remove_duplicate` and `conflict`. It creates no folders and writes no journal.
8. **Errors.** A per-file `OSError` gives `failed` (with the message) and the run continues. Any other exception,
   or `KeyboardInterrupt`, ends the run. The journal holds everything done so far, and the exception is
   re-raised to the UI, which shows it and points at Undo.

`OrganizeResult(outcomes: list[Outcome], journal_path: Path | None, dry_run: bool, copy: bool)`, where
`Outcome(flavor, src, dst, kind, reason)`. Progress: `progress(stage, current, total, detail)` with stages
`organize` and `prune`. An exception inside the callback is swallowed.

## 7. Undo (`journal.py`)

`latest_undoable(journal_dir)` returns the newest journal without an `undone` record. `undo(path, progress=None)`
walks its entries in reverse:

- `moved` or `copied_source_left`: if `dst` exists with the recorded size and `src` is free, move it back (same
  device rename, else copy-verify-delete). `copied_source_left` only deletes `dst` if `src` still exists with the
  same size.
- `copied`: delete `dst` if it exists with the recorded size and `src` still exists.
- `duplicate_removed`: copy `dst` back to `src` if `src` is free.
- Anything else, or a check that fails, gives `undo_skipped` (with the reason).

Afterwards empty `DD`, `MM` and `YYYY` folders that this journal's targets lived in are removed, bottom-up, only
when empty and only if their names are digits of the right length. The journal gets
`{"undone": <iso>, "restored": n, "skipped": m}` appended. An undone journal is never offered again. Undo uses the
same path guard as execute, applied to the journal's `src`/`dst` pairs (the src parent must be a `Screenshots`
folder of the configured install).

## 8. Events (`events.py`, tool `screenshots`)

| Event | Level | When |
|---|---|---|
| `scan.started` | info | a scan of the chosen flavors started |
| `scan.completed` | info | counts per flavor (to file, duplicates, conflicts, skipped) |
| `scan.warning` | warning | an unreadable Screenshots folder |
| `organize.started` | info | a run (or dry run) started: mode, dest, count |
| `shot.moved` / `shot.copied` | info | one file filed |
| `shot.would_file` | info | dry run: one file that would be filed |
| `shot.duplicate_removed` | info | the source was identical to the filed copy and was removed |
| `shot.already_filed` | info | copy mode: an identical file was already at the target |
| `shot.conflict` | warning | a different file with the same name is at the target |
| `shot.skipped` | warning | the source vanished or changed after the scan |
| `shot.source_left` | warning | copied across drives, but the source could not be deleted |
| `shot.refused` | error | the path guard refused a file |
| `shot.failed` | error | a file could not be filed |
| `organize.completed` | info | totals (warning if any file failed) |
| `journal.pruned` | info | older journals were deleted |
| `undo.started` / `undo.completed` | info | undo of a journal |
| `undo.skipped` | warning | an entry could not be undone safely |

Unrecognised file names are counted in `scan.completed` (with up to 20 sample names) rather than logged one by
one. `docs/events.md` is regenerated.

## 9. TUI

All screens have `Header`, `BrandBar`, `Footer` and `NavHint`, and use the shared `NAV_BINDINGS`, `ButtonRow`,
`Ka0sCheckbox` and `ConfirmScreen`.

Flow (`ScreenshotsFlow`): `require_install` → first open of the tool: `ScreenshotSettingsScreen` →
`FlavorScreen(..., include_all=True, last=...)` → scan (thread worker, progress bar on the review screen) →
`ShotReviewScreen` → `ConfirmScreen` → `ShotProgressScreen` → `ShotResultScreen`. `s` opens the shared WoW-folder
settings, then this tool's settings. `t` goes back to the tool menu, and `Esc` on the flavor screen also does.

- **`FlavorScreen`** gains optional `include_all: bool = False` and `last: str | None`. With `include_all`, the
  first option is "All flavors" and the screen dismisses with the sentinel `ALL_FLAVORS`. Existing callers do not
  change. The organizer stores the choice in `last_flavor_choice`; picking a single flavor also updates
  `[general] last_flavor`, as it does today.
- **`ScreenshotSettingsScreen`** has fields for the destination folder (placeholder: "Empty = in place:
  <WoW>/<flavor>/Screenshots/YYYY/MM/DD"), "Copy instead of move", and "Journals to keep". It shows an error line
  on invalid input.
- **`ShotReviewScreen`**:
  - Left: a tree of flavor → YYYY → MM → DD (count) with tick marks at every level, all ticked at the start. Day
    nodes load their files lazily. Each flavor has read-only "Conflicts (n)" and "Skipped (n)" nodes.
  - Right: totals for the ticked items (to file, possible duplicates, conflicts, skipped), mode, destination and
    the journal folder.
  - Buttons: **Organize (o)**, **Dry run (y)**, **Rescan (r)**, **Undo last run (z)**, **Tools (t)**. Undo is
    disabled when there is no undoable journal. (`u` stays the app-wide update key.) The other keys match the
    cleaner's review screen: Space tick/untick, `a` all, `n` none, `f` flavors, `q` quit.
  - If nothing is left to file it says so, and Organize and Dry run are disabled.
- **Confirm:** "Move N screenshots to <dest>?" (or Copy, or "Dry run: …"). Starts on No for a real run and on Yes
  for a dry run. Undo confirm: "Undo the run from <stamp>: put back N files?", starting on No.
- **`ShotProgressScreen`:** stage title, progress bar and the current file name. Updated through
  `app.call_from_thread`.
- **`ShotResultScreen`:** a summary table (one row per outcome kind with counts) and a per-file `DataTable`
  (flavor, outcome, file, target, reason). It shows the journal path. Buttons, as on the cleaner's result screen:
  **Rescan (r)**, **Flavors (f)**, **Tools (t)**, **Quit (q)**.

## 10. Testing

`tests/fixtures.py` gains `build_screenshot_tree(root)`, which adds the following to the synthetic install:

- `_retail_/Screenshots`: valid shots on two days, a `.PNG`, a `.tga`, an invalid date (`WoWScrnShot_023119_…`),
  an unrelated `notes.txt`, and an existing in-place `2025/01/02/` folder with a shot in it.
- `_classic_era_/Screenshots`: shots on one day.

Tests also create an external destination holding a duplicate, a conflict and a foreign `digikam4.db`.

- `test_screenshots_naming.py`: valid and invalid names, case, extensions, calendar validity.
- `test_screenshots_planner.py`: in-place vs external targets, top-level only, duplicate/conflict states,
  flavors without Screenshots, progress calls.
- `test_screenshots_organizer.py`: same-device move, cross-device move through an injected `move_fn` raising
  `EXDEV`, copy mode, dry run creates nothing, duplicate removed vs conflict kept, re-check skip, path-guard
  refusal, per-file `OSError`, journal lines written as it goes, journal pruning, foreign files untouched.
- `test_screenshots_journal.py`: undo of each action kind, mismatch skips, empty date folder pruning (never a
  non-date or non-empty folder), an undone journal is not offered again, a journal cut short by a crash still
  undoes.
- `test_screenshots_settings.py`: round trip, defaults on bad values, `validate_dest`.
- `test_screenshots_app.py` (`TuiTestCase`): menu → tool → first-run settings → All flavors → review → organize →
  result; dry run; undo; single-flavor pick; the `FlavorScreen` "All flavors" option; the cleaner's flavor
  screen is unchanged.
- `test_docs.py` / `test_events.py` keep passing (events.md regenerated, the README tools table).

No test touches a real install, the real archive or the network.

## 11. Documentation

- README: a Screenshot Organizer section and tools-table row.
- `docs/architecture.md`: config schema, data flow and screens.
- `docs/events.md`: regenerated.
- `docs/adding-a-tool.md`: its worked example now matches the shipped tool.
- `CLAUDE.md`: mentions the second tool.

## 12. Out of scope

Date from EXIF or file times, renaming files, deduplicating within the archive, thumbnails or a gallery, a
WoW-running check, and more than one level of undo history in the UI (older journals are kept for reference
only).
