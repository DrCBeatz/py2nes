"""Directional attack windows and damage reactions, built from runtime commands.

An attack reserves three bytes of room state and no hardware sprites. Register
its start action before post-physics hit rules. A target can be touched only once
per swing, including a target whose invulnerability prevents damage.
"""

from dataclasses import dataclass, field

from .behaviors import Health, _actions, _condition, _name, _transaction
from .ir import Add, Condition, If, Set, Variable
from .model import integer
from .physics import Actor, PlayAnimation, Velocity, fixed


@dataclass(frozen=True, eq=False)
class AttackOverlaps(Condition):
    """Pixel rectangle in front of an actor; signed endpoints never wrap."""
    actor: Actor
    target: Actor
    facing_left: Variable
    reach: int
    height: int
    offset_y: int = 0

    def __post_init__(self):
        if not isinstance(self.actor, Actor) or not isinstance(self.target, Actor):
            raise TypeError("attack overlap needs two actors")
        if not isinstance(self.facing_left, Variable) or self.facing_left.kind != "flag":
            raise TypeError("attack facing must be a runtime flag")
        integer(self.reach, "attack reach", 1, 32)
        integer(self.height, "attack height", 1, 32)
        integer(self.offset_y, "attack offset_y", -31, 31)


@dataclass(frozen=True)
class Attack:
    actor: Actor
    remaining: Variable
    touched: Variable
    facing_left: Variable
    reach: int
    height: int
    offset_y: int
    active_frames: int
    cooldown_frames: int
    enabled: Condition
    animation: str | None
    on_start: tuple
    _game: object = field(repr=False, compare=False)

    @property
    def active(self):
        return self.remaining.gt(self.cooldown_frames)

    @property
    def recovering(self):
        return self.remaining.ne(0) & self.remaining.le(self.cooldown_frames)

    @property
    def busy(self):
        return self.remaining.ne(0)

    @property
    def ready(self):
        return self.remaining.eq(0) & self.enabled

    def start(self):
        """Start if ready; active_frames includes the tick executing this action.

        Facing is captured at start. Cooldown follows the active window; presses
        during either phase are ignored rather than buffered.
        """
        facing = self.actor.facing_left if self.actor.facing_left is not None else False
        animation = (() if self.animation is None else
                     (PlayAnimation(self.actor, self.animation, restart=True),))
        return If(self.ready,
                  Set(self.remaining, self.active_frames + self.cooldown_frames),
                  Set(self.touched, 0), Set(self.facing_left, facing),
                  *animation, *self.on_start)

    def cancel(self):
        return If(True, Set(self.remaining, 0), Set(self.touched, 0))

    def hits(self, target):
        """Test a visible, untouched target; hit() consumes the contact."""
        if not isinstance(target, Actor):
            raise TypeError("attack hits needs an Actor")
        if target is self.actor:
            raise ValueError("an attack cannot target its own actor")
        self._game._validate(target)
        return (self.active & self.enabled &
                (self.touched & (1 << (target.index % 8))).eq(0) &
                AttackOverlaps(self.actor, target, self.facing_left,
                               self.reach, self.height, self.offset_y))

    def hit(self, target, damage=1, *, on_hit=()):
        """Return a post-physics action applying one contact per target/swing.

        target is Health or Hurtbox. Invulnerable contacts are consumed without
        damage or feedback, so expiration cannot cause a late hit in that swing.
        on_hit runs after accepted damage and the target's damage callbacks,
        including lethal hits. A transition in a target callback ends the event
        before subsequent on_hit actions, like other sequential commands.
        """
        if isinstance(target, Hurtbox):
            health = target.health
            damage_action = target.damage(damage, source=self.actor)
        elif isinstance(target, Health):
            health = target
            damage_action = target.damage(damage)
        else:
            raise TypeError("attack hit target must be Health or Hurtbox")
        self._game._validate(health)
        feedback = _actions(on_hit)
        result = If(self.hits(health.actor),
                    Set(self.touched, self.touched | (1 << (health.actor.index % 8))),
                    If(health.vulnerable, damage_action, *feedback))
        self._game._validate(result)
        return result


