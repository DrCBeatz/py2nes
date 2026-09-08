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
This original demo uses raw sprites and decorative platforms. For the complete
gameplay example, run:

```sh
python examples/keys_and_platforms.py
```

Open `build/keys_and_platforms.nes`. Left/right moves, A jumps, and Start resets.
Collect all three keys, avoid the moving hazard, and reach the door. This example
uses solid platforms, a 16×16 animated character, changing counters, win/lose
messages, and sound effects. The existing demos and their raw-sprite API still work.

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

Ordinary Python functions can generate tiles/maps/scenes and reusable action
groups. Passing a Python function as an event action raises an error.

## 1. Runtime variables and conditions

```python
from py3nes import Add, If, Set

keys = game.byte("keys", initial=0)
collected = game.flag("collected", initial=False)
won = game.flag("won")
direction = game.signed_byte("direction", initial=-1)

game.bind_pressed(Button.A, If(~collected, Add(keys, 1), Set(collected, True)))
game.every_frame(If(keys.ge(3), Set(won, True), otherwise=(Set(won, False),)))
```

`byte` (also `variable`) allocates an unsigned byte, 0–255. `signed_byte` allocates
a two's-complement byte, −128–127. Arithmetic wraps after every operation;
255 + 1 is 0, and signed 127 + 1 is −128. `Set(target, expression)` assigns the
current runtime value; `Add(target, expression)` adds to it. Expressions support
`+`, `-`, bitwise `&`, `|`, `^`, and `~`. Signed and unsigned variable expressions
cannot be mixed implicitly. Flags accept `Set` with 0/1, bool, or another flag;
`Add` on a flag is rejected.

Comparisons use `.eq()`, `.ne()`, `.lt()`, `.le()`, `.gt()`, and `.ge()` and follow
the operand's signedness. Combine conditions using `&`, `|`, and `~` with
parentheses. A flag can be used directly in `If`, and `~flag` means false.
Runtime expressions cannot be evaluated with Python `if`, `and`, or `or`.
Use the comparison methods rather than Python's `==` or `!=`, which also raise
an error so a rule cannot accidentally become a build-time constant.

Names start with an ASCII letter, use letters/digits/underscores, and are unique
within the game. Prefixes `actor_` and `rt_` are reserved. Up to 64 user variables
are supported; each uses one byte of RAM. Actor state is allocated separately.
Generated labels are `v_<name>`, allowing inspection in an emulator debugger.
Every branch is validated for references to variables and actors from this game.

## 2. Actors, solid platforms, velocity, and gravity

```python
from py3nes import Hitbox, If, Teleport, Velocity

game.map([[platform_tile] * 12], column=5, row=25, solid=True)
player = game.actor(tile=PLAYER_TILE, name="player", x=40, y=160,
                    hitbox=Hitbox(8, 8), gravity=1, max_fall_speed=5)
game.every_frame(Velocity(player, vx=0))
game.bind_held(Button.RIGHT, Velocity(player, vx=2))
game.bind_held(Button.LEFT, Velocity(player, vx=-2))
game.bind_pressed(Button.A, If(player.grounded, Velocity(player, vy=-8)))
game.bind_pressed(Button.START, Teleport(player, x=40, y=160))
```

Actors have independent runtime variables `x`, `y`, `vx`, `vy`, `grounded`,
`visible`, `frame`, `frame_timer`, and `animation_enabled`. Actor coordinates are
actual screen pixels: actor `y=80` displays at pixel 80. The renderer performs
the OAM Y conversion. Original `game.sprite()` coordinates remain raw OAM bytes.

Velocity is signed integer pixels per gameplay tick, limited to −8…8. With an
expression, `Velocity` clamps signed values to that range and unsigned values
to 0…8. An omitted component preserves its current velocity. Gravity adds
0…4 pixels/tick to vertical velocity before movement, capped by
`max_fall_speed` (1…8). For example, gravity 1 and jump velocity −8 reach a peak
28 pixels above the starting position. There is no fractional-pixel physics yet.

