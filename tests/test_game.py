"""Public build-time API semantics and resource accounting."""

import unittest

from py3nes import (Button, CHAR_TO_TILE, DEFAULT_PALETTE, Game, Map,
                    Move, SetPosition, SetTile, Sprite, Tile, Trigger)
from py3nes.assets import FONT_TILES, encode_text


def custom_tile(number):
    """Distinct two-color assets that cannot collide with the monochrome font."""
    return Tile.from_rows([[2] + [0] * 7,
                           [(number >> bit) & 1 for bit in range(7, -1, -1)]]
                          + [[0] * 8 for _ in range(6)])


def screen_row(game, row, column, width):
    start = row * 32 + column
    return tuple(game.nametable()[start:start + width])


class GameBackgroundTests(unittest.TestCase):
    def test_layers_overwrite_in_registration_order_including_blank_tiles(self):
        game = Game()
        first = game.map([[1, 2], [3, 4]], column=2, row=3)
        game.text("X", column=2, row=3)
        last = game.map([[0]], column=3, row=4)
        self.assertEqual(screen_row(game, 3, 2, 2), (CHAR_TO_TILE["X"], 2))
        self.assertEqual(screen_row(game, 4, 2, 2), (3, 0))
        self.assertIs(game.maps[0], first)
        self.assertIs(game.maps[-1], last)
        self.assertEqual(len(game.nametable()), 1024)
        self.assertEqual(game.nametable()[960:], bytes(64))

    def test_map_object_position_can_be_retained_or_overridden_with_zero(self):
        game = Game()
        original = Map([[1]], column=3, row=4)
        self.assertEqual(game.map(original), original)
        moved = game.map(original, column=0, row=0)
        self.assertEqual((moved.column, moved.row), (0, 0))
        self.assertEqual((original.column, original.row), (3, 4))
        self.assertEqual(game.nametable()[0], 1)
        self.assertEqual(game.nametable()[4 * 32 + 3], 1)

    def test_map_rejects_unregistered_tiles_without_adding_a_layer(self):
        game = Game()
        with self.assertRaises(ValueError):
            game.map([[0, 64]])
        self.assertEqual(game.maps, ())
        self.assertEqual(game.nametable(), bytes(1024))

    def test_text_uppercases_newlines_and_pads_shorter_rows(self):
        game = Game()
        box = game.text("ab\nc\n", column=2, row=4)
        self.assertEqual((box.text, box.width, box.height, box.border), ("AB\nC\n", 2, 3, False))
        self.assertEqual(screen_row(game, 4, 2, 2), encode_text("AB"))
        self.assertEqual(screen_row(game, 5, 2, 2), (CHAR_TO_TILE["C"], 0))
        self.assertEqual(screen_row(game, 6, 2, 2), (0, 0))
        self.assertEqual(game.text_boxes, (box,))

    def test_text_empty_string_is_one_blank_cell(self):
        game = Game()
        game.map([[1]], column=31, row=29)
        box = game.text("", column=31, row=29)
        self.assertEqual((box.width, box.height), (1, 1))
        self.assertEqual(game.nametable()[959], 0)

    def test_invalid_text_and_overflow_leave_background_unchanged(self):
        cases = [dict(text="A\tB"), dict(text="caf\u00e9"),
                 dict(text="AB", column=31), dict(text="A\nB", row=29),
                 dict(text="A" * 33), dict(text="\n" * 30)]
        for kwargs in cases:
            game = Game()
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                game.text(**kwargs)
            self.assertEqual(game.maps, ())
            self.assertEqual(game.text_boxes, ())
        with self.assertRaises(TypeError):
            Game().text(b"HELLO")


