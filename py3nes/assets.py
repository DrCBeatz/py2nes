"""Build-time graphics: NES tiles, a small original font, and a default palette."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Tile:
    """An immutable 8 × 8 tile whose pixels are palette indexes from 0 to 3."""

    pixels: tuple[tuple[int, ...], ...]

    def __post_init__(self) -> None:
        try:
            pixels = tuple(tuple(row) for row in self.pixels)
        except TypeError as exc:
            raise TypeError("Tile pixels must be a sequence of eight pixel rows") from exc
        if len(pixels) != 8 or any(len(row) != 8 for row in pixels):
            raise ValueError("A tile must contain exactly eight rows of eight pixels")
        for row in pixels:
            for pixel in row:
                if not isinstance(pixel, int) or isinstance(pixel, bool):
                    raise TypeError("Tile pixels must be integers from 0 to 3")
                if not 0 <= pixel <= 3:
                    raise ValueError("Tile pixels must be integers from 0 to 3")
        object.__setattr__(self, "pixels", pixels)

    @classmethod
    def from_rows(cls, rows: Sequence[str | Sequence[int]]) -> Tile:
        """Read eight rows of pixels; strings use ``0``–``3`` or ``.`` for zero."""
        parsed = []
        for row in rows:
            if isinstance(row, str):
                if any(character not in ".0123" for character in row):
                    raise ValueError("Tile row strings may contain only '.', '0', '1', '2', '3'")
                parsed.append(tuple(0 if character == "." else int(character) for character in row))
            else:
                parsed.append(tuple(row))
        return cls(tuple(parsed))

    def to_chr(self) -> bytes:
        """Encode the tile as 16 NES CHR bytes: low bitplane, then high bitplane."""
        low = []
        high = []
        for row in self.pixels:
            low_byte = 0
            high_byte = 0
            for pixel in row:
                low_byte = (low_byte << 1) | (pixel & 1)
                high_byte = (high_byte << 1) | ((pixel >> 1) & 1)
            low.append(low_byte)
            high.append(high_byte)
        return bytes(low + high)


# These hand-authored 5 × 7 shapes occupy columns 1–5 of each 8 × 8 tile.
# A blank eighth row separates lines of text. Only color 1 is used by the font.
_GLYPHS = {
    " ": "00000/00000/00000/00000/00000/00000/00000",
    "!": "00100/00100/00100/00100/00100/00000/00100",
    '"': "01010/01010/01010/00000/00000/00000/00000",
    "#": "01010/01010/11111/01010/11111/01010/01010",
    "$": "00100/01111/10100/01110/00101/11110/00100",
    "%": "11001/11010/00010/00100/01000/01011/10011",
    "&": "01100/10010/10100/01000/10101/10010/01101",
    "'": "00100/00100/01000/00000/00000/00000/00000",
    "(": "00010/00100/01000/01000/01000/00100/00010",
    ")": "01000/00100/00010/00010/00010/00100/01000",
    "*": "00000/00100/10101/01110/10101/00100/00000",
    "+": "00000/00100/00100/11111/00100/00100/00000",
    ",": "00000/00000/00000/00000/00110/00100/01000",
    "-": "00000/00000/00000/11111/00000/00000/00000",
    ".": "00000/00000/00000/00000/00000/00110/00110",
    "/": "00001/00010/00010/00100/01000/01000/10000",
    "0": "01110/10001/10011/10101/11001/10001/01110",
    "1": "00100/01100/00100/00100/00100/00100/01110",
    "2": "01110/10001/00001/00010/00100/01000/11111",
    "3": "11110/00001/00001/01110/00001/00001/11110",
    "4": "00010/00110/01010/10010/11111/00010/00010",
    "5": "11111/10000/10000/11110/00001/00001/11110",
    "6": "00110/01000/10000/11110/10001/10001/01110",
    "7": "11111/00001/00010/00100/00100/01000/01000",
    "8": "01110/10001/10001/01110/10001/10001/01110",
    "9": "01110/10001/10001/01111/00001/00010/01100",
    ":": "00000/00110/00110/00000/00110/00110/00000",
    ";": "00000/00110/00110/00000/00110/00100/01000",
    "<": "00010/00100/01000/10000/01000/00100/00010",
    "=": "00000/00000/11111/00000/11111/00000/00000",
    ">": "01000/00100/00010/00001/00010/00100/01000",
    "?": "01110/10001/00001/00010/00100/00000/00100",
    "@": "01110/10001/10111/10101/10111/10000/01110",
    "A": "01110/10001/10001/11111/10001/10001/10001",
    "B": "11110/10001/10001/11110/10001/10001/11110",
    "C": "01111/10000/10000/10000/10000/10000/01111",
    "D": "11100/10010/10001/10001/10001/10010/11100",
    "E": "11111/10000/10000/11110/10000/10000/11111",
    "F": "11111/10000/10000/11110/10000/10000/10000",
    "G": "01110/10001/10000/10111/10001/10001/01110",
    "H": "10001/10001/10001/11111/10001/10001/10001",
    "I": "01110/00100/00100/00100/00100/00100/01110",
    "J": "00111/00010/00010/00010/10010/10010/01100",
    "K": "10001/10010/10100/11000/10100/10010/10001",
    "L": "10000/10000/10000/10000/10000/10000/11111",
    "M": "10001/11011/10101/10101/10001/10001/10001",
    "N": "10001/11001/11001/10101/10011/10011/10001",
    "O": "01110/10001/10001/10001/10001/10001/01110",
    "P": "11110/10001/10001/11110/10000/10000/10000",
    "Q": "01110/10001/10001/10001/10101/10010/01101",
    "R": "11110/10001/10001/11110/10100/10010/10001",
    "S": "01111/10000/10000/01110/00001/00001/11110",
    "T": "11111/00100/00100/00100/00100/00100/00100",
    "U": "10001/10001/10001/10001/10001/10001/01110",
    "V": "10001/10001/10001/10001/10001/01010/00100",
    "W": "10001/10001/10001/10101/10101/11011/10001",
    "X": "10001/10001/01010/00100/01010/10001/10001",
    "Y": "10001/10001/01010/00100/00100/00100/00100",
    "Z": "11111/00001/00010/00100/01000/10000/11111",
    "[": "01110/01000/01000/01000/01000/01000/01110",
    "\\": "10000/01000/01000/00100/00010/00010/00001",
    "]": "01110/00010/00010/00010/00010/00010/01110",
    "^": "00100/01010/10001/00000/00000/00000/00000",
    "_": "00000/00000/00000/00000/00000/00000/11111",
}

CHAR_TO_TILE: dict[str, int] = {chr(code): code - 32 for code in range(32, 96)}
FONT_TILES: tuple[Tile, ...] = tuple(
    Tile.from_rows(["0" + row + "00" for row in _GLYPHS[character].split("/")] + ["00000000"])
    for character in CHAR_TO_TILE
)


def encode_text(text: str) -> tuple[int, ...]:
    """Uppercase text and map it to font tiles; unsupported characters raise an error."""
    if not isinstance(text, str):
        raise TypeError("Text must be a string")
    encoded = []
    for character in text.upper():
        if character not in CHAR_TO_TILE:
            raise ValueError(f"Unsupported font character: {character!r}; use ASCII space through underscore")
        encoded.append(CHAR_TO_TILE[character])
    return tuple(encoded)


# Four background palettes, followed by four sprite palettes. Each palette's
# first entry is universal black; the font reads as bright white on black.
DEFAULT_PALETTE = bytes((
    0x0F, 0x30, 0x21, 0x11,
    0x0F, 0x30, 0x27, 0x17,
    0x0F, 0x30, 0x2A, 0x1A,
    0x0F, 0x30, 0x24, 0x14,
    0x0F, 0x30, 0x21, 0x16,
    0x0F, 0x30, 0x28, 0x18,
    0x0F, 0x30, 0x2A, 0x1A,
    0x0F, 0x30, 0x24, 0x14,
))
