# Feedback round 2: tree counts and columns everywhere, Config Editor polish

The user's second smoke test (Config Editor, on `feat/config-editor-feedback-1`, after spec
`2026-11-04-config-editor-feedback-1-design.md`) asked for six changes, two of them suite-wide standards that every
tool adopts. Decisions R1-R6.

## Decisions

| ID | Decision |
|---|---|
| R1 | **Help panel colour (Config Editor).** The CVar name at the top of the help panel is coloured (my call: the suite's gold header colour, bold) and every label (Value, Default, State, Category, Type, Blizzard, Note, Recommended, Scope, Sources and the source names in the bullets) is coloured (my call: the theme's cyan accent, bold). Values stay in the normal text colour; state and category keep their CF3 colours. |
| R2 | **Leaf counts on every tree node: a suite standard.** Every tree node that has children shows, after its label and dimmed, how many leaf-level items sit below it at any depth: `27 items`, `1 item`. "Leaf-level" is the thing the tool lists and acts on (WTF Cleaner's addon entries, Config Editor's CVar rows, Macro Editor's macros, a file pair, a profile, a screenshot, a backup, a SavedVariables key...), counted as the tree currently shows them (after the search and the tool's own Show filters). Each tool decides what its leaf is and documents it in its internals doc. WTF Cleaner already does this (`Retail  27 items`) and is the reference look. New MUST rule in `docs/standards.md` section 7, enforced by a test per tool, and a shared helper in `wowtools/ui/` so the text and style are one implementation. Lazily loaded nodes count from the model, not from loaded children. Example: `Retail 100 items` > `ADD1KTED2KA0S 80 items` > `Frostmourne 60 items` > `Aellâ 20 items`. |
| R3 | **Not-set rows darker (Config Editor).** A row for a CVar the file doesn't set (Show all known) is drawn in a darker dim than today: still readable on the dark background (my call: at least 3:1 contrast), clearly darker than the set rows. |
| R4 | **Columns for node data: a suite standard.** Wherever a tree node shows more than one piece of data (a name plus a reason, size, age, date, value, status...), the pieces sit in aligned columns, as the Config Editor's CVar rows do (FB2): each column as wide as its widest cell among the sibling rows it aligns with, long cells cut with `…`, the secondary columns dim or coloured as the tool already colours them, and the columns refit when the pane is narrow (cut the widest free-text column first, never the short status-like ones). New MUST rule in section 7 beside R2; the fitting logic moves from `config_editor/report.py` into one shared helper (`wowtools/ui/columns.py`, pure functions, no Textual import needed) that every tool uses. Every tool is changed to adopt it where it shows data on nodes (WTF Cleaner's `name · reason · files · size · age` is the user's example). A node with only a name and its R2 count is not a column row. |
| R5 | **Category counts (Config Editor).** Each entry in the category dropdown shows how many CVar rows it would show under the current filters (search, Changed only, Show all known, game version), across the whole tree: `Graphics (22 items)`, `Sound (1 item)`, `All categories (340 items)`. The counts update when a filter changes. |
| R6 | **Shrink "other".** The 250 CVars in "other" are re-sorted. Three new groups are added (my call, read off that list): **game state** (what the client remembers rather than a setting: `seen*`, `last*`, `read*`, `new*Season`, renown and transmog trackers, `num*` counters, unlocked lists), **debug** (developer, logging, error and event-log, frame stack, taint, profiling CVars) and **system** (threads, async, cache, install and hardware detection, kiosk, OS). "Other" keeps only what fits nothing, ideally a handful. The new groups get their own colours (theme) and appear in the dropdown. |

## Not changing

Each tool's tree structure, keys, safety nets and writes. Only labels (R2 counts, R4 columns) and the Config Editor
items change.

## Builder notes

- Per-tool work also updates its internals doc (what its leaf is, which columns) and its user guide where a
  screenshot or a described row changes. Screenshots are retaken by the user by hand; note which ones go stale.
- One CHANGELOG `[Unreleased]` line for the suite-wide counts and columns.
- 120x30 and 80x30 still fit (STD-7.23); at 80 columns columns shrink to their minimums and a row may scroll.
