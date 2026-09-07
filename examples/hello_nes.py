"""Build with: python examples/hello_nes.py (after pip install -e .)."""

from pathlib import Path

from py3nes import Button, Game, Map, Move, SetPosition, SetTile, Tile


PLAYER_TILE = Tile.from_rows([
    "..2222..",
    "..2222..",
    "...22...",
    "22111122",
    "..1111..",
    "..2222..",
    ".22..22.",
    "11....11",])

game = Game(region="NTSC", mapper="NROM")
game.text("OH HAI", column=2, row=2)
game.text("MY GUD FREN", column=2, row=4)
game.text("DIS IS MY GAM", column=8, row=6)

# This function runs once in Python. Its output becomes static background data.
def make_platform(width: int) -> Map:
    brick = game.tile([
        "22222222",
        "21112111",
        "21112111",
        "22222222",
        "11211121",
        "11211121",
        "22222222",
        "33333333",
    ])
    return Map([[brick] * width])


game.map(make_platform(28), column=2, row=10)
game.map(make_platform(14), column=9, row=19)
game.text_box("D-PAD: MOVE\nA: CHANGE TILE\nB: RESTORE TILE\nSTART: RESET POSITION",
              column=2, row=20, width=28, height=7)
game.text_box("HENLO EV-RY 1\n\nOH HAI", column=2, row=13, width=28, height=5)
player = game.sprite(tile=PLAYER_TILE, x=80, y=80)
alternate = game.tile([
    "..1111..",
    "..1111..",
    "...11...",
    "11222211",
    "..2222..",
    "..1111..",
    ".11..11.",
    "22....22",
])

game.bind_held(Button.RIGHT, Move(player, dx=1))
game.bind_held(Button.LEFT, Move(player, dx=-1))
game.bind_held(Button.DOWN, Move(player, dy=1))
game.bind_held(Button.UP, Move(player, dy=-1))
game.bind_pressed(Button.A, SetTile(player, alternate))
game.bind_pressed(Button.B, SetTile(player, player.tile))
game.bind_pressed(Button.START, SetPosition(player, x=80, y=80))

if __name__ == "__main__":
    result = game.build(Path(__file__).resolve().parents[1] / "build" / "hello_nes.nes")
    print(f"ROM: {result.rom_path}")
    print(f"Assembly: {result.assembly_path}")