Movement sweeps one pixel at a time and checks every tile covered by the hitbox,
so movement cannot tunnel through a solid tile. Walls and ceilings stop the
corresponding velocity; landing sets `grounded`. Actors stay inside the screen,
with Y at least 1. `Hitbox(width, height, offset_x=0, offset_y=0)` gives independent
collision bounds; width/height are 1…32 pixels. The actor's overall bounds include
its graphics and hitbox. Spawning/teleporting into a solid tile does not perform
automatic depenetration; choose a clear position.

`solid=True` fills a map's collision grid; `solid=False` clears it. A matching grid
of bools, or `Map(..., solid=grid)`, allows mixed solid/empty tiles. Omitting
`solid` leaves the collision layer untouched, even when graphics overwrite it.
`game.collision_data()` returns the final 32×30 mask. Actor `collides=False` skips
tile collision while retaining screen bounds, which is useful for collectibles.

`Overlaps(actor_a, actor_b)` tests their hitboxes; touching edges do not overlap,
and hidden actors never overlap. `Hide(actor)` hides all its parts and pauses
its physics/animation; `Show(actor)` restores it. `Teleport` resets velocity and
grounded state. Use a flag with an overlap check to collect something only once:

```python
from py3nes import Hide, Overlaps

game.after_physics(If(~collected & Overlaps(player, key),
                      Set(collected, True), Add(keys, 1), Hide(key)))
```

Each tick runs controller/frame events in registration order, then actor physics,
then `after_physics` events, then animation/rendering. Use `after_physics` for
collection and win rules that should see this tick's final positions. Event
conditions read live RAM; earlier actions can affect later conditions in the same
tick. Changes made after physics are processed by collision on the next tick.

## 3. Changing text, counters, and background tiles

```python
from py3nes import SetBackgroundTile, WriteNumber, WriteText

game.after_physics(WriteNumber(keys, column=7, row=4, digits=1))
game.bind_pressed(Button.B, WriteText("DOOR UNLOCKED", column=2, row=8, width=20))
game.bind_pressed(Button.SELECT, SetBackgroundTile(tile=0, column=10, row=12))
```

`WriteText` queues one uppercase line; `width` pads with spaces to erase previous
text. `WriteText("", ..., width=20)` clears twenty cells. `WriteNumber` converts
an unsigned byte into 1–3 zero-padded decimal digits. Three digits show all
values 0–255; shorter fields keep the low decimal digits. A signed expression is
interpreted as its unsigned byte representation. Coordinates are tile positions.
`SetBackgroundTile` changes graphics; it does not change collision information.

The compiler calculates a conservative worst-case total of **64 tile writes per
gameplay tick**, including all events and the larger branch of each `If`. It
rejects larger descriptions with a clear error; it never silently drops writes.
Even mutually exclusive separate events count toward that bound, so use one
`If(..., otherwise=...)` when expressing alternatives.

Main constructs the queue before publishing the frame. NMI applies at most
**16 tile writes per vertical blank**. Larger batches appear progressively over
multiple video frames and pause gameplay until drained; they are not atomic
whole-screen updates. Keep routine HUD updates small and use larger batches for
occasional messages. This handshake prevents partially constructed commands
from reaching the PPU.

## 4. Animation, larger characters, and sound

```python
from py3nes import Animate, PlaySound, Tone

standing = game.metasprite([[head_left, head_right], [foot_left, foot_right]])
walking = game.metasprite([[head_left, head_right], [step_left, step_right]])
hero = game.actor(frames=[standing, walking], x=80, y=160,
                  frame_ticks=6, gravity=1)
game.bind_pressed(Button.B, Animate(hero, False))  # freeze current animation frame
game.bind_pressed(Button.A, Animate(hero), PlaySound(Tone(660, frames=6, volume=8)))
```

