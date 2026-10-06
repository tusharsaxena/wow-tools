"""The help screen (spec D18): `h` on the tool menu explains the suite, `h` on any screen of a tool explains that
tool. One scrollable Markdown pane under a title, in the suite's look; Esc, q or h goes back to the screen it was
opened from, as it was. The suite's text is SUITE_HELP below; each tool keeps its own in its package (`help.py`,
a HELP constant), read through `Tool.help()`."""
from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Header, Markdown, Static

from wowtools.core.config import (DEFAULT_KEEP_BACKUPS, DEFAULT_KEEP_JOURNALS, DEFAULT_PARALLELISM, MAX_PARALLELISM,
                                   MIN_PARALLELISM)
from wowtools.tools import TOOLS
from wowtools.ui.branding import TERMS, BottomBar
from wowtools.ui.widgets import NavHint

README_URL = "https://github.com/tusharsaxena/wow-tools#readme"
HELP_HINT = "↑↓ PgUp PgDn scroll · Esc/q/h back"


def suite_help() -> str:
    """The tool menu's help: every tool in TOOLS in a line, then what all of them share."""
    tools = "\n".join(f"- **{tool.title}**: {tool.description}" for tool in TOOLS.values())
    return f"""\
Ka0s WoW Tools tidies up the files World of Warcraft leaves on your computer. It runs outside the game: pick a
tool here (`↑` `↓`, then `Enter`); leaving a tool brings you back to this menu.

## The tools

{tools}

## How every tool works

1. **Pick a game version** (a *flavor*: Retail, Classic, ...) or **All flavors**, and an account when there are
   several.
2. **Review** what the tool found: a tree on the right, filters and buttons on the left. Untick what to leave alone.
3. **Dry run** shows what would happen and changes nothing (where the tool has one).
4. Press the tool's main button, read the summary and confirm. Files are **backed up first**.
5. The **results** screen lists every file and what happened to it. Changed your mind? **Undo** the last run.

## Keys

| Key | Does |
|---|---|
| `↑` `↓` `Tab` | Move |
| `Enter` | Choose, or press the focused button |
| `←` `→` | Switch between a screen's two panes, or move along a row of buttons |
| `Space` | Tick or untick the highlighted line |
| `a` / `n` | Tick / untick everything the tree shows |
| `/` | Filter a tree (`Enter` keeps the filter, `Esc` clears it) |
| `x` / `c` | Expand / collapse every line of a tree |
| `Esc` | Go back |
| `s` | Settings |
| `c` | The changelog (on this menu) |
| `u` | Install an update, when the bottom bar offers one |
| `h` | This help, or a tool's help on any of its screens |
| `q` | Quit |

A button shows its own key under its name (**Clean** over `(w)`); the bottom row lists the keys no button has.

## Settings

`s` opens the shared settings first, then the open tool's own. Shared by every tool: your **WoW folder**, the
**backups to keep** per game version ({DEFAULT_KEEP_BACKUPS} by default; `0` keeps them all), the **journals** (undo
records) each tool keeps ({DEFAULT_KEEP_JOURNALS} by default) and how many **game versions to work on at once**
({DEFAULT_PARALLELISM} by default, from {MIN_PARALLELISM} to {MAX_PARALLELISM}; the Saved Variables Browser's search
also reads that many files at once; use 1 on a hard drive or a WSL `/mnt` folder).
Everything is saved in the `config` folder.

## Button colours

Buttons are coloured by what they do, the same in every tool: **red** deletes, **amber** overwrites or changes
files, **green** only adds (a backup), **violet** undoes, **cyan** is a dry run, **blue** confirms, **grey** moves
between screens or rescans, **dim grey** backs out. An "are you sure?" window opens with **Yes** selected, in the
colour of what it does.

## Words

- **Flavor**: a game version (`_retail_`, `_classic_era_`, ...). **All flavors** works on every one at once.
- **Dry run**: every check, nothing changed.
- **Journal**: the record of a run that **Undo** uses. **Backup**: a zip taken before anything changes.

## Terms of use

{TERMS.removeprefix("Terms of use: ")}

**Learn more:** [{README_URL}]({README_URL})
"""


class HelpScreen(Screen[None]):
    """`title` over one scrollable Markdown pane holding `text`. Esc, q or h dismisses it."""

    DEFAULT_CSS = """
    HelpScreen #help-title { color: $accent; text-style: bold; padding: 0 2; margin-top: 1; }
    HelpScreen #help-body { height: 1fr; margin: 1 2 0 2; border: tall $primary; }
    HelpScreen #help-body:focus { background-tint: $foreground 4%; }
    HelpScreen #help-body Markdown { margin: 0; padding: 0 1; }
    HelpScreen NavHint { padding: 0 2; margin: 0; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape,q,h", "close", "Back")]

    def __init__(self, title: str, text: str) -> None:
        super().__init__()
        self.title_text = title
        self.text = text

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self.title_text, id="help-title")
        with VerticalScroll(id="help-body"):
            yield Markdown(self.text, id="help-text")
        yield NavHint(HELP_HINT)
        yield BottomBar()

    def on_mount(self) -> None:
        self.sub_title = "Help"
        self.query_one("#help-body", VerticalScroll).focus()

    def action_close(self) -> None:
        self.dismiss(None)
