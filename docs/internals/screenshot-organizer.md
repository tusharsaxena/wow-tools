# Screenshot Organizer internals

How the Screenshot Organizer (`wowtools/tools/screenshot_organizer/`) plans, files and undoes, and how its screens are built.

User guide: [screenshot-organizer.md](../screenshot-organizer.md). Rules every tool follows: [standards.md](../standards.md).
Back to [architecture](../architecture.md#tools).

## Contents

- [Data flow](#data-flow)
  - [Targets](#targets)
  - [Scan](#scan)
  - [No per-file resolve or stat](#no-per-file-resolve-or-stat)
  - [Guard](#guard)
  - [Filing](#filing)
  - [Journal](#journal)
  - [Undo](#undo)
- [Screens](#screens)

## Data flow

    scan(flavors, dest_dir, progress=None) → Plan(flavors[FlavorPlan(items[ShotItem], skipped[Skipped])], dest_dir)
    TUI selection → execute(items, dest_dir, copy, dry_run, journal_dir, keep_journals, progress=None)
                      → OrganizeResult(outcomes[Outcome], journal_path, pruned)
    undo(journal_path, wow_root, progress=None) → OrganizeResult(undo=True)

Modules in `tools/screenshot_organizer/` (all UI-free except `app.py` and `review_screen.py`): `naming` (`parse_shot_name`,
`day_parts`), `settings` (`ShotSettings`, `source_dir`, `target_root`, `validate_dest`),
`planner`, `organizer`, `journal` (`resolve_journal_dir`), `undo` and `report` (labels, stage titles, rows and the confirm text).

### Targets

`target_root(flavor, dest_dir)` is `<dest_dir>/<flavor folder>`, or the flavor's `Screenshots`
folder when `dest_dir` is `None` (in place). A shot goes to `target_root/YYYY/MM/DD/<name>`; the day comes from
`WoWScrnShot_MMDDYY_HHMMSS.<jpg|jpeg|png|tga>` only. `validate_dest` wraps `install.validate_output_dir` (a full path, not
the WoW folder, not inside any flavor's `WTF`, `Interface` or `Screenshots`); it runs on the settings screen and
again in `action_rescan`, which refuses to scan a hand-edited bad `dest_dir`.

### Scan

One listing per `Screenshots` folder (top-level files only) and one names-only listing
(`planner.list_names`) per target day folder. Only a name already at the target is stat'ed, to set the state:
`new`, `maybe_duplicate` (same size) or `conflict` (other size). In copy mode (`scan(..., copy=True)`) a same-size
target is `filed` instead (the modified time is not compared: not every copy keeps it): the original stays in `Screenshots` after a copy, so it is not "to file" (`FlavorPlan.to_file` leaves it out), the review
screen lists it in an unticked Already filed group, and `execute` still compares hashes if it is ticked.
`waiting_count(flavor, dest_dir, copy=)` (the flavor picker's counts) lists names only; in copy mode it also lists
each target day folder and leaves out names already there. `count_waiting(flavors, dest_dir, copy=, parallelism=)`
runs it for every flavor, up to `parallelism` at once (`core/parallel.py`), into `{folder: count | None}` for the
picker's worker. `scan` itself stays one loop (cheap listings sharing one target-folder cache), and so does
`execute` (one journal, one shared cache, and a journal write error must stop the whole run). Unparsable names become `Skipped`. Progress is
`cb(current, total, label)` once per flavor, plus a tick every 500 files.

### No per-file resolve or stat

`resolve()` and per-entry `stat` are slow over WSL drvfs, so neither the scan
nor `execute` calls them per file. `execute` reuses one listing per source folder (re-check: missing or changed
size gives `skipped`) and one names-only listing per target day folder. Beyond that it stats only where a hash, a
copy, or the no-overwrite `lexists` check right before a rename or copy needs it (POSIX `rename` overwrites).
`os.makedirs` runs once per day folder.

### Guard

Every item is checked lexically, with no resolve: `src.parent` must equal `source_dir(flavor)`, the
name must parse to the planned day, and `dst` must equal exactly
`target_root(flavor, dest_dir)/YYYY/MM/DD/<src.name>` with no `..` part. A failure is `refused` and the file is
not touched. The TUI passes the scanned plan's `dest_dir`, so a settings change after a scan can't make the guard
refuse every file.

### Filing

A same-name file at the target is hashed (SHA-256): identical means `duplicate_removed` (move: the
source is deleted) or `already_filed` (copy); different means `conflict`, and neither file is touched. A move is
`fsutil.rename_no_replace` (POSIX: hard link then unlink, so a file that appears at the target is never
replaced; Windows: `os.rename`); on `EXDEV` (and always in copy mode) `copy_verified` copies to `<name>.partial`, checks size and
SHA-256, then renames into place. After a cross-device move a failed source delete is `source_left`, a warning. A
`FileExistsError` from the last check is `conflict`. Nothing is ever overwritten. A dry run walks the same checks,
hashing included, and reports `would_move` / `would_copy` / `would_remove_duplicate`; it creates no folders and
writes no journal. A per-file `OSError` is `failed` and the run continues; anything else (including
`KeyboardInterrupt`) raises `OrganizeError` with `.result`. Progress is `cb(stage, current, total, detail)` with
the stages in `report.STAGE_TITLES` (`organize`, `prune`, `undo`), wrapped by `fsutil.safe_progress`.

### Journal

Code: `journal.py`, the organizer's entries on top of `core/journal.py`. A real run writes `<WoW>/wow-tools/screenshot-organizer/journal/journal-<YYYYMMDD-HHMMSS>.jsonl`
(`-2`, `-3`… on a clash), JSON Lines:

    {"version": 1, "started": iso, "copy": bool, "dest_dir": stored path | null, "suite_version": "...", "flavors": [...]}
    {"action": "moved" | "copied" | "copied_source_left" | "duplicate_removed", "src": stored, "dst": stored, "size": n}
    {"finished": iso, "entries": n}
    {"undone": iso, "restored": n, "skipped": n}

`JournalWriter.open()` writes the header before anything is touched; if that fails the run raises
`OrganizeError` and nothing moves. Each action is appended and flushed after it happens. If an append fails, the
change is reported done with a "not journaled" reason and the run stops (`JournalWriteError`). A header-only
journal is deleted, so a run that changes nothing leaves none. After a run that wrote one, `prune_journals` keeps
the newest `keep_journals` (undone ones count). `read_journal` skips torn lines (it reads with
`errors="replace"`), and `mark_undone` starts its record on a new line after a torn last line.

### Undo

Code: `undo.py`. `latest_undoable(journal_dir)` returns the newest journal with entries that is not undone,
and never reaches back past an undone one: one level of undo only. `undo()` walks the entries newest first. Each
entry passes a guard: `src` directly in a `Screenshots` folder of a flavor under `wow_root`, with a WoW screenshot
name; `dst` exactly `target_root(flavor, header dest_dir)/YYYY/MM/DD/<src name>`, the date from the name (so a
tampered journal cannot point Undo at a file anywhere else). `read_journal` drops entries without paths or with a
size that is not a number, and `latest_undoable` treats an unreadable journal as not offered. Then:

- `moved`: if `dst` has the recorded size and `src` is free, move it back (`move_file`, copy-verify-delete across
  devices; a failed delete of the archive copy is still `restored`, with a reason); a missing `dst` with `src` back
  at the recorded size (an interrupted Undo, or put back by hand) is `undo_skipped` ("the screenshot is already
  back in the Screenshots folder"), so the journal is closed;
- `copied` / `copied_source_left`: delete `dst` if both `src` and `dst` have the recorded size (`copy_removed`);
  a missing `dst` next to an intact `src` is already undone (`copy_removed`, "the copy was already gone");
- `duplicate_removed`: if `src` is free and `dst` has the recorded size, `copy_verified(dst, src)`;
- for `moved` and `duplicate_removed`, a `dst` that is missing altogether is `failed` (it may be on an unplugged
  archive drive; its reason says to connect it and try Undo again, shortened to "the filed copy is missing" when
  the journal is marked undone anyway); anything else, or a
  failed check, is `undo_skipped`; an `OSError` is `failed`.

Then the `DD`, `MM` and `YYYY` folders it touched are removed bottom-up while empty and digit-named, and an
`undone` line is appended (even when every entry was skipped), unless nothing was put back and something failed:
then `OrganizeResult.marked_undone` is False, the journal stays undoable and the result says Undo can be tried
again (the WTF Cleaner's rule).

## Screens

The Screenshot Organizer's screens live in `tools/screenshot_organizer/`. `app.py` holds `ScreenshotsFlow` (`FLOW`:
`require_install` → `ScreenshotSettingsScreen` on the tool's first open → `FlavorScreen(include_all=True,
last=last_flavor_choice, note="counting…")`, whose notes a `fill_notes` worker then replaces with each flavor's
`waiting_text` ("N screenshots to file", "nothing to file" or "no Screenshots folder") → review; every flavor is
listed, and with no Screenshots folder anywhere the picker is not shown) and `ScreenshotSettingsScreen` (destination,
copy mode; `validate_dest` errors show inline). `review_screen.py` holds:

- `ShotReviewScreen`: a `TreeFilter` and `ReviewBase`; the `FilterBar` (filter box and **Filter** button) (`/`, the left pane's first control: it
  matches flavor, year, month, day (`2024-01-02`) and file names on the plan, day and Already filed files included,
  and opens a day whose files match) and the flavor → year → month → day → file tree (day files load on expand; read-only
  Conflicts and Skipped nodes; in copy mode an Already filed node, unticked, that `a` leaves alone) and the Organize / Dry run / Rescan / Undo last run buttons. It uses the
  shared `ConfirmScreen`;
- `ShotProgressScreen`, a `ProgressScreen` (ids `shots-*`): one unnamed row (stage and bar) and the current file for a run, dry run or undo;
- `ShotResultScreen`, a `ResultBase`: a summary table (with a "Target folder" row) plus a per-file `DataTable` whose Target column
  names each folder inside it.
