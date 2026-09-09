"""Named screens, entrances, and explicit room transitions.

Room builders run in Python. ChangeRoom is a cartridge-runtime action; it loads
the destination screen and resets its temporary state before applying on_enter.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from .game import Game
from .ir import ActionSpec, Variable, walk_actions
from .model import Event, Trigger, integer
from .physics import Actor


def _name(value, description):
    if not isinstance(value, str) or not value.isascii() or not value.isidentifier():
        raise ValueError(f"{description} must be a nonempty ASCII identifier")


@dataclass(frozen=True)
class Spawn:
    """One actor's screen-space placement at a named room entrance."""

    actor: Actor
    x: int
    y: int

    def __post_init__(self):
        if not isinstance(self.actor, Actor):
            raise TypeError("spawn actor must be an Actor returned by room.actor()")
        integer(self.x, "spawn x", 0, 256 - self.actor.width)
        integer(self.y, "spawn y", 1, 240 - self.actor.height)


@dataclass(frozen=True)
class ChangeRoom(ActionSpec):
    """End this game tick and enter a room, optionally at a named spawn.

The destination's temporary variables and actors reset, then the spawn is
applied and its on_enter rules execute. Global and persistent room state survive.
"""

    room: Room
    spawn: str | None = None

    def __post_init__(self):
        if not isinstance(self.room, Room):
            raise TypeError("ChangeRoom destination must be a Room returned by game.room()")
        if self.spawn is not None:
            _name(self.spawn, "spawn name")


class Room(Game):
    """A screen with independent visuals, collision, actors, rules, and entrances.

Use game.room() to create rooms. Most Game construction methods work here too.
Room variables reset on every entry unless declared persistent=True. Persistent
room variables may be referenced from other rooms, for example to reset a game.
Actor state always resets. Graphics and the cartridge palette belong to Game.
"""

    def __init__(self, parent: Game, name: str, index: int):
        if not isinstance(parent, Game) or isinstance(parent, Room):
            raise TypeError("rooms must belong directly to a Game")
        _name(name, "room name")
        integer(index, "room index", 0, 15)
        super().__init__(region=parent.region, mapper=parent.mapper, palette=parent.palette)
        self._parent = parent
        self._name = name
        self._index = index
        self._tiles = parent._tiles
        self._enter_events = []
        self._spawns = {}
        self._persistent_variables = []
        self._user_names = set()

    @property
    def parent(self):
        return self._parent

    @property
    def name(self):
        return self._name

    @property
    def index(self):
        return self._index

    @property
    def _root(self):
        return self.parent

    @property
    def enter_events(self):
        return tuple(self._enter_events)

    @property
    def spawns(self):
        return MappingProxyType(self._spawns)

    @property
    def persistent_variables(self):
        return tuple(self._persistent_variables)

    @property
    def reset_variables(self):
        persistent = {id(variable) for variable in self._persistent_variables}
        return tuple(variable for variable in self.variables if id(variable) not in persistent)

    def _actor_index(self):
        return self.index * 8 + len(self._actors)

    def _variable(self, name, initial, kind, *, persistent=False):
        # Validate the public name before constructing its private assembly name.
        Variable(name, initial, kind)
        if name.startswith(("actor_", "rt_", "room_")):
            raise ValueError("variable prefixes actor_, room_, and rt_ are reserved by the runtime")
        if not isinstance(persistent, bool):
            raise TypeError("persistent must be a bool")
        if name in self._user_names:
            raise ValueError(f"duplicate variable name in room {self.name!r}: {name}")
        public = sum(not variable.name.startswith("actor_")
                     for scope in (self.parent,) + self.parent.rooms for variable in scope.variables)
        if public >= 64:
            raise ValueError("maximum 64 user variables per game")
        variable = Variable(f"room_{self.index}_{name}", initial, kind)
        self._variables.append(variable)
        self._user_names.add(name)
        if persistent:
            self._persistent_variables.append(variable)
        return variable

    def byte(self, name: str, initial: int = 0, *, persistent: bool = False) -> Variable:
        """Allocate a byte that resets on entry, unless persistent=True."""
        return self._variable(name, initial, "u8", persistent=persistent)

    variable = byte

    def signed_byte(self, name: str, initial: int = 0, *, persistent: bool = False) -> Variable:
        """Allocate a signed byte that resets on entry, unless persistent=True."""
        return self._variable(name, initial, "i8", persistent=persistent)

    def flag(self, name: str, initial: bool = False, *, persistent: bool = False) -> Variable:
        """Allocate a flag; persistent=True remembers changes across room visits."""
        return self._variable(name, initial, "flag", persistent=persistent)

    def spawn(self, name: str, actor: Actor, *, x: int, y: int) -> Spawn:
        """Name an entrance placement for an actor owned by this room."""
        _name(name, "spawn name")
        if name in self._spawns:
            raise ValueError(f"duplicate spawn name in room {self.name!r}: {name}")
        if len(self._spawns) >= 255:
            raise ValueError("maximum 255 named spawns per room")
        result = Spawn(actor, x, y)
        self._validate(actor)
        self._spawns[name] = result
        return result

    def on_enter(self, *actions: ActionSpec) -> Event:
        """Run once after room state resets and its chosen spawn is applied."""
        event = Event(Trigger.FRAME, actions)
        if any(isinstance(action, ChangeRoom) for action in walk_actions(event.actions)):
            raise ValueError("on_enter cannot contain ChangeRoom; transitions belong in gameplay rules")
        self._validate(event)
        self._enter_events.append(event)
        return event

    def room(self, name: str):
        raise ValueError("rooms cannot contain rooms; call game.room()")

    def start(self, room, *, spawn: str | None = None):
        raise ValueError("choose the starting room with game.start()")

    def to_assembly(self) -> str:
        raise ValueError("compile the containing game with game.to_assembly() or game.build()")
