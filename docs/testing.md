# Testing

How the test suite runs and what it checks. The testing rules every change follows are in
[standards.md](standards.md#10-testing). Back to [architecture](architecture.md).

## Running the tests

`python3 scripts/run_tests.py` deals the tests round-robin into one process per CPU (at most 16); `python3 -m
unittest discover -s tests -t .` runs them in one process. Textual tests subclass `tests.fixtures.TuiTestCase`,
which turns off asyncio debug mode. `tests/fixtures.py` builds a synthetic install in a temp
folder, and TUI tests use Textual's `App.run_test()` pilot, at `BASE` (120x30) for anything about layout (see
[Look and feel and terminal size](architecture.md#look-and-feel-and-terminal-size)). No test touches a real WoW folder or the network.

CI (`.github/workflows/tests.yml`) runs on every push and pull request: Ubuntu and Windows, Python 3.10 (the floor)
and 3.13. Each job byte-compiles `wowtools`, `scripts` and `tests`, runs `gen_event_docs.py --check`, then
`run_tests.py`.