class GameTextBoxTests(unittest.TestCase):
    def test_word_wrapping_border_geometry_and_deduplication(self):
        game = Game()
        box = game.text_box("hello world", column=2, row=3, width=7)
        self.assertEqual((box.width, box.height, box.border), (7, 4, True))
        grid = game.maps[-1].tiles
        self.assertEqual(grid[1][1:-1], encode_text("HELLO"))
        self.assertEqual(grid[2][1:-1], encode_text("WORLD"))
        self.assertEqual(len(set(grid[0][1:-1] + grid[-1][1:-1])), 1)
        self.assertEqual(len({grid[1][0], grid[1][-1], grid[2][0], grid[2][-1]}), 1)
        border_ids = {grid[0][0], grid[0][-1], grid[-1][0], grid[-1][-1],
                      grid[0][1], grid[1][0]}
        self.assertEqual(len(border_ids), 6)
        self.assertTrue(all(index >= 64 for index in border_ids))
        chr_before = game.chr_data()
        game.text_box("NEXT", column=15, row=3, width=7)
        self.assertEqual(game.chr_data(), chr_before)

    def test_long_words_wrap_and_explicit_empty_lines_are_preserved(self):
        game = Game()
        box = game.text_box("abcdefgh\n\nz", column=0, row=0, width=3, border=False)
        self.assertEqual(box.height, 5)
        self.assertEqual(game.maps[-1].tiles,
                         (encode_text("ABC"), encode_text("DEF"), encode_text("GH "),
                          (0, 0, 0), encode_text("Z  ")))

    def test_explicit_height_pads_unused_interior_rows(self):
        game = Game()
        box = game.text_box("A", column=0, row=0, width=5, height=5)
        self.assertEqual(box.height, 5)
        grid = game.maps[-1].tiles
        self.assertEqual(grid[1][1:-1], encode_text("A  "))
        self.assertEqual(grid[2][1:-1], (0, 0, 0))
        self.assertEqual(grid[3][1:-1], (0, 0, 0))

    def test_content_overflow_and_unsupported_whitespace_do_not_mutate_game(self):
        for text, height in (("ONE TWO", 3), ("A\tB", 5), ("A\rB", 5)):
            game = Game()
            chr_before = game.chr_data()
            with self.subTest(text=text), self.assertRaises(ValueError):
                game.text_box(text, column=0, row=0, width=5, height=height)
            self.assertEqual(game.chr_data(), chr_before)
            self.assertEqual(game.maps, ())
            self.assertEqual(game.text_boxes, ())

    def test_border_capacity_is_checked_before_registering_any_border_tiles(self):
        game = Game()
        for number in range(187):
            game.tile(custom_tile(number))
        chr_before = game.chr_data()
        with self.assertRaises(ValueError):
            game.text_box("A", column=0, row=0, width=3)
        self.assertEqual(game.chr_data(), chr_before)
        self.assertEqual(game.maps, ())
        self.assertEqual(game.text_boxes, ())
        self.assertEqual(game.tile(custom_tile(187)), 251)

    def test_border_can_use_exactly_the_remaining_six_slots(self):
        game = Game()
        for number in range(186):
            game.tile(custom_tile(number))
        game.text_box("A", column=0, row=0, width=3)
        self.assertEqual(len(game.maps), 1)
        with self.assertRaises(ValueError):
            game.tile(custom_tile(186))
        game.text_box("B", column=3, row=0, width=3)
        self.assertEqual(len(game.maps), 2)


