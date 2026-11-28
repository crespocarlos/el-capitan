"""The Textual front end over `tui_model`: one table per view, its rows keyed by task and updated in place.

Keys: `t` `w` `p` views, `r` refresh, `g` GitHub `landed`, `a` DONE rows, `/` filter, `o` `O` the issue and PR,
`s` a status move, `L` the command log, `q` quit. Reads (full every `interval`, LIVE every `LIVE_TICK`) and moves
run in thread workers; a move runs `crew-task.py` only once its dialog confirms the command. The app never writes
a file itself and never calls a model.
"""

from __future__ import annotations

import shlex
import subprocess
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from rich.markup import escape
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import get_current_worker

from crew.tui.tui_model import LINKED, Caches, Filters, Move, View, Watch, collect, landed_for, live_tick, parse_filter

Runner = Callable[[list[str]], tuple[int, str, str]]
LIVE_TICK = 1.5  # seconds between transcript reads for the LIVE cells
PENDING = "⋯ "  # before the STATE of a task whose move is still running
DIALOG = "align: center middle; #box { width: 90%; height: auto; max-height: 80%; border: round $accent; padding: 0 1; }"


def run_command(argv: list[str]) -> tuple[int, str, str]:
    """Run one `crew-task.py` call: its exit code, stdout and stderr."""
    done = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    return done.returncode, done.stdout, done.stderr


def shown(argv: list[str]) -> str:
    """A command as the dialog and the log show it, the home directory as `~`."""
    return shlex.join(argv).replace(str(Path.home()), "~")


def cells(view: View, index: int, pending: bool = False) -> list[str]:
    """One row as Textual markup: the linked cells as `[link=…]`, every cell's text escaped, `PENDING` before STATE.

    The URLs come only from `GITHUB_PR_URL` and `ISSUE_URL`, whose owner/repo class holds no bracket,
    so a URL cannot end the tag early.
    """
    links = view.links[index] if index < len(view.links) else {}
    found = [f"[link={links[key]}]{escape(cell)}[/link]" if key in links else escape(cell) for key, cell in zip(view.header, view.rows[index])]
    return [PENDING + found[0], *found[1:]] if pending else found


class Status(ModalScreen):
    """The selected task's moves, one per line (`DRAFTING → APPROVED [a] Approve`; an unavailable one says why). A
    letter or the arrows pick one, its text is typed inline, the command it runs shows muted below with how to confirm;
    `enter` returns `(title, argv)`, `esc` cancels."""

    DEFAULT_CSS = f"Status {{ {DIALOG} }} #text {{ display: none; }} #text.open {{ display: block; }} #command {{ color: $text-muted; }}"
    AUTO_FOCUS = "#moves"  # the app's own (`#table`) is not on this screen
    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def __init__(self, slug: str, moves: list[Move]) -> None:
        super().__init__()
        self.slug, self.moves = slug, moves
        self.move: Move | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="box") as box:
            box.border_title = f"status move: {escape(self.slug)}"
            yield OptionList(*(Option(Text(move.title()), disabled=bool(move.why)) for move in self.moves), id="moves")
            yield Input(id="text")
            yield Static(id="command")

    def on_mount(self) -> None:
        self.query_one(OptionList).highlighted = next((i for i, move in enumerate(self.moves) if not move.why), None)

    def preview(self) -> None:
        box = self.query_one(Input)
        hint = "enter runs with this text · esc cancels" if self.focused is box else "enter runs this · esc cancels"
        self.query_one("#command", Static).update(escape(f"{shown(self.move.argv(box.value.strip()))}\n{hint}") if self.move else "")

    def on_descendant_focus(self) -> None:
        self.preview()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self.move = self.moves[event.option_index]
        box = self.query_one(Input)
        box.set_class(bool(self.move.ask), "open")
        box.placeholder, box.value = self.move.ask, self.move.default
        self.preview()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        move = self.moves[event.option_index]
        if move.ask:
            self.query_one(Input).focus()
        else:
            self.dismiss((move.title(), move.argv()))

    def on_key(self, event: events.Key) -> None:
        """While the list has focus, a move's letter picks it (one that takes text moves the focus to its box), and no
        other printable key reaches the app behind the dialog."""
        if not (event.is_printable and isinstance(self.focused, OptionList)):
            return
        event.stop()
        index = next((i for i, move in enumerate(self.moves) if move.key == event.character and not move.why), None)
        if index is None:
            return
        self.query_one(OptionList).highlighted = index
        if self.moves[index].ask:
            self.query_one(Input).focus()

    def on_input_changed(self) -> None:
        self.preview()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()  # not the app's filter box
        if self.move and event.value.strip():
            self.dismiss((self.move.title(), self.move.argv(event.value.strip())))
        elif self.move:
            self.notify(f"a {self.move.ask} is needed; esc cancels", severity="warning")


