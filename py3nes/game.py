"""Public builder API. All Python code runs before the ROM is started."""

from dataclasses import replace
from pathlib import Path
import textwrap
from typing import Sequence

from .assets import DEFAULT_PALETTE, FONT_TILES, Tile, encode_text
from .build import BuildResult, compile_rom, emit_assembly
from .model import (Action, Button, Event, Map, Move, SetPosition, SetTile,
                    Sprite, TextBox, Trigger, integer)


class Game:
    """Build an NTSC, mapper-0 game with static backgrounds and sprite events."""

    def __init__(self, *, region: str = "NTSC", mapper: str = "NROM",
                 palette: Sequence[int] = DEFAULT_PALETTE) -> None:
        if region != "NTSC":
            raise ValueError("only region='NTSC' is currently supported")
        if mapper != "NROM":
            raise ValueError("only mapper='NROM' is currently supported")
        colors = tuple(palette)
        if len(colors) != 32:
            raise ValueError("palette must contain 32 NES color indices")
        for color in colors:
            integer(color, "palette color", 0, 63)
        # These four sprite entries physically mirror background entries.
        if any(colors[i] != colors[i + 16] for i in (0, 4, 8, 12)):
            raise ValueError("palette entries 16/20/24/28 must match their mirrors 0/4/8/12")
        self.region = region
        self.mapper = mapper
        self.palette = bytes(colors)
        self._tiles = list(FONT_TILES)
        self._sprites: list[Sprite] = []
        self._events: list[Event] = []
        self._layers: list[Map] = []
        self._text_boxes: list[TextBox] = []

    @property
    def sprites(self) -> tuple[Sprite, ...]:
        return tuple(self._sprites)

    @property
    def events(self) -> tuple[Event, ...]:
        return tuple(self._events)

    @property
    def maps(self) -> tuple[Map, ...]:
        return tuple(self._layers)

    @property
    def text_boxes(self) -> tuple[TextBox, ...]:
        return tuple(self._text_boxes)

    def tile(self, pixels: Tile | Sequence[str | Sequence[int]]) -> int:
        """Register an 8×8 tile, deduplicating identical graphics; return its index."""
        tile = pixels if isinstance(pixels, Tile) else Tile.from_rows(pixels)
        try:
            return self._tiles.index(tile)
        except ValueError:
            if len(self._tiles) == 256:
                raise ValueError("pattern table is full: 256 tiles including the 64 font tiles")
            self._tiles.append(tile)
            return len(self._tiles) - 1

    def _tile_index(self, tile: int) -> int:
        integer(tile, "tile", 0, 255)
        if tile >= len(self._tiles):
            raise ValueError(f"tile {tile} is not registered; call game.tile() first")
        return tile

    def sprite(self, *, tile: int | Tile, x: int = 0, y: int = 0,
               palette: int = 0, flip_horizontal: bool = False,
               flip_vertical: bool = False, behind_background: bool = False) -> Sprite:
        """Add one hardware sprite. Y uses the NES's raw OAM coordinate (screen y−1)."""
        if len(self._sprites) == 64:
            raise ValueError("the NES supports at most 64 hardware sprites")
        # Validate all fields before registering graphics, so rejected calls do
        # not consume pattern-table slots or otherwise alter the description.
        index = 0 if isinstance(tile, Tile) else self._tile_index(tile)
        result = Sprite(len(self._sprites), index, x, y, palette,
                        flip_horizontal, flip_vertical, behind_background)
        if isinstance(tile, Tile):
            result = replace(result, tile=self.tile(tile))
        self._sprites.append(result)
        return result

    def map(self, tiles: Map | Sequence[Sequence[int]], *,
            column: int | None = None, row: int | None = None) -> Map:
        """Place a tile rectangle. Later background calls overwrite earlier ones."""
        if isinstance(tiles, Map):
            result = replace(tiles, column=tiles.column if column is None else column,
                             row=tiles.row if row is None else row)
        else:
            result = Map(tiles, 0 if column is None else column, 0 if row is None else row)
        for line in result.tiles:
            for tile in line:
                self._tile_index(tile)
        self._layers.append(result)
        return result

    def text(self, text: str, *, column: int = 0, row: int = 0) -> TextBox:
        """Place uppercase text, with explicit newlines and no automatic wrapping."""
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        lines = text.upper().split("\n")
        encoded = [encode_text(line) for line in lines]
        width = max(1, max(map(len, encoded)))
        box = TextBox(text.upper(), column, row, width, len(lines), border=False)
        self.map([line + (0,) * (width - len(line)) for line in encoded], column=column, row=row)
        self._text_boxes.append(box)
        return box

    def text_box(self, text: str, *, column: int, row: int, width: int,
                 height: int | None = None, border: bool = True) -> TextBox:
        """Wrap static text into a rectangle, raising if it will not fit."""
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        if not isinstance(border, bool):
            raise TypeError("border must be a bool")
        integer(width, "width", 3 if border else 1, 32)
        inner_width = width - (2 if border else 0)
        # Validate before wrapping, which can otherwise discard unsupported whitespace.
        for line in text.upper().split("\n"):
            encode_text(line)
        wrapper = textwrap.TextWrapper(width=inner_width, break_long_words=True,
                                       break_on_hyphens=False)
        lines = [line for paragraph in text.upper().split("\n")
                 for line in (wrapper.wrap(paragraph) or [""])]
        if height is None:
            height = len(lines) + (2 if border else 0)
        box = TextBox(text.upper(), column, row, width, height, border)
        inner_height = height - (2 if border else 0)
        if len(lines) > inner_height:
            raise ValueError(f"text needs {len(lines)} rows but the box has {inner_height} interior rows")
        grid = [[0] * width for _ in range(height)]
        offset = int(border)
        for y, line in enumerate(lines):
            for x, tile in enumerate(encode_text(line)):
                grid[y + offset][x + offset] = tile
        if border:
            # Lines meet at pixel (3,3); corners and edges connect across whole tiles.
            patterns = {
                "h": lambda x, y: y == 3,
                "v": lambda x, y: x == 3,
                "tl": lambda x, y: (y == 3 and x >= 3) or (x == 3 and y >= 3),
                "tr": lambda x, y: (y == 3 and x <= 3) or (x == 3 and y >= 3),
                "bl": lambda x, y: (y == 3 and x >= 3) or (x == 3 and y <= 3),
                "br": lambda x, y: (y == 3 and x <= 3) or (x == 3 and y <= 3),
            }
            borders = {name: Tile(tuple(tuple(int(fn(x, y)) for x in range(8))
                                        for y in range(8))) for name, fn in patterns.items()}
            missing = set(borders.values()).difference(self._tiles)
            if len(self._tiles) + len(missing) > 256:
                raise ValueError("not enough tile slots for the text box border")
            indices = {name: self.tile(tile) for name, tile in borders.items()}
            grid[0] = [indices["tl"]] + [indices["h"]] * (width - 2) + [indices["tr"]]
            grid[-1] = [indices["bl"]] + [indices["h"]] * (width - 2) + [indices["br"]]
            for y in range(1, height - 1):
                grid[y][0] = grid[y][-1] = indices["v"]
        self.map(grid, column=column, row=row)
        self._text_boxes.append(box)
        return box

    def add_event(self, event: Event) -> Event:
        """Register an explicit event and check that all targets belong to this game."""
        if not isinstance(event, Event):
            raise TypeError("event must be an Event description")
        for action in event.actions:
            if not any(action.sprite is sprite for sprite in self._sprites):
                raise ValueError("action sprite belongs to a different game or was not registered")
            if isinstance(action, SetTile):
                self._tile_index(action.tile)
        self._events.append(event)
        return event

    def bind_held(self, button: Button, *actions: Action) -> Event:
        """Run actions on each game tick while a button is held."""
        return self.add_event(Event(Trigger.HELD, actions, button))

    def bind_pressed(self, button: Button, *actions: Action) -> Event:
        """Run actions once on a button's transition from released to held."""
        return self.add_event(Event(Trigger.PRESSED, actions, button))

    def every_frame(self, *actions: Action) -> Event:
        """Run actions every game tick, in event registration order."""
        return self.add_event(Event(Trigger.FRAME, actions))

    def nametable(self) -> bytes:
        """Return 960 background tile indices and 64 palette-zero attribute bytes."""
        table = bytearray(1024)
        for layer in self._layers:
            for y, line in enumerate(layer.tiles):
                start = (layer.row + y) * 32 + layer.column
                table[start:start + layer.width] = bytes(line)
        return bytes(table)

    def chr_data(self) -> bytes:
        """Return 8 KiB of CHR ROM; both pattern tables contain the same graphics."""
        patterns = b"".join(tile.to_chr() for tile in self._tiles).ljust(4096, b"\0")
        return patterns + patterns

    def to_assembly(self) -> str:
        """Generate self-contained ca65 source without requiring installed build tools."""
        from .codegen import generate_assembly
        return generate_assembly(nametable=self.nametable(), chr_data=self.chr_data(),
                                 palette=self.palette, sprites=self.sprites, events=self.events)

    def emit_assembly(self, path: str | Path) -> Path:
        """Write a .s (or .asm) file and sibling .cfg linker configuration."""
        from .codegen import LINKER_CONFIG
        return emit_assembly(self.to_assembly(), LINKER_CONFIG, path)

    def build(self, output: str | Path, *, ca65: str = "ca65", ld65: str = "ld65") -> BuildResult:
        """Generate assembly and invoke ca65/ld65 to produce a .nes cartridge image."""
        from .codegen import LINKER_CONFIG
        return compile_rom(self.to_assembly(), LINKER_CONFIG, output, ca65=ca65, ld65=ld65)
