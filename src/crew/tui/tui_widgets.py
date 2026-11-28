"""The app's pieces: a row as markup (links, glyph colours, the pending mark), the status dialog, the lines screen (the
command log, cost) and the runner of a confirmed `crew-task.py` move."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable
from pathlib import Path

from rich.markup import escape
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from crew.tui.tui_github import CI, DRAFT, ISSUES, STATES
from crew.tui.tui_moves import Move
from crew.tui.tui_views import NEEDS_YOU, View

Runner = Callable[[list[str]], tuple[int, str, str]]

PENDING = "⋯ "  # before the STATE of a task whose move is still running

# The theme variable of each glyph `tui_github` and `tui_views` write; NO_COLOR (Textual's own) leaves glyph and word.
COLOURS = {
    **{STATES["MERGED"]: "success", STATES["CLOSED"]: "error", STATES["OPEN"]: "accent", ISSUES["CLOSED"]: "success"},
    **{DRAFT: "foreground-darken-1", CI["SUCCESS"]: "success", CI["FAILURE"]: "error", CI["PENDING"]: "warning", NEEDS_YOU: "warning"},
}

DIALOG = "align: center middle; #box { width: 90%; height: auto; max-height: 80%; border: round $accent; padding: 0 1; }"


def run_command(argv: list[str]) -> tuple[int, str, str]:
    """Run one `crew-task.py` call: its exit code, stdout and stderr."""
    done = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    return done.returncode, done.stdout, done.stderr


def shown(argv: list[str]) -> str:
    """A command as the dialog and the log show it, the home directory as `~`."""
    return shlex.join(argv).replace(str(Path.home()), "~")


def coloured(text: str, palette: dict[str, str]) -> str:
    """Escaped cell text with each state glyph in its theme colour (`palette`: the app's CSS variables)."""
    text = escape(text)
    for token, name in COLOURS.items():
        text = text.replace(token, f"[{palette[name]}]{token}[/]") if palette.get(name) else text
    return text


def cells(view: View, index: int, pending: bool = False, palette: dict[str, str] | None = None) -> list[str]:
    """One row as markup: linked cells as `[link=…]` (the URLs, from `GITHUB_PR_URL` and `ISSUE_URL`, hold no
    bracket), every cell escaped and coloured, `PENDING` before STATE."""
    links = view.links[index] if index < len(view.links) else {}
    palette = palette or {}
    found = [
        f"[link={links[key]}]{coloured(cell, palette)}[/link]" if key in links else coloured(cell, palette)
        for key, cell in zip(view.header, view.rows[index], strict=True)
    ]
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


class Lines(ModalScreen):
    """Lines to read: the command log (`L`) or the cost report (`c`); `esc` or the same key closes it."""

    DEFAULT_CSS = f"Lines {{ {DIALOG} }}"
    AUTO_FOCUS = "#box"
    BINDINGS = [Binding("escape,L,c", "dismiss", "Close")]

    def __init__(self, title: str, lines: list[str], empty: str) -> None:
        super().__init__()
        self.title_text, self.lines, self.empty = title, lines, empty

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="box") as box:
            box.border_title = self.title_text
            yield Static(escape("\n".join(self.lines)) or self.empty)
