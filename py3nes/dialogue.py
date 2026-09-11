"""Interactive text built from explicit sequences and safe background writes."""

from __future__ import annotations

from dataclasses import dataclass
import textwrap

from .assets import encode_text
from .effects import WriteText
from .ir import ActionSpec, If, Set, Variable
from .model import Button, TextBox
from .sequences import (ButtonPressed, Do, Sequence, WaitForButton, _Transaction,
                        _actions, _dispatch, _sequence)


@dataclass(frozen=True, init=False)
class Choice:
    """One dialogue answer and the explicit actions to execute when chosen."""

    label: str
    actions: tuple[ActionSpec, ...]

    def __init__(self, label, *actions):
        if not isinstance(label, str):
            raise TypeError("choice label must be a string")
        if not label or "\n" in label:
            raise ValueError("choice label must be one nonempty line")
        encode_text(label)
        object.__setattr__(self, "label", label.upper())
        object.__setattr__(self, "actions", _actions(actions, "Choice"))


@dataclass(frozen=True, eq=False)
class Dialogue:
    """A paged conversation in a reserved, initially blank screen rectangle.

Pages and clearing are uploaded one row per game tick through the existing
vblank queue. ``active`` includes drawing and clearing. A fresh confirmation
press advances a complete page; UP/DOWN selects a final answer. The selected
answer's actions run once, before clearing and ``on_finish``.

The builder reserves the rectangle with blank tiles. Closing clears it to
blank; it does not restore tiles written there by other gameplay rules. Keep
this region free of HUD updates and level graphics. Palette attributes and
collision are unchanged. Dialogues in a room share a modal lock, so starting a
second while the first is active is ignored.
"""

    sequence: Sequence
    selection: Variable | None
    pages: tuple[str, ...]
    column: int
    row: int
    width: int
    height: int

    @property
    def active(self):
        return self.sequence.active

    def start(self):
        return self.sequence.start()

    def cancel(self):
        return self.sequence.cancel()


@dataclass(frozen=True)
class _Choose:
    selection: Variable
    choices: tuple[Choice, ...]
    column: int
    row: int
    button: Button

    def _sequence_case(self, advance):
        selected = tuple(choice.actions + advance for choice in self.choices)
        count = len(self.choices)

        def move(delta):
            cases = []
            for index in range(count):
                destination = (index + delta) % count
                cases.append((WriteText(" ", self.column, self.row + index),
                              WriteText(">", self.column, self.row + destination),
                              Set(self.selection, destination)))
            return _dispatch(self.selection, cases)

        return (If(ButtonPressed(self.button), *_dispatch(self.selection, selected),
                   otherwise=(If(ButtonPressed(Button.UP), *move(-1),
                                 otherwise=(If(ButtonPressed(Button.DOWN), *move(1)),)),)),)


def _page_lines(text, width, height):
    if not isinstance(text, str):
        raise TypeError("dialogue pages must be strings")
    for paragraph in text.upper().split("\n"):
        encode_text(paragraph)
    wrapper = textwrap.TextWrapper(width=width, break_long_words=True, break_on_hyphens=False)
    lines = [line for paragraph in text.upper().split("\n")
             for line in (wrapper.wrap(paragraph) or [""])]
    if len(lines) > height:
        raise ValueError(f"dialogue page needs {len(lines)} rows but only {height} are available")
    return lines + [""] * (height - len(lines))


def dialogue(game, name, pages, *, column=2, row=22, width=28, height=4,
             button=Button.A, choices=(), on_start=(), on_finish=(), freeze=()):
    """Register paged text, optional final choices, and a reserved display area.

``pages`` is a string or a nonempty sequence of strings. Text wraps within each
page; overflowing pages are errors. Two to four optional ``Choice`` answers
occupy the last rows of the final page. Each label needs two additional columns
for the selection cursor. Use ``freeze=(player,)`` with a freezable actor for
modal physics and movement; other gameplay rules can test ``~dialogue.active``.

``on_start`` runs on acquisition and ``on_finish`` after normal close or cancel.
Neither callback executes in Python at runtime: both contain explicit actions.
"""
    box = TextBox("", column, row, width, height, border=False)
    ButtonPressed(button)
    pages = (pages,) if isinstance(pages, str) else tuple(pages)
    if not pages:
        raise ValueError("dialogue needs at least one page")
    choices = tuple(choices)
    if any(not isinstance(choice, Choice) for choice in choices):
        raise TypeError("dialogue choices must be Choice descriptions")
    if choices and not 2 <= len(choices) <= 4:
        raise ValueError("dialogue supports two to four choices")
    if choices and button in (Button.UP, Button.DOWN):
        raise ValueError("choice confirmation must differ from UP and DOWN")
    if choices and (width < 3 or height <= len(choices)):
        raise ValueError("choices need one text row and one row per answer")
    for choice in choices:
        if len(choice.label) > width - 2:
            raise ValueError("choice label does not fit the dialogue width (including cursor)")
        game._validate(choice.actions)
    grids = [_page_lines(page, width, height - (len(choices) if index == len(pages) - 1 else 0))
             for index, page in enumerate(pages)]
    if choices:
        grids[-1] += [("> " if index == 0 else "  ") + choice.label
                      for index, choice in enumerate(choices)]
    with _Transaction(game):
        selection = game.byte(f"dialogue_{name}_selection") if choices else None
        steps = []
        for index, grid in enumerate(grids):
            steps.extend(Do(WriteText(line, column, row + offset, width=width))
                         for offset, line in enumerate(grid))
            if choices and index == len(grids) - 1:
                steps.append(_Choose(selection, choices, column, row + height - len(choices), button))
            else:
                steps.append(WaitForButton(button))
        cleanup = len(steps)
        steps.extend(Do(WriteText("", column, row + offset, width=width)) for offset in range(height))
        # A separate finish tick keeps on_finish's writes independent of clearing.
        steps.append(Do())
        starts = _actions(on_start, "on_start")
        if selection is not None:
            starts = (Set(selection, 0),) + starts
        result = _sequence(game, name, steps, on_start=starts, on_finish=on_finish,
                           freeze=freeze, cancel_step=cleanup, modal=True)
        game.map([[0] * box.width for _ in range(box.height)], column=column, row=row)
        return Dialogue(result, selection, tuple(page.upper() for page in pages),
                        column, row, width, height)
