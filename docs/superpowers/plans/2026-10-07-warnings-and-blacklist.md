# Warnings view and the blacklist key: plan

Spec: `../specs/2026-10-07-warnings-and-blacklist-design.md` (W1-W2, B1-B4). Ledger:
`2026-10-07-warnings-and-blacklist.status.md`. Branch `feat/warnings-blacklist`. Tests first, full suite green,
one commit per task, ledger updated; push at the end; no merge without the user's go-ahead.

- **K1** Shared `WarningsScreen` + clickable warning line + key (W1); adopt in all five tools (W2); help and tests.
- **K2** Blacklist pair helpers to core and the shared `b` tree action (B1); Ace3 on them, assertions unchanged.
- **K3** WTF Cleaner blacklist (B2, B4).
- **K4** Docs (guides, README, CHANGELOG, architecture, events), review, push.
