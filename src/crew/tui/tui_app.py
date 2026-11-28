"""The Textual front end over `tui_model`: three tabs over one table, rows keyed by task and updated in place. Keys:
`1` `2` `3` tabs, `enter`/`→` expand (`←` folds), `PgUp`/`PgDn` scroll, `/` filter, `o` `O` `y` `Y` open and
copy, `s` a status move, `p` detail, `c` cost, `L` log, `r` `R` refresh, `?` Textual's key panel; the footer shows the keys the
selected row takes. Reads, the GitHub read and moves run in thread workers; a move runs only once its dialog confirms."""

from __future__ import annotations

import threading
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path

from rich.markup import escape
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widgets import DataTable, Footer, Header, Input, Static, Tab, Tabs
from textual.worker import get_current_worker

from crew.tui.tui_github import REFRESH, Facts, Run, fetch, load_facts, run_gh, save_facts
from crew.tui.tui_model import Caches, Filters, Watch, collect, freshness, live_tick, parse_filter
from crew.tui.tui_views import TABS, View, expanded
from crew.tui.tui_widgets import Lines, Runner, Status, cells, run_command, shown

LIVE_TICK = 1.5  # seconds between transcript reads for the LIVE cells
PANE_MIN = 100  # columns below which the detail pane stays hidden


