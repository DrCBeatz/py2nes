"""Build explicit, tick-driven sequences from ordinary runtime actions.

Python constructs the sequence once. Its program counter and countdown live in
cartridge RAM; no Python function or coroutine executes in the NES runtime.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ir import ActionSpec, Add, Condition, If, Set, Variable, as_condition
from .model import Button, Event, Trigger, integer


@dataclass(frozen=True, eq=False)
class ButtonPressed(Condition):
    """True only on a controller button's released-to-held transition."""

    button: Button

    def __post_init__(self):
        if not isinstance(self.button, Button) or self.button not in tuple(Button):
            raise ValueError("ButtonPressed needs one Button")


def _actions(values, description):
    result = tuple(values)
    if any(not isinstance(action, ActionSpec) for action in result):
        raise TypeError(f"{description} requires explicit actions, not Python callbacks")
    return result


@dataclass(frozen=True, init=False)
class Do:
    """Execute these actions together, then advance on the next game tick."""

    actions: tuple[ActionSpec, ...]

    def __init__(self, *actions):
        object.__setattr__(self, "actions", _actions(actions, "Do"))


@dataclass(frozen=True)
class Wait:
    """Consume exactly 1..255 gameplay ticks before the following step.

The existing display queue can pause gameplay while it uploads tiles, so these
are game ticks, not a promise of elapsed wall-clock time or video frames.
"""

    ticks: int

    def __post_init__(self):
        integer(self.ticks, "wait ticks", 1, 255)


@dataclass(frozen=True)
class WaitUntil:
    """Wait until a runtime condition is true; then advance next tick."""

    condition: Condition

    def __post_init__(self):
        object.__setattr__(self, "condition", as_condition(self.condition))


@dataclass(frozen=True)
class WaitForButton:
    """Wait for a fresh press; holding the button never advances repeatedly."""

    button: Button = Button.A

    def __post_init__(self):
        ButtonPressed(self.button)


@dataclass(frozen=True, eq=False)
class Sequence:
    """A registered sequence, with explicit start/cancel action constructors.

``active`` remains true throughout the sequence. Starting an active sequence is
ignored. Optional frozen actors remain visible and keep their velocities while
their physics/animation pause. Modal sequences in the same room are serialized;
starting while another owns the modal lock, or an actor was already frozen, is
ignored. Actors passed to ``freeze`` need ``freezable=True``.

Room-local sequences reset on entry. Cancellation runs ``on_finish`` once; a
``ChangeRoom`` action immediately abandons the source sequence with the room.
"""

    name: str
    active: Variable
    step: Variable
    countdown: Variable
    _start_actions: tuple[ActionSpec, ...]
    _finish_actions: tuple[ActionSpec, ...]
    _can_start: Condition
    _cancel_step: int | None = None

    def start(self):
        """Construct an action that starts an idle, available sequence."""
        return If(self._can_start, *self._start_actions)

    def cancel(self):
        """Construct an action that finishes an active sequence once.

Dialogue sequences first clear their reserved display area. They stay active
and keep their modal lock until clearing finishes.
"""
        if self._cancel_step is not None:
            return If(self.active & self.step.lt(self._cancel_step),
                      Set(self.step, self._cancel_step), Set(self.countdown, 0))
        return If(self.active, *self._finish_actions)


def _dispatch(variable, cases, offset=0):
    """A balanced, mutually exclusive tree: exactly one case runs per tick.

This also exposes branch exclusivity to the existing VRAM budget analysis;
display writes from different sequence steps are never added together.
"""
    if len(cases) == 1:
        return cases[0]
    midpoint = len(cases) // 2
    return (If(variable.lt(offset + midpoint),
               *_dispatch(variable, cases[:midpoint], offset),
               otherwise=_dispatch(variable, cases[midpoint:], offset + midpoint)),)


class _Transaction:
    """Small builder rollback used by sequences and their dialogue adapter."""

    def __init__(self, game):
        self.game = game
        self.lists = {name: list(getattr(game, name))
                      for name in ("_variables", "_events", "_layers")}
        self.user_names = set(game._user_names) if hasattr(game, "_user_names") else None
        self.modal = {name: getattr(game, name, None) for name in
                      ("_sequence_modal_busy", "_sequence_modal_handlers", "_sequence_modal_event")}

    def __enter__(self):
        return self

    def __exit__(self, exception, *_):
        if exception is not None:
            for name, values in self.lists.items():
                getattr(self.game, name)[:] = values
            if self.user_names is not None:
                self.game._user_names = self.user_names
            for name, value in self.modal.items():
                if value is None:
                    self.game.__dict__.pop(name, None)
                else:
                    setattr(self.game, name, value)


