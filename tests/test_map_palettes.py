"""Background palette metadata stays immutable and matches map geometry."""

import unittest

from py3nes import Game
from py3nes.model import Map


class MapPaletteTests(unittest.TestCase):
    def test_legacy_positional_collision_argument_and_unspecified_palette(self):
        patch = Map([[1]], 2, 4, [[True]])
        self.assertEqual(patch.solid, ((True,),))
        self.assertIsNone(patch.palettes)

    def test_palette_grid_is_copied_without_changing_tile_or_collision_values(self):
        palettes = [[0, 1], [2, 3]]
        patch = Map([[1, 2], [3, 4]], palettes=palettes)
        palettes[0][0] = 3
        self.assertEqual(patch.palettes, ((0, 1), (2, 3)))
        self.assertEqual(patch.tiles, ((1, 2), (3, 4)))
        self.assertIsNone(patch.solid)

    def test_rejects_palette_grid_with_wrong_shape(self):
        for palettes in ([], [[]], [[0]], [[0, 0]], [[0, 0], [0]], [[0, 0], [0, 0], [0, 0]]):
            with self.subTest(palettes=palettes), self.assertRaisesRegex(ValueError, "palette grid must match"):
                Map([[0, 0], [0, 0]], palettes=palettes)

    def test_rejects_palette_values_outside_hardware_range(self):
        for palette in (-1, 4, 256):
            with self.subTest(palette=palette), self.assertRaises(ValueError):
                Map([[0]], palettes=[[palette]])
        for palette in (True, 1.0, "1", None):
            with self.subTest(palette=palette), self.assertRaises(TypeError):
                Map([[0]], palettes=[[palette]])


class BackgroundPaletteTests(unittest.TestCase):
    def test_attribute_byte_packs_four_hardware_quadrants(self):
        game = Game()
        game.map([[1] * 4] * 4,
                 palette=[[0, 0, 1, 1], [0, 0, 1, 1], [2, 2, 3, 3], [2, 2, 3, 3]])
        self.assertEqual(game.nametable()[960], 0b11100100)
        self.assertEqual(game.nametable()[961:], bytes(63))

    def test_bottom_screen_row_only_uses_top_attribute_quadrants(self):
        game = Game()
        game.map([[1] * 4] * 2, column=28, row=28,
                 palette=[[1, 1, 3, 3], [1, 1, 3, 3]])
        self.assertEqual(game.nametable()[1023], 0b00001101)
        self.assertEqual(game.nametable()[960:1023], bytes(63))

    def test_palette_conflicts_across_patches_report_aligned_screen_region(self):
        game = Game()
        game.map([[1]], column=5, row=3, palette=1)
        game.map([[2]], column=4, row=2, palette=2)
        with self.assertRaisesRegex(ValueError, r"16x16 region at tile \(4, 2\)"):
            game.nametable()

    def test_whole_quadrant_overlay_replaces_earlier_palette_assignments(self):
        game = Game()
        # Only final visible assignments matter: the first layer is covered.
        game.map([[1, 1], [1, 1]], palette=[[0, 1], [2, 3]])
        game.map([[2, 2], [2, 2]], palette=3)
        self.assertEqual(game.nametable()[960], 3)
        self.assertEqual(game.nametable()[:2], bytes([2, 2]))

    def test_unspecified_palette_inherits_surrounding_attribute_selection(self):
        game = Game()
        game.map([[1, 1], [1, 1]], palette=2)
        game.text("A", column=1, row=1)
        self.assertEqual(game.nametable()[960], 2)
        self.assertEqual(Game().nametable()[960:], bytes(64))

    def test_invalid_palette_argument_does_not_add_a_map(self):
        game = Game()
        for palette in (True, -1, 4, [[0, 0]], [[1.5]]):
            with self.subTest(palette=palette), self.assertRaises((TypeError, ValueError)):
                game.map([[1]], palette=palette)
        self.assertEqual(game.maps, ())

    def test_rooms_choose_palettes_independently(self):
        game = Game()
        first, second = game.room("first"), game.room("second")
        first.map([[1, 1], [1, 1]], palette=1)
        second.map([[1, 1], [1, 1]], palette=3)
        self.assertEqual(first.nametable()[960], 1)
        self.assertEqual(second.nametable()[960], 3)


if __name__ == "__main__":
    unittest.main()