class CrewApp(App):
    """Crew dashboard: reads task state and GitHub; a confirmed `s` move runs `crew-task.py`."""

    TITLE = "crew"
    AUTO_FOCUS = "#table"  # the hidden filter box would otherwise take the keys
    CSS = (
        "#filter { display: none; } #filter.open { display: block; } #notes { height: auto; padding: 0 1; }"
        " #body { height: 1fr; } #table { height: 1fr; }"
        " #detail { display: none; width: 40%; padding: 0 1; border-left: solid $primary; } #detail.open { display: block; }"
    )
    BINDINGS = [
        Binding("1", "show('ongoing')", "Ongoing", show=False),
        Binding("2", "show('summary')", "Summary", show=False),
        Binding("3", "show('runs')", "Runs", show=False),
        Binding("right", "fold(True)", "Expand", priority=True),
        Binding("left", "fold(False)", "Fold", priority=True),
        Binding("o", "open('PR')", "Open PR"),
        Binding("O", "open('ISSUE')", "Open issue"),
        Binding("y", "copy('PR')", "Copy PR"),
        Binding("Y", "copy('path')", "Copy path"),
        Binding("s", "move", "Status move"),
        Binding("slash", "filter", "Filter"),
        Binding("escape", "clear_filter", "Clear filter"),
        Binding("p", "pane", "Detail"),
        Binding("c", "cost", "Cost"),
        Binding("L", "command_log", "Log", show=False),
        Binding("r", "reload", "Refresh", show=False),
        Binding("R", "github", "GitHub", show=False),
        Binding("question_mark", "show_help_panel", "Keys"),
        Binding("q", "quit", "Quit", show=False),
    ]

    def __init__(
        self,
        tasks_dir: Path,
        filters: Filters,
        interval: float = 12.0,
        gh: Run = run_gh,
        opener: Callable[[str], object] = webbrowser.open,
        runner: Runner = run_command,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """`gh` replaces the `gh api graphql` call, `opener` the browser behind `o`/`O`, `runner` the `crew-task.py`
        process behind `s`, `clock` the time the views are read at (tests pass stubs)."""
        super().__init__()
        self.tasks_dir, self.filters, self.interval, self.gh = tasks_dir, filters, interval, gh
        self.opener, self.runner, self.clock = opener, runner, clock
        self.command_log: list[str] = []  # every move's command, output and exit code (`L`)
        self.pending: set[str] = set()  # tasks marked `PENDING`: a move running, or the read after it not yet shown
        self.moving: set[str] = set()  # tasks whose move is still running
        self.view_name = self.drawn = "ongoing"
        self.cursors: dict[str, str | None] = {}  # each view's selected key, kept across refreshes and view switches
        self.opened: set[str] = set()  # the expanded tasks
        self.pane = True  # the detail pane, shown when the terminal is at least PANE_MIN wide
        self.facts: Facts = load_facts()
        self.views: dict[str, View] = {}
        self.shown_view: View | None = None  # the view as drawn: children in
        self.watched: Watch | None = None
        self.live_total = "-"
        self.caches = Caches()  # each transcript's offset and sums, kept between reads
        self.reading = threading.Lock()  # the full read and the live tick share `caches`

    def compose(self) -> ComposeResult:
        yield Header()
        yield Tabs(*(Tab(label, id=name) for name, label in TABS.items()), id="tabs")
        yield Input(placeholder="repo:OWNER/NAME status:STATE word   (Enter applies, esc clears)", id="filter")
        with Horizontal(id="body"):
            yield DataTable(id="table", zebra_stripes=True, cursor_type="row")
            yield Static(id="detail")
        yield Static(id="notes")
        yield Footer()

    def on_mount(self) -> None:
        self.action_reload()
        self.set_interval(self.interval, self.action_reload)
        self.set_interval(LIVE_TICK, self.tick)
        self.set_interval(REFRESH, self.action_github)

    @work(thread=True, exclusive=True, group="read")
    def action_reload(self) -> None:
        """The full read, off the UI thread; a newer read cancels an older one's result."""
        settled = self.pending - self.moving  # moves finished before this read began, so it shows their result
        with self.reading:
            views, watch = collect(self.tasks_dir, self.filters, self.facts, now=self.clock(), caches=self.caches)
        if not get_current_worker().is_cancelled:
            self.call_from_thread(self.loaded, views, watch, settled)

    def loaded(self, views: dict[str, View], watch: Watch, settled: set[str] | None = None) -> None:
        first = self.watched is None
        self.views, self.watched = views, watch
        self.pending -= settled or set()
        for name, label in TABS.items():
            self.query_one(f"#{name}", Tab).label = f"{label} ({views[name].count})"
        self.draw()
        if first:
            self.action_github()

    @work(thread=True, exclusive=True, group="github")
    def action_github(self) -> None:
        """One `gh api graphql` read of every PR and issue, cached on disk; offline keeps the last good facts."""
        if self.watched is None:
            return
        facts = fetch(self.watched.urls, self.facts, self.gh, clones=self.watched.clones)
        save_facts(facts)
        if not get_current_worker().is_cancelled:  # the app is closing
            self.call_from_thread(self.github_read, facts)

    def github_read(self, facts: Facts) -> None:
        self.facts = facts
        self.action_reload()

    @work(thread=True, exclusive=True, group="live")
    def tick(self) -> None:
        """The fast tick: only the transcripts, read on from where the last read stopped; skipped during a full read."""
        if self.watched is None or not self.reading.acquire(blocking=False):
            return
        try:
            found, total = live_tick(self.watched, self.caches)
        finally:
            self.reading.release()
        if not get_current_worker().is_cancelled:  # the app is closing
            self.call_from_thread(self.show_live, found, total)

    def show_live(self, found: dict[str, str], total: str) -> None:
        view = self.views.get("ongoing")
        if view:
            at = view.header.index("LIVE")
            view.rows = [(*row[:at], found.get(key, "-"), *row[at + 1 :]) for key, row in zip(view.keys, view.rows, strict=True)]
        self.live_total = total
        self.draw()

    def selected(self) -> tuple[View | None, int]:
        """The view on show (as drawn) and the index of the selected row's key in it (-1 for none)."""
        try:
            table = self.query_one("#table", DataTable)
        except NoMatches:  # before compose
            return None, -1
        view = self.shown_view
        if view is None or not table.row_count:
            return view, -1
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return view, view.keys.index(key) if key in view.keys else -1

    def selected_key(self) -> str:
        view, index = self.selected()
        return view.keys[index] if view and index >= 0 else ""

    def link(self, key: str) -> str:
        """The selected row's `PR` or `ISSUE` URL, or ""."""
        view, index = self.selected()
        return view.links[index].get(key, "") if view and index >= 0 else ""

    def draw(self) -> None:
        """Update the table in place: changed cells, added and removed rows, then the new order; the cursor stays on
        its key. Then the detail pane, the header and the footer's keys."""
        if self.view_name not in self.views:
            return
        view = expanded(self.views[self.view_name], self.opened)
        table = self.query_one("#table", DataTable)
        self.shown_view = view
        if table.row_count:
            self.cursors[self.drawn] = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        self.drawn = self.view_name
        chosen = self.cursors.get(self.view_name)
        if tuple(str(column.label) for column in table.columns.values()) != view.header:
            table.clear(columns=True)
            for column in view.header:
                table.add_column(column, key=column)
        palette = self.get_css_variables()
        rows = {key: cells(view, i, key in self.pending, palette) for i, key in enumerate(view.keys)}
        for gone in [key for key in table.rows if key.value not in rows]:
            table.remove_row(gone)
        for key, values in rows.items():
            if key not in table.rows:
                table.add_row(*values, key=key)
                continue
            for column, before, after in zip(view.header, table.get_row(key), values, strict=True):
                if before != after:
                    table.update_cell(key, column, after, update_width=True)
        if [row.key.value for row in table.ordered_rows] != view.keys:
            order = {tuple(values): i for i, values in enumerate(rows.values())}
            table.sort(key=lambda values: order.get(tuple(values), 0))
        if chosen in rows and table.get_row_index(chosen) != table.cursor_row:
            table.move_cursor(row=table.get_row_index(chosen))
        self.sub_title = f"{freshness(self.facts, self.clock())} | live {self.live_total} | filter: {self.describe()}"
        self.query_one("#notes", Static).update(escape("\n".join(view.notes)))
        self.show_detail()

    def show_detail(self) -> None:
        pane = self.query_one("#detail", Static)
        lines = self.views[self.view_name].details.get(self.selected_key().split("::")[0], []) if self.view_name in self.views else []
        pane.set_class(self.pane and bool(lines) and self.size.width >= PANE_MIN, "open")
        pane.update(escape("\n".join(lines)))
        self.refresh_bindings()

    def on_data_table_row_highlighted(self) -> None:
        self.show_detail()

    def on_data_table_row_selected(self) -> None:
        """`enter` expands the selected task, or folds it (from a child row too)."""
        key = self.selected_key()
        self.action_fold(key not in self.opened and "::" not in key)

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tab.id and event.tab.id != self.view_name:
            self.action_show(event.tab.id)

    def on_resize(self) -> None:
        self.call_after_refresh(self.draw)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """The footer's context: each key shows only where the selected row or the tab takes it. The arrows are the
        table's own anywhere else (the filter box, a dialog)."""
        if action == "fold" and not isinstance(self.focused, DataTable):
            return False
        view, index = self.selected()
        key = view.keys[index] if view and index >= 0 else ""
        has_children = bool(self.views.get(self.view_name) and self.views[self.view_name].children.get(key))
        if action == "fold":
            return (has_children and key not in self.opened) if parameters[0] else (key in self.opened or "::" in key)
        if action in ("open", "copy") and parameters[0] != "path":
            return bool(self.link(str(parameters[0])))
        if action == "copy":
            return key.startswith("/")
        if action == "move":
            return self.view_name == "ongoing" and bool(view and index >= 0 and view.moves[index])
        if action == "clear_filter":
            return bool(self.filters.states or self.filters.text)
        if action == "pane":
            return self.size.width >= PANE_MIN and self.view_name != "runs"
        return True

    def describe(self) -> str:
        words = [f"repo:{self.filters.repo}"] if self.filters.repo else []
        words += [f"status:{state.lower()}" for state in self.filters.states]
        return " ".join(words + list(self.filters.text)) or "none"

    def action_show(self, name: str) -> None:
        self.view_name = name
        self.query_one(Tabs).active = name
        self.draw()

    def action_fold(self, opening: bool) -> None:
        """Expand the selected task (`→`, `enter`), or fold it or its child's parent (`←`, `enter`)."""
        key = self.selected_key().split("::")[0]
        if opening and self.views[self.view_name].children.get(key):
            self.opened.add(key)
        elif not opening and key in self.opened:
            table = self.query_one("#table", DataTable)
            table.move_cursor(row=table.get_row_index(key))
            self.opened.discard(key)
        self.draw()

    def action_open(self, key: str) -> None:
        """Open the selected row's PR (a child's own, else the task's newest) or the task's issue in the browser."""
        if url := self.link(key):
            self.opener(url)

    def action_copy(self, key: str) -> None:
        """Copy the selected row's PR URL (`y`) or the task's directory (`Y`)."""
        if text := self.link(key) if key == "PR" else self.selected_key().split("::")[0]:
            self.copy_to_clipboard(text)
            self.notify(f"copied {text}")

    def action_pane(self) -> None:
        self.pane = not self.pane
        self.show_detail()

    def action_cost(self) -> None:
        self.push_screen(Lines("cost", [row[0] for row in self.views["cost"].rows] if "cost" in self.views else [], "not read yet"))

    def action_move(self) -> None:
        """The status dialog for the selected task; the command it confirms runs in a worker, the row marked pending."""
        view, index = self.selected()
        if view is None or index < 0 or not view.moves[index]:
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
        why = next((line for line in lines if line.startswith("error:")), lines[-1] if lines else "")  # the refusal, not a trailing note
        self.notify(" ".join([f"{title}: exit {code}", *([why] if code else [])]), severity="information" if code == 0 else "error")
        self.action_reload()

    def action_command_log(self) -> None:
        self.push_screen(Lines("command log", self.command_log, "no command has run yet"))

    def action_filter(self) -> None:
        box = self.query_one("#filter", Input)
        box.add_class("open")
        box.focus()

    def action_clear_filter(self) -> None:
        self.filters = parse_filter("", self.filters)
        box = self.query_one("#filter", Input)
        box.value = ""
        box.remove_class("open")
        self.query_one("#table", DataTable).focus()
        self.action_reload()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        try:
            self.filters = parse_filter(event.value, self.filters)
        except ValueError as error:
            self.notify(str(error), severity="error")
            return
        event.input.remove_class("open")
        self.query_one("#table", DataTable).focus()
        self.action_reload()
