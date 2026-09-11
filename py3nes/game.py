"""Public builder API. All Python code runs before the ROM is started."""

from dataclasses import fields, is_dataclass, replace
from collections.abc import Mapping
from pathlib import Path
import textwrap
from typing import Sequence

from .assets import DEFAULT_PALETTE, FONT_TILES, Tile, encode_text
from .build import BuildResult, compile_rom, emit_assembly
from .model import (Action, Button, Event, Map, SetTile,
                    Sprite, TextBox, Trigger, integer)
from .ir import Variable
from .physics import Actor, AnimationClip, AnimationRange, Hitbox, Metasprite, SpritePart
from .effects import SetBackgroundTile


class Game:
    """Build an NTSC, mapper-0 game from assets, state, actors, and explicit rules."""

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
        self._variables: list[Variable] = []
        self._actors: list[Actor] = []
        self._post_events: list[Event] = []
        self._oam_used = 0
        self._rooms = []
        self._start_room = None
        self._start_spawn = None

    @property
    def rooms(self):
        """Named rooms in their registration order."""
        return tuple(self._rooms)

    def room(self, name: str):
        """Create an independently populated screen; graphics are shared by all rooms."""
        from .rooms import Room
        if any(room.name == name for room in self._rooms):
            raise ValueError(f"duplicate room name: {name}")
        if len(self._rooms) >= 16:
            raise ValueError("maximum 16 rooms per game; ROM and RAM budgets also apply")
        result = Room(self, name, len(self._rooms))
        self._rooms.append(result)
        return result

    def start(self, room, *, spawn: str | None = None):
        """Choose the initial room and optional entrance (defaults to the first room)."""
        from .rooms import ChangeRoom
        destination = ChangeRoom(room, spawn)
        self._validate(destination)
        self._start_room = room
        self._start_spawn = spawn
        return room

    @property
    def _root(self):
        return self

    @property
    def variables(self):
        return tuple(self._variables)

    @property
    def actors(self):
        return tuple(self._actors)

    @property
    def post_events(self):
        return tuple(self._post_events)

    def _variable(self, name, initial, kind):
        variable = Variable(name, initial, kind)
        if name.startswith(("actor_", "rt_", "room_")):
            raise ValueError("variable prefixes actor_, room_, and rt_ are reserved by the runtime")
        if any(v.name == name for v in self._variables):
            raise ValueError(f"duplicate variable name: {name}")
        public = sum(not v.name.startswith("actor_")
                     for scope in (self._root,) + self._root.rooms for v in scope.variables)
        if public >= 64:
            raise ValueError("maximum 64 user variables per game")
        self._variables.append(variable)
        return variable

    def byte(self, name: str, initial: int = 0) -> Variable:
        """Allocate an unsigned byte in ROM runtime RAM, with modulo-256 arithmetic."""
        return self._variable(name, initial, "u8")

    variable = byte

    def signed_byte(self, name: str, initial: int = 0) -> Variable:
        """Allocate a two's-complement byte (-128..127), with signed comparisons."""
        return self._variable(name, initial, "i8")

    def flag(self, name: str, initial: bool = False) -> Variable:
        """Allocate a Boolean flag. Set accepts 0/1, bool, or another flag."""
        return self._variable(name, initial, "flag")

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
        if self._oam_used == 64:
            raise ValueError("the NES supports at most 64 hardware sprites")
        # Validate all fields before registering graphics, so rejected calls do
        # not consume pattern-table slots or otherwise alter the description.
        index = 0 if isinstance(tile, Tile) else self._tile_index(tile)
        result = Sprite(self._oam_used, index, x, y, palette,
                        flip_horizontal, flip_vertical, behind_background)
        if isinstance(tile, Tile):
            result = replace(result, tile=self.tile(tile))
        self._sprites.append(result)
        self._oam_used += 1
        return result

    def metasprite(self, tiles, *, palette=0) -> Metasprite:
        """Combine a rectangular grid of tiles into one larger actor graphic."""
        rows = tuple(tuple(row) for row in tiles)
        if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
            raise ValueError("metasprite tiles must be a nonempty rectangular grid")
        if len(rows) > 4 or len(rows[0]) > 4:
            raise ValueError("metasprite grid must fit 4×4 tiles")
        integer(palette, "sprite palette", 0, 3)
        before = len(self._tiles)
        try:
            parts = tuple(SpritePart(self.tile(tile) if isinstance(tile, Tile) else self._tile_index(tile),
                                     x * 8, y * 8, palette)
                          for y, row in enumerate(rows) for x, tile in enumerate(row))
            return Metasprite(parts)
        except (TypeError, ValueError):
            del self._tiles[before:]
            raise

    def actor(self, *, tile=None, frames=None, animations=None, name=None, x=0, y=1,
              hitbox=None, gravity=0, max_fall_speed=4, frame_ticks=8, collides=True,
              subpixel=False, facing=None, freezable=False) -> Actor:
        """Create an actor with screen coordinates, velocity, collision and animation."""
        if len(self._actors) >= 8:
            raise ValueError("maximum 8 actors per room" if self is not self._root else "maximum 8 actors per game")
        if sum(value is not None for value in (tile, frames, animations)) != 1:
            raise ValueError("provide either tile or frames or animations for an actor")
        if name is None:
            name = f"actor{len(self._actors)}"
        if any(a.name == name for a in self._actors):
            raise ValueError(f"duplicate actor name: {name}")
        before = len(self._tiles)
        try:
            clips = []
            inputs = (tile,) if frames is None else frames
            if animations is not None:
                if not isinstance(animations, Mapping) or not animations:
                    raise ValueError("animations must be a nonempty mapping of names to AnimationClip descriptions")
                inputs = []
                for clip_name, clip in animations.items():
                    if not isinstance(clip, AnimationClip):
                        raise TypeError("animations values must be AnimationClip descriptions")
                    clips.append(AnimationRange(clip_name, len(inputs), len(clip.frames),
                                                clip.frame_ticks, clip.loop))
                    inputs.extend(clip.frames)
                if len(inputs) > 32:
                    raise ValueError("actor animations may contain at most 32 frames in total")
                if facing is None:
                    facing = "right"
            graphics = []
            for graphic in inputs:
                if not isinstance(graphic, Metasprite):
                    index = self.tile(graphic) if isinstance(graphic, Tile) else self._tile_index(graphic)
                    graphic = Metasprite((SpritePart(index),))
                for part in graphic.parts:
                    self._tile_index(part.tile)
                graphics.append(graphic)
            if not graphics:
                raise ValueError("actor needs at least one animation frame")
            if hitbox is None:
                hitbox = Hitbox(max(p.dx + 8 for g in graphics for p in g.parts),
                                max(p.dy + 8 for g in graphics for p in g.parts))
            actor = Actor(self._actor_index(), name, tuple(graphics), self._oam_used,
                          x, y, hitbox, gravity, max_fall_speed, frame_ticks, collides,
                          subpixel=subpixel, clips=tuple(clips), facing=facing,
                          freezable=freezable)
            if self._oam_used + actor.oam_slots > 64:
                raise ValueError("actors and sprites together may use at most 64 OAM slots")
        except (TypeError, ValueError):
            del self._tiles[before:]
            raise
        self._actors.append(actor)
        self._variables.extend(actor.variables)
        self._oam_used += actor.oam_slots
        return actor

    def _actor_index(self):
        return len(self._actors)

    def map(self, tiles: Map | Sequence[Sequence[int]], *,
            column: int | None = None, row: int | None = None, solid=None, palette=None) -> Map:
        """Place a tile rectangle. Later background calls overwrite earlier ones."""
        if isinstance(tiles, Map):
            result = replace(tiles, column=tiles.column if column is None else column,
                             row=tiles.row if row is None else row)
        else:
            result = Map(tiles, 0 if column is None else column, 0 if row is None else row)
        if solid is not None:
            mask = tuple((solid,) * result.width for _ in range(result.height)) if isinstance(solid, bool) else solid
            result = replace(result, solid=mask)
        if palette is not None:
            mask = (tuple((palette,) * result.width for _ in range(result.height))
                    if isinstance(palette, int) else palette)
            result = replace(result, palettes=mask)
        for line in result.tiles:
            for tile in line:
                self._tile_index(tile)
        self._layers.append(result)
        return result

    def platformer(self, actor, **options):
        """Bind movement, acceleration, friction, buffered jumping and jump release."""
        from .controls import platformer
        return platformer(self, actor, **options)

    def timer(self, name, **options):
        """Create a saturating countdown that advances in gameplay ticks."""
        from .behaviors import timer
        return timer(self, name, **options)

    def state_machine(self, name, **options):
        """Build named runtime states with entry actions and conditional transitions."""
        from .behaviors import state_machine
        return state_machine(self, name, **options)

    def patrol(self, actor, **options):
        """Give an actor a reusable horizontal patrol behavior."""
        from .behaviors import patrol
        return patrol(self, actor, **options)

    def health(self, actor, **options):
        """Attach health and a temporary damage cooldown to an actor."""
        from .behaviors import health
        return health(self, actor, **options)

    def checkpoint(self, actor, **options):
        """Describe named respawn positions for an actor."""
        from .behaviors import checkpoint
        return checkpoint(self, actor, **options)

    def sequence(self, name, *steps, **options):
        """Build an explicit sequence of actions and waits across gameplay ticks."""
        from .sequences import sequence
        return sequence(self, name, *steps, **options)

    def dialogue(self, name, pages, **options):
        """Reserve a text area and build a paged, interactive conversation."""
        from .dialogue import dialogue
        return dialogue(self, name, pages, **options)

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
        self._validate(event)
        self._events.append(event)
        return event

    def _validate(self, value, depth=0):
        """Validate every branch and nested expression, even currently false branches."""
        from .rooms import ChangeRoom
        if depth > 192:
            raise ValueError("runtime description is nested too deeply (maximum 32 expression/action levels)")
        if isinstance(value, ChangeRoom):
            if value.room.parent is not self._root or not any(value.room is room for room in self._root.rooms):
                raise ValueError("ChangeRoom destination belongs to a different game or was not registered")
        elif isinstance(value, Variable):
            allowed = self._variables if self is self._root else self._variables + self._root._variables
            allowed = allowed + [variable for room in self._root.rooms for variable in room.persistent_variables]
            if not any(value is v for v in allowed):
                raise ValueError("variable belongs to a different game/room or was not registered")
        elif isinstance(value, Actor):
            if not any(value is a for a in self._actors):
                raise ValueError("actor belongs to a different game/room or was not registered")
        elif isinstance(value, Sprite):
            if not any(value is s for s in self._sprites):
                raise ValueError("action sprite belongs to a different game/room or was not registered")
        elif is_dataclass(value):
            if isinstance(value, (SetTile, SetBackgroundTile)):
                self._tile_index(value.tile)
            for field in fields(value): self._validate(getattr(value, field.name), depth + 1)
        elif isinstance(value, (tuple, list)):
            for item in value: self._validate(item, depth + 1)

    def bind_held(self, button: Button, *actions: Action) -> Event:
        """Run actions on each game tick while a button is held."""
        return self.add_event(Event(Trigger.HELD, actions, button))

    def bind_pressed(self, button: Button, *actions: Action) -> Event:
        """Run actions once on a button's transition from released to held."""
        return self.add_event(Event(Trigger.PRESSED, actions, button))

    def every_frame(self, *actions: Action) -> Event:
        """Run actions every game tick, in event registration order."""
        return self.add_event(Event(Trigger.FRAME, actions))

    def after_physics(self, *actions: Action) -> Event:
        """Evaluate gameplay rules after movement/collision, before rendering this tick."""
        event = Event(Trigger.FRAME, actions)
        self._validate(event)
        self._post_events.append(event)
        return event

    def collision_data(self) -> bytes:
        """Return a separate 32×30 grid of solid flags; graphics do not imply collision."""
        collision = bytearray(960)
        for layer in self._layers:
            if layer.solid is not None:
                for y, row in enumerate(layer.solid):
                    start = (layer.row + y) * 32 + layer.column
                    collision[start:start + len(row)] = bytes(row)
        return bytes(collision)

    def nametable(self) -> bytes:
        """Return tile indices and packed palettes for 16×16 pixel regions."""
        table = bytearray(1024)
        palettes = [None] * 960
        for layer in self._layers:
            for y, line in enumerate(layer.tiles):
                start = (layer.row + y) * 32 + layer.column
                table[start:start + layer.width] = bytes(line)
                if layer.palettes is not None:
                    palettes[start:start + layer.width] = layer.palettes[y]
        for row in range(0, 30, 2):
            for column in range(0, 32, 2):
                choices = {palettes[(row + dy) * 32 + column + dx]
                           for dy in range(2) for dx in range(2)} - {None}
                if len(choices) > 1:
                    raise ValueError(f"background palettes conflict in 16x16 region at tile ({column}, {row}); "
                                     "all four tiles must share a palette")
                palette = next(iter(choices), 0)
                address = 960 + (row // 4) * 8 + column // 4
                shift = ((row % 4) // 2) * 4 + ((column % 4) // 2) * 2
                table[address] |= palette << shift
        return bytes(table)

    def chr_data(self) -> bytes:
        """Return 8 KiB of CHR ROM; both pattern tables contain the same graphics."""
        patterns = b"".join(tile.to_chr() for tile in self._tiles).ljust(4096, b"\0")
        return patterns + patterns

    def to_assembly(self) -> str:
        """Generate self-contained ca65 source without requiring installed build tools."""
        from .codegen import generate_assembly
        self._validate_rooms()
        room_options = {}
        if self.rooms:
            room_options = dict(rooms=self.rooms,
                                start_room=(self._start_room or self.rooms[0]).index,
                                start_spawn=self._start_spawn)
        return generate_assembly(nametable=self.nametable(), chr_data=self.chr_data(),
                                 palette=self.palette, sprites=self.sprites, events=self.events,
                                 variables=self.variables + tuple(v for room in self.rooms for v in room.variables),
                                 actors=self.actors, collision=self.collision_data(),
                                 post_events=self.post_events, **room_options)

    def _validate_rooms(self):
        from .ir import walk_actions
        from .rooms import ChangeRoom
        if self.rooms and (self.maps or self.sprites or self.actors):
            raise ValueError("named rooms cannot be mixed with game-level maps, text, sprites, or actors; add them to a room")
        if self._start_room is not None:
            self._validate(ChangeRoom(self._start_room, self._start_spawn))
            self._validate_spawn(self._start_room, self._start_spawn)
        for scope in (self,) + self.rooms:
            for event in scope.events + scope.post_events + getattr(scope, "enter_events", ()):
                scope._validate(event)
                for action in walk_actions(event.actions):
                    if isinstance(action, ChangeRoom):
                        self._validate_spawn(action.room, action.spawn)

    @staticmethod
    def _validate_spawn(room, name):
        if name is not None and name not in room.spawns:
            raise ValueError(f"room {room.name!r} has no spawn named {name!r}")

    def emit_assembly(self, path: str | Path) -> Path:
        """Write a .s (or .asm) file and sibling .cfg linker configuration."""
        from .codegen import LINKER_CONFIG, ROOM_LINKER_CONFIG
        return emit_assembly(self.to_assembly(), ROOM_LINKER_CONFIG if self.rooms else LINKER_CONFIG, path)

    def build(self, output: str | Path, *, ca65: str = "ca65", ld65: str = "ld65") -> BuildResult:
        """Generate assembly and invoke ca65/ld65 to produce a .nes cartridge image."""
        from .codegen import LINKER_CONFIG, ROOM_LINKER_CONFIG
        return compile_rom(self.to_assembly(), ROOM_LINKER_CONFIG if self.rooms else LINKER_CONFIG,
                           output, ca65=ca65, ld65=ld65)
