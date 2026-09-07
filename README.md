# py3nes

Describe a small NES game in Python, generate readable 6502 assembly, and compile
it into an actual `.nes` ROM using `ca65` and `ld65` from cc65.

Python runs at **build time**. `Move(...)` and other actions describe instructions
that execute later on the NES or in an emulator. Python callbacks are not executed
by the ROM, and Python source is not translated into 6502 instructions.

## Quick start

Requires Python 3.10+ and [cc65](https://cc65.github.io/). The Python library has
no runtime Python dependencies.

```sh
# macOS; on Debian/Ubuntu use: sudo apt install cc65
brew install cc65
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python examples/hello_nes.py
```

Open `build/hello_nes.nes` in an NES emulator. Use the controller's D-pad to move,
A/B to change/restore the character tile, and Start to reset its position.
The platform is decorative; this version has no collision system.

```python
from py3nes import Button, Game, Move, Tile

PLAYER_TILE = Tile.from_rows([
    "..2222..",
    ".222222.",
    ".313313.",
    ".333333.",
    "..3333..",
    ".222222.",
    ".2.22.2.",
    "...11...",
])

game = Game(region="NTSC", mapper="NROM")
game.text("HELLO NES", column=2, row=2)
player = game.sprite(tile=PLAYER_TILE, x=80, y=80)
game.bind_held(Button.RIGHT, Move(player, dx=1))
game.bind_held(Button.LEFT, Move(player, dx=-1))
game.build("demo.nes")
```

`build()` returns a `BuildResult` with `rom_path`, `assembly_path`, `config_path`,
`map_path`, and `labels_path`. It keeps `demo.s`, `demo.cfg`, `demo.map`, and
`demo.lbl` beside the ROM. A failed assembler/linker invocation preserves the
previous ROM and reports the diagnostic. Use `build(..., ca65="/path/to/ca65",
ld65="/path/to/ld65")` to select tool executables.

## Backgrounds, text, and sprites

- `game.tile(Tile.from_rows(...))` registers eight rows of eight pixels and returns
  a tile index. Strings contain `0`–`3`, with `.` as an alias for zero. Pixel values
  select palette colors; sprite color zero is transparent. Identical tiles share
  an index. `game.sprite(tile=...)` also accepts a `Tile` directly.
- `game.map(Map([[tile, tile], [tile, tile]]), column=2, row=10)` places a background
  rectangle. A nested sequence of tile indices works too. Maps must fit the
  32×30 tile screen; later placements overwrite earlier ones.
- `game.text("HELLO\nNES", column=2, row=2)` converts text to uppercase using the
  built-in 8×8 font. Letters, digits, spaces, and ASCII punctuation through `_`
  are supported. Unsupported characters and offscreen text raise errors.
- `game.text_box("SOME LONG TEXT", column=2, row=20, width=28, height=6)` wraps text
  in a border. Dimensions include the border; omit `height` to fit the text,
  or pass `border=False`. Text boxes are static background graphics.
- `game.sprite(tile=tile, x=80, y=80, palette=0)` adds one hardware 8×8 sprite.
  Optional flags: `flip_horizontal`, `flip_vertical`, and `behind_background`.

Text/map positions are measured in tiles. Sprite positions are byte coordinates
in pixels. To keep the generated code direct, **Y is the raw NES OAM value**:
`y=80` appears with its top at screen pixel 81. Y values 239–255 hide the sprite;
the first screen scanline cannot contain sprites. X values near 255 clip the
sprite at the right edge. These conventions follow the
[NES OAM format](https://www.nesdev.org/wiki/PPU_OAM).

The first 64 tiles are the font; `CHAR_TO_TILE["A"]` gives a font tile index.
There is room for up to 192 additional tiles. Bordered text boxes use six of
those slots, shared across boxes. Backgrounds use palette 0. Sprites choose one
of four sprite palettes. `Game(palette=...)` accepts 32 NES color indices:
16 background entries, then 16 sprite entries. Entries 16/20/24/28 must match
their hardware mirrors 0/4/8/12.

## Events are explicit descriptions

```python
from py3nes import Button, Move, SetPosition, SetTile

game.bind_held(Button.UP, Move(player, dy=-1))
game.bind_pressed(Button.START, SetPosition(player, x=80, y=80))
game.bind_pressed(Button.A, SetTile(player, tile=alternate_tile))
# Multiple actions in one event:
game.bind_pressed(Button.B,
                  SetPosition(player, x=80, y=80),
                  SetTile(player, tile=player.tile))
# An unconditional action each gameplay tick:
# game.every_frame(Move(player, dx=1))
```

`bind_held` checks the current button state. `bind_pressed` checks the transition
from released to held. Register one button per event; separate events can fire
together. Events and their actions run in registration order, so later writes
to the same coordinate/tile win. `Move` adds signed deltas from −255 to 255, with
byte wraparound (255 + 1 becomes 0). Movement has no automatic clipping or
collision detection. Actions must target sprites from the same `Game`.

The returned `Sprite`, `Map`, `TextBox`, and `Event` descriptions are immutable.
For example, `player.x` remains its initial build-time value; live coordinates
exist only in the running ROM's RAM. Advanced construction can use
`game.add_event(Event(Trigger.HELD, (Move(player, dx=1),), Button.RIGHT))`.

Ordinary Python functions can generate tiles/maps/scenes using these methods.
Passing a Python function as an event action raises an error. Runtime variables,
arbitrary expressions, branching, collision rules, and dynamic score text are
future extensions to this explicit action language.

## Assembly and command-line builds

```python
assembly = game.to_assembly()        # no cc65 installation needed
game.emit_assembly("build/demo.s")  # also writes build/demo.cfg
```

The assembly contains the runtime, scene data, iNES header, and CHR bytes;
there are no generated asset includes to locate. It can be assembled manually:

```sh
ca65 -g -o build/demo.o build/demo.s
ld65 -C build/demo.cfg -m build/demo.map -Ln build/demo.lbl \
     -o build/demo.nes build/demo.o
```

Alternatively, a description script can export a module-level `game` variable:

```sh
python -m py3nes examples/hello_nes.py -o build/demo.nes
python -m py3nes examples/hello_nes.py --assembly-only -o build/demo.s
```

Guard direct `game.build(...)` calls with `if __name__ == "__main__":` so CLI
loading does not build twice. Description scripts execute as normal local Python
programs, including any top-level side effects.

## ROM layout and runtime

The first version emits NTSC NROM-128: a 16-byte iNES header, 16 KiB of PRG ROM
mapped at `$C000` (mirrored at `$8000`), and 8 KiB of CHR ROM. Both pattern tables
contain the same 256 tiles. Nametable mirroring is horizontal. Unsupported
regions and mappers are rejected. The linker reports PRG overflow.

Reset disables audio/IRQs, waits for PPU initialization, clears RAM, uploads the
palette and static nametable, and initializes all 64 sprite slots. Unused sprites
are hidden. The main loop reads controller 1 and runs generated events. It marks
the completed OAM buffer ready; NMI transfers it during vertical blank and then
releases the main loop for its next update. A late update skips a transfer instead
of exposing a partially modified buffer. Normal updates run once per NTSC frame;
very large event lists can cause gameplay ticks to span frames. There is no audio.

Hardware constraints remain visible: 64 sprites total, at most eight per scanline,
one static screen, and no scrolling or runtime background updates. Hardware setup
and input behavior are based on NESdev's
[PPU initialization](https://www.nesdev.org/wiki/PPU_power_up_state),
[PPU registers](https://www.nesdev.org/wiki/PPU_registers), and
[controller interface](https://www.nesdev.org/wiki/Controller_reading).
The linker configuration follows the [ld65 documentation](https://cc65.github.io/doc/ld65.html).

## Development

```sh
python -m pip install -e '.[test]'
python -m unittest discover -s tests -v
```

The tests check description validation and graphics encoding, compile ROMs with
cc65, and execute their real 6502 instructions using py65 with a small mocked NES
bus. They exercise reset uploads, controller edge detection, movement, OAM DMA,
and NMI register preservation. Compiler/emulation integration tests skip if cc65
or py65 is unavailable. This bus is not a cycle-accurate PPU emulator; see
`tools/emulator_smoke.mjs` for a separate full-emulator smoke check using JSNES:

```sh
npm install --prefix build/emulator jsnes@2.1.0 pngjs@7.0.0
python examples/hello_nes.py
node tools/emulator_smoke.mjs
```

This checks rendered text and controller behavior, then saves initial and moved
frames beside the demo ROM as PNG files. Node is needed only for this extra check.

Licensed under MIT. The bundled font and example graphics are original.
