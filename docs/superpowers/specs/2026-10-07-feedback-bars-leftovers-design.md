# Bottom bars during a scan, one-press Leftovers: design

Date: 2026-10-07. Branch: `fix/feedback-2026-10-07-b`. Plan and ledger:
`../plans/2026-10-07-feedback-bars-leftovers.md`, `../plans/2026-10-07-feedback-bars-leftovers.status.md`.

User feedback 2026-10-07 (screenshots of the Ace3 Profile Manager): clicking Leftovers should first tick all leftover
characters, then remove them; and scanning or rescanning moves the action strip under the tree to the top of the
pane, when it should stay at the bottom, in every tool, as a standard.

## Decisions

| # | Topic | Decision |
|---|---|---|
| L1 | Leftovers (`o`) | Pressing Leftovers (button or `o`) first ticks every leftover character shown in the tree (the same set as More… → "Tick all leftover characters": what the View, the Show boxes and the `/` filter show; locked addons excluded as today), then opens the existing "Remove leftover characters?" confirm for exactly the ticked leftovers. With none shown it says "No leftover characters are shown." and changes nothing. Cancelling the confirm keeps the ticks (visible, so the user sees what would have gone). Help, guide, docs and CHANGELOG say so. |
| L2 | Bars stay at the bottom | While a scan (or anything else) stands in for a tree, the rows under the tree (the Ace3 guide and action bar, the SV Browser action bar, any future one) stay at the bottom of the pane: the shared `two_pane_css` gives `#scan-box` the tree's space (`height: 1fr`), so the stand-in fills the pane as the tree does. Applies to every two-pane screen through the shared CSS. |
| L3 | Standard | A new STD-7 MUST in `docs/standards.md`: a screen's bottom bars and button rows keep their position whatever stands in for the tree (scan progress, an empty or failed scan, a load); enforced by a test that scans every tool's review (and every two-pane screen with a scan box) and checks the rows under the tree and the left pane's button row sit at the same place during and after the scan. |
| L4 | Risk disclaimer | User feedback (screenshot of the SV Browser's USE AT YOUR OWN RISK popup): WTF Cleaner and Ace3 Profile Manager get the same kind of disclaimer, shown at most once per session. One shared disclaimer popup in `wowtools/ui/` (title, tool-specific text, Back (Esc) / I understand, I understand focused), shown after the flavor pick and before the first scan, at most once per tool per app session (remembered on the app; a Back does not count as seen, so it is asked again next time). The SV Browser keeps its text and moves to the shared popup and the once-per-session rule (this replaces its spec's D2 "each time the tool is opened"). Each tool logs its own accepted/declined events (registered; docs/events.md regenerated). Texts: honest about what each tool deletes or rewrites, that backups and Undo exist, and to close WoW first. Help, guides, README, CHANGELOG updated. |
| L5 | `t` on the pickers | The flavor and account picker screens (`ui/flavor_screen.py` and any other pre-review picker) bind `t` to go back to the tool menu, like every review and result screen; Esc keeps doing what it does today. The footer and hint name both (D17: no button carries `t`). Help and guides updated. |

