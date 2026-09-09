"""Tiled imports preserve editor data and produce playable room transitions."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import tempfile
import unittest

try:
    from PIL import Image
except ImportError:
    Image = None

from py3nes import Button, Game, Hitbox, If, Set, Tile
from py3nes.tiled import TiledMap, TiledObject, load_tiled
from tests.runtime_harness import HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME, RuntimeHarness


def properties(**values):
    kinds = {bool: "bool", int: "int", float: "float", str: "string"}
    return [{"name": key, "type": kinds[type(value)], "value": value}
            for key, value in values.items()]


def object_(id=1, name="player", kind="player", x=16, y=16, width=8, height=8, **props):
    return dict(id=id, name=name, type=kind, x=x, y=y, width=width, height=height,
                properties=properties(**props))


class TiledDescriptionTests(unittest.TestCase):
    def test_direct_spawn_description_requires_a_valid_actor_and_visible_y(self):
        for props in ({}, {"actor": None}, {"actor": "two words"}, {"actor": 1}):
            with self.subTest(properties=props), self.assertRaises(ValueError):
                TiledObject(1, "entrance", "spawn", 8, 8, 0, 0, props)
        with self.assertRaisesRegex(ValueError, "spawn y"):
            TiledObject(1, "entrance", "spawn", 8, 0, 0, 0, {"actor": "player"})
        self.assertEqual(TiledObject(1, "entrance", "spawn", 8, 8, 0, 0,
                                     {"actor": "player"}).properties["actor"], "player")

    def test_direct_exit_description_requires_destination_and_rectangle(self):
        for props in ({}, {"room": None}, {"room": "two words"},
                      {"room": "garden", "spawn": 1}, {"room": "garden", "spawn": "bad name"}):
            with self.subTest(properties=props), self.assertRaises(ValueError):
                TiledObject(1, "door", "exit", 8, 8, 8, 8, props)
        with self.assertRaisesRegex(ValueError, "nonempty rectangle"):
            TiledObject(1, "door", "exit", 8, 8, 0, 0, {"room": "garden"})

    def test_direct_description_rejects_nonfinite_properties(self):
        for value in (float("inf"), -float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite"):
                TiledObject(1, "player", "player", 0, 1, 0, 0, {"speed": value})

    def test_direct_map_rejects_objects_outside_its_dimensions(self):
        for x, y, width, height in ((8, 0, 0, 0), (0, 8, 0, 0), (7, 1, 2, 2)):
            obj = TiledObject(1, "player", "player", x, y, width, height, {})
            with self.subTest(object=obj), self.assertRaisesRegex(ValueError, "map dimensions"):
                TiledMap("screen.tmj", [[None]], [[False]], [[0]], [obj])


@unittest.skipIf(Image is None, "requires optional Pillow image importer")
class TiledTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="py3nes-tiled-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        image = Image.new("P", (16, 8))
        image.putpalette([0, 0, 0, 255, 255, 255, 0, 255, 0, 0, 0, 255] + [0] * 756)
        image.putdata([1 if x < 8 and y == 0 else 2 if x == 15 else 0
                       for y in range(8) for x in range(16)])
        image.save(self.path / "tiles.png")
        self.tileset = dict(firstgid=1, name="tiles", image="tiles.png", tilewidth=8,
                            tileheight=8, columns=2, tilecount=2, imagewidth=16, imageheight=8)
        self.data = dict(type="map", orientation="orthogonal", infinite=False, width=4,
                         height=4, tilewidth=8, tileheight=8, tilesets=[self.tileset],
                         layers=[dict(type="tilelayer", name="background", width=4,
                                      height=4, data=[1, 0, 2, 0] + [0] * 12)])

    def load(self, data=None, **kwargs):
        path = self.path / "room.tmj"
        path.write_text(json.dumps(self.data if data is None else data))
        return load_tiled(path, **kwargs)

    def objects(self, *objects):
        self.data["layers"].append(dict(type="objectgroup", name="objects", objects=list(objects)))

    @staticmethod
    def actor(room, obj):
        return room.actor(tile=1, name=obj.name, x=obj.x, y=obj.y, gravity=0)

    def test_background_collision_palette_and_no_loading_side_effects(self):
        self.data["layers"][0]["properties"] = properties(palette=2)
        self.data["layers"].append(dict(type="tilelayer", name="collision", visible=False,
                                         width=4, height=4, data=[0] * 12 + [1] * 4))
        game = Game()
        room = game.room("hall")
        before = game.chr_data()
        description = self.load()
        self.assertEqual(game.chr_data(), before)
        self.assertEqual((description.width, description.height), (4, 4))
        self.assertIsNone(description.tiles[0][1])
        description.apply(room)
        self.assertEqual(room.collision_data()[96:100], bytes([1] * 4))
        self.assertEqual(room.nametable()[96:100], bytes(4))
        self.assertEqual(room.nametable()[960] & 0x0F, 0b1010)
        self.assertEqual(game._tiles[room.nametable()[0]], description.tiles[0][0])

    def test_external_tileset_paths_resolve_against_the_tileset_file(self):
        assets = self.path / "assets"
        assets.mkdir()
        (self.path / "tiles.png").rename(assets / "tiles.png")
        external = dict(self.tileset)
        del external["firstgid"]
        (assets / "world.tsj").write_text(json.dumps(external))
        self.data["tilesets"] = [{"firstgid": 10, "source": "assets/world.tsj"}]
        self.data["layers"][0]["data"] = [10, 0, 11, 0] + [0] * 12
        description = self.load()
        self.assertEqual(description.tiles[0][0].pixels[0], (1,) * 8)
        self.assertEqual(description.tiles[0][2].pixels[7][-1], 2)

    def test_multiple_tilesets_and_horizontal_vertical_flips(self):
        second = dict(self.tileset, firstgid=5)
        self.data["tilesets"].append(second)
        self.data["layers"][0]["data"] = [0x80000002, 0x40000005, 0xC0000006, 0] + [0] * 12
        description = self.load()
        self.assertEqual(description.tiles[0][0].pixels[0][0], 2)
        self.assertEqual(description.tiles[0][1].pixels[7], (1,) * 8)
        self.assertEqual(description.tiles[0][2].pixels[7][0], 2)

    def test_objects_are_immutable_and_spawns_resolve_after_actor_factories(self):
        self.objects(object_(2, "door", "spawn", 8, 8, 0, 0, actor="player"),
                     object_(3, "to_garden", "exit", 24, 16, 8, 16, room="garden", spawn="gate"),
                     object_(1, speed=2))
        description = self.load()
        with self.assertRaises(TypeError):
            description.objects[2].properties["speed"] = 3
        with self.assertRaises(FrozenInstanceError):
            description.objects[2].x = 1
        game = Game()
        room = game.room("hall")
        result = description.apply(room, actor_factories={"player": self.actor})
        self.assertIs(result.actors["player"], room.actors[0])
        self.assertIs(result.spawns["door"].actor, room.actors[0])
        self.assertEqual(result.exits["to_garden"].properties["room"], "garden")
        self.assertEqual(room.spawns["door"].x, 8)
        self.assertFalse(room.events)
        with self.assertRaises(TypeError):
            result.actors["other"] = room.actors[0]

    def test_spawn_can_reference_actor_already_built_in_the_room(self):
        self.objects(object_(2, "entrance", "spawn", 8, 8, 0, 0, actor="player"))
        game = Game()
        room = game.room("hall")
        player = room.actor(tile=1, name="player")
        result = self.load().apply(room)
        self.assertIs(result.spawns["entrance"].actor, player)
        self.assertEqual(dict(result.actors), {})

    def test_unknown_factories_or_actor_references_fail_without_mutation(self):
        self.objects(object_(), object_(2, "door", "spawn", 8, 8, 0, 0, actor="player"))
        description = self.load()
        game = Game()
        room = game.room("hall")
        before = (game.chr_data(), room.maps, room.actors, room.variables)
        with self.assertRaisesRegex(ValueError, "factory"):
            description.apply(room)
        self.assertEqual((game.chr_data(), room.maps, room.actors, room.variables), before)
        self.data["layers"][-1]["objects"][1]["properties"] = properties(actor="missing")
        with self.assertRaisesRegex(ValueError, "unknown actor"):
            self.load().apply(room, actor_factories={"player": self.actor})
        self.assertEqual((game.chr_data(), room.maps, room.actors, room.variables), before)

    def test_factory_failure_rolls_back_shared_tiles_all_rooms_and_global_state(self):
        self.objects(object_())
        description = self.load()
        game = Game()
        first, other = game.room("first"), game.room("other")
        old_tiles = game._tiles
        before = game.chr_data()

        def broken(room, obj):
            game.byte("side_effect")
            other.flag("local")
            game.room("unexpected")
            room.actor(tile=Tile.from_rows(["33333333"] * 8), name=obj.name, x=obj.x, y=obj.y)
            raise RuntimeError("factory failed")

        with self.assertRaisesRegex(RuntimeError, "factory failed"):
            description.apply(first, actor_factories={"player": broken})
        self.assertEqual(game.chr_data(), before)
        self.assertIs(game._tiles, old_tiles)
        self.assertIs(other._tiles, old_tiles)
        self.assertEqual(game.rooms, (first, other))
        self.assertFalse(game.variables or other.variables or first.actors or first.maps)
        self.assertEqual(first._oam_used, 0)
        self.assertEqual(other._user_names, set())

    def test_bad_factory_result_and_invalid_spawn_roll_back(self):
        self.data.update(width=32, height=30)
        self.data["layers"][0].update(width=32, height=30, data=[1] * 960)
        self.objects(object_(), object_(2, "door", "spawn", 255, 16, 0, 0, actor="player"))
        game = Game()
        room = game.room("hall")
        description = self.load()
        with self.assertRaisesRegex(ValueError, "return an actor"):
            description.apply(room, actor_factories={"player": lambda room, obj: None})
        with self.assertRaisesRegex(ValueError, "object's name"):
            description.apply(room, actor_factories={"player": lambda room, obj: room.actor(tile=1)})
        with self.assertRaisesRegex(ValueError, "spawn x"):
            description.apply(room, actor_factories={"player": self.actor})
        self.assertFalse(room.actors or room.maps)

    def test_direct_description_copies_mutable_input_grids(self):
        tiles, solid, palettes, objects = [[None]], [[False]], [[0]], []
        description = TiledMap("room.tmj", tiles, solid, palettes, objects)
        tiles[0][0] = Tile.from_rows(["11111111"] * 8)
        solid[0][0] = True
        palettes[0][0] = 3
        objects.append(object_())
        self.assertEqual(description.tiles, ((None,),))
        self.assertEqual(description.solid, ((False,),))
        self.assertEqual(description.palettes, ((0,),))
        self.assertEqual(description.objects, ())

    def test_pattern_table_overflow_is_atomic(self):
        game = Game()
        room = game.room("hall")
        for number in range(1, 1000):
            tile = Tile(tuple(tuple(((number >> x) & 1) + (2 if y == 7 else 0)
                                    for x in range(8)) for y in range(8)))
            game.tile(tile)
            if len(game._tiles) == 256:
                break
        self.assertEqual(len(game._tiles), 256)
        before = game.chr_data()
        with self.assertRaisesRegex(ValueError, "pattern table is full"):
            self.load().apply(room)
        self.assertEqual(game.chr_data(), before)
        self.assertFalse(room.maps)

    def test_exits_validate_all_destinations_before_registering_rules(self):
        self.objects(object_(), object_(2, "first", "exit", 0, 8, 8, 16, room="garden", spawn="door"),
                     object_(3, "second", "exit", 24, 8, 8, 16, room="unknown"))
        game = Game()
        hall, garden = game.room("hall"), game.room("garden")
        target = garden.actor(tile=1)
        garden.spawn("door", target, x=8, y=8)
        result = self.load().apply(hall, actor_factories={"player": self.actor})
        with self.assertRaisesRegex(ValueError, "not supplied"):
            result.bind_exits(result.actors["player"], {"garden": garden})
        self.assertFalse(hall.events)
        result.bind_exits(result.actors["player"], {"garden": garden, "unknown": garden})
        self.assertEqual(len(hall.events), 2)

    def test_tile_palette_overrides_layer_and_tileset_defaults(self):
        self.tileset["properties"] = properties(palette=1)
        self.tileset["tiles"] = [{"id": 1, "properties": properties(palette=3)}]
        self.data["layers"][0]["properties"] = properties(palette=2)
        description = self.load()
        self.assertEqual(description.palettes[0], (2, 2, 3, 3))
        self.data["layers"][0]["data"][1] = 2
        with self.assertRaisesRegex(ValueError, "palette conflict"):
            self.load()

    def test_hidden_editor_layers_and_objects_are_skipped(self):
        self.data["layers"].append({"type": "imagelayer", "visible": False})
        self.objects(dict(id=9, visible=False, type="unsupported"))
        self.assertFalse(self.load().objects)

    def test_json_float_overflow_is_rejected_before_reaching_a_factory(self):
        self.objects(object_(speed=1.0))
        path = self.path / "overflow.tmj"
        # JSON's exponent syntax can overflow without using its rejected NaN/Infinity tokens.
        path.write_text(json.dumps(self.data).replace('"value": 1.0', '"value": 1e400'))
        with self.assertRaisesRegex(ValueError, "finite"):
            load_tiled(path)

    def test_later_tile_layers_replace_only_nonempty_cells(self):
        self.data["layers"].append(dict(type="tilelayer", name="detail", width=4,
                                         height=4, data=[0, 2] + [0] * 14))
        description = self.load()
        self.assertIsNotNone(description.tiles[0][0])
        self.assertEqual(description.tiles[0][1], description.tiles[0][2])

    def test_unsupported_map_and_layer_formats_are_rejected(self):
        base = deepcopy(self.data)
        variants = [dict(infinite=True), dict(orientation="isometric"), dict(tilewidth=16),
                    dict(width=33), dict(height=31)]
        for changes in variants:
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                self.load(base | changes)
        for changes in [dict(type="group"), dict(offsetx=8), dict(parallaxx=0.5),
                        dict(opacity=0.5), dict(tintcolor="#ffffff"), dict(width=3),
                        dict(data="AAAA", encoding="base64"), dict(data=[1]),
                        dict(data=[True] + [0] * 15), dict(data=[0x20000001] + [0] * 15),
                        dict(data=[99] + [0] * 15)]:
            data = deepcopy(base)
            data["layers"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                self.load(data)

    def test_unsupported_tilesets_and_overlapping_gid_ranges_are_rejected(self):
        base = deepcopy(self.data)
        for changes in [dict(spacing=1), dict(margin=1), dict(columns=3), dict(imagewidth=32),
                        dict(tilewidth=16), dict(tileoffset={"x": 1}),
                        dict(transparentcolor="#000000"), dict(tiles=[{"id": 0, "animation": []}])]:
            data = deepcopy(base)
            data["tilesets"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.load(data)
        self.data["tilesets"].append(dict(self.tileset, firstgid=2))
        with self.assertRaisesRegex(ValueError, "overlap"):
            self.load()

    def test_object_geometry_ids_names_and_properties_are_validated(self):
        base = deepcopy(self.data)
        cases = [dict(gid=1), dict(rotation=90), dict(ellipse=True), dict(x=1.5),
                 dict(x=32), dict(y=32), dict(width=17), dict(name="two words"),
                 dict(type=""), dict(properties=[{"name": "target", "type": "object", "value": 2}])]
        for changes in cases:
            data = deepcopy(base)
            data["layers"].append(dict(type="objectgroup", objects=[object_() | changes]))
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                self.load(data)
        for second in (object_(1, "other"), object_(2, "player")):
            data = deepcopy(base)
            data["layers"].append(dict(type="objectgroup", objects=[object_(), second]))
            with self.assertRaisesRegex(ValueError, "unique"):
                self.load(data)

    @unittest.skipUnless(HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME)
    def test_imported_exit_runs_on_real_6502_and_arrives_at_named_spawn(self):
        self.objects(object_(), object_(2, "to_garden", "exit", 16, 16, 16, 16,
                                       room="garden", spawn="door"))
        game = Game()
        hall, garden = game.room("hall"), game.room("garden")
        player = garden.actor(tile=2)
        garden.spawn("door", player, x=104, y=80)
        result = self.load().apply(hall, actor_factories={"player": self.actor})
        result.bind_exits(result.actors["player"], {"garden": garden})
        with RuntimeHarness(game) as run:
            self.assertEqual(run.read("rt_room"), hall.index)
            run.frame(Button.UP)
            self.assertEqual(run.read("rt_room"), garden.index)
            self.assertEqual(run.variable(player.x.name), 104)
            self.assertEqual(run.variable(player.y.name), 80)

    @unittest.skipUnless(HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME)
    def test_region_overlap_uses_hitbox_and_handles_right_edge_without_byte_wrap(self):
        game = Game()
        room = game.room("hall")
        player = room.actor(tile=1, name="player", x=240, y=80, hitbox=Hitbox(8, 8, 8, 0))
        entered = game.flag("entered")
        edge = TiledObject(1, "edge", "exit", 255, 80, 1, 8, {"room": "hall"})
        room.every_frame(If(edge.contains(player), Set(entered, True)))
        with RuntimeHarness(game) as run:
            run.frame()
            self.assertEqual(run.variable(entered.name), 1)


if __name__ == "__main__":
    unittest.main()
