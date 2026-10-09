# Faster tests: plan

Spec: `../specs/2026-10-09-faster-tests-design.md`. Ledger: `2026-10-09-faster-tests.status.md`.

| Task | What |
|---|---|
| F0 | spec, plan, ledger |
| F1 | `run_tests.py --windows` and `--all` (tests first; the cmd.exe call is injectable so tests never start Windows) |
| F2 | shards balanced by recorded test time |
| F3 | measure shard counts, pick the default |
| F4/F5 | two-job CI matrix; the gate, standards and docs say when CI is checked |
| FR | review, the new gate (`--all`), push; CI checked once; ask the user to merge |
