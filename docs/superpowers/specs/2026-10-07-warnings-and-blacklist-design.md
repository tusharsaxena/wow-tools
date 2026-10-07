# Warnings view and the blacklist key: design

Date: 2026-10-07. Branch: `feat/warnings-blacklist` (built on `feat/wtf-orphan-backups`, not merged yet). Plan:
`../plans/2026-10-07-warnings-and-blacklist.md`, ledger `../plans/2026-10-07-warnings-and-blacklist.status.md`.

User feedback 2026-10-07: "⚠ 4 scan warnings (see the log)" is useless, since nobody reads the logs; and a `b` key
should blacklist the highlighted tree entry (example: `ElkBuffBars` in the WTF Cleaner review) in every tool where
blacklisting makes sense. Each tool keeps its own blacklist mechanism; only the `b` action on a tree node is shared.

## Decisions

| # | Topic | Decision |
|---|---|---|
| W1 | Warnings view | One shared `WarningsScreen` in `wowtools/ui/` (a full screen in the suite look: title, a list or tree of warnings grouped by flavor where known, each showing *where* (path or name) and *what*, the `/` filter, `h` help, Esc/Back returns). Every place that today says "(see the log)" or counts warnings opens it: the warning line becomes clickable (mouse), and one key (free on every screen that shows warnings; the implementer picks it, e.g. `!`, and puts it on a button or the footer per D17) opens it by keyboard. The line drops "(see the log)" for "(click or press <key> to see them)" or similar. |
| W2 | Which warnings | Every tool's scan warnings and unreadable-folder/file notes it already collects: WTF Cleaner (`ScanWarning`s), Screenshot Organizer (folders it could not read), Ace3 Profile Manager (scan warnings), Interface Backup (scan warnings, the tree's warning rows, the restore screen's warnings), Saved Variables Browser (unreadable files and flavor scan warnings). Messages are the existing texts; nothing new is invented. The logs keep logging them. |
| B1 | Shared `b` | A shared tree action in `wowtools/ui/review.py` (mixin or helper): `b` on the highlighted node asks the screen for the blacklist target of that node (`blacklist_target(node) -> (flavor folder, addon) | None`; a file or profile node maps to its addon; a group node with no single addon does nothing, with a short notice), then the tool's own `toggle_blacklist(flavor, addon)`, then a toast "<Addon> (<Flavor>) is now / no longer on the blacklist" and a rebuild. The pair helpers (`Pair`, `parse_blacklist`, `format_blacklist`, `is_blacklisted`, `toggle_pair`, `unique_pairs`) move from the Ace3 Profile Manager into `wowtools/core/` (two-tool rule); Ace3 keeps its behaviour, its blacklist screen and its session unlock `u`, and every Ace3 test assertion. |
| B2 | WTF Cleaner blacklist | New, WTF-Cleaner-only: `[wtf_cleaner] blacklist` (same `flavor:Addon` pair format as Ace3, case-insensitive, `*` = every flavor). A blacklisted addon is never cleaned: its rows stay in the review tree, greyed, tagged "blacklisted", unticked and not tickable (space, `a`, `n` skip them), not counted in the criteria counts, the summary or the confirm, and never passed to Clean or Dry run. `b` on an addon row or one of its file rows toggles it for that flavor. The settings form gains no new rows (it must fit at 120x30); the guide says how to edit the list by hand and that `b` takes an addon off again. Logged as `wtf.blacklist_changed` (or the tool's existing event naming). |
| B3 | Not in scope | Screenshot Organizer and Interface Backup (no addon-level target), Saved Variables Browser (it changes only what the user edits). |
| B4 | Keys | `b` must be free on the WTF Cleaner review (check); it shows in the footer or on a button per D17, and in each tool's help. |
