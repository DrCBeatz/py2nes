# Directional attacks and recoil

Combat builds on actors, health, and named animations. An attack is a temporary
rectangle in front of an actor's collision hitbox; it does not allocate a sprite
or another actor. All timers and checks become explicit 6502 instructions.

```python
from py3nes import Button, PlaySound, Velocity

guard_health = room.health(guard, points=2, invulnerability_frames=20)
guard_hurt = room.hurtbox(guard_health, stun_frames=12, knockback=2, lift=1,
                          animation="hurt", on_hurt=(PlaySound(hit_sound),))
room.patrol(guard, left=112, right=200, speed=0.75, animation="walk",
            enabled=guard_health.alive, suspended=guard_hurt.stunned)

sword = room.attack(player, reach=14, height=12, offset_y=2,
    active_frames=8, cooldown_frames=12, animation="attack",
    on_start=(Velocity(player, vx=0), PlaySound(swing_sound)))
room.bind_pressed(Button.B, sword.start())
room.after_physics(sword.hit(guard_hurt))
```

## Attack lifecycle

`game.attack(actor, ...)` returns an `Attack` with:

- `start()`: an action that begins a ready attack and captures facing.
- `cancel()`: an action that clears its active window and recovery.
- `active`: a condition true during the attack's damage window.
- `recovering`: a condition true during its subsequent cooldown.
- `busy`: a condition true during either phase.
- `ready`: a condition true when idle, visible, unfrozen, and enabled.
- `hits(actor)`: a condition that checks an untouched target without consuming it.
- `hit(health_or_hurtbox, damage=1, on_hit=())`: an action that consumes contact
  and applies damage when the target is vulnerable.

The active window includes the tick executing `start()`. Recovery follows it;
`active_frames + cooldown_frames` must fit 1–255 gameplay ticks. Further starts
while busy are ignored. Holding a button bound through `bind_pressed` does not
repeat an attack; a fresh press is required. Optional `enabled` pauses its clock
and disables starting/hitting while false. Hidden or frozen actors also pause it.

Each actor can be touched once per swing. Contact with an invulnerable target
still consumes that target's contact, preventing delayed damage when its
invulnerability expires. `on_hit` runs only when damage is accepted, including a
lethal hit. It follows the target's damage and health callbacks; a room or mode
transition in those callbacks ends the event before later feedback. Register
`hit()` in `after_physics` so it checks the final positions
for that tick. Multiple target rules can share an attack.

Facing is captured when an attack starts, so changing the actor's facing later
does not redirect the current swing. Actors without facing state attack right.
`reach` and `height` are 1–32 pixels; height defaults to the actor hitbox height.
`offset_y` is −31…31 relative to the hitbox's top edge. Right-facing rectangles
begin at its right edge; left-facing rectangles end at its left edge. Merely
touching rectangle edges is not a hit. Signed endpoint calculations prevent an
attack extending off-screen from wrapping around and hitting the opposite edge.

An attack uses three room-state bytes. Geometry checks share three work-RAM
scratch bytes. Attack state resets on room entry. Its animation and `on_start`
actions are optional; the caller decides how movement behaves during a swing.

## Hurt reactions and movement

`game.hurtbox(health, stun_frames=12, knockback=2, lift=0, animation=None,
on_hurt=(), enabled=None)` adds a one-byte stun countdown to an existing Health.
It reuses the actor's collision hitbox and exposes `stunned` and `clear()`.

```python
player_health = room.health(player, points=3, invulnerability_frames=45)
player_hurt = room.hurtbox(player_health, stun_frames=12, knockback=2, lift=1.5,
                           animation="hurt", on_hurt=(PlaySound(hit_sound),))
room.platformer(player, suspended=player_hurt.stunned | sword.active,
                 animate=False)
room.after_physics(If(Overlaps(player, guard),
    player_hurt.damage(source=guard, on_hurt=(sword.cancel(),))))
```

`hurtbox.damage(amount=1, source=None, on_hurt=None, on_death=None)` first checks
the underlying Health's vulnerability. Accepted nonlethal damage sets stun,
applies velocity away from the source's X coordinate, clears a buffered jump,
starts the hurt animation, and runs feedback. `lift` is upward speed; fractional
values require a subpixel actor. When source is omitted, horizontal speed becomes
zero. Solid-map collision remains active during recoil. At the end of stun,
horizontal recoil stops.

Movement helpers distinguish **disabled** from **suspended**:

- `enabled=False` makes platformer/patrol controls stop horizontal movement.
- `suspended=True` skips their steering and animation selection while preserving
  existing velocity. Use this for recoil or an active attack.

For custom animation rules, skip normal idle/walk selection while stunned or
attacking so it does not replace the hurt/attack clip immediately. The example
also cancels an active player swing when damage is accepted.

Health's original `on_hurt` callback runs unless explicitly overridden on
`damage()`. Hurtbox's own feedback is appended to nonlethal reactions. Lethal
damage clears old stun and runs the original or overridden death callback without
adding recoil to a respawned actor. Compose death behavior explicitly:

```python
room.after_physics(If(Overlaps(player, guard),
    player_hurt.damage(source=guard, on_death=(
        sword.cancel(), checkpoint.respawn(), player_health.restore(),
    ))))
```

Attack, health, and stun clocks use gameplay ticks and pause with ordinary
game-mode rules. They reset with their room. Inventory and lives can remain
global. Combat does not choose enemy AI, award points, or create projectiles;
use its actions and conditions to compose those rules.

See [polished_adventure.py](../examples/polished_adventure.py) for a complete game
with two-hit guards, three lives, checkpoints, title/pause/game-over modes, and
an ending sequence. Its graphics, sound effects, and attack timings are editable
Python descriptions.