def _register_handler(game, active, body, modal):
    if not modal:
        return game.add_event(Event(Trigger.FRAME, (If(active, *body),)))
    # Modal ownership makes the handlers mutually exclusive. Keeping that fact
    # visible as one If tree avoids summing the upload budgets of conversations
    # that cannot run together. The first modal helper fixes its event position.
    handlers = getattr(game, "_sequence_modal_handlers", ()) + ((active, body),)
    dispatch = ()
    for owner, commands in reversed(handlers):
        dispatch = (If(owner, *commands, otherwise=dispatch),)
    event = Event(Trigger.FRAME, dispatch)
    game._validate(event)
    previous = getattr(game, "_sequence_modal_event", None)
    if previous is None:
        game.add_event(event)
    else:
        index = next(index for index, candidate in enumerate(game._events) if candidate is previous)
        game._events[index] = event
    game._sequence_modal_handlers = handlers
    game._sequence_modal_event = event
    return event


def sequence(game, name, *steps, on_start=(), on_finish=(), freeze=()):
    """Register a sequence and return its runtime state/action constructors.

Steps are ``Do(*actions)``, ``Wait(ticks)``, ``WaitUntil(condition)``, or
``WaitForButton(button)``. A bare action is shorthand for ``Do(action)``.
Every step, including a satisfied wait, consumes one game tick. Call ``start``
from an event (or a room's ``on_enter``); constructing it does not start it.
"""
    return _sequence(game, name, steps, on_start=on_start, on_finish=on_finish, freeze=freeze)


def _sequence(game, name, steps, *, on_start=(), on_finish=(), freeze=(),
              cancel_step=None, modal=False):
    # Validate before allocating: failed helpers must not leave partial rules.
    Variable(name)
    on_start, on_finish = _actions(on_start, "on_start"), _actions(on_finish, "on_finish")
    steps = tuple(Do(step) if isinstance(step, ActionSpec) else step for step in steps)
    if not 1 <= len(steps) <= 255:
        raise ValueError("a sequence needs 1..255 steps")
    actors = tuple(freeze)
    if len({id(actor) for actor in actors}) != len(actors):
        raise ValueError("freeze actors must not contain duplicates")
    from .physics import Actor
    for actor in actors:
        if not isinstance(actor, Actor):
            raise TypeError("freeze requires Actor descriptions")
        game._validate(actor)
        if not getattr(actor, "freezable", False):
            raise ValueError("modal actors need actor(..., freezable=True)")
    for step in steps:
        if not isinstance(step, (Do, Wait, WaitUntil, WaitForButton)) and not hasattr(step, "_sequence_case"):
            raise TypeError("sequence steps must be Do, Wait, WaitUntil, or WaitForButton descriptions")
        if isinstance(step, Do):
            game._validate(step.actions)
        elif isinstance(step, WaitUntil):
            game._validate(step.condition)
    game._validate(on_start + on_finish)
    with _Transaction(game):
        active = game.flag(f"sequence_{name}_active")
        pc = game.byte(f"sequence_{name}_step")
        countdown = game.byte(f"sequence_{name}_countdown")
        can_start = ~active
        acquire, release = (), ()
        if actors or modal:
            from .physics import Freeze
            busy = getattr(game, "_sequence_modal_busy", None)
            if busy is None:
                busy = game.flag("sequence_modal_busy")
                game._sequence_modal_busy = busy
            can_start = can_start & ~busy
            for actor in actors:
                can_start = can_start & ~actor.frozen
            acquire = (Set(busy, True),) + tuple(Freeze(actor) for actor in actors)
            release = tuple(Freeze(actor, False) for actor in actors) + (Set(busy, False),)
        finish = (Set(active, False), Set(pc, 0), Set(countdown, 0)) + release + on_finish
        start = (Set(active, True), Set(pc, 0), Set(countdown, 0)) + acquire + on_start
        result = Sequence(name, active, pc, countdown, start, finish, can_start, cancel_step)
        cases = []
        for index, step in enumerate(steps):
            advance = ((Set(pc, index + 1), Set(countdown, 0))
                       if index + 1 < len(steps) else finish)
            if isinstance(step, Do):
                case = step.actions + advance
            elif isinstance(step, Wait):
                if step.ticks == 1:
                    case = advance
                else:
                    case = (If(countdown.eq(0), Set(countdown, step.ticks - 1),
                               otherwise=(If(countdown.eq(1), *advance,
                                             otherwise=(Add(countdown, -1),)),)),)
            elif isinstance(step, (WaitUntil, WaitForButton)):
                condition = (step.condition if isinstance(step, WaitUntil)
                             else ButtonPressed(step.button))
                case = (If(condition, *advance),)
            else:
                case = step._sequence_case(advance)
            cases.append(case)
        game._validate(start + finish)
        _register_handler(game, active, _dispatch(pc, cases), bool(actors) or modal)
        return result
