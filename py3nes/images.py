"""Import pixel artwork without quantization or guessing its NES color indexes.

Pillow is loaded only when a PNG is opened; the rest of py3nes has no image
dependency. Image colors select pixel values 0–3, not NES hardware colors.
The latter still come from the game's background and sprite palettes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from os import PathLike
import re

from .assets import Tile
from .model import integer


Color = str | Sequence[int]


@dataclass(frozen=True)
class TileSheet:
    """A rectangular grid of immutable 8×8 tiles; dimensions are in tiles."""

    tiles: tuple[tuple[Tile, ...], ...]

    def __post_init__(self) -> None:
        rows = tuple(tuple(row) for row in self.tiles)
        if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
            raise ValueError("tile sheet must be a nonempty rectangular grid")
        if any(not isinstance(tile, Tile) for row in rows for tile in row):
            raise TypeError("tile sheet cells must be Tile descriptions")
        object.__setattr__(self, "tiles", rows)

    @property
    def width(self) -> int:
        return len(self.tiles[0])

    @property
    def height(self) -> int:
        return len(self.tiles)

    def tile(self, column: int, row: int) -> Tile:
        """Select a tile by its zero-based column and row."""
        integer(column, "tile column", 0, self.width - 1)
        integer(row, "tile row", 0, self.height - 1)
        return self.tiles[row][column]

    def region(self, column: int, row: int, width: int, height: int) -> tuple[tuple[Tile, ...], ...]:
        """Select a tile grid for a map or a larger character's animation frame."""
        integer(column, "region column", 0, self.width - 1)
        integer(row, "region row", 0, self.height - 1)
        integer(width, "region width", 1, self.width)
        integer(height, "region height", 1, self.height)
        if column + width > self.width or row + height > self.height:
            raise ValueError("region must fit inside the tile sheet")
        return tuple(tiles[column:column + width] for tiles in self.tiles[row:row + height])


def _color(value: Color) -> tuple[int, int, int, int]:
    if isinstance(value, str):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value):
            raise ValueError("PNG colors must use #RRGGBB or #RRGGBBAA hex notation")
        channels = tuple(int(value[index:index + 2], 16) for index in range(1, len(value), 2))
    else:
        try:
            channels = tuple(value)
        except TypeError as exc:
            raise TypeError("PNG colors must be RGB/RGBA sequences or hex strings") from exc
        if len(channels) not in (3, 4):
            raise ValueError("PNG colors must contain three RGB or four RGBA channels")
        for channel in channels:
            integer(channel, "PNG color channel", 0, 255)
    if len(channels) == 3:
        channels += (255,)
    if channels[3] not in (0, 255):
        raise ValueError("NES tiles do not support partial transparency")
    return channels


def _color_lookup(colors: Sequence[Color]) -> dict[tuple[int, int, int, int], int]:
    if isinstance(colors, (str, bytes)):
        raise TypeError("colors must be a sequence of one to four RGB/RGBA colors")
    normalized = tuple(_color(color) for color in colors)
    if not 1 <= len(normalized) <= 4:
        raise ValueError("colors must contain one to four entries for NES pixel values 0–3")
    if len(set(normalized)) != len(normalized):
        raise ValueError("PNG colors must be distinct")
    if any(color[3] == 0 for color in normalized[1:]):
        raise ValueError("a transparent color may appear only at pixel value 0")
    return {color: index for index, color in enumerate(normalized)}


def load_png(path: str | PathLike[str], *, colors: Sequence[Color] | None = None) -> TileSheet:
    """Read an 8-pixel-aligned PNG into tiles, preserving exact pixel values.

    With ``colors=None``, the PNG must use indexed color and its visible pixels
    must use palette indexes 0–3. For RGB/RGBA images, supply one to four colors
    in pixel-value order, e.g. ``["#000000", "#FFFFFF", "#80C020", "#204080"]``.
    RGB/RGBA tuples and ``#RRGGBBAA`` strings are also accepted. Transparent
    pixels always become value 0; partial transparency is rejected. Opaque
    colors must match exactly, so accidental antialiasing is reported rather
    than silently changing the artwork. Color mapping does not set the game's
    hardware palette. Animated PNGs are not accepted; arrange frames in a sheet.
    """
    lookup = None if colors is None else _color_lookup(colors)
    try:
        from PIL import Image
    except ImportError as exc:
        raise ImportError('PNG import requires Pillow; install it with pip install "py3nes[images]"') from exc

    with Image.open(path) as source:
        if source.format != "PNG":
            raise ValueError("load_png requires a PNG image")
        if getattr(source, "is_animated", False):
            raise ValueError("animated PNGs are unsupported; put animation frames in a tile sheet")
        width, height = source.size
        if width < 8 or height < 8 or width % 8 or height % 8:
            raise ValueError(f"PNG dimensions must be positive multiples of 8 pixels, got {width}×{height}")
        if lookup is None and source.mode != "P":
            raise ValueError("RGB/RGBA or grayscale PNGs require an explicit colors=[...] mapping; "
                             "alternatively export indexed PNG using palette indexes 0–3")
        rgba = source.convert("RGBA")
        original = source.load()
        pixels = rgba.load()
        values = []
        for y in range(height):
            row = []
            for x in range(width):
                color = pixels[x, y]
                if color[3] == 0:
                    value = 0
                elif color[3] != 255:
                    raise ValueError(f"PNG pixel ({x}, {y}) has partial transparency; NES tiles require alpha 0 or 255")
                elif lookup is None:
                    value = original[x, y]
                    if value > 3:
                        raise ValueError(f"PNG pixel ({x}, {y}) uses palette index {value}; "
                                         "use indexes 0–3 or supply colors=[...]")
                else:
                    try:
                        value = lookup[color]
                    except KeyError as exc:
                        raise ValueError(f"PNG pixel ({x}, {y}) color {color} is absent from colors; "
                                         "use exact colors without antialiasing") from exc
                row.append(value)
            values.append(row)
    return TileSheet(tuple(
        tuple(Tile(tuple(tuple(row[x:x + 8]) for row in values[y:y + 8]))
              for x in range(0, width, 8))
        for y in range(0, height, 8)
    ))