`game.metasprite` accepts a rectangular grid of at most 4×4 registered tile
indices or `Tile` descriptions, with an optional `palette=0..3`. For irregular
layouts, use `Metasprite((SpritePart(tile, dx=0, dy=0, palette=0), ...))`.
Each part can set `flip_horizontal` and `flip_vertical`. `game.actor(tile=...)`
accepts a tile or a metasprite; `frames=[...]` accepts up to 32 animation frames.
Each actor reserves enough OAM slots for its largest frame and hides unused slots.
Animation loops every `frame_ticks` gameplay ticks. `Set(hero.frame, 0)` selects
a frame; `Animate(hero, False)` holds it. The default hitbox covers the graphics.

There are at most 8 actors and 64 hardware sprite slots shared with legacy
sprites. A 16×16 character consumes four slots, and the NES's eight sprites per
scanline limit still applies. Automatic sprite flicker is not implemented.

`Tone(frequency=440, frames=8, volume=10, duty=2)` describes a constant-volume
pulse sound. Frequency is quantized to a valid hardware timer; volume is 0–15,
duration 1–255 video frames, and duty 0–3. `PlaySound(tone)` replaces the current
sound on pulse channel 1; `StopSound()` silences it. Sound commands commit at the
next ready frame, and durations advance every video frame even if graphics or
physics delay gameplay. There is no music sequencer or multi-channel mixer yet.
The implementation follows NESdev's [pulse-channel register reference](https://www.nesdev.org/wiki/APU_Pulse).

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

The compiler emits NTSC NROM-128: a 16-byte iNES header, 16 KiB of PRG ROM
mapped at `$C000` (mirrored at `$8000`), and 8 KiB of CHR ROM. Both pattern tables
contain the same 256 tiles. Nametable mirroring is horizontal. Unsupported
regions and mappers are rejected. The linker reports PRG overflow.

Reset disables audio/IRQs, waits for PPU initialization, clears RAM, uploads the
palette and static nametable, and initializes all 64 sprite slots. Unused sprites
are hidden. It initializes variables and renders actors before the first display.
The main loop runs gameplay and publishes complete sprite, display, and audio
requests. NMI transfers those during vertical blank and releases main when the
queue is drained. A late update skips a transfer instead of exposing a partially
modified buffer. Normal updates run once per NTSC frame. Large event lists,
many fast/large colliding actors, and large display batches can make gameplay
ticks span video frames. Eight large actors at maximum speed are not guaranteed
to fit one frame; sound durations continue at video-frame rate.

Assembly comments report allocated variable/work RAM and zero-page space; the
linker map reports actual code/data use. Stack, OAM, work RAM, and zero-page
allocations are kept separate. The compiler rejects RAM exhaustion and excessive
expression/condition depth, and ld65 rejects ROM overflow.

Hardware constraints remain visible: 64 sprites total, at most eight per scanline,
one screen with mutable background tiles, and no scrolling or bank switching. Hardware setup
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
bus. They exercise reset uploads, controller edge detection, typed state and
branches, collision and animation, OAM DMA, display queues, decimal conversion,
sound timing, and NMI register preservation. Compiler/emulation tests skip if cc65
or py65 is unavailable. This bus is not a cycle-accurate PPU emulator; see
`tools/emulator_smoke.mjs` for a separate full-emulator smoke check using JSNES:

```sh
npm install --prefix build/emulator jsnes@2.1.0 pngjs@7.0.0
python examples/hello_nes.py
node tools/emulator_smoke.mjs
python examples/keys_and_platforms.py
node tools/platformer_smoke.mjs
```

This checks rendered text and controller behavior, then saves initial and moved
frames beside the demo ROM as PNG files. The platformer check plays through the
level with controller inputs and verifies collection, victory, and restart.
Node is needed only for these extra checks.

Licensed under MIT. The bundled font and example graphics are original.
