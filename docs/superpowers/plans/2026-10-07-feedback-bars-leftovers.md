# Bottom bars during a scan, one-press Leftovers: plan

Spec: `../specs/2026-10-07-feedback-bars-leftovers-design.md`. Ledger: `2026-10-07-feedback-bars-leftovers.status.md`.

| Task | What |
|---|---|
| L0 | branch, spec, plan, ledger |
| L1 | Leftovers ticks every shown leftover, then confirms (test first; help, guide, docs/ace3-profile-manager.md, CHANGELOG) |
| L2 | `#scan-box` fills the tree's space; new STD-7 rule + layout test over every tool (docs/standards.md, CHANGELOG) |
| LR | whole-branch review, green gate, push |
| L4 | shared risk disclaimer for WTF Cleaner, Ace3 and SV Browser, at most once per tool per session |
| L5 | `t` goes back to the tool menu from the flavor and account pickers (Esc kept) |
| LR2 | review of L4-L5, green gate, push, CI |
| L6 | the review shows its scan box before any disk access; the Screenshot Organizer's destination check and Undo lookup move into the scan worker; audit every tool |
| LR3 | review of L6, green gate, push, CI |
| L7 | `q` quits from any screen (app-wide binding; inputs type; refused while busy) |
| L8 | "Don't show this again" on the risk popup (per-tool `skip_risk_warning`) |
| L9 | one toast anchor and stack, action tip included |
| L10 | long warning lists collapse behind a counted tree row in every popup |
| LR4 | review of L7-L10, green gate, push, CI |
