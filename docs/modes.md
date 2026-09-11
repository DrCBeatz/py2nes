# Game modes and pausing

Modes give the runtime one explicit scheduler state: title, playing, paused,
game over, victory, or another name chosen by the game. Python builds the mode
descriptions; the resulting byte state and dispatch code execute on the NES.

```python
from py3nes import Button, Game, WriteText

game = Game()
title = game.mode("title")
playing = game.mode("playing", gameplay=True)
paused = game.mode("paused", pause_music=True)
game.start_mode(title)

title.on_enter(WriteText("PRESS START", column=10, row=12))
playing.on_enter(WriteText("", column=10, row=12, width=11))
paused.on_enter(WriteText("PAUSED", column=10, row=12, width=11))

# Register global mode controls before ordinary rules.
game.bind_pressed(Button.START, playing.change(), scope=title)
game.bind_pressed(Button.START, paused.change(), scope=playing)
game.bind_pressed(Button.START, playing.change(), scope=paused)
```

The first registered mode is the default start mode; `start_mode()` selects a
different one. Up to sixteen modes are supported. Modes belong to `Game`, and
room events may reference any of that game's modes. Games that do not register
modes retain the original scheduling and allocate no mode state.

## What pauses

Only modes declared `gameplay=True` advance actor physics and animation. In
other modes, actor positions, velocities, grounded/jump state and animation
counters remain in place. Actors are still rendered, so menu rules can explicitly
show, hide, reposition or select an animation frame without advancing physics.

Ordinary events also run only in gameplay modes. This includes helper-generated
platformer input, enemy behaviors, health/invulnerability timers, attacks,
state machines, and sequences. They retain their state while suspended and
resume from it. A mode does not reset a room or its variables.

The controller continues to be sampled, the PPU upload queue continues to drain,
and sound effects continue. `pause_music=True` also mutes and freezes the song.
Leaving that mode releases its music hold; a separate explicit `PauseMusic()`
hold remains until `PauseMusic(False)`. `PlayMusic` can still select/restart a
song during a paused mode, and the selected song remains paused. Audio changes
become visible to NMI only after main publishes a complete tick.

## Event scopes and menu sequences

`bind_pressed`, `bind_held`, `every_frame`, and `after_physics` accept `scope=`:

| Scope | When the event runs |
| --- | --- |
| Omitted / `"gameplay"` | Any mode with `gameplay=True` |
| A `GameMode` | Only that exact mode |
| `"always"` | Every mode |

Use a build-time context to scope all events emitted by a helper:

```python
from py3nes import Do, Wait, WriteText

victory = game.mode("victory")
with game.during(victory):
    ending = game.sequence(
        "ending",
        Do(WriteText("YOU WIN!", column=12, row=10)),
        Wait(90),
        Do(WriteText("PRESS START", column=10, row=12)),
    )
victory.on_enter(ending.start())
game.bind_pressed(Button.START, title.change(), scope=victory)
```

This sequence advances while gameplay is suspended. A `room.during(mode)`
context scopes just that room's new rules. A `game.during(mode)` context also
applies to room rules built inside it unless a room context overrides it.
Contexts nest and restore the previous scope on exit, including exceptions.
Explicit `scope="gameplay"` overrides a surrounding menu context.

`after_physics` events in menu/always scopes still run in the post-event phase,
even when physics itself is suspended. Scope changes preserve registration
order; they do not reorder events or grant menu inputs priority. Put pause/menu
bindings before gameplay rules when those bindings must interrupt that tick.

Wait durations count completed ticks of the sequence's scope, not elapsed video
frames. Display backpressure may hold all tick scheduling while queued writes
upload. Modal sequences still share their room's modal lock across scopes: an
active gameplay conversation keeps its lock while paused. Use a normal sequence
for a pause overlay, or explicitly finish the conversation before starting a
different modal one.

## Transitions and state lifetime

`mode.active` is a runtime condition. `mode.change()` constructs `ChangeMode`;
requesting the already active mode is ignored. `mode.change(restart=True)`
executes entry again even if that mode is already active.

A taken mode change ends the current event immediately and skips the remaining
rules and physics for that tick. Earlier RAM changes remain. Unpublished display
writes from the source tick are discarded before the new mode's entry actions;
already published uploads complete first. Entry actions run once, and the new
mode's ordinary rules begin on the next tick. The controller's previous state
is preserved, so holding the button that opened a menu does not create another
fresh press when gameplay resumes.

`mode.on_enter(...)` runs after startup room initialization and on every taken
transition. It uses game-level variables and may contain `ChangeRoom`. Code
after a taken room change is skipped as usual. The destination room resets its
temporary state, applies its spawn and runs `room.on_enter`, even in a paused
or title mode. This makes an explicit new-game flow straightforward:

```python
from py3nes import ChangeRoom, If, Set

new_run = game.flag("new_run", True)
# hall and its "start" entrance are created elsewhere in the game description.
playing.on_enter(If(new_run, Set(new_run, False), ChangeRoom(hall, "start")))
game.bind_pressed(Button.START, Set(new_run, True), playing.change(), scope=title)
```

Mode entry may not recursively change mode, and room entry may not change room
or mode. Put subsequent transitions in scoped events or sequences. Screen
contents are not automatically cleared when modes change; use explicit writes
or a room change. Each mode's entry has its own 64-tile-write budget. Ordinary
event budgets account for mutually exclusive scopes rather than adding every
menu's writes together.

Sequences preserve their program counters across mode changes. A transition
inside a sequence step or dialogue answer advances that step immediately before
suspending it, preventing the transition from replaying when its mode resumes.
A final transitioning step runs sequence cleanup and `on_finish` before changing
mode. Dialogue clearing after a transitioning answer resumes with its original
mode; for a fully closed window before leaving, change mode from `on_finish`.

See [`polished_adventure.py`](../examples/polished_adventure.py) for title,
pause, game-over and victory flows combined with rooms, combat and music.
