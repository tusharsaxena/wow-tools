# CLAUDE.md: Ka0s WoW Tools

Out-of-game World of Warcraft companion tools (Ka0s branded): one Python 3.10+ Textual TUI suite, run with
`./wow-tools.sh` (Windows: `wow-tools.cmd`; `./wow-tools.sh update [--check]` updates it). The tool menu opens first;
tools never start on their own and have no CLI mode. They share one in-repo library, `wowtools/core/` (UI-free)
and `wowtools/ui/` (Textual); third-party code lives in `vendor/`. The five tools (`TOOLS` in
`wowtools/tools/__init__.py`):

- WTF Cleaner (`wtf-cleaner`, package `tools/wtf_cleaner`)
- Screenshot Organizer (`screenshot-organizer`, package `tools/screenshot_organizer`)
- Interface Backup (`interface-backup`, package `tools/interface_backup`)
- Ace3 Profile Manager (`ace3-profile-manager`, package `tools/ace3_profile_manager`)
- Saved Variables Browser (`sv-browser`, package `tools/sv_browser`)

## Read first

1. **[docs/standards.md](docs/standards.md)**: the MUST / SHOULD rules every tool follows (`STD-N.M`), each with its
   reason and the test that enforces it. All work here conforms to it. **If a change would break a MUST, stop and
   flag it to the user**; never deviate or "fix" silently. An accepted deviation becomes a row in its
   [Documented deviations](docs/standards.md#documented-deviations) table; one not listed there is not accepted.
2. **[docs/architecture.md](docs/architecture.md)**: the hub. Layers, every core and UI module, the config schema,
   the look and feel, and the Documentation map.
3. For a change, the matching recipe in [docs/common-tasks.md](docs/common-tasks.md); for tests,
   [docs/testing.md](docs/testing.md); for one tool's data flow, its `docs/internals/<tool>.md`.

## The green gate

Before every commit, all three pass ([testing.md](docs/testing.md#the-green-gate)):

```sh
python3 scripts/run_tests.py --all        # WSL + native Windows suites at once, about 3 min; -k TEXT, -j N
ruff check --no-cache .                   # not run in CI
python3 scripts/gen_event_docs.py --check # docs/events.md matches the event registries
```

Without a Windows Python (or off WSL), the first line is the plain `python3 scripts/run_tests.py` (WSL only, about
90 s) and CI covers Windows before the merge. `--windows` runs only the Windows suite.

## Hard rules

- Never commit, push, merge, tag or release unless the user asks. An approved plan covers its own per-task commits
  and milestone pushes; merging into master and releasing are two separate approvals; never file a GitHub issue to
  track a release (STD-12.2, STD-12.3).
- Never edit `vendor/` by hand; rebuild it with `scripts/update_vendor.py` ([vendoring.md](docs/vendoring.md),
  STD-11.3).
- Tests never touch a real WoW install or the network: `tests/fixtures.py` temp trees, `make_config`,
  `TuiTestCase` for Textual tests (STD-10.3 to STD-10.5).
- `docs/superpowers/` specs and plans (once merged) and `reviews/` bundles are frozen records: read them for decision IDs (D17,
  W1, B1 ...), never edit them (STD-12.4).
- Never write a user's file except through the shared safety nets: atomic write, `rename_no_replace`,
  snapshot/originals zip, crash marker and journal before the first destructive write; a dry run changes nothing
  ([standards.md section 5](docs/standards.md#5-data-safety), STD-5.10 to STD-5.18, STD-5.27).
- `wowtools/core/` never imports `textual`; a tool never imports another tool; what two tools need lives once in
  `core/` or `ui/` (STD-1.6, STD-2.1, STD-2.2).
- Log only registered events and regenerate `docs/events.md` after a registry change (STD-6.1, STD-6.4). Every
  user-noticeable change gets a `CHANGELOG.md` line (STD-11.1).
- Moving text in a doc keeps the strings `tests/test_docs.py` pins, or updates that test in the same commit
  (STD-9.6).

## Documentation index

| Group | Document | Read it for |
|---|---|---|
| Developer | [docs/standards.md](docs/standards.md) | The MUST / SHOULD rules and the documented deviations |
| Developer | [docs/architecture.md](docs/architecture.md) | The hub: layers, core and UI modules, config schema, look and feel, documentation map |
| Developer | [docs/internals/](docs/internals/) | One per tool: [wtf-cleaner](docs/internals/wtf-cleaner.md), [screenshot-organizer](docs/internals/screenshot-organizer.md), [interface-backup](docs/internals/interface-backup.md), [ace3-profile-manager](docs/internals/ace3-profile-manager.md), [sv-browser](docs/internals/sv-browser.md) |
| Developer | [docs/testing.md](docs/testing.md) | The runner, CI, fixtures, Textual tests, the meta-tests |
| Developer | [docs/common-tasks.md](docs/common-tasks.md) | Recipes: a tool, a setting, a `[general]` setting, an event, a button, a tree screen, a shared helper, a WTF Cleaner criterion, a button colour, a rename, vendoring, a release |
| Developer | [docs/adding-a-tool.md](docs/adding-a-tool.md) | Adding a tool step by step, and renaming one |
| Developer | [docs/releasing.md](docs/releasing.md) | Version, `CHANGELOG.md` entry, tag, `scripts/build_release.py` assets |
| Developer | [docs/vendoring.md](docs/vendoring.md) | `vendor/`, `requirements.lock` and `scripts/update_vendor.py` |
| Developer | [docs/events.md](docs/events.md) | Every log event and its level (generated, never edited by hand) |
| User | [README.md](README.md) | Install, run, update, settings, terms of use |
| User | [docs/wtf-cleaner.md](docs/wtf-cleaner.md), [docs/screenshot-organizer.md](docs/screenshot-organizer.md), [docs/interface-backup.md](docs/interface-backup.md), [docs/ace3-profile-manager.md](docs/ace3-profile-manager.md), [docs/sv-browser.md](docs/sv-browser.md) | The user guide of each tool (also its in-app help link) |
| User | [CHANGELOG.md](CHANGELOG.md) | Release notes, shown in-app on `c` |
| Process | [docs/superpowers/specs/](docs/superpowers/specs/), [docs/superpowers/plans/](docs/superpowers/plans/) | Dated design specs (decision IDs), plans and their `.status.md` ledgers. Frozen |
| Process | [reviews/](reviews/) | Dated review bundles. Frozen |
| Process | [docs/ideas/](docs/ideas/) | Dated, scored ideas for new tools (not plans) |
