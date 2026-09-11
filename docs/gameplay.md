# Gameplay, dialogue, and music (v0.5)

All of these APIs construct descriptions in Python. The generated ROM contains
6502 instructions, byte state, and asset data. It does not run Python callbacks
or coroutines. Helpers work on `Game` or `Room`; a room's helper state resets
on entry. Inventory remains explicit through global or persistent room variables.

## Named animations and facing

```python
from py3nes import AnimationClip, Face, Freeze, PlayAnimation

player = room.actor(
    name="player", x=40, y=208,
    animations={
        "idle": AnimationClip([standing]),
        "walk": AnimationClip([standing, walking], frame_ticks=6),
        "jump": AnimationClip([walking], loop=False),
        "hurt": AnimationClip([hurt_pose], loop=False),
    },
    gravity=0.25, subpixel=True, freezable=True,
)
room.platformer(player)
```

Provide exactly one of `tile`, `frames`, or `animations`. Clip frames accept the
same registered tiles, `Tile` descriptions, and metasprites as `frames`.
Animation names are ASCII identifiers, the first clip starts initially, and
all clips together may contain at most 32 frames. Each clip has its own tick
duration and loop setting. Non-looping clips hold their final frame.

`PlayAnimation(player, "hurt")` switches clips and resets its frame/timer only
when the clip changes; `restart=True` explicitly restarts even the same clip.
`player.frame` remains an absolute index within the combined frames.

Named animations enable facing, initially right. `Face(player, "left")` mirrors
both part positions and each hardware sprite's horizontal flip bit around the
actor width. The physics hitbox stays fixed. Older `tile`/`frames` actors can
opt in with `facing="right"`. The platformer helper updates facing from input;
with `idle` and `walk` (or `run`) clips, it selects them automatically and also
uses optional `jump`/`fall` clips. Use `animate=False` to select clips yourself.

Actors with `freezable=True` expose `frozen`. `Freeze(player)` pauses physics and
animation while leaving the actor visible. `Freeze(player, False)` resumes.
The platformer helper respects this flag, retaining velocity while frozen.
Other custom rules can use `~player.frozen` or a dialogue's active flag.
These optional actor fields consume RAM only when enabled.

## Timers and named states

```python
from py3nes import State, Transition, Velocity

pause = room.timer("guard_pause")
behavior = room.state_machine("guard", initial="left", states={
    "left": State(
        enter=(pause.start(60),), tick=(Velocity(guard, vx=-1),),
        transitions=(Transition(pause.expired, "right"),)),
    "right": State(
        enter=(pause.start(60),), tick=(Velocity(guard, vx=1),),
        transitions=(Transition(pause.expired, "left"),)),
})
```

`room.timer(name, frames=0, enabled=None)` creates a saturating countdown.
It exposes `remaining`, `running`, `expired`, `start(frames)`, and `stop()`.
Counts are 0–255 gameplay ticks. Zero stays zero; it does not wrap. Register the
timer before rules that restart/read it for the ordering shown above.

`state_machine(name, states=..., initial=None, enabled=None)` supports up to
16 named states. Entry actions run once, followed by that state's tick actions
and its first matching transition. A transition's destination begins on the
next enabled tick; states never cascade through several updates in one tick.
Use `behavior.is_state("left")` in conditions and `behavior.change("right")`
as an action. Changing to the same state leaves it alone unless `restart=True`.
The optional enabled condition pauses dispatch, preserving its current state.

Timers and nonmodal sequences register ordinary events in call order. Modal
helpers share one exclusive event at the first modal helper's registration
position; later modal helpers join it and share its display-write budget.
Timers and sequences count
gameplay ticks: a large display upload can span several video frames while
gameplay waits for the queue to drain.

## Patrol, health, and checkpoints

```python
room.patrol(guard, left=112, right=200, speed=0.75, animation="walk")
checkpoint = room.checkpoint(player,
    points={"entrance": (40, 208), "ledge": (128, 184)}, initial="entrance")
health = room.health(player, points=3, invulnerability_frames=45)
room.after_physics(If(Overlaps(player, guard),
    health.damage(on_death=(checkpoint.respawn(), health.restore()))))
```

Patrol boundaries refer to the actor's top-left X coordinate. Fractional speed
requires a subpixel actor. The actor must initially be inside its patrol range;
solid walls still block it. Optional `enabled` pauses movement. Patrol selects
facing when supported, and an optional animation clip. It does not detect cliffs
or find paths.

Health exposes `points`, `invulnerability`, `alive`, and `vulnerable`.
`damage(amount=1)` subtracts without underflow and ignores damage during
invulnerability, while hidden/frozen, or when the optional enabled condition is
false. Nonlethal damage runs `on_hurt`; lethal damage runs `on_death` once.
Both are tuples of explicit actions, configurable on the helper or each damage
action. The default death action hides the actor.

`health.restore()` restores maximum health and starts invulnerability;
`restore(points=2, invulnerable=False)` chooses different settings. It does not
show a hidden actor by itself. `checkpoint.respawn()` teleports and shows the
actor, clearing its movement/jump state. `checkpoint.activate("ledge")` selects
a named position. Health restoration, inventory, and room changes remain
explicit. Checkpoint selection and health reset when re-entering a room.

## Sequences and dialogue

