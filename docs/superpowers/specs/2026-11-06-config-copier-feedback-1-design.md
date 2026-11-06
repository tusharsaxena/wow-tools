# Config Copier feedback round 1: change the source, a Diff that stands out, side-by-side diff

The user's first smoke test of the Config Copier (2026-11-06, on master after feedback round 2) asked for four
changes. The Macro Editor passed its smoke test with no feedback. Decisions CP1-CP4.

## Decisions

| ID | Decision |
|---|---|
| CP1 | **Change the source.** Today a picked source can only be dropped by going back to the tool menu (Rescan keeps it). The review gets a **Change source** action on `p` (my call: the key and a compact `navigate` button by the Source line in the left pane). It clears the source and returns to the source picker for the same flavor choice (the one the user picked on the flavor screen, All flavors included), with nothing ticked: ticks belong to the old source. It goes through the review's normal way out (`action_leave`), so it is refused while a run writes and asks first only where leaving already asks. Rescan keeps the source, as now. |
| CP2 | **No change to `⚠ action bars`.** The user asked what it means; the answer (a replaced `macros-cache.txt` on a character that already has macros renumbers its macros, so action bar buttons may point at the wrong macro) satisfied them. Label and docs unchanged. |
| CP3 | **A Diff button that stands out.** The user found the Diff button under the tree too dim (it is a disabled grey `navigate` button whenever the highlighted row is not a replaced file). STD-8.2 keeps one colour per action kind and amber means "overwrites files", so yellow is out (user: "make diff stand out in a different way"). My call: Diff becomes a `confirm` kind button (the suite's blue, "the expected next step": looking at what a copy replaces before writing it), and while it is disabled a short dim line beside it says why: `highlight a replaced file to see its diff` (the reason the `d` key already gives, shortened). Where the action bar is too narrow for it (80 columns: about 30 cells beside a 50-cell left pane) the line is cut at its end with `…` to the room left after the button, and hidden below 10 cells; the button never moves (my call). While a scan or a run is going on the line is empty. No STD-8.2 deviation. |
| CP4 | **Side-by-side diff, inline on a key.** The diff screen opens side by side: the target's file as it is on the left, what the copy gives it on the right, each with its own line numbers; removed lines red on the left, added green on the right, a changed run of lines paired row by row (a `replace` opcode: old line i beside new line i, the longer side's extra lines beside a blank), kept lines on both sides, the same three lines of context and `…` gaps as today, a `config-cache.wtf` whole with its kept state lines noted. `v` switches to today's inline (unified) view and back; it is bound only on the diff screen and shown on its hint line and as a button. My calls: below 100 columns (two columns under about 45 cells each) the screen opens inline and its head says so (`v` still switches); a long line is cut at its end with `…` rather than wrapped, so the two sides stay row-aligned (inline keeps today's behaviour); the view chosen with `v` lasts for the session (the next diff opens in it), not saved as a setting. An explicit `v` choice wins over the width rule: the 100-column rule applies only while the user has not pressed `v` this session (the session holds the user's chosen view, or none), and the head's `opened inline: the window is narrow` note shows only when the width rule picked inline. The width is checked when a diff opens, not on a resize while it is open (my calls). The head line's counts (lines removed, added, state lines kept) are the same in both views. |

## Not changing

The planner, the merge, the copy, its safety nets and journal, the tree and its counts and columns (round 2), the
`⚠ action bars` label, the source picker itself.

## Builder notes

- The side-by-side rows are a pure function in `config_copier/report.py` beside `diff_rows` (no Textual), tested
  on its own; the screen only draws them. No other tool has a diff, so nothing moves to `ui/`.
- `v` on the diff screen matches the suite's existing `v` = switch view (Ace3 Profile Manager, SV Browser).
- User guide `docs/config-copier.md` (keys table, the Diff section, the review's left pane), internals doc, the
  in-app help (`config_copier/help.py`), and one short CHANGELOG `[Unreleased]` line (the Config Copier is
  unreleased: fold it into its Added line if that reads better). Stale screenshots are noted, not retaken (the user
  retakes them).
- 120x30 and 80x24 still fit (STD-7.23, STD-7.28).
