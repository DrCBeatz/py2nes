"""Import a documented subset of Tiled JSON into the declarative room API.

Maps are finite orthogonal screens, at most 32 by 30 cells, using 8 by 8
PNG tiles. Tile data must be JSON integer arrays. Inline and external JSON
tilesets are supported, with no spacing or margins. Horizontal/vertical tile
flips are baked into graphics; diagonal/hexagonal transforms are rejected.

A tile layer named ``collision`` (case insensitive), or with the Boolean
property ``collision=True``, contributes solid cells instead of graphics.
Its editor visibility does not disable collision. Other hidden layers and
objects are skipped. Visible tile layers replace earlier nonempty cells;
pixel alpha blending, group layers and image layers are not supported.

Object classes select actor factories, except ``spawn`` and ``exit``. Objects
must be named points or axis-aligned rectangles with integer pixel positions.
Spawns refer to an actor by name through property ``actor``. Rectangular exits
use string properties ``room`` and optional ``spawn``. Custom scalar properties
remain available to build-time actor factories. No Python is read from a map.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from .assets import Tile
from .ir import If
from .model import Button, Map, integer
from .physics import Actor

if TYPE_CHECKING:
    from .rooms import Room, Spawn


def _identifier(value, label):
    if not isinstance(value, str) or not value.isascii() or not value.isidentifier():
        raise ValueError(f"{label} must be a nonempty ASCII identifier")
    return value


def _pixel(value, label, low, high):
    # Tiled stores pixel measurements as doubles, including whole numbers.
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return integer(value, label, low, high)


def _properties(data, label):
    result = {}
    raw = data.get("properties", [])
    if not isinstance(raw, list):
        raise ValueError(f"{label}: properties must be a JSON array")
    for entry in raw:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise ValueError(f"{label}: property must have a string name")
        name, kind, value = entry["name"], entry.get("type", "string"), entry.get("value")
        if name in result:
            raise ValueError(f"{label}: duplicate property {name!r}")
        valid = {
            "string": isinstance(value, str),
            "color": isinstance(value, str),
            "int": isinstance(value, int) and not isinstance(value, bool),
            "float": isinstance(value, (int, float)) and not isinstance(value, bool),
            "bool": isinstance(value, bool),
        }
        if not valid.get(kind, False):
            raise ValueError(f"{label}: property {name!r} needs a scalar string, color, int, float or bool value")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"{label}: property {name!r} must be finite")
        result[name] = value
    return MappingProxyType(result)


def _json(path):
    try:
        result = json.loads(path.read_text(encoding="utf-8"),
                            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
        raise ValueError(f"invalid Tiled JSON in {path}: {exc}") from exc
    if not isinstance(result, dict):
        raise ValueError(f"Tiled file {path} must contain a JSON object")
    return result


def _list(data, key, label):
    value = data.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{label}: {key} must be an array of objects")
    return value


@dataclass(frozen=True)
class TiledObject:
    """An editor object with a stable Tiled ID and immutable scalar properties."""

    id: int
    name: str
    kind: str
    x: int
    y: int
    width: int
    height: int
    properties: Mapping

    def __post_init__(self):
        integer(self.id, "Tiled object ID", 1, 0x7FFFFFFF)
        _identifier(self.name, "Tiled object name")
        _identifier(self.kind, "Tiled object class")
        integer(self.x, "object x", 0, 255)
        integer(self.y, "object y", 0, 239)
        integer(self.width, "object width", 0, 256 - self.x)
        integer(self.height, "object height", 0, 240 - self.y)
        if (self.width == 0) != (self.height == 0):
            raise ValueError("Tiled objects must be points or nonempty rectangles")
        properties = dict(self.properties)
        if any(not isinstance(key, str) or not isinstance(value, (str, int, float, bool))
               for key, value in properties.items()):
            raise ValueError("Tiled object properties must have string keys and scalar values")
        if any(isinstance(value, float) and not math.isfinite(value) for value in properties.values()):
            raise ValueError("Tiled object numeric properties must be finite")
        label = f"object {self.name!r}"
        if self.kind == "spawn":
            _identifier(properties.get("actor"), f"{label} actor property")
            if self.y == 0:
                raise ValueError(f"{label}: actor spawn y must be at least 1")
        elif self.kind == "exit":
            _identifier(properties.get("room"), f"{label} room property")
            if "spawn" in properties:
                _identifier(properties["spawn"], f"{label} spawn property")
            if not self.width or not self.height:
                raise ValueError(f"{label}: exit must be a nonempty rectangle")
        object.__setattr__(self, "properties", MappingProxyType(properties))

    def contains(self, actor: Actor):
        """Describe strict rectangle/hitbox overlap, suitable for ``If``.

        The name refers to entering the region: partial overlap counts. Bounds
        are rearranged at build time to avoid wrapping 8-bit coordinate sums.
        """
        if not isinstance(actor, Actor):
            raise TypeError("region target must be an Actor")
        if not self.width or not self.height:
            raise ValueError("point objects cannot be used as overlap regions")
        box = actor.hitbox
        min_x = max(0, self.x - box.offset_x - box.width + 1)
        max_x = min(255, self.x + self.width - box.offset_x - 1)
        min_y = max(0, self.y - box.offset_y - box.height + 1)
        max_y = min(255, self.y + self.height - box.offset_y - 1)
        if max_x < min_x or max_y < min_y:
            return actor.x.lt(0)  # A constant-false comparison with valid byte operands.
        return (actor.visible & actor.x.ge(min_x) & actor.x.le(max_x)
                & actor.y.ge(min_y) & actor.y.le(max_y))


@dataclass(frozen=True)
class ImportedRoom:
    """References produced by applying a Tiled description to an existing room."""

    room: Room
    actors: Mapping[str, Actor]
    spawns: Mapping[str, Spawn]
    exits: Mapping[str, TiledObject]

    def __post_init__(self):
        for name in ("actors", "spawns", "exits"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def bind_exits(self, player: Actor, rooms: Mapping[str, Room], *, button=Button.UP):
        """Bind all exits to a button press while the player overlaps their region.

        Import every destination before calling this method. For locked exits,
        use ``exits[name].contains(player)`` in your own conditional rule instead.
        No rules are registered unless all destinations and entrances validate.
        """
        from .rooms import ChangeRoom, Room
        if not isinstance(player, Actor) or not any(player is actor for actor in self.room.actors):
            raise ValueError("exit player must belong to the imported room")
        pending = []
        for exit in self.exits.values():
            name = exit.properties["room"]
            if name not in rooms:
                raise ValueError(f"exit {exit.name!r}: destination room {name!r} was not supplied")
            destination = rooms[name]
            if not isinstance(destination, Room) or destination.parent is not self.room.parent:
                raise ValueError(f"exit {exit.name!r}: destination must belong to the same game")
            spawn = exit.properties.get("spawn")
            if spawn is not None and spawn not in destination.spawns:
                raise ValueError(f"exit {exit.name!r}: unknown destination spawn {spawn!r}")
            pending.append(If(exit.contains(player), ChangeRoom(destination, spawn)))
        before = len(self.room._events)
        try:
            return tuple(self.room.bind_pressed(button, action) for action in pending)
        except Exception:
            del self.room._events[before:]
            raise


@dataclass(frozen=True)
class TiledMap:
    """A loaded, game-independent screen description; loading allocates no ROM tiles.

    Blank cells contain ``None``. Other cells contain immutable Tile descriptions.
    All returned grids and objects can be inspected without constructing a Game.
    """

    source: Path
    tiles: tuple[tuple[Tile | None, ...], ...]
    solid: tuple[tuple[bool, ...], ...]
    palettes: tuple[tuple[int, ...], ...]
    objects: tuple[TiledObject, ...]

    def __post_init__(self):
        tiles = tuple(tuple(row) for row in self.tiles)
        # Reuse the screen shape/mask checks without allocating any ROM assets.
        model = Map(tuple(tuple(0 for _ in row) for row in tiles),
                    solid=self.solid, palettes=self.palettes)
        if any(tile is not None and not isinstance(tile, Tile) for row in tiles for tile in row):
            raise TypeError("Tiled map cells must be Tile descriptions or None")
        objects = tuple(self.objects)
        if any(not isinstance(obj, TiledObject) for obj in objects):
            raise TypeError("Tiled map objects must be TiledObject descriptions")
        for obj in objects:
            if (obj.x >= model.width * 8 or obj.y >= model.height * 8
                    or obj.x + obj.width > model.width * 8 or obj.y + obj.height > model.height * 8):
                raise ValueError(f"object {obj.name!r} must fit inside the Tiled map dimensions")
        for key in ("id", "name"):
            values = [getattr(obj, key) for obj in objects]
            if len(set(values)) != len(values):
                raise ValueError(f"Tiled object {key}s must be unique across the map")
        object.__setattr__(self, "source", Path(self.source))
        object.__setattr__(self, "tiles", tiles)
        object.__setattr__(self, "solid", model.solid)
        object.__setattr__(self, "palettes", model.palettes)
        object.__setattr__(self, "objects", objects)

    @property
    def width(self):
        return len(self.tiles[0])

    @property
    def height(self):
        return len(self.tiles)

    def apply(self, room: Room, *, actor_factories: Mapping[str, Callable] | None = None) -> ImportedRoom:
        """Place this screen and construct its actors/spawns in a Room.

        An actor factory receives ``(room, object)`` and must return the actor
        it registered with that object's name and coordinates. Factories run
        once during the Python build. Builder state is rolled back on failure;
        a factory's external side effects, such as writing files, are its own.
        """
        from .rooms import Room
        if not isinstance(room, Room):
            raise TypeError("Tiled maps must be applied to a Room returned by game.room()")
        factories = dict(actor_factories or {})
        existing = {actor.name: actor for actor in room.actors}
        descriptions = [obj for obj in self.objects if obj.kind not in ("spawn", "exit")]
        for obj in descriptions:
            if obj.name in existing:
                raise ValueError(f"Tiled actor {obj.name!r} already exists in room {room.name!r}")
            if not callable(factories.get(obj.kind)):
                raise ValueError(f"Tiled object {obj.name!r}: supply an actor factory for class {obj.kind!r}")
        actor_names = set(existing) | {obj.name for obj in descriptions}
        for obj in self.objects:
            if obj.kind == "spawn":
                if obj.properties["actor"] not in actor_names:
                    raise ValueError(f"spawn {obj.name!r}: unknown actor {obj.properties['actor']!r}")
                if obj.name in room.spawns:
                    raise ValueError(f"spawn {obj.name!r} already exists in room {room.name!r}")
        snapshot = _snapshot(room.parent)
        try:
            indices = tuple(tuple(0 if tile is None else room.tile(tile) for tile in row) for row in self.tiles)
            room.map(Map(indices, solid=self.solid, palettes=self.palettes))
            actors = {}
            for obj in descriptions:
                actor = factories[obj.kind](room, obj)
                if not isinstance(actor, Actor) or not any(actor is value for value in room.actors):
                    raise ValueError(f"factory for {obj.name!r} must return an actor registered in this room")
                if actor.name != obj.name or (actor.initial_x, actor.initial_y) != (obj.x, obj.y):
                    raise ValueError(f"factory for {obj.name!r} must use the object's name, x and y")
                if any(actor is value for value in existing.values()):
                    raise ValueError(f"factory for {obj.name!r} must construct a new actor")
                actors[obj.name] = actor
            available = existing | actors
            spawns = {obj.name: room.spawn(obj.name, available[obj.properties["actor"]], x=obj.x, y=obj.y)
                      for obj in self.objects if obj.kind == "spawn"}
            room.nametable()  # Also validates palette boundaries against pre-existing room layers.
            return ImportedRoom(room, actors, spawns,
                                {obj.name: obj for obj in self.objects if obj.kind == "exit"})
        except Exception:
            _restore(snapshot)
            raise


def _snapshot(game):
    # Preserve list/dict/set identities, especially shared CHR tile storage.
    result = []
    for scope in (game,) + game.rooms:
        attributes = dict(vars(scope))
        containers = [(value, value.copy()) for value in attributes.values()
                      if isinstance(value, (list, dict, set))]
        result.append((scope, attributes, containers))
    return result


def _restore(snapshot):
    for scope, attributes, containers in snapshot:
        vars(scope).clear()
        vars(scope).update(attributes)
        for original, contents in containers:
            if isinstance(original, list):
                original[:] = contents
            else:
                original.clear()
                original.update(contents)


def _tilesets(data, directory, colors):
    from .images import load_png
    graphics = {}
    palettes = {}
    defaults = {}
    for entry in _list(data, "tilesets", "map"):
        first = integer(entry.get("firstgid"), "tileset firstgid", 1, 0x0FFFFFFF)
        if "source" in entry:
            if not isinstance(entry["source"], str):
                raise ValueError("tileset source must be a relative JSON file path")
            path = directory / entry["source"]
            definition, base = _json(path), path.parent
        else:
            definition, base = entry, directory
        label = f"tileset {definition.get('name', first)!r}"
        if definition.get("tilewidth") != 8 or definition.get("tileheight") != 8:
            raise ValueError(f"{label}: only 8 by 8 pixel tiles are supported")
        if definition.get("spacing", 0) != 0 or definition.get("margin", 0) != 0:
            raise ValueError(f"{label}: spacing and margin must be zero")
        offset = definition.get("tileoffset", {})
        if not isinstance(offset, dict) or offset.get("x", 0) != 0 or offset.get("y", 0) != 0:
            raise ValueError(f"{label}: tile offsets are not supported")
        if "transparentcolor" in definition:
            raise ValueError(f"{label}: use PNG transparency instead of a Tiled transparentcolor override")
        if not isinstance(definition.get("image"), str):
            raise ValueError(f"{label}: requires a PNG tilesheet; image-collection tilesets are not supported")
        sheet = load_png(base / definition["image"], colors=colors)
        if definition.get("columns") != sheet.width:
            raise ValueError(f"{label}: columns must match the PNG width in tiles")
        count = integer(definition.get("tilecount"), "tileset tilecount", 1, sheet.width * sheet.height)
        for key, actual in (("imagewidth", sheet.width * 8), ("imageheight", sheet.height * 8)):
            if key in definition and definition[key] != actual:
                raise ValueError(f"{label}: {key} does not match the PNG")
        palette = integer(_properties(definition, label).get("palette", 0), "tileset palette", 0, 3)
        for index in range(count):
            gid = first + index
            if gid in graphics:
                raise ValueError("Tiled tileset GID ranges must not overlap")
            graphics[gid] = sheet.tiles[index // sheet.width][index % sheet.width]
            defaults[gid] = palette
        seen = set()
        for tile in _list(definition, "tiles", label):
            local = integer(tile.get("id"), "tileset local tile ID", 0, count - 1)
            if local in seen:
                raise ValueError(f"{label}: duplicate local tile ID {local}")
            seen.add(local)
            if any(key in tile for key in ("animation", "objectgroup", "image")):
                raise ValueError(f"{label}: tile animations, tile collision objects and tile images are unsupported; use actors and a collision layer")
            props = _properties(tile, f"{label} tile {local}")
            if "palette" in props:
                palettes[first + local] = integer(props["palette"], "tile palette", 0, 3)
    return graphics, palettes, defaults


def _gid(value, graphics, label):
    integer(value, f"{label} GID", 0, 0xFFFFFFFF)
    if value & 0x30000000:
        raise ValueError(f"{label}: diagonal/hexagonal tile transforms are not supported")
    gid = value & 0x0FFFFFFF
    if value and not gid:
        raise ValueError(f"{label}: a flipped empty tile is invalid")
    if gid and gid not in graphics:
        raise ValueError(f"{label}: unknown global tile ID {gid}")
    if not gid:
        return 0, None
    pixels = graphics[gid].pixels
    if value & 0x80000000:
        pixels = tuple(tuple(reversed(row)) for row in pixels)
    if value & 0x40000000:
        pixels = tuple(reversed(pixels))
    return gid, Tile(pixels)


def _objects(layer, width, height):
    result = []
    for raw in _list(layer, "objects", "object layer"):
        if raw.get("visible", True) is False:
            continue
        label = f"object {raw.get('name', raw.get('id', '?'))!r}"
        if any(key in raw for key in ("gid", "template", "text", "polygon", "polyline")) or any(
                raw.get(key, False) for key in ("ellipse", "capsule")):
            raise ValueError(f"{label}: use a point or rectangle, not a tile, template, text or polygon object")
        if raw.get("rotation", 0) != 0 or raw.get("opacity", 1) != 1:
            raise ValueError(f"{label}: rotation and opacity are unsupported")
        kind = raw.get("type") or raw.get("class")
        props = _properties(raw, label)
        x = _pixel(raw.get("x"), f"{label} x", 0, width * 8 - 1)
        y = _pixel(raw.get("y"), f"{label} y", 0, height * 8 - 1)
        w = _pixel(raw.get("width", 0), f"{label} width", 0, width * 8 - x)
        h = _pixel(raw.get("height", 0), f"{label} height", 0, height * 8 - y)
        if raw.get("point", False) and (w or h):
            raise ValueError(f"{label}: point objects must have zero width and height")
        obj = TiledObject(raw.get("id"), raw.get("name"), kind, x, y, w, h, props)
        result.append(obj)
    return result


def load_tiled(path: str | Path, *, colors=None) -> TiledMap:
    """Load a finite Tiled JSON map and PNG assets without modifying any Game.

    ``colors`` follows :func:`py3nes.images.load_png`: indexed PNGs can omit it;
    RGB/RGBA PNGs supply the source colors corresponding to pixel indices 0..3.
    A ``palette`` integer property (0..3) selects the NES background subpalette,
    with precedence tile definition, layer, tileset. Every occupied cell in a
    16 by 16 pixel attribute quadrant must select the same subpalette.
    """
    path = Path(path).resolve()
    data = _json(path)
    if data.get("orientation") != "orthogonal" or data.get("infinite", False) is not False:
        raise ValueError("Tiled maps must be finite and orthogonal")
    if data.get("tilewidth") != 8 or data.get("tileheight") != 8:
        raise ValueError("Tiled maps must use 8 by 8 pixel tiles")
    width = integer(data.get("width"), "Tiled map width", 1, 32)
    height = integer(data.get("height"), "Tiled map height", 1, 30)
    graphics, tile_palettes, default_palettes = _tilesets(data, path.parent, colors)
    tiles = [[None] * width for _ in range(height)]
    solid = [[False] * width for _ in range(height)]
    palettes = [[None] * width for _ in range(height)]
    objects = []
    for layer in _list(data, "layers", "map"):
        label = f"layer {layer.get('name', '?')!r}"
        props = _properties(layer, label)
        collision = str(layer.get("name", "")).lower() == "collision"
        if "collision" in props:
            if not isinstance(props["collision"], bool):
                raise ValueError(f"{label}: collision property must be a bool")
            collision = collision or props["collision"]
        if not collision and layer.get("visible", True) is False:
            continue
        if (any(layer.get(key, 0) != 0 for key in ("x", "y", "offsetx", "offsety"))
                or any(layer.get(key, 1) != 1 for key in ("parallaxx", "parallaxy", "opacity"))
                or layer.get("mode", "normal") != "normal" or "tintcolor" in layer):
            raise ValueError(f"{label}: offsets, parallax, opacity, tint and blending are unsupported")
        kind = layer.get("type")
        if kind == "objectgroup":
            if collision:
                raise ValueError(f"{label}: collision must use a tile layer")
            objects.extend(_objects(layer, width, height))
            continue
        if kind != "tilelayer":
            raise ValueError(f"{label}: only tile layers and object layers are supported")
        if layer.get("width") != width or layer.get("height") != height:
            raise ValueError(f"{label}: layer dimensions must match the map")
        raw = layer.get("data")
        if (not isinstance(raw, list) or "chunks" in layer or layer.get("encoding")
                or layer.get("compression")):
            raise ValueError(f"{label}: use an uncompressed JSON array for tile data")
        if len(raw) != width * height:
            raise ValueError(f"{label}: tile data length does not match the map dimensions")
        layer_palette = props.get("palette")
        if layer_palette is not None:
            integer(layer_palette, f"{label} palette", 0, 3)
        for index, value in enumerate(raw):
            gid, tile = _gid(value, graphics, label)
            y, x = divmod(index, width)
            if collision:
                solid[y][x] = solid[y][x] or bool(gid)
            elif gid:
                tiles[y][x] = tile
                palettes[y][x] = tile_palettes.get(gid, default_palettes[gid] if layer_palette is None else layer_palette)
    # Empty cells do not constrain palette choice; fill their quadrant's choice
    # so Map can represent hardware attributes without accidental conflicts.
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            cells = [(cy, cx) for cy in range(y, min(y + 2, height))
                     for cx in range(x, min(x + 2, width))]
            choices = {palettes[cy][cx] for cy, cx in cells if palettes[cy][cx] is not None}
            if len(choices) > 1:
                raise ValueError(f"Tiled palette conflict in 16 by 16 pixel block at tile ({x}, {y})")
            palette = next(iter(choices), 0)
            for cy, cx in cells:
                palettes[cy][cx] = palette
    return TiledMap(path, tuple(map(tuple, tiles)), tuple(map(tuple, solid)),
                    tuple(map(tuple, palettes)), tuple(objects))
