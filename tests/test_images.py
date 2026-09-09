"""PNG decoding checks against known pixels, including transparent palette entries."""

from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    from PIL import Image
except ImportError:
    Image = None

from py3nes.assets import Tile
from py3nes import Game
from py3nes.images import TileSheet, load_png


class TileSheetTests(unittest.TestCase):
    def test_copies_grid_and_regions_preserve_tile_order(self):
        tiles = [Tile.from_rows([str(value) * 8] * 8) for value in range(4)]
        rows = [[tiles[0], tiles[1]], [tiles[2], tiles[3]]]
        sheet = TileSheet(rows)
        rows[0][0] = tiles[3]
        self.assertEqual((sheet.width, sheet.height), (2, 2))
        self.assertIs(sheet.tile(0, 0), tiles[0])
        self.assertEqual(sheet.region(1, 0, 1, 2), ((tiles[1],), (tiles[3],)))
        with self.assertRaises(FrozenInstanceError):
            sheet.tiles = ()

    def test_rejects_nonrectangular_grids_and_nontiles(self):
        tile = Tile.from_rows(["0" * 8] * 8)
        for rows in ([], [[]], [[tile], [tile, tile]]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                TileSheet(rows)
        with self.assertRaises(TypeError):
            TileSheet([[1]])

    def test_rejects_selection_outside_sheet(self):
        tile = Tile.from_rows(["0" * 8] * 8)
        sheet = TileSheet([[tile, tile], [tile, tile]])
        for column, row in ((-1, 0), (0, -1), (2, 0), (0, 2)):
            with self.subTest(column=column, row=row), self.assertRaises(ValueError):
                sheet.tile(column, row)
        for arguments in ((0, 0, 0, 1), (0, 0, 1, 0), (1, 0, 2, 1), (0, 1, 1, 2)):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                sheet.region(*arguments)
        with self.assertRaises(TypeError):
            sheet.tile(True, 0)

    def test_missing_pillow_error_explains_optional_extra(self):
        with patch.dict(sys.modules, {"PIL": None}), self.assertRaisesRegex(ImportError, r"py3nes\[images\]"):
            load_png("unused.png")


@unittest.skipIf(Image is None, 'PNG tests require pip install "py3nes[test,images]"')
class PNGTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "tiles.png"

    def save(self, mode="P", size=(8, 8), value=0, *, transparency=None):
        image = Image.new(mode, size, value)
        if mode == "P":
            image.putpalette([0, 0, 0, 255, 255, 255, 255, 0, 0, 0, 255, 0] + [0] * (768 - 12))
        image.save(self.path, transparency=transparency) if transparency is not None else image.save(self.path)
        return image

    def test_indexed_pixels_split_into_tiles_and_encode_exact_bitplanes(self):
        image = self.save(size=(16, 16))
        for y in range(16):
            for x in range(16):
                image.putpixel((x, y), (x // 8) + 2 * (y // 8))
        image.save(self.path)
        sheet = load_png(self.path)
        self.assertEqual((sheet.width, sheet.height), (2, 2))
        self.assertEqual(sheet.tile(0, 0).to_chr(), bytes(16))
        self.assertEqual(sheet.tile(1, 0).to_chr(), bytes([255] * 8 + [0] * 8))
        self.assertEqual(sheet.tile(0, 1).to_chr(), bytes([0] * 8 + [255] * 8))
        self.assertEqual(sheet.tile(1, 1).to_chr(), bytes([255] * 16))

    def test_indexed_art_preserves_indices_even_when_colors_are_identical(self):
        image = self.save(value=3)
        image.putpalette([0] * 768)
        image.save(self.path)
        self.assertEqual(load_png(self.path).tile(0, 0).pixels, ((3,) * 8,) * 8)

    def test_imported_tiles_register_and_form_metasprites_with_shared_chr_data(self):
        self.save(size=(16, 16), value=2)
        sheet = load_png(self.path)
        game = Game()
        tile_index = game.tile(sheet.tile(0, 0))
        graphic = game.metasprite(sheet.region(0, 0, 2, 2), palette=3)
        self.assertEqual([part.tile for part in graphic.parts], [tile_index] * 4)
        self.assertEqual([(part.dx, part.dy) for part in graphic.parts], [(0, 0), (8, 0), (0, 8), (8, 8)])
        self.assertEqual([part.palette for part in graphic.parts], [3] * 4)
        self.assertEqual(game.chr_data()[tile_index * 16:tile_index * 16 + 16], bytes([0] * 8 + [255] * 8))

    def test_transparent_palette_entry_outside_first_four_maps_to_zero(self):
        self.save(value=7, transparency=7)
        self.assertEqual(load_png(self.path).tile(0, 0).to_chr(), bytes(16))

    def test_per_entry_alpha_table_and_partial_alpha_validation(self):
        self.save(value=2, transparency=bytes([255, 255, 0, 255]))
        self.assertEqual(load_png(self.path).tile(0, 0).to_chr(), bytes(16))
        self.save(value=2, transparency=bytes([255, 255, 128, 255]))
        with self.assertRaisesRegex(ValueError, "partial transparency"):
            load_png(self.path)

    def test_opaque_high_palette_index_requires_mapping(self):
        self.save(value=4)
        with self.assertRaisesRegex(ValueError, r"pixel \(0, 0\).*palette index 4"):
            load_png(self.path)
        self.assertEqual(load_png(self.path, colors=["#000000"]).tile(0, 0).to_chr(), bytes(16))

    def test_rgb_mapping_uses_declared_order_instead_of_sorted_colors(self):
        image = self.save("RGB", value=(255, 0, 0))
        image.putpixel((0, 0), (255, 255, 255))
        image.putpixel((1, 0), (0, 255, 0))
        image.putpixel((2, 0), (0, 0, 0))
        image.save(self.path)
        tile = load_png(self.path, colors=["#000000", (255, 255, 255), "#00ff00", (255, 0, 0, 255)]).tile(0, 0)
        self.assertEqual(tile.pixels[0], (1, 2, 0, 3, 3, 3, 3, 3))
        self.assertEqual(tile.pixels[1], (3,) * 8)

    def test_nonindexed_images_require_explicit_mapping(self):
        for mode, value in (("RGB", (0, 0, 0)), ("RGBA", (0, 0, 0, 0)), ("L", 0)):
            self.save(mode, value=value)
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "explicit colors"):
                load_png(self.path)

    def test_fully_transparent_pixels_ignore_rgb_and_map_to_zero(self):
        image = self.save("RGBA", value=(12, 42, 99, 0))
        image.putpixel((1, 0), (255, 255, 255, 255))
        image.save(self.path)
        tile = load_png(self.path, colors=["#00000000", "#FFFFFFFF"]).tile(0, 0)
        self.assertEqual(tile.pixels[0], (0, 1, 0, 0, 0, 0, 0, 0))

    def test_rgb_transparency_chunk_is_honored(self):
        self.save("RGB", value=(255, 0, 255), transparency=(255, 0, 255))
        self.assertEqual(load_png(self.path, colors=["#000000"]).tile(0, 0).to_chr(), bytes(16))

    def test_partial_alpha_and_unmapped_pixels_report_coordinate(self):
        self.save("RGBA", value=(0, 0, 0, 127))
        with self.assertRaisesRegex(ValueError, r"pixel \(0, 0\).*partial transparency"):
            load_png(self.path, colors=["#000000"])
        self.save("RGB", value=(1, 0, 0))
        with self.assertRaisesRegex(ValueError, r"pixel \(0, 0\).*absent from colors"):
            load_png(self.path, colors=["#000000"])

    def test_rejects_bad_dimensions_and_wrong_format(self):
        for size in ((7, 8), (8, 9), (16, 15)):
            self.save(size=size)
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "multiples of 8"):
                load_png(self.path)
        Image.new("RGB", (8, 8)).save(self.path, format="BMP")
        with self.assertRaisesRegex(ValueError, "requires a PNG"):
            load_png(self.path)

    def test_rejects_animated_png_instead_of_silently_importing_one_frame(self):
        first = Image.new("RGBA", (8, 8), (0, 0, 0, 255))
        second = Image.new("RGBA", (8, 8), (255, 255, 255, 255))
        first.save(self.path, save_all=True, append_images=[second], duration=100, loop=0)
        with self.assertRaisesRegex(ValueError, "animated PNG"):
            load_png(self.path, colors=["#000000", "#FFFFFF"])

    def test_rejects_ambiguous_and_invalid_color_declarations(self):
        self.save()
        bad_values = ([], ["#000000"] * 5, ["#000000", (0, 0, 0)],
                      ["red"], ["#ABC"], [(0, 0)], [(0, 0, 256)],
                      [(0, 0, 0, 127)], ["#000000", "#00000000"])
        for colors in bad_values:
            with self.subTest(colors=colors), self.assertRaises(ValueError):
                load_png(self.path, colors=colors)
        for colors in ("#000000", [True], [(True, 0, 0)]):
            with self.subTest(colors=colors), self.assertRaises(TypeError):
                load_png(self.path, colors=colors)


if __name__ == "__main__":
    unittest.main()
