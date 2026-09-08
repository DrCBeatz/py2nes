"""Descriptions for background updates and the NES's first pulse channel."""

from dataclasses import dataclass

from .assets import encode_text
from .ir import ActionSpec, Expr, as_expr
from .model import integer


def _position(column: int, row: int, width: int = 1) -> None:
    integer(column, "column", 0, 31)
    integer(row, "row", 0, 29)
    if column + width > 32:
        raise ValueError("display update must fit on one 32-tile screen row")


@dataclass(frozen=True)
class WriteText(ActionSpec):
    """Queue one uppercase line; width pads it with spaces to erase old text."""

    text: str
    column: int
    row: int
    width: int | None = None

    def __post_init__(self) -> None:
        encoded = encode_text(self.text)
        width = len(encoded) if self.width is None else integer(self.width, "width", 0, 32)
        if len(encoded) > width:
            raise ValueError("text is longer than its display width")
        _position(self.column, self.row, width)
        object.__setattr__(self, "width", width)

    @property
    def tiles(self) -> tuple[int, ...]:
        encoded = encode_text(self.text)
        return encoded + (0,) * (self.width - len(encoded))


@dataclass(frozen=True)
class WriteNumber(ActionSpec):
    """Queue a zero-padded byte value; 1 or 2 digits keep the low decimal digits.

    The expression is interpreted as an unsigned byte (0..255), including when
    its underlying variable is signed. Three digits can display every value.
    """

    value: Expr | int
    column: int
    row: int
    digits: int = 3

    def __post_init__(self) -> None:
        integer(self.digits, "digits", 1, 3)
        _position(self.column, self.row, self.digits)
        object.__setattr__(self, "value", as_expr(self.value))


@dataclass(frozen=True)
class SetBackgroundTile(ActionSpec):
    """Queue a background tile change; collision data is independent."""

    tile: int
    column: int
    row: int

    def __post_init__(self) -> None:
        integer(self.tile, "tile", 0, 255)
        _position(self.column, self.row)


@dataclass(frozen=True)
class Tone:
    """A constant-volume pulse tone, lasting ``frames`` NTSC video frames.

    Duty values 0, 1, 2, 3 select 12.5%, 25%, 50%, 25% inverted. Frequency is
    quantized to the closest hardware timer. Playing another tone replaces it.
    """

    frequency: int = 440
    frames: int = 8
    volume: int = 10
    duty: int = 2

    def __post_init__(self) -> None:
        integer(self.frequency, "frequency", 1, 20000)
        integer(self.frames, "frames", 1, 255)
        integer(self.volume, "volume", 0, 15)
        integer(self.duty, "duty", 0, 3)
        if not 8 <= self.timer <= 0x7FF:
            raise ValueError("frequency is outside the audible NTSC pulse timer range")

    @property
    def timer(self) -> int:
        # NTSC master clock / 12, then pulse timer / 16 / (timer + 1).
        return round((21_477_272 / 12) / (16 * self.frequency)) - 1

    @property
    def control(self) -> int:
        return self.duty << 6 | 0x30 | self.volume


@dataclass(frozen=True)
class PlaySound(ActionSpec):
    """Start a tone at the next committed video frame, replacing pulse 1."""

    tone: Tone

    def __post_init__(self) -> None:
        if not isinstance(self.tone, Tone):
            raise TypeError("PlaySound requires a Tone description")


@dataclass(frozen=True)
class StopSound(ActionSpec):
    """Stop the current pulse tone at the next committed video frame."""


def write_count(action: object) -> int:
    """Worst-case tile writes for one leaf action (branches are handled by IR)."""
    if isinstance(action, WriteText):
        return action.width
    if isinstance(action, WriteNumber):
        return action.digits
    if isinstance(action, SetBackgroundTile):
        return 1
    return 0