class GameGraphicsTests(unittest.TestCase):
    def test_tile_deduplication_includes_font_and_normalized_input(self):
        game = Game()
        self.assertEqual(game.tile(["........"] * 8), 0)
        self.assertEqual(game.tile(FONT_TILES[CHAR_TO_TILE["A"]]), CHAR_TO_TILE["A"])
        tile = custom_tile(7)
        self.assertEqual(game.tile(tile), 64)
        self.assertEqual(game.tile(tile.pixels), 64)
        self.assertEqual(game.tile(custom_tile(8)), 65)

    def test_pattern_capacity_and_existing_tile_lookup_at_capacity(self):
        game = Game()
        for number in range(192):
            self.assertEqual(game.tile(custom_tile(number)), 64 + number)
        chr_before = game.chr_data()
        with self.assertRaises(ValueError):
            game.tile(custom_tile(192))
        self.assertEqual(game.chr_data(), chr_before)
        self.assertEqual(game.tile(custom_tile(191)), 255)
        self.assertEqual(game.tile(FONT_TILES[0]), 0)

    def test_chr_rom_has_duplicate_padded_pattern_tables(self):
        game = Game()
        tile = custom_tile(7)
        index = game.tile(tile)
        data = game.chr_data()
        self.assertEqual(len(data), 8192)
        self.assertEqual(data[:4096], data[4096:])
        self.assertEqual(data[index * 16:(index + 1) * 16], tile.to_chr())
        self.assertEqual(data[(index + 1) * 16:4096], bytes(4096 - (index + 1) * 16))

    def test_sprite_limit_and_tile_validation(self):
        game = Game()
        for index in range(64):
            self.assertEqual(game.sprite(tile=0).index, index)
        chr_before = game.chr_data()
        with self.assertRaises(ValueError):
            game.sprite(tile=custom_tile(0))
        self.assertEqual(len(game.sprites), 64)
        self.assertEqual(game.chr_data(), chr_before)
        with self.assertRaises(ValueError):
            Game().sprite(tile=64)

    def test_invalid_sprite_does_not_consume_a_new_tile(self):
        game = Game()
        chr_before = game.chr_data()
        rejected_tile = custom_tile(0)
        with self.assertRaises(ValueError):
            game.sprite(tile=rejected_tile, x=-1)
        self.assertEqual(game.sprites, ())
        self.assertEqual(game.chr_data(), chr_before)
        self.assertEqual(game.tile(custom_tile(1)), 64)

    def test_palette_is_copied_and_validated(self):
        source = list(DEFAULT_PALETTE)
        game = Game(palette=source)
        source[1] = 0x21
        self.assertEqual(game.palette, DEFAULT_PALETTE)
        for palette in (DEFAULT_PALETTE[:-1], DEFAULT_PALETTE + b"\x0f"):
            with self.subTest(palette=palette), self.assertRaises(ValueError):
                Game(palette=palette)
        for value, error in ((-1, ValueError), (64, ValueError), (True, TypeError), (1.0, TypeError)):
            invalid = list(DEFAULT_PALETTE)
            invalid[1] = value
            with self.subTest(value=value), self.assertRaises(error):
                Game(palette=invalid)
        for mirror in (16, 20, 24, 28):
            invalid = list(DEFAULT_PALETTE)
            invalid[mirror] = 0
            with self.subTest(mirror=mirror), self.assertRaises(ValueError):
                Game(palette=invalid)

    def test_unsupported_hardware_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            Game(region="PAL")
        with self.assertRaises(ValueError):
            Game(mapper="MMC1")


class GameEventTests(unittest.TestCase):
    def test_event_and_action_order_are_preserved(self):
        game = Game()
        sprite = game.sprite(tile=0)
        move = Move(sprite, dx=1)
        position = SetPosition(sprite, 80, 90)
        held = game.bind_held(Button.RIGHT, move, position)
        pressed = game.bind_pressed(Button.A, SetTile(sprite, 1))
        frame = game.every_frame(Move(sprite, dy=1))
        self.assertEqual(game.events, (held, pressed, frame))
        self.assertEqual(held.actions, (move, position))
        self.assertEqual((held.trigger, pressed.trigger, frame.trigger),
                         (Trigger.HELD, Trigger.PRESSED, Trigger.FRAME))

    def test_foreign_and_unregistered_sprite_targets_are_rejected(self):
        game = Game()
        game.sprite(tile=0)
        foreign = Game().sprite(tile=0)
        unregistered = Sprite(0, 0, 0, 0)
        for sprite in (foreign, unregistered):
            with self.subTest(sprite=sprite), self.assertRaises(ValueError):
                game.bind_held(Button.RIGHT, Move(sprite, dx=1))
        self.assertEqual(game.events, ())

    def test_empty_events_callbacks_and_unregistered_set_tile_are_rejected(self):
        game = Game()
        sprite = game.sprite(tile=0)
        for bind in (lambda *actions: game.bind_held(Button.RIGHT, *actions),
                     lambda *actions: game.bind_pressed(Button.A, *actions), game.every_frame):
            with self.subTest(bind=bind), self.assertRaises(ValueError):
                bind()
            with self.subTest(bind=bind), self.assertRaises(TypeError):
                bind(lambda: None)
        with self.assertRaises(ValueError):
            game.every_frame(SetTile(sprite, 64))
        with self.assertRaises(TypeError):
            game.add_event(lambda: None)
        self.assertEqual(game.events, ())


if __name__ == "__main__":
    unittest.main()
