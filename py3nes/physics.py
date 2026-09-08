"""Screen-space actors and explicit physics/animation descriptions.

Coordinates are pixels; unlike raw Sprite OAM coordinates, actor Y is the actual
visible top edge. Velocity is a signed integer number of pixels per game tick.
"""

from dataclasses import dataclass, field

from .ir import ActionSpec, Condition, Expr, Variable, as_expr
from .model import integer


@dataclass(frozen=True)
class Hitbox:
    width: int = 8
    height: int = 8
    offset_x: int = 0
    offset_y: int = 0

    def __post_init__(self):
        integer(self.width, "hitbox width", 1, 32)
        integer(self.height, "hitbox height", 1, 32)
        integer(self.offset_x, "hitbox offset_x", 0, 31)
        integer(self.offset_y, "hitbox offset_y", 0, 31)


@dataclass(frozen=True)
class SpritePart:
    tile: int
    dx: int = 0
    dy: int = 0
    palette: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False

    def __post_init__(self):
        integer(self.tile, "sprite part tile", 0, 255)
        integer(self.dx, "sprite part dx", 0, 31)
        integer(self.dy, "sprite part dy", 0, 31)
        integer(self.palette, "sprite part palette", 0, 3)
        for key in ("flip_horizontal", "flip_vertical"):
            if not isinstance(getattr(self, key), bool):
                raise TypeError(f"{key} must be a bool")

    @property
    def attributes(self):
        return self.palette | (int(self.flip_horizontal) << 6) | (int(self.flip_vertical) << 7)


@dataclass(frozen=True)
class Metasprite:
    parts: tuple[SpritePart, ...]

    def __post_init__(self):
        parts = tuple(self.parts)
        if not parts or len(parts) > 16:
            raise ValueError("a metasprite needs between 1 and 16 sprite parts")
        if not all(isinstance(part, SpritePart) for part in parts):
            raise TypeError("metasprite parts must be SpritePart descriptions")
        object.__setattr__(self, "parts", parts)


@dataclass(frozen=True, eq=False)
class Actor:
    index: int
    name: str
    frames: tuple[Metasprite, ...]
    oam_start: int
    initial_x: int
    initial_y: int
    hitbox: Hitbox = field(default_factory=Hitbox)
    gravity: int = 0
    max_fall_speed: int = 4
    frame_ticks: int = 8
    collides: bool = True
    x: Variable = field(init=False)
    y: Variable = field(init=False)
    vx: Variable = field(init=False)
    vy: Variable = field(init=False)
    grounded: Variable = field(init=False)
    visible: Variable = field(init=False)
    animation_enabled: Variable = field(init=False)
    frame: Variable = field(init=False)
    frame_timer: Variable = field(init=False)

    def __post_init__(self):
        integer(self.index, "actor index", 0, 7)
        if not isinstance(self.name, str) or not self.name.isidentifier() or not self.name.isascii():
            raise ValueError("actor name must be an ASCII identifier")
        frames = tuple(self.frames)
        if not frames or len(frames) > 32 or not all(isinstance(f, Metasprite) for f in frames):
            raise ValueError("actor frames must contain between 1 and 32 Metasprites")
        object.__setattr__(self, "frames", frames)
        if not isinstance(self.hitbox, Hitbox):
            raise TypeError("actor hitbox must be a Hitbox")
        integer(self.oam_start, "actor OAM start", 0, 63)
        if self.oam_start + self.oam_slots > 64:
            raise ValueError("actor sprite parts exceed the 64 hardware sprite slots")
        integer(self.initial_x, "actor x", 0, 256 - self.width)
        integer(self.initial_y, "actor y", 1, 240 - self.height)
        integer(self.gravity, "gravity", 0, 4)
        integer(self.max_fall_speed, "max_fall_speed", 1, 8)
        integer(self.frame_ticks, "frame_ticks", 1, 255)
        if not isinstance(self.collides, bool):
            raise TypeError("collides must be a bool")
        for key, value, kind in (
            ("x", self.initial_x, "u8"), ("y", self.initial_y, "u8"),
            ("vx", 0, "i8"), ("vy", 0, "i8"),
            ("grounded", 0, "flag"), ("visible", 1, "flag"),
            ("animation_enabled", 1, "flag"), ("frame", 0, "u8"),
            ("frame_timer", 0, "u8"),
        ):
            object.__setattr__(self, key, Variable(f"actor_{self.index}_{key}", value, kind))

    @property
    def variables(self):
        return (self.x, self.y, self.vx, self.vy, self.grounded, self.visible,
                self.animation_enabled, self.frame, self.frame_timer)

    @property
    def oam_slots(self):
        return max(len(frame.parts) for frame in self.frames)

    @property
    def width(self):
        return max(self.hitbox.offset_x + self.hitbox.width,
                   max(part.dx + 8 for frame in self.frames for part in frame.parts))

    @property
    def height(self):
        return max(self.hitbox.offset_y + self.hitbox.height,
                   max(part.dy + 8 for frame in self.frames for part in frame.parts))


def _actor(value):
    if not isinstance(value, Actor):
        raise TypeError("action target must be an Actor returned by game.actor()")


@dataclass(frozen=True)
class Velocity(ActionSpec):
    actor: Actor
    vx: int | Expr | None = None
    vy: int | Expr | None = None

    def __post_init__(self):
        _actor(self.actor)
        if self.vx is None and self.vy is None:
            raise ValueError("Velocity needs vx and/or vy")
        for key in ("vx", "vy"):
            value = getattr(self, key)
            if value is not None:
                if isinstance(value, int):
                    integer(value, key, -8, 8)
                else:
                    as_expr(value)


@dataclass(frozen=True)
class Teleport(ActionSpec):
    actor: Actor
    x: int
    y: int

    def __post_init__(self):
        _actor(self.actor)
        integer(self.x, "teleport x", 0, 256 - self.actor.width)
        integer(self.y, "teleport y", 1, 240 - self.actor.height)


@dataclass(frozen=True)
class Show(ActionSpec):
    actor: Actor

    def __post_init__(self):
        _actor(self.actor)


@dataclass(frozen=True)
class Hide(ActionSpec):
    actor: Actor

    def __post_init__(self):
        _actor(self.actor)


@dataclass(frozen=True)
class Animate(ActionSpec):
    actor: Actor
    enabled: bool = True

    def __post_init__(self):
        _actor(self.actor)
        if not isinstance(self.enabled, bool):
            raise TypeError("animation enabled must be a bool")


@dataclass(frozen=True, eq=False)
class Overlaps(Condition):
    first: Actor
    second: Actor

    def __post_init__(self):
        _actor(self.first)
        _actor(self.second)
