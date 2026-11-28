"""The Textual front end over `tui_model`: one table per view, refreshed on an interval and on `r`.

Keys: `t` tasks, `w` workers, `p` report, `r` refresh, `g` read `landed` from GitHub, `a` DONE rows on or off,
`/` a filter (`repo:R status:S done`), `o` and `O` open the selected task's issue and PR, `s` a status move,
`q` quit. A move runs `crew-task.py` only after its confirm dialog, which shows the exact command; the app
never writes a file itself and never calls a model.
"""

from __future__ import annotations

import shlex
import subprocess
import webbrowser
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, OptionList, Static

from crew.tui.tui_model import LINKED, Filters, Move, Seen, View, collect, landed_for, parse_filter

Runner = Callable[[list[str]], tuple[int, str, str]]
DIALOG = "align: center middle; #box { width: 90%; height: auto; max-height: 80%; border: round $accent; padding: 0 1; }"


def run_command(argv: list[str]) -> tuple[int, str, str]:
    """Run one `crew-task.py` call: its exit code, stdout and stderr."""
    done = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    return done.returncode, done.stdout, done.stderr


def cells(view: View, index: int) -> list[str]:
    """One row as Textual markup: the linked cells as `[link=…]`, every cell's text escaped.

    The URLs come only from `GITHUB_PR_URL` and `ISSUE_URL`, whose owner/repo class holds no bracket,
    so a URL cannot end the tag early.
    """
    links = view.links[index] if index < len(view.links) else {}
    return [f"[link={links[key]}]{escape(cell)}[/link]" if key in links else escape(cell) for key, cell in zip(view.header, view.rows[index])]


class Pick(ModalScreen):
    """The moves `crew-task.py` offers from the selected task's state; Enter picks one, Escape closes."""

    DEFAULT_CSS = f"Pick {{ {DIALOG} }}"
    AUTO_FOCUS = "#box"  # the app's own (`#table`) is not on this screen
    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def __init__(self, slug: str, moves: list[Move]) -> None:
        super().__init__()
        self.slug, self.moves = slug, moves

    def compose(self) -> ComposeResult:
        box = OptionList(*(move.label for move in self.moves), id="box")
        box.border_title = f"status move: {escape(self.slug)}"
        yield box

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.moves[event.option_index])


class Ask(ModalScreen):
    """The free text a move takes (a BLOCKED reason, a `--force` note), prefilled with its default."""

    DEFAULT_CSS = f"Ask {{ {DIALOG} }}"
    AUTO_FOCUS = "#box"  # the app's own (`#table`) is not on this screen
    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def __init__(self, move: Move) -> None:
        super().__init__()
        self.move = move

    def compose(self) -> ComposeResult:
        yield Input(self.move.default, placeholder=self.move.ask, id="box")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip():
            self.dismiss(event.value.strip())
        else:
            self.notify(f"a {self.move.ask} is needed; Escape cancels", severity="warning")


class Confirm(ModalScreen):
    """The exact command a move runs; `y` runs it (the user's approval for a gate), `n` or Escape cancels."""

    DEFAULT_CSS = f"Confirm {{ {DIALOG} }}"
    AUTO_FOCUS = "#box"  # the app's own (`#table`) is not on this screen
    BINDINGS = [Binding("y", "dismiss(True)", "Run"), Binding("n,escape", "dismiss(False)", "Cancel")]

    def __init__(self, argv: list[str]) -> None:
        super().__init__()
        self.argv = argv

    def compose(self) -> ComposeResult:
        command = escape(shlex.join(self.argv))
        yield Static(f"Run this command?\n\n{command}\n\ny runs it, n or Escape cancels", id="box")


