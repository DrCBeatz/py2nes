"""Immutable descriptions, consumed by the compiler rather than run as gameplay."""

from dataclasses import dataclass
from enum import Enum, IntFlag
from typing import Union


def integer(value: int, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}, got {value}")
    return value


class Button(IntFlag):
    RIGHT = 0x01
    LEFT = 0x02
    DOWN = 0x04
    UP = 0x08
    START = 0x10
    SELECT = 0x20
    B = 0x40
    A = 0x80


class Trigger(str, Enum):
    HELD = "held"
    PRESSED = "pressed"
    FRAME = "frame"


@dataclass(frozen=True, eq=False)
class Sprite:
    """One hardware 8×8 sprite. Coordinates are raw OAM bytes (visible Y is y+1)."""

    index: int
    tile: int
    x: int
    y: int
    palette: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    behind_background: bool = False

    def __post_init__(self) -> None:
        integer(self.index, "sprite index", 0, 63)
        integer(self.tile, "tile", 0, 255)
        integer(self.x, "x", 0, 255)
        integer(self.y, "y", 0, 255)
        integer(self.palette, "sprite palette", 0, 3)
        for name in ("flip_horizontal", "flip_vertical", "behind_background"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")

    @property
    def attributes(self) -> int:
        return (self.palette | (int(self.behind_background) << 5)
                | (int(self.flip_horizontal) << 6) | (int(self.flip_vertical) << 7))


@dataclass(frozen=True)
class Map:
    """A rectangular patch of background tile indices, placed in a 32×30 screen."""

    tiles: tuple[tuple[int, ...], ...]
    column: int = 0
    row: int = 0

    def __post_init__(self) -> None:
        rows = tuple(tuple(row) for row in self.tiles)
        if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
            raise ValueError("map must be a nonempty rectangular grid")
        integer(self.column, "column", 0, 31)
        integer(self.row, "row", 0, 29)
        if self.column + len(rows[0]) > 32 or self.row + len(rows) > 30:
            raise ValueError("map must fit inside the 32×30 tile screen")
        for row in rows:
            for tile in row:
                integer(tile, "map tile", 0, 255)
        object.__setattr__(self, "tiles", rows)

    @property
    def width(self) -> int:
        return len(self.tiles[0])

    @property
    def height(self) -> int:
        return len(self.tiles)


@dataclass(frozen=True)
class TextBox:
    """Static text rectangle. Width and height include the optional border."""

    text: str
    column: int
    row: int
    width: int
    height: int
    border: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")
        if not isinstance(self.border, bool):
            raise TypeError("border must be a bool")
        integer(self.column, "column", 0, 31)
        integer(self.row, "row", 0, 29)
        integer(self.width, "width", 3 if self.border else 1, 32)
        integer(self.height, "height", 3 if self.border else 1, 30)
        if self.column + self.width > 32 or self.row + self.height > 30:
            raise ValueError("text box must fit inside the 32×30 tile screen")


@dataclass(frozen=True)
class Move:
    """Add signed deltas to a sprite's OAM coordinates, wrapping modulo 256."""

    sprite: Sprite
    dx: int = 0
    dy: int = 0

    def __post_init__(self) -> None:
        _sprite(self.sprite)
        integer(self.dx, "dx", -255, 255)
        integer(self.dy, "dy", -255, 255)


@dataclass(frozen=True)
class SetPosition:
    sprite: Sprite
    x: int
    y: int

    def __post_init__(self) -> None:
        _sprite(self.sprite)
        integer(self.x, "x", 0, 255)
        integer(self.y, "y", 0, 255)


@dataclass(frozen=True)
class SetTile:
    sprite: Sprite
    tile: int

    def __post_init__(self) -> None:
        _sprite(self.sprite)
        integer(self.tile, "tile", 0, 255)


Action = Union[Move, SetPosition, SetTile]


def _sprite(value: Sprite) -> None:
    if not isinstance(value, Sprite):
        raise TypeError("action target must be a Sprite returned by game.sprite()")


@dataclass(frozen=True)
class Event:
    trigger: Trigger
    actions: tuple[Action, ...]
    button: Button | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.trigger, Trigger):
            raise TypeError("trigger must be a Trigger")
        actions = tuple(self.actions)
        if not actions:
            raise ValueError("an event needs at least one action")
        for action in actions:
            if not isinstance(action, (Move, SetPosition, SetTile)):
                raise TypeError("gameplay uses Move, SetPosition, or SetTile descriptions; Python callbacks run only at build time")
        if self.trigger is Trigger.FRAME:
            if self.button is not None:
                raise ValueError("a frame event cannot have a button")
        elif not isinstance(self.button, Button) or int(self.button) not in {int(b) for b in Button}:
            raise ValueError("bind one Button per event; register separate events for multiple buttons")
        object.__setattr__(self, "actions", actions)