class Log(ModalScreen):
    """Every command a move ran this session, with its output and exit code; `esc` or `L` closes it."""

    DEFAULT_CSS = f"Log {{ {DIALOG} }}"
    AUTO_FOCUS = "#box"
    BINDINGS = [Binding("escape,L", "dismiss", "Close")]

    def __init__(self, lines: list[str]) -> None:
        super().__init__()
        self.lines = lines

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="box") as box:
            box.border_title = "command log"
            yield Static(escape("\n".join(self.lines)) or "no command has run yet")


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
        Binding("L", "command_log", "Command log"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        tasks_dir: Path,
        filters: Filters,
        interval: float = 12.0,
        reader: Callable | None = None,
        opener: Callable[[str], object] = webbrowser.open,
        runner: Runner = run_command,
    ) -> None:
        """`reader` replaces the `gh` read behind `g`, `opener` the browser behind `o`/`O`, `runner` the
        `crew-task.py` process behind `s` (tests pass stubs)."""
        super().__init__()
        self.tasks_dir, self.filters, self.interval, self.reader = tasks_dir, filters, interval, reader
        self.opener, self.runner = opener, runner
        self.command_log: list[str] = []  # every move's command, output and exit code (`L`)
        self.pending: set[str] = set()  # tasks marked `PENDING`: a move running, or the read after it not yet shown
        self.moving: set[str] = set()  # tasks whose move is still running
        self.view_name = self.drawn = "tasks"
        self.cursors: dict[str, str | None] = {}  # each view's selected key, kept across refreshes and view switches
        self.landed: dict[str, str] | None = None
        self.views: dict[str, View] = {}
        self.watched: Watch | None = None
        self.live_total = "-"
        self.caches = Caches()  # each transcript's offset and sums, kept between reads
        self.reading = threading.Lock()  # the full read and the live tick share `caches`

    def compose(self) -> ComposeResult:
        yield Header()
        hint = "repo:OWNER/NAME status:STATE done   (Enter applies; repo and done stay unless set)"
        yield Input(placeholder=hint, id="filter")
        yield DataTable(id="table", zebra_stripes=True, cursor_type="row")
        yield Static(id="notes")
        yield Footer()

    def on_mount(self) -> None:
        self.action_reload()
        self.set_interval(self.interval, self.action_reload)
        self.set_interval(LIVE_TICK, self.tick)

    @work(thread=True, exclusive=True, group="read")
    def action_reload(self) -> None:
        """The full read, off the UI thread; a newer read cancels an older one's result."""
        settled = self.pending - self.moving  # moves finished before this read began, so it shows their result
        with self.reading:
            views, watch = collect(self.tasks_dir, self.filters, self.landed, caches=self.caches)
        if not get_current_worker().is_cancelled:
            self.call_from_thread(self.loaded, views, watch, settled)

    def loaded(self, views: dict[str, View], watch: Watch, settled: set[str] | None = None) -> None:
        self.views, self.watched = views, watch
        self.pending -= settled or set()
        self.draw()

    @work(thread=True, exclusive=True, group="live")
    def tick(self) -> None:
        """The fast tick: only the transcripts, read on from where the last read stopped; skipped during a full read."""
        if self.watched is None or not self.reading.acquire(blocking=False):
            return
        try:
            found, total = live_tick(self.watched, self.caches)
        finally:
            self.reading.release()
        self.call_from_thread(self.show_live, found, total)

    def show_live(self, found: dict[str, str], total: str) -> None:
        view = self.views.get("tasks")
        if view:
            at = view.header.index("LIVE")
            view.rows = [(*row[:at], found.get(key, "-"), *row[at + 1 :]) for key, row in zip(view.keys, view.rows)]
        self.live_total = total
        self.draw()

    def selected(self) -> tuple[View | None, int]:
        """The view on show and the index of the selected row's key in it (-1 for none)."""
        view, table = self.views.get(self.view_name), self.query_one("#table", DataTable)
        if view is None or not table.row_count:
            return view, -1
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return view, view.keys.index(key) if key in view.keys else -1

    def draw(self) -> None:
        """Update the table in place: changed cells, added and removed rows, then the new order; the cursor stays on
        its key."""
        view = self.views.get(self.view_name)
        if view is None:
            return
        table = self.query_one("#table", DataTable)
        if table.row_count:
            self.cursors[self.drawn] = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        self.drawn = self.view_name
        chosen = self.cursors.get(self.view_name)
        if tuple(str(column.label) for column in table.columns.values()) != view.header:
            table.clear(columns=True)
            for column in view.header:
                table.add_column(column, key=column)
        rows = {key: cells(view, i, key in self.pending) for i, key in enumerate(view.keys)}
        for gone in [key for key in table.rows if key.value not in rows]:
            table.remove_row(gone)
        for key, values in rows.items():
            if key not in table.rows:
                table.add_row(*values, key=key)
                continue
            for column, before, after in zip(view.header, table.get_row(key), values):
                if before != after:
                    table.update_cell(key, column, after, update_width=True)
        if [row.key.value for row in table.ordered_rows] != view.keys:
            order = {tuple(values): i for i, values in enumerate(rows.values())}
            table.sort(key=lambda values: order.get(tuple(values), 0))
        if chosen in rows and table.get_row_index(chosen) != table.cursor_row:
            table.move_cursor(row=table.get_row_index(chosen))
        self.sub_title = f"{view.title} | live {self.live_total} | filter: {self.describe()}"
        self.query_one("#notes", Static).update(escape("\n".join(view.notes)))

    def describe(self) -> str:
        words = [f"repo:{self.filters.repo}"] if self.filters.repo else []
        words += [f"status:{state.lower()}" for state in self.filters.states]
        return " ".join(words + (["done"] if self.filters.done else [])) or "none"

    def action_show(self, name: str) -> None:
        self.view_name = name
        self.draw()

    def action_open(self, key: str) -> None:
        """Open the selected task's issue (`ISSUE`) or newest PR (`PR`) in the browser; a note when it has none."""
        view, index = self.selected()
        if key not in LINKED or view is None or not 0 <= index < len(view.links):
            return
        url = view.links[index].get(key)
        if url:
            self.opener(url)
        else:
            self.notify(f"this task has no {key.lower()}")

    def action_move(self) -> None:
        """The status dialog for the selected task; the command it confirms runs in a worker, the row marked pending."""
        view, index = self.selected()
        if view is None or not 0 <= index < len(view.moves):
            return
        if not view.moves[index]:
            self.notify(f"crew-task.py offers no move from {view.rows[index][0]}")
            return
        key = view.keys[index]
        if key in self.pending:
            self.notify("a move for this task is still running; L shows the log")
            return

        def confirmed(chosen: tuple[str, list[str]] | None) -> None:
            if chosen:
                self.pending.add(key)
                self.moving.add(key)
                self.notify(f"running: {chosen[0]}; L shows the command log")
                self.draw()
                self.run_move(key, *chosen)

        self.push_screen(Status(view.rows[index][1], view.moves[index]), confirmed)

    @work(thread=True, group="move")
    def run_move(self, key: str, title: str, argv: list[str]) -> None:
        code, out, err = self.runner(argv)
        self.call_from_thread(self.moved, key, title, argv, code, out + err)

    def moved(self, key: str, title: str, argv: list[str], code: int, output: str) -> None:
        """Log what the move printed and its exit code (a refusal says why), notify, reload; the marker goes with it."""
        self.moving.discard(key)
        lines = output.strip().splitlines()
        self.command_log += [f"$ {shown(argv)}", *lines, f"exit {code}", ""]
        self.notify(" ".join([f"{title}: exit {code}", *(lines[-1:] if code else [])]), severity="information" if code == 0 else "error")
        self.action_reload()

    def action_command_log(self) -> None:
        self.push_screen(Log(self.command_log))

    @work(thread=True, exclusive=True, group="landed")
    def action_landed(self) -> None:
        """Read GitHub in a thread worker, so the app stays live; a second press replaces the first."""
        self.call_from_thread(self.notify, "reading each DONE task's PR on GitHub")
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