class CrewApp(App):
    """Crew dashboard: reads task state; a confirmed `s` move runs `crew-task.py`."""

    TITLE = "crew"
    AUTO_FOCUS = "#table"  # the hidden filter box would otherwise take the keys
    CSS = "#filter { display: none; } #filter.open { display: block; } #notes { height: auto; padding: 0 1; }"
    BINDINGS = [
        Binding("t", "show('tasks')", "Tasks"),
        Binding("w", "show('workers')", "Workers"),
        Binding("p", "show('report')", "Report"),
        Binding("r", "reload", "Refresh"),
        Binding("g", "landed", "GitHub landed"),
        Binding("a", "toggle_done", "DONE on/off"),
        Binding("slash", "filter", "Filter"),
        Binding("o", "open('ISSUE')", "Open issue"),
        Binding("O", "open('PR')", "Open PR"),
        Binding("s", "move", "Status move"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        tasks_dir: Path,
        filters: Filters,
        interval: float = 5.0,
        reader: Callable | None = None,
        opener: Callable[[str], object] = webbrowser.open,
        runner: Runner = run_command,
    ) -> None:
        """`reader` replaces the `gh` read behind `g`, `opener` the browser behind `o`/`O`, `runner` the
        `crew-task.py` process behind `s` (tests pass stubs)."""
        super().__init__()
        self.tasks_dir, self.filters, self.interval, self.reader = tasks_dir, filters, interval, reader
        self.opener, self.runner = opener, runner
        self.ran: list[str] = []  # the last move's command, exit code and output, shown under the notes
        self.view_name = "tasks"
        self.landed: dict[str, str] | None = None
        self.views: dict[str, View] = {}
        self.live_cache: dict[str, Seen] = {}  # each running agent's transcript offset and sums, kept between refreshes

    def compose(self) -> ComposeResult:
        yield Header()
        hint = "repo:OWNER/NAME status:STATE done   (Enter applies; repo and done stay unless set)"
        yield Input(placeholder=hint, id="filter")
        yield DataTable(id="table", zebra_stripes=True)
        yield Static(id="notes")
        yield Footer()

    def on_mount(self) -> None:
        self.action_reload()
        self.set_interval(self.interval, self.action_reload)

    def action_reload(self) -> None:
        self.views = collect(self.tasks_dir, self.filters, self.landed, live_cache=self.live_cache)
        self.draw()

    def draw(self) -> None:
        view = self.views[self.view_name]
        table = self.query_one("#table", DataTable)
        table.clear(columns=True)
        table.add_columns(*view.header)
        table.add_rows([cells(view, index) for index in range(len(view.rows))])
        self.sub_title = f"{view.title} | filter: {self.describe()}"
        self.query_one("#notes", Static).update(escape("\n".join(view.notes + self.ran)))

    def describe(self) -> str:
        words = [f"repo:{self.filters.repo}"] if self.filters.repo else []
        words += [f"status:{state.lower()}" for state in self.filters.states]
        return " ".join(words + (["done"] if self.filters.done else [])) or "none"

    def action_show(self, name: str) -> None:
        self.view_name = name
        self.draw()

    def action_open(self, key: str) -> None:
        """Open the selected task's issue (`ISSUE`) or newest PR (`PR`) in the browser; a note when it has none."""
        view = self.views.get(self.view_name)
        row = self.query_one("#table", DataTable).cursor_row
        if key not in LINKED or view is None or not 0 <= row < len(view.links):
            return
        url = view.links[row].get(key)
        if url:
            self.opener(url)
        else:
            self.notify(f"this task has no {key.lower()}")

    def action_move(self) -> None:
        """Pick a move for the selected task, give its text, confirm the command, then run it and reload."""
        view = self.views.get(self.view_name)
        row = self.query_one("#table", DataTable).cursor_row
        if view is None or not 0 <= row < len(view.moves):
            return
        if not view.moves[row]:
            self.notify("crew-task.py offers no move from this state")
            return

        def picked(move: Move | None) -> None:
            if move is not None and move.ask:
                self.push_screen(Ask(move), lambda text: text is not None and confirm(move.argv(text)))
            elif move is not None:
                confirm(move.argv())

        def confirm(argv: list[str]) -> None:
            self.push_screen(Confirm(argv), lambda yes: yes and self.run_move(argv))

        self.push_screen(Pick(view.rows[row][1], view.moves[row]), picked)

    def run_move(self, argv: list[str]) -> None:
        """Run the confirmed command, show what it printed and its exit code (a refusal says why), reload."""
        code, out, err = self.runner(argv)
        self.ran = ["", f"$ {shlex.join(argv)}", *out.strip().splitlines(), *err.strip().splitlines(), f"exit {code}"]
        self.notify(f"crew-task.py exit {code}", severity="information" if code == 0 else "error")
        self.action_reload()

    def action_landed(self) -> None:
        """Read GitHub in a thread worker, so the app stays live; a second press waits for the first."""
        self.notify("reading each DONE task's PR on GitHub")
        self.run_worker(self.read_landed, thread=True, group="landed", exclusive=True)

    def read_landed(self) -> None:
        found = landed_for(self.tasks_dir, self.filters, self.reader)
        self.call_from_thread(self.landed_read, found)

    def landed_read(self, found: dict[str, str]) -> None:
        self.landed = found
        self.action_reload()

    def action_toggle_done(self) -> None:
        self.filters = replace(self.filters, done=not self.filters.done)
        self.action_reload()

    def action_filter(self) -> None:
        box = self.query_one("#filter", Input)
        box.add_class("open")
        box.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        try:
            self.filters = parse_filter(event.value, self.filters)
        except ValueError as error:
            self.notify(str(error), severity="error")
            return
        event.input.remove_class("open")
        self.query_one("#table", DataTable).focus()
        self.action_reload()