```python
from py3nes import Do, Wait, WaitForButton, WriteText

intro = room.sequence("intro",
    Do(WriteText("WELCOME", 2, 10)),
    Wait(60),
    Do(WriteText("PRESS A", 2, 11)),
    WaitForButton(Button.A),
    freeze=(player,),
)
room.on_enter(intro.start())
```

Each sequence executes at most one step per tick. Steps are `Do(*actions)`,
`Wait(1..255)`, `WaitUntil(condition)`, or `WaitForButton(button)`. A bare action
is shorthand for `Do(action)`. There may be up to 255 steps. `active` remains
true until completion; `start()` ignores requests while already active.
`cancel()` ends an active sequence. Optional `on_start` and `on_finish` tuples
run once at their respective lifecycle points; cancellation also runs finish.

```python
from py3nes import Choice

chat = room.dialogue("guide", [
    "THE GARDEN KEY OPENS THE TOWER.",
    "WILL YOU LOOK FOR IT?",
], column=2, row=11, width=28, height=4,
    choices=(Choice("YES", Set(quest_started, True)), Choice("LATER")),
    freeze=(player,))
room.bind_pressed(Button.B, If(near_guide, chat.start()))
```

Text wraps within each supplied page. A page that does not fit raises an error.
A fresh A press advances a completed page; holding A never advances repeatedly.
`button=` selects another confirmation button. Optional two to four choices
occupy the last rows of the final page, reducing its text area. Up/Down moves
the cursor, confirmation runs the selected actions once, and `selection` keeps
its zero-based value until the next start.

**Dialogue reserves a blank rectangle at build time.** It writes one row per
tick through the existing safe VRAM queue, then clears those rows when closed.
It does not restore a background or HUD dynamically written into that area.
Keep the reserved rectangle separate from level graphics and changing HUD text.
Attributes and collision are unchanged. `active` includes drawing and clearing;
cancel also clears the area before releasing control and running finish actions.

`freeze=(player,)` requires `freezable=True` and automatically freezes/resumes
the specified actors. Dialogues and sequences that freeze actors share a
room-local modal lock: starting another while busy is ignored, as is trying to
acquire an actor that was already frozen. Other gameplay rules remain active;
use `enabled=~chat.active` where an enemy or timer should also pause. A room
change abandons the source sequence; it does not run its finish actions.

## FamiStudio music and sound effects

The bundled MIT-licensed FamiStudio 4.5.1 engine supports the standard NTSC pulse,
triangle, and noise channels. DPCM samples, expansion audio, PAL, and custom
tuning are currently unsupported. Song loops and endings come from the project.
See the [upstream sound-engine documentation](https://famistudio.org/doc/soundengine/).

```python
from py3nes import load_famistudio, PlayMusic, PauseMusic, StopMusic

music = load_famistudio("my_music.fms")
room.on_enter(PlayMusic(music, song="Explore"))
game.bind_pressed(Button.SELECT, PauseMusic())
```

Loading `.fms` or FamiStudio text `.txt` invokes the installed editor CLI at
build time. macOS auto-detection finds `/Applications/FamiStudio.app` and its
.NET runtime. Elsewhere, put `FamiStudio` on PATH, set `FAMISTUDIO` to its
executable/app/DLL, or pass `executable=`. Paths with spaces are supported.
The source project is never modified. Export failures are reported as
`MusicExportError`.

To share a game that builds without the editor, export once:

```python
from py3nes import export_famistudio
export_famistudio("my_music.fms", "my_music.music.json")
music = load_famistudio("my_music.music.json")
```

The portable JSON embeds CA65 music data. Direct FamiStudio CA65 `.s`/`.asm`
exports are also accepted. Use FamiStudio tempo consistently across a game's
music assets, or FamiTracker tempo consistently; mixing modes is rejected.

`PlayMusic(music, song=0)` accepts a song index or name. Repeating the current
song keeps it playing; `restart=True` restarts it. Music continues across rooms
unless another music action changes it. `PauseMusic(False)` resumes;
`StopMusic()` stops music while effects can finish. If several music commands
execute in one tick, the last command wins.

```python
from py3nes import PlaySound, SoundEffect, Tone
pickup = SoundEffect((Tone(660, frames=3), Tone(880, frames=3),
                      Tone(1320, frames=5)), priority=2)
room.bind_pressed(Button.B, PlaySound(pickup))
```

Effects contain 1–64 successive tones with independent pitch, volume, duty, and
duration. Priorities are 0–255: higher priority effects take precedence, equal
priorities replace one another, and a plain `Tone` has priority zero. With music,
the FamiStudio mixer chooses between music and the effect on pulse channel 1
by volume, so keep effects louder than that music channel to make them prominent.
Music regains the channel when the effect finishes. There is one effect voice;
`StopSound()` stops it without stopping music.

Open [little_rooms.fms](../examples/assets/music/little_rooms.fms) directly in
FamiStudio and edit the Explore or Victory song. The equivalent
[text project](../examples/assets/music/little_rooms.txt) is also included for
readable source control. After saving the native project, re-export:

```sh
python -c 'from py3nes import export_famistudio; export_famistudio("examples/assets/music/little_rooms.fms", "examples/assets/music/little_rooms.music.json")'
python -m py3nes examples/living_adventure.py -o build/living_adventure.nes
```

The generated assembly embeds the engine, note tables, and music data. It remains
self-contained. Music adds code and work RAM, accounted against the same NROM
limits. Audio updates occur after NMI has completed display transfers and scroll
writes; music continues while gameplay is waiting for a large display upload.