def attack(game, actor, *, reach=12, height=None, offset_y=0, active_frames=6,
           cooldown_frames=10, animation=None, on_start=(), enabled=None, name=None):
    """Create an attack clock; explicitly bind start() and register hit() rules.

    The rectangle begins immediately outside the actor's collision hitbox.
    Height defaults to that hitbox's height; offset_y is relative to its top.
    Suspend movement/animation selection with attack.active or attack.busy when
    desired. Existing movement and animation rules remain explicit.
    """
    if not isinstance(actor, Actor):
        raise TypeError("attack needs an Actor")
    game._validate(actor)
    name = _name(actor.name if name is None else name)
    height = actor.hitbox.height if height is None else height
    integer(reach, "attack reach", 1, 32)
    integer(height, "attack height", 1, 32)
    integer(offset_y, "attack offset_y", -31, 31)
    integer(active_frames, "attack active_frames", 1, 255)
    integer(cooldown_frames, "attack cooldown_frames", 0, 254)
    if active_frames + cooldown_frames > 255:
        raise ValueError("attack active_frames + cooldown_frames must be at most 255")
    callbacks = _actions(on_start)
    if animation is not None:
        PlayAnimation(actor, animation)
    condition = _condition(enabled, actor)
    with _transaction(game):
        result = Attack(actor, game.byte(f"attack_{name}_remaining"),
                        game.byte(f"attack_{name}_touched"),
                        game.flag(f"attack_{name}_left"), reach, height, offset_y,
                        active_frames, cooldown_frames, condition, animation,
                        callbacks, game)
        game._validate(result.start())
        game.every_frame(If(condition & result.busy, Add(result.remaining, -1)))
    return result


@dataclass(frozen=True)
class Hurtbox:
    """A health receiver with a timed recoil reaction using Actor.hitbox."""
    health: Health
    remaining: Variable
    stun_frames: int
    knockback: int | float
    lift: int | float
    animation: str | None
    on_hurt: tuple
    _game: object = field(repr=False, compare=False)

    @property
    def actor(self):
        return self.health.actor

    @property
    def stunned(self):
        return self.remaining.ne(0)

    def clear(self):
        """Clear pending stun on a checkpoint respawn or other manual reset."""
        return Set(self.remaining, 0)

    def damage(self, amount=1, *, source=None, on_hurt=None, on_death=None):
        """Apply health damage; nonlethal hits recoil away from source's X.

        If source is omitted, horizontal velocity stops during the reaction.
        Death uses Health's callback (or its explicit override) without applying
        recoil to a newly respawned actor. Lethal damage clears previous stun
        before invoking the death callback.
        """
        if source is not None:
            if not isinstance(source, Actor):
                raise TypeError("damage source must be an Actor")
            self._game._validate(source)
        actor = self.actor
        if source is None:
            recoil = Velocity(actor, vx=0, vy=-self.lift)
        else:
            recoil = If(source.x.le(actor.x),
                        Velocity(actor, vx=self.knockback, vy=-self.lift),
                        otherwise=(Velocity(actor, vx=-self.knockback, vy=-self.lift),))
        animation = (() if self.animation is None else
                     (PlayAnimation(actor, self.animation, restart=True),))
        callbacks = self.health.on_hurt if on_hurt is None else _actions(on_hurt)
        clear_jump = (Set(actor.jump_buffer, 0),) if actor.subpixel else ()
        hurt = (Set(self.remaining, self.stun_frames), recoil, *clear_jump,
                *animation, *callbacks, *self.on_hurt)
        death = self.health.on_death if on_death is None else _actions(on_death)
        result = self.health.damage(amount, on_hurt=hurt,
                                    on_death=(Set(self.remaining, 0), *death))
        self._game._validate(result)
        return result


def hurtbox(game, health, *, stun_frames=12, knockback=2, lift=0,
            animation=None, on_hurt=(), enabled=None, name=None):
    """Attach recoil to Health; suspend controls/patrol while stunned.

    Recoil uses normal actor velocity and solid collision. Do not use
    enabled=~stunned for movement helpers that explicitly stop disabled actors;
    their suspended=stunned option preserves recoil while skipping input.
    """
    if not isinstance(health, Health):
        raise TypeError("hurtbox needs Health returned by game.health()")
    game._validate(health)
    actor = health.actor
    name = _name(actor.name if name is None else name)
    integer(stun_frames, "hurt stun_frames", 1, 255)
    fixed(knockback, "hurt knockback", 0, 8)
    fixed(lift, "hurt lift", 0, 8)
    Velocity(actor, vx=knockback, vy=-lift)
    callbacks = _actions(on_hurt)
    if animation is not None:
        PlayAnimation(actor, animation)
    condition = _condition(enabled, actor)
    with _transaction(game):
        result = Hurtbox(health, game.byte(f"hurt_{name}_remaining"), stun_frames,
                         knockback, lift, animation, callbacks, game)
        game._validate(result.damage())
        game.every_frame(If(condition & result.stunned,
                            Add(result.remaining, -1),
                            If(~result.stunned, Velocity(actor, vx=0))))
    return result
