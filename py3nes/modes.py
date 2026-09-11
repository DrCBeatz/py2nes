"""Explicit game modes and build-time event scopes.

Modes control the game's scheduler. Existing events run in gameplay modes;
menu events opt into a named mode or the ``"always"`` scope.
"""

from contextlib import contextmanager
from dataclasses import dataclass

from .ir import ActionSpec, Condition, walk_actions
from .model import Event, Trigger


class GameMode:
    """A named scheduler mode created by ``game.mode``.

    Non-gameplay modes preserve physics, animations and ordinary events. Input
    is still sampled, display queues drain, and explicitly scoped menu events
    continue. ``pause_music`` freezes music; independent sound effects continue.
    """

    def __init__(self, game, name, index, *, gameplay=False, pause_music=False):
        from .rooms import _name
        _name(name, "mode name")
        if not isinstance(gameplay, bool) or not isinstance(pause_music, bool):
            raise TypeError("gameplay and pause_music must be bools")
        self._game, self._name, self._index = game, name, index
        self._gameplay, self._pause_music = gameplay, pause_music
        self._enter_events = []

    name = property(lambda self: self._name)
    index = property(lambda self: self._index)
    gameplay = property(lambda self: self._gameplay)
    pause_music = property(lambda self: self._pause_music)
    enter_events = property(lambda self: tuple(self._enter_events))

    @property
    def active(self):
        return ModeActive(self)

    def change(self, *, restart=False):
        """Finish this tick and enter this mode; same-mode changes are ignored."""
        return ChangeMode(self, restart=restart)

    def on_enter(self, *actions):
        """Run once at startup/entry. Room changes are allowed; mode changes are not.

        Entry actions use global state. Set room actors in ``room.on_enter``.
        """
        event = Event(Trigger.FRAME, actions, scope="always")
        if any(isinstance(action, ChangeMode) for action in walk_actions(actions)):
            raise ValueError("mode on_enter cannot contain ChangeMode")
        self._game._validate(event)
        self._enter_events.append(event)
        return event


@dataclass(frozen=True, eq=False)
class ModeActive(Condition):
    mode: GameMode

    def __post_init__(self):
        if not isinstance(self.mode, GameMode):
            raise TypeError("ModeActive needs a GameMode from game.mode()")


@dataclass(frozen=True)
class ChangeMode(ActionSpec):
    """End this tick and enter a mode, preserving room and sequence state.

    Earlier RAM changes survive; unpublished display writes are discarded.
    The next mode's rules begin on the next tick. ``restart=True`` re-enters
    even when the requested mode is already active.
    """

    mode: GameMode
    restart: bool = False

    def __post_init__(self):
        if not isinstance(self.mode, GameMode):
            raise TypeError("ChangeMode needs a GameMode from game.mode()")
        if not isinstance(self.restart, bool):
            raise TypeError("mode restart must be a bool")


def validate_scope(scope):
    if scope is not None and scope not in ("always", "gameplay") and not isinstance(scope, GameMode):
        raise ValueError("event scope must be a GameMode, 'always', or 'gameplay'")


@contextmanager
def during(game, scope):
    """Assign a scope to events created inside this build-time context."""
    validate_scope(scope)
    if isinstance(scope, GameMode):
        game._validate(scope)
    previous = game._event_scope
    game._event_scope = "gameplay" if scope is None else scope
    try:
        yield game
    finally:
        game._event_scope = previous
