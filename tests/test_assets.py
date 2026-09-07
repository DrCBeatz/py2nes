"""Known NES encodings and asset validation, independent of the compiler."""

from dataclasses import FrozenInstanceError
import unittest

from py3nes.assets import CHAR_TO_TILE, DEFAULT_PALETTE, FONT_TILES, Tile, encode_text


class TileTests(unittest.TestCase):
    def test_chr_has_separate_bitplanes_and_leftmost_pixel_is_high_bit(self):
        tile = Tile.from_rows([
            "10000000",
            "00000001",
            "20000000",
            "00000002",
            "30000000",
            "00000003",
            "01230123",
            "33333333",
        ])
        self.assertEqual(
            tile.to_chr(),
            bytes([0x80, 0x01, 0x00, 0x00, 0x80, 0x01, 0x55, 0xFF,
                   0x00, 0x00, 0x80, 0x01, 0x80, 0x01, 0x33, 0xFF]),
        )

    def test_nested_input_is_copied_and_frozen(self):
        rows = [[0] * 8 for _ in range(8)]
        tile = Tile(rows)
        rows[0][0] = 3
        self.assertEqual(tile.pixels, ((0,) * 8,) * 8)
        with self.assertRaises(FrozenInstanceError):
            tile.pixels = ((1,) * 8,) * 8

    def test_dots_and_numeric_rows_are_equivalent(self):
        self.assertEqual(Tile.from_rows([".123.123"] * 8), Tile.from_rows([[0, 1, 2, 3] * 2] * 8))

    def test_rejects_wrong_dimensions(self):
        for rows in ([], [[0] * 8] * 7, [[0] * 8] * 9, [[0] * 7] * 8,
                     [[0] * 9] * 8, [[0] * 8] * 7 + [[0] * 7]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                Tile(rows)

    def test_rejects_invalid_pixel_values(self):
        for pixel in (-1, 4, 256):
            with self.subTest(pixel=pixel), self.assertRaises(ValueError):
                Tile.from_rows([[pixel] * 8] * 8)
        for pixel in (True, 1.0, "1", None):
            with self.subTest(pixel=pixel), self.assertRaises(TypeError):
                Tile.from_rows([[pixel] * 8] * 8)
        with self.assertRaises(ValueError):
            Tile.from_rows(["1111111x"] * 8)


class FontTests(unittest.TestCase):
    def test_font_covers_printable_uppercase_ascii_with_blank_tile_zero(self):
        self.assertEqual(CHAR_TO_TILE, {chr(code): code - 32 for code in range(32, 96)})
        self.assertEqual(len(FONT_TILES), 64)
        self.assertEqual(FONT_TILES[0].to_chr(), bytes(16))
        self.assertEqual(len({tile.to_chr() for tile in FONT_TILES}), 64)
        for tile in FONT_TILES:
            with self.subTest(tile=tile):
                self.assertEqual(tile.to_chr()[8:], bytes(8))
                self.assertEqual(tile.pixels[-1], (0,) * 8)

    def test_text_uppercases_and_preserves_spaces(self):
        self.assertEqual(encode_text("Hello NES!"), (40, 37, 44, 44, 47, 0, 46, 37, 51, 1))
        self.assertEqual(encode_text(""), ())
        self.assertEqual(encode_text("_"), (63,))

    def test_unsupported_text_does_not_silently_disappear(self):
        for text in ("A\nB", "A\tB", "caf\u00e9", "`", "{", "\x00"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                encode_text(text)
        with self.assertRaises(TypeError):
            encode_text(b"HELLO")

    def test_palette_is_complete_and_uses_safe_visible_colors(self):
        self.assertIsInstance(DEFAULT_PALETTE, bytes)
        self.assertEqual(len(DEFAULT_PALETTE), 32)
        self.assertEqual(DEFAULT_PALETTE[::4], bytes([0x0F] * 8))
        self.assertEqual(DEFAULT_PALETTE[1], 0x30)
        self.assertTrue(all(color < 64 and color & 0x0F not in (0x0D, 0x0E)
                            for color in DEFAULT_PALETTE))
        self.assertTrue(all(DEFAULT_PALETTE[i] != 0x0F
                            for i in range(16, 32) if i % 4))


if __name__ == "__main__":
    unittest.main()
