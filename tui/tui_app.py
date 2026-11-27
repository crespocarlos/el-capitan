"""The Textual front end over `tui_model`: one table per view, refreshed on an interval and on `r`.

Keys: `t` tasks, `w` workers, `p` report, `r` refresh, `g` read `landed` from GitHub, `a` DONE rows
on or off, `/` a filter (`repo:R status:S done`), `o` and `O` open the selected task's issue and PR in
the browser, `q` quit. ISSUE and PR cells are terminal links. It shows what the model read; it never writes.
"""
from __future__ import annotations

import webbrowser
from dataclasses import replace
from pathlib import Path
from typing import Callable

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, Input, Static

from tui_model import LINKED, Filters, View, collect, landed_for, parse_filter


def cells(view: View, index: int) -> list[str]:
    """One row as Textual markup: the linked cells as `[link=…]`, every cell's text escaped.

    The URLs come only from `GITHUB_PR_URL` and `ISSUE_URL`, whose owner/repo class holds no bracket,
    so a URL cannot end the tag early.
    """
    links = view.links[index] if index < len(view.links) else {}
    return [f"[link={links[key]}]{escape(cell)}[/link]" if key in links else escape(cell)
            for key, cell in zip(view.header, view.rows[index])]


class CrewApp(App):
    """Read-only crew dashboard."""

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
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, tasks_dir: Path, filters: Filters, interval: float = 5.0,
                 reader: Callable | None = None, opener: Callable[[str], object] = webbrowser.open) -> None:
        """`reader` replaces the `gh` read behind `g`, `opener` the browser behind `o`/`O` (tests pass stubs)."""
        super().__init__()
        self.tasks_dir, self.filters, self.interval, self.reader = tasks_dir, filters, interval, reader
        self.opener = opener
        self.view_name = "tasks"
        self.landed: dict[str, str] | None = None
        self.views: dict[str, View] = {}

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
        self.views = collect(self.tasks_dir, self.filters, self.landed)
        self.draw()

    def draw(self) -> None:
        view = self.views[self.view_name]
        table = self.query_one("#table", DataTable)
        table.clear(columns=True)
        table.add_columns(*view.header)
        table.add_rows([cells(view, index) for index in range(len(view.rows))])
        self.sub_title = f"{view.title} | filter: {self.describe()}"
        self.query_one("#notes", Static).update("\n".join(view.notes))

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
