# py3nes

Describe a small NES game in Python, generate readable 6502 assembly, and compile
it into an actual `.nes` ROM using `ca65` and `ld65` from cc65.

Python runs at **build time**. `Move(...)` and other actions describe instructions
that execute later on the NES or in an emulator. Python callbacks are not executed
by the ROM, and Python source is not translated into 6502 instructions.

## Quick start

Requires Python 3.10+ and [cc65](https://cc65.github.io/). The core Python library
has no third-party dependencies; PNG and Tiled imports use the optional Pillow
dependency installed with `pip install -e '.[images]'`.

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

For an adventure spanning several screens, run:

```sh
python examples/three_rooms.py
```

Open `build/three_rooms.nes`. Left/right moves, A jumps, and **Up enters a door**.
Visit the garden on the left, jump onto its ledge to collect the key, return to
the hall, and unlock the tower on the right. Press Up at the tower's final exit
to win. Start begins a new game. Revisiting the garden demonstrates that the
collected key stays gone while the player resets to the room's entrance.

For the same adventure built from editable PNG artwork and Tiled room maps:

```sh
python -m pip install -e '.[images]'
python -m py3nes examples/visual_adventure.py -o build/visual_adventure.nes
```

Open `build/visual_adventure.nes` in your emulator. Edit the
[PNG tilesheet](examples/assets/adventure/tiles.png) in a pixel-art editor or open
[hall.tmj](examples/assets/adventure/hall.tmj),
[garden.tmj](examples/assets/adventure/garden.tmj), and
[tower.tmj](examples/assets/adventure/tower.tmj) in Tiled, then rerun the build.
Controls and room goals follow the three-room adventure above. Gameplay rules
remain in [visual_adventure.py](examples/visual_adventure.py).

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
those slots, shared across boxes. Backgrounds default to palette 0 and can choose
one of four palettes per 16×16 pixel region using `map(..., palette=...)`.
Sprites choose one of four sprite palettes. `Game(palette=...)` accepts 32 NES color indices:
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
within their game or room scope. Prefixes `actor_`, `room_`, and `rt_` are reserved.
Up to 64 user variables across all scopes are supported; each uses one byte of
RAM. Actor state is allocated separately.
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

For an integer actor, velocity is signed integer pixels per gameplay tick, limited to −8…8. With an
expression, `Velocity` clamps signed values to that range and unsigned values
to 0…8. An omitted component preserves its current velocity. Gravity adds
0…4 pixels/tick to vertical velocity before movement, capped by
`max_fall_speed` (1…8). For example, gravity 1 and jump velocity −8 reach a peak
28 pixels above the starting position. Existing integer actors retain this behavior.

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

### Fractional motion and platformer controls

Fractional gravity or terminal speed automatically enables subpixel movement;
`subpixel=True` also enables it explicitly. The runtime keeps 1/256-pixel
remainders while the renderer displays whole pixels. Low downward speed keeps
accumulating, so `max_fall_speed=0.25` moves one pixel every four ticks.

```python
player = game.actor(tile=PLAYER_TILE, x=40, y=160, gravity=0.25,
                    max_fall_speed=5, subpixel=True)
game.platformer(player, speed=2.25, acceleration=0.25, friction=0.375,
                jump_speed=5.5, jump_cut=2,
                buffer_frames=5, coyote_frames=4)
```

`platformer` is a Python factory for explicit events, available on both `Game`
and `Room`. Left/right approach the target speed; releasing direction approaches
zero using friction. Opposite directions cancel. Pressing A requests a jump;
holding A permits a higher jump and releasing it limits upward speed. A press
just before landing is remembered for `buffer_frames` additional ticks. The
`coyote_frames` window allows a jump shortly after walking off a ledge, while
a successful jump consumes that opportunity and prevents double jumping.

Use `left=...`, `right=...`, and `jump=...` to change buttons. An optional
`enabled=~won` condition disables the controls, stops horizontal movement, and
cancels pending jumps. `animate=False` leaves animation management to your own
rules. The helper uses two events and returns them; call it once per actor,
before custom movement rules that should override it.

The constituent actions can also be used directly:

```python
from py3nes import ApproachVelocity, ButtonDown, CutJump, Jump

game.bind_held(Button.RIGHT, ApproachVelocity(player, vx=2.25, acceleration=0.25))
game.bind_pressed(Button.A, Jump(player, speed=5.5, buffer_frames=5, coyote_frames=4))
game.every_frame(If(~ButtonDown(Button.A), CutJump(player, max_rise_speed=2)))
```

Choose the helper or install your own complete controls. `ButtonDown` is a
runtime condition that can be combined with flags and other conditions.
`ApproachVelocity` supports `vx` and/or `vy` targets, approaching without
overshoot; approaching zero implements friction. `Jump` handles grounding and
buffering itself, so its pressed event should not be gated on `grounded`.
`CutJump` leaves downward or already slower upward motion unchanged.

Motion literals must be finite multiples of `1/256`: `0.25`, `0.375`, and
`1 / 256` are valid, while `0.1` produces a precision error. Velocity remains
limited to −8…8, gravity to 0…4, and terminal speed to 1/256…8. Acceleration is
positive and at most 8; jump speed is positive and at most 8. Buffer/coyote
windows are 0…254 ticks. These values are converted to integers during the
Python build; the cartridge uses no floating-point interpreter.

For debugging, subpixel actors add `x_fraction`, `y_fraction`, `vx_fraction`,
and `vy_fraction` bytes. A complete value is its existing integer byte plus
the corresponding fraction divided by 256. Signed integer bytes use floor:
velocity −0.25 is `vx=-1`, `vx_fraction=192`. Ordinary byte expressions and
`Set(actor.vx, ...)` still operate on the integer byte; use `Velocity` to assign
a complete velocity. A whole-pixel expression passed to `Velocity` clears that
component's fraction. Teleport and room entry clear fractional state and queued
jumps; collisions clear the affected remainder so actors do not creep through
walls. Integer and subpixel actors can share the same room.

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

There are at most 8 actors and 64 hardware sprite slots per room, shared with
legacy sprites. A 16×16 character consumes four slots, and the NES's eight sprites per
scanline limit still applies. Automatic sprite flicker is not implemented.

`Tone(frequency=440, frames=8, volume=10, duty=2)` describes a constant-volume
pulse sound. Frequency is quantized to a valid hardware timer; volume is 0–15,
duration 1–255 video frames, and duty 0–3. `PlaySound(tone)` replaces the current
sound on pulse channel 1; `StopSound()` silences it. Sound commands commit at the
next ready frame, and durations advance every video frame even if graphics or
physics delay gameplay. There is no music sequencer or multi-channel mixer yet.
The implementation follows NESdev's [pulse-channel register reference](https://www.nesdev.org/wiki/APU_Pulse).

## 5. Rooms, entrances, and state lifetime

Create named rooms with `game.room("name")`. Each room provides `text`, `text_box`,
`map`, `sprite`, `actor`, button bindings, `every_frame`, and `after_physics`.
Backgrounds, collision, actor placements, and local rules belong to that room.
Register shared graphics with `game.tile`/`game.metasprite`; the same methods on
a room use the game's shared tile collection. All rooms share the cartridge
palette. Build the containing `game`, rather than an individual room.

```python
from py3nes import (Button, ChangeRoom, Game, Hide, If, Overlaps,
                    Set, WriteNumber)

game = Game()
keys = game.byte("keys")
hall = game.room("hall")
garden = game.room("garden")
hall_player = hall.actor(tile=1, name="player", x=40, y=100)
garden_player = garden.actor(tile=1, name="player", x=40, y=100)
key = garden.actor(tile=2, name="key", x=80, y=100, collides=False)
key_taken = garden.flag("key_taken", persistent=True)

hall.spawn("start", hall_player, x=120, y=100)
hall.spawn("from_garden", hall_player, x=40, y=100)
garden.spawn("entrance", garden_player, x=40, y=100)
game.start(hall, spawn="start")

# These minimal bindings switch rooms anywhere. The complete example wraps
# ChangeRoom in If(Overlaps(player, door), ...) to require being at a door.
hall.bind_pressed(Button.UP, ChangeRoom(garden, spawn="entrance"))
garden.bind_pressed(Button.UP, ChangeRoom(hall, spawn="from_garden"))
garden.after_physics(If(~key_taken & Overlaps(garden_player, key),
                       Set(key_taken, True), Set(keys, 1), Hide(key)))
garden.on_enter(If(key_taken, Hide(key)), WriteNumber(keys, 2, 2, digits=1))

# A global rule works in every room. Reset persistent state explicitly.
game.bind_pressed(Button.START, Set(keys, 0), Set(key_taken, False),
                  ChangeRoom(hall, spawn="start"))
```

Room and spawn names are ASCII identifiers; room names are unique within the
game, and spawn names within a room. A spawn names one actor's position in screen
pixels. It must reference that room's actor and fit the actor's bounds. Spawn
names can be declared after their `ChangeRoom` rules; compilation checks that
every referenced spawn exists. Without `spawn=...`, actors use their original
placements. The first room is the default starting room; `game.start(...)`
selects another room or a named initial entrance.

State lifetime is explicit:

| Description | On room entry | Accessible from |
| --- | --- | --- |
| `game.byte`, `game.flag`, `game.signed_byte` | Keeps its current value | All rooms and global rules |
| `room.byte`/`flag`/`signed_byte` | Resets to its declared initial value | Its own room |
| The same room methods with `persistent=True` | Keeps its current value | All rooms and global rules |
| Actor state and raw sprite data | Resets to original values | Its own room |

Persistence means **across room transitions during the current run**. There is
no battery-backed save or automatic new-game operation. Power/reset initializes
all state; a Start binding resets only the values its actions explicitly change.
Persistent room state is accessible elsewhere so a restart can clear collected
item flags. Temporary room variables, actors, and sprites cannot be referenced
from another room or global rules. Use a global inventory variable and separate
player placements per room.

On entry, the runtime resets temporary variables and actor state, applies the
chosen spawn, evaluates `on_enter` actions in registration order, then establishes
grounded state and renders the actors. `on_enter` also runs for the initial room.
Use it to hide previously collected items and restore messages from persistent
state: ordinary background edits are rebuilt from the room's description on
every entry. `on_enter` cannot contain another `ChangeRoom`, including inside an
`If`. Entering the current room again performs the same reset/load sequence.

Global controller/frame events run before the active room's events, followed by
its physics, global `after_physics` rules, and the room's `after_physics` rules.
The first executed `ChangeRoom` immediately ends that gameplay tick; remaining
actions and rules do not run, and pending source-room display updates are
discarded. Controller history survives entry, so a held button does not become
a second `bind_pressed` event in the destination.
Transitions also stop the previous room's sound effect and discard its pending
sound request. An `on_enter` sound starts with the next normal display commit.

Transitions briefly disable rendering, load the destination background and
collision selection, apply its entry actions, and transfer a complete sprite
list before showing the room. Entry display writes finish while the screen is
blank. The 64-write validation limit applies separately to each room's entry
actions and each possible active-room gameplay tick, including global rules.
This is a full-screen transition; it does not scroll between adjacent rooms.
The screen upload follows the NES PPU's allowance for VRAM writes with
[rendering disabled](https://www.nesdev.org/wiki/PPU_programmer_reference).

The current limit is 16 named rooms, 8 actors/64 hardware sprite slots per room,
and 64 user variables total. Actual capacity also depends on ROM and RAM usage;
the compiler/linker report exhaustion. Actor state for all rooms is allocated in
RAM, while OAM slots are reused by the active room. Debug labels for room variables
are `v_room_<room_index>_<name>`; actor labels use a unique numeric actor index.
The byte `rt_room` reports the active room index.

Existing games without named rooms keep their original API and ROM layout.
With named rooms, place visual content and actors on the rooms; mixing root
`game.text`/`map`/`actor`/`sprite` content with named rooms raises an error.
Root variables and global event rules remain useful in a room-based game.

## 6. PNG artwork and background palettes

Install the image extra, then draw an indexed PNG in a pixel-art editor. Image
dimensions must be multiples of 8 pixels, without tile spacing or margins.
PNG palette indexes 0–3 become NES pixel values directly; palette index 0 is
normally the transparent entry. Fully transparent pixels always map to zero.

```sh
python -m pip install -e '.[images]'
```

```python
from py3nes import Game, load_png

game = Game()
sheet = load_png("examples/assets/adventure/tiles.png")
brick = game.tile(sheet.tile(0, 0))
standing = game.metasprite(sheet.region(0, 1, 2, 2), palette=0)
walking = game.metasprite(sheet.region(2, 1, 2, 2), palette=0)
player = game.actor(frames=[standing, walking], x=40, y=208, gravity=1)
game.map([[brick] * 32] * 2, row=28, solid=True, palette=1)
```

`load_png` returns an immutable `TileSheet`. Its `width` and `height` are in tiles;
`tile(column, row)` selects one `Tile`, and `region(column, row, width, height)`
selects a rectangular grid for `game.metasprite`. `sheet.tiles` exposes the full
grid. To use a region as a background, register its cells with `game.tile` and
pass their tile indices to `game.map`. Loading does not allocate graphics in a
game; registration deduplicates identical tiles and checks the existing budget.

RGB/RGBA PNGs require an explicit mapping in pixel-value order:

```python
sheet = load_png("art/player.png",
                 colors=["#00000000", "#ECEEEC", "#4C9AEC", "#A84000"])
```

Supply one to four RGB/RGBA tuples or `#RRGGBB`/`#RRGGBBAA` strings. Opaque pixel
colors must match exactly. Partial transparency, extra colors, and animated PNGs
raise errors; arrange animation frames in a sheet. No color quantization or
antialiasing is applied. With indexed PNGs, the preview RGB palette does not
change pixel indexes. With either format, final NES colors still come from
`Game(palette=...)`; loading an image does not replace the cartridge palette.
See [the bundled artwork layout](examples/assets/adventure/ART.md).

`game.map(..., palette=2)` assigns background subpalette 2 to every tile in a
patch. A matching grid of integers 0–3, or `Map(..., palettes=grid)`, assigns
different subpalettes. The final assignments must agree inside every screen-
aligned 2×2-tile region: this follows the NES's
[16×16 pixel attribute granularity](https://www.nesdev.org/wiki/PPU_attribute_tables).
Conflicts report the affected region at build time. Later explicit assignments
replace earlier ones at the same cells; omitting `palette` preserves underlying
assignments, allowing text to inherit a surrounding region's palette.
The current display-update actions change tile numbers, leaving these attributes
unchanged. Each room has independent background palette assignments while all
rooms share the cartridge's palette colors.

## 7. Visual room design with Tiled

[Tiled](https://www.mapeditor.org/) can author background tiles, collision, actor
placements, entrances, and exit regions. Save maps as JSON (`.tmj`) with **finite,
orthogonal, 8×8-pixel tiles** and at most **32 columns × 30 rows**. Use uncompressed
JSON arrays for tile-layer data. An external JSON tileset (`.tsj`) or inline
tileset must reference a PNG sheet with no spacing or margin. Paths resolve
relative to the file containing the reference, independent of the build's
working directory. The importer follows Tiled's
[JSON map and tileset format](https://doc.mapeditor.org/en/stable/reference/json-map-format/).

Use ordinary tile layers for backgrounds. Later nonempty cells replace earlier
ones; empty cells leave earlier graphics visible. A tile layer named `collision`
(case insensitive), or with a Boolean custom property `collision=true`, marks
every nonempty cell solid. Collision layers remain active when hidden in the
editor. Other hidden layers and objects are skipped. Collision is independent
of visible tiles, so platforms need cells in both layers when appropriate.

An integer custom property `palette` selects background subpalette 0–3. It can
appear on a tileset, tile layer, or individual tile definition, with precedence
**tile definition, layer, tileset**. The default is 0. Occupied cells in each
16×16 pixel region must agree; empty cells inherit that region's selection.
Horizontal and vertical tile flips are baked into the imported graphics and
deduplicated. Diagonal flips, tile animation, image collections, tile collision
objects, infinite maps, group/image layers, opacity, tint, and layer offsets are
currently rejected.

Place named points or axis-aligned rectangles on object layers. Coordinates are
whole screen pixels, and names/classes are ASCII identifiers. In Tiled's object
properties, set **Class** (older exports call this `type`):

| Class | Interpretation | Required custom properties |
| --- | --- | --- |
| `player`, `key`, or another application class | Calls the corresponding Python actor factory | Whatever that factory requires |
| `spawn` | Names an actor's entrance position | String `actor`: actor object name |
| `exit` | Names a rectangular destination region | String `room`; optional string `spawn` |

Actor factories run once during the Python build and receive `(room, object)`.
They must construct and return an actor using the object's `name`, `x`, and `y`.
The object's immutable `properties` mapping exposes scalar custom properties;
its rectangle dimensions can inform a factory's hitbox if desired. No Python
code is embedded in the map. For a map containing an object of class `player`:

```python
def make_player(room, obj):
    return room.actor(name=obj.name, frames=[standing, walking],
                      x=obj.x, y=obj.y, gravity=1)

hall = game.room("hall")
imported = hall.import_tiled("levels/hall.tmj",
                             actor_factories={"player": make_player})
player = imported.actors["player"]
game.start(hall, spawn="start")  # A spawn object named start, actor="player".
```

The returned `ImportedRoom` exposes `actors`, `spawns`, and `exits` by object
name. For inspection without modifying a game, `load_tiled(path, colors=None)`
returns an immutable `TiledMap`; call its `apply(room, actor_factories=...)` to
construct the content. The `colors` option has the same meaning as `load_png`.
Failed imports restore builder state, including tile allocation and actors.

Import all rooms before connecting exits:

```python
imported.bind_exits(player, {"hall": hall, "garden": garden})
```

This creates `Button.UP` press rules that change rooms while the player overlaps
each exit rectangle. Pass `button=Button.A` to choose another button. Destination
rooms and optional spawns are validated before adding rules. For locked doors,
write a conditional rule using `imported.exits["tower_door"].contains(player)`
and `ChangeRoom(...)` instead of automatically binding that room's exits.
Keep inventory, conditions, and gameplay rules in Python while editing room
geometry and placements in Tiled.

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

The compiler emits NTSC mapper-0 cartridges with a 16-byte iNES header and
8 KiB of CHR ROM. Games without named rooms use NROM-128: 16 KiB of PRG ROM mapped
at `$C000`, mirrored at `$8000`. Named-room games use NROM-256: 32 KiB of PRG ROM
mapped at `$8000–$FFFF`. Both pattern tables contain the same 256 tiles.
Nametable mirroring is horizontal. Unsupported regions and mappers are rejected.
The linker reports PRG overflow.

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

Hardware constraints remain visible: 64 sprites on the active screen, at most
eight per scanline, one displayed room with mutable background tiles, and no
scrolling or bank switching. Hardware setup
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
sound timing, room transitions and state lifetime, and NMI register preservation.
Compiler/emulation tests skip if cc65
or py65 is unavailable. This bus is not a cycle-accurate PPU emulator; see
`tools/emulator_smoke.mjs` for a separate full-emulator smoke check using JSNES:

```sh
npm install --prefix build/emulator jsnes@2.1.0 pngjs@7.0.0
python examples/hello_nes.py
node tools/emulator_smoke.mjs
python examples/keys_and_platforms.py
node tools/platformer_smoke.mjs
python examples/three_rooms.py
node tools/rooms_smoke.mjs
python -m py3nes examples/visual_adventure.py -o build/visual_adventure.nes
node tools/visual_adventure_smoke.mjs
```

This checks rendered text and controller behavior, then saves initial and moved
frames beside the demo ROM as PNG files. The platformer check plays through the
level with controller inputs and verifies collection, victory, and restart.
The rooms check tries the locked tower, collects the garden key, revisits the
garden to verify persistence, wins in the tower, and starts a new game. It saves
screenshots of the hall, collected key, unlocked hall, and victory.
The visual-adventure check also verifies imported PNG graphics, per-room
background palettes, fractional movement, and the full edited-map adventure.
Node is needed only for these extra checks.

Licensed under MIT. The bundled font and example graphics are original.
