"""Reusable gameplay descriptions lowered to ordinary byte/condition actions.

Factories register events in call order. Their state is local to the Game/Room
on which they are created, and room-local state resets on every room entry.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType

from .ir import ActionSpec, Add, If, Set, Variable, as_condition
from .model import integer
from .physics import Actor, Face, Hide, PlayAnimation, Show, Teleport, Velocity, fixed


def _name(value, kind="behavior name"):
    if not isinstance(value, str) or not value.isascii() or not value.isidentifier():
        raise ValueError(f"{kind} must be an ASCII identifier")
    return value


def _actions(values):
    values = tuple(values)
    if any(not isinstance(action, ActionSpec) for action in values):
        raise TypeError("behavior actions must be explicit actions, not Python callbacks")
    return values


def _condition(enabled, actor=None):
    result = as_condition(True if enabled is None else enabled)
    if actor is not None:
        result = result & actor.visible
        if actor.frozen is not None:
            result = result & ~actor.frozen
    return result


@contextmanager
def _transaction(game):
    """A failed helper cannot consume variable names, bytes, or event slots."""
    lists = [(getattr(game, key), len(getattr(game, key)))
             for key in ("_variables", "_events", "_post_events")]
    names = set(game._user_names) if hasattr(game, "_user_names") else None
    try:
        yield
    except (TypeError, ValueError):
        for values, size in lists:
            del values[size:]
        if names is not None:
            game._user_names.clear()
            game._user_names.update(names)
        raise


@dataclass(frozen=True)
class Timer:
    """A saturating byte countdown. Expiration remains true until restarted."""
    remaining: Variable

    @property
    def expired(self):
        return self.remaining.eq(0)

    @property
    def running(self):
        return self.remaining.ne(0)

    def start(self, frames):
        integer(frames, "timer frames", 0, 255)
        return Set(self.remaining, frames)

    def stop(self):
        return Set(self.remaining, 0)


def timer(game, name, *, frames=0, enabled=None):
    """Register one decrement per tick, before subsequently registered events.

    Starting from a later event retains the full requested count for that tick.
    A countdown begun at N expires on its Nth subsequent enabled update.
    """
    _name(name, "timer name")
    integer(frames, "timer frames", 0, 255)
    condition = _condition(enabled)
    with _transaction(game):
        result = Timer(game.byte(f"timer_{name}", frames))
        game.every_frame(If(condition & result.running, Add(result.remaining, -1)))
    return result


@dataclass(frozen=True)
class Transition:
    condition: object
    target: str

    def __post_init__(self):
        object.__setattr__(self, "condition", as_condition(self.condition))
        _name(self.target, "transition target")


@dataclass(frozen=True)
class State:
    enter: tuple = ()
    tick: tuple = ()
    transitions: tuple[Transition, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "enter", _actions(self.enter))
        object.__setattr__(self, "tick", _actions(self.tick))
        transitions = tuple(self.transitions)
        if any(not isinstance(t, Transition) for t in transitions):
            raise TypeError("state transitions must be Transition descriptions")
        if len(transitions) > 16:
            raise ValueError("maximum 16 transitions per state")
        object.__setattr__(self, "transitions", transitions)


@dataclass(frozen=True)
class StateMachine:
    current: Variable
    entered: Variable
    names: tuple[str, ...]

    def is_state(self, name):
        return self.current.eq(self._index(name))

    def _index(self, name):
        try:
            return self.names.index(name)
        except ValueError:
            raise ValueError(f"unknown state {name!r}") from None

    def change(self, name, *, restart=False):
        if not isinstance(restart, bool):
            raise TypeError("state restart must be a bool")
        index = self._index(name)
        return If(True if restart else self.current.ne(index),
                  Set(self.current, index), Set(self.entered, False))


def state_machine(game, name, *, states, initial=None, enabled=None):
    """Run one state's tick and first matching transition per enabled frame.

    Entry actions run once before a state's first tick. A transition selects the
    next state immediately; its entry and tick run on the next enabled frame.
    Pausing preserves both the selected state and pending entry.
    """
    _name(name, "state machine name")
    states = dict(states)
    if not states or len(states) > 16:
        raise ValueError("a state machine needs between 1 and 16 states")
    for key, state in states.items():
        _name(key, "state name")
        if not isinstance(state, State):
            raise TypeError("state machine values must be State descriptions")
        for transition in state.transitions:
            if transition.target not in states:
                raise ValueError(f"unknown transition state {transition.target!r}")
    names = tuple(states)
    initial = names[0] if initial is None else initial
    if initial not in states:
        raise ValueError(f"unknown initial state {initial!r}")
    condition = _condition(enabled)
    with _transaction(game):
        result = StateMachine(game.byte(f"state_{name}", names.index(initial)),
                              game.flag(f"state_{name}_entered"), names)
        branches = []
        for key, state in states.items():
            transitions = ()
            for transition in reversed(state.transitions):
                transitions = (If(transition.condition,
                                  result.change(transition.target, restart=True), otherwise=transitions),)
            body = (If(~result.entered, Set(result.entered, True), *state.enter),) + state.tick + transitions
            branches.append(body)

        def dispatch(start, end):
            # A balanced selector avoids spending one nesting level per state,
            # leaving room for transition priority and user conditions.
            if end - start == 1:
                return If(result.current.eq(start), *branches[start])
            middle = (start + end) // 2
            return If(result.current.lt(middle), dispatch(start, middle),
                      otherwise=(dispatch(middle, end),))

        game.every_frame(If(condition, dispatch(0, len(branches))))
    return result


@dataclass(frozen=True)
class Patrol:
    actor: Actor
    moving_left: Variable


def patrol(game, actor, *, left, right, speed=1, enabled=None, animation=None, name=None,
           suspended=None):
    """Move between two top-left X coordinates; solid walls still stop motion.

    ``suspended`` skips steering and endpoint clamping while preserving velocity,
    for example during a combat recoil. ``enabled=False`` stops horizontal motion.
    """
    if not isinstance(actor, Actor):
        raise TypeError("patrol needs an Actor")
    game._validate(actor)
    integer(left, "patrol left", 0, 256 - actor.width)
    integer(right, "patrol right", 0, 256 - actor.width)
    if left >= right:
        raise ValueError("patrol left must be less than right")
    if not left <= actor.initial_x <= right:
        raise ValueError("patrol actor must start within its patrol range")
    fixed(speed, "patrol speed", 1 / 256, 8)
    name = _name(actor.name if name is None else name)
    steering = as_condition(True) if suspended is None else ~as_condition(suspended)
    with _transaction(game):
        result = Patrol(actor, game.flag(f"patrol_{name}_left"))
        # The integer coordinate alone does not mean the left endpoint was
        # reached: x=left with fraction=192 is still 0.75 pixels to its right.
        at_left = (actor.x.lt(left) | (actor.x.eq(left) & actor.x_fraction.eq(0))
                   if actor.subpixel else actor.x.le(left))
        going_left = [Velocity(actor, vx=-speed)]
        going_right = [Velocity(actor, vx=speed)]
        if actor.facing_left is not None:
            going_left.append(Face(actor, "left"))
            going_right.append(Face(actor, "right"))
        actions = [If(actor.x.ge(right), Set(result.moving_left, True),
                      otherwise=(If(at_left, Set(result.moving_left, False)),)),
                   If(result.moving_left, *going_left, otherwise=tuple(going_right))]
        if animation is not None:
            actions.append(PlayAnimation(actor, animation))
        active = as_condition(True if enabled is None else enabled) & actor.visible
        movement = If(active, *actions, otherwise=(Velocity(actor, vx=0),))
        if actor.frozen is not None:
            movement = If(~actor.frozen, movement)
        if suspended is not None:
            movement = If(steering, movement)
        game.every_frame(movement)
        reset_fraction = (Set(actor.x_fraction, 0),) if actor.subpixel else ()
        clamping = _condition(enabled, actor)
        if suspended is not None:
            clamping = clamping & steering
        game.after_physics(If(clamping,
                             If(actor.x.ge(right), Set(actor.x, right), *reset_fraction,
                                Set(result.moving_left, True),
                                otherwise=(If(at_left, Set(actor.x, left), *reset_fraction,
                                              Set(result.moving_left, False)),))))
    return result


@dataclass(frozen=True)
class Health:
    actor: Actor
    points: Variable
    invulnerability: Variable
    maximum: int
    invulnerability_frames: int
    on_hurt: tuple
    on_death: tuple
    enabled: object

    @property
    def alive(self):
        return self.points.ne(0)

    @property
    def vulnerable(self):
        return self.alive & self.invulnerability.eq(0) & self.enabled

    def damage(self, amount=1, *, on_hurt=None, on_death=None):
        """Apply saturating damage once while vulnerable; lethal damage runs death actions."""
        integer(amount, "damage amount", 1, 255)
        hurt = self.on_hurt if on_hurt is None else _actions(on_hurt)
        death = self.on_death if on_death is None else _actions(on_death)
        return If(self.vulnerable,
                  Set(self.invulnerability, self.invulnerability_frames),
                  If(self.points.le(amount), Set(self.points, 0), *death,
                     otherwise=(Add(self.points, -amount), *hurt)))

    def restore(self, points=None, *, invulnerable=True):
        points = self.maximum if points is None else points
        integer(points, "restored health", 1, self.maximum)
        if not isinstance(invulnerable, bool):
            raise TypeError("invulnerable must be a bool")
        return If(True, Set(self.points, points),
                  Set(self.invulnerability, self.invulnerability_frames if invulnerable else 0))


def health(game, actor, *, points=3, invulnerability_frames=60, on_hurt=(),
           on_death=None, enabled=None, name=None):
    """Attach room-local health; call damage() from contact/attack events."""
    if not isinstance(actor, Actor):
        raise TypeError("health needs an Actor")
    game._validate(actor)
    integer(points, "health points", 1, 255)
    integer(invulnerability_frames, "invulnerability_frames", 0, 255)
    name = _name(actor.name if name is None else name)
    hurt = _actions(on_hurt)
    death = (Hide(actor),) if on_death is None else _actions(on_death)
    condition = _condition(enabled, actor)
    with _transaction(game):
        result = Health(actor, game.byte(f"health_{name}", points),
                        game.byte(f"health_{name}_invulnerability"), points,
                        invulnerability_frames, hurt, death, condition)
        # Validate callbacks now, even if no damage action is later registered.
        game._validate(result.damage())
        game.every_frame(If(condition & result.invulnerability.ne(0), Add(result.invulnerability, -1)))
    return result


@dataclass(frozen=True)
class Checkpoint:
    actor: Actor
    current: Variable
    placements: object

    def activate(self, name):
        try:
            index = tuple(self.placements).index(name)
        except ValueError:
            raise ValueError(f"unknown checkpoint {name!r}") from None
        return Set(self.current, index)

    def respawn(self):
        actions = ()
        for index, (x, y) in reversed(tuple(enumerate(self.placements.values()))):
            actions = (If(self.current.eq(index), Teleport(self.actor, x, y), Show(self.actor), otherwise=actions),)
        return actions[0]


def checkpoint(game, actor, *, points=None, initial=None, name=None):
    """Remember one named placement within this room; respawn clears motion state.

    Health and inventory are explicit: compose respawn() with health.restore()
    when appropriate. Room transitions reset this local checkpoint selection.
    """
    if not isinstance(actor, Actor):
        raise TypeError("checkpoint needs an Actor")
    game._validate(actor)
    points = {"start": (actor.initial_x, actor.initial_y)} if points is None else dict(points)
    if not points or len(points) > 16:
        raise ValueError("checkpoint needs between 1 and 16 placements")
    for key, position in points.items():
        _name(key, "checkpoint placement name")
        position = tuple(position)
        if len(position) != 2:
            raise ValueError("checkpoint placement must be an (x, y) pair")
        Teleport(actor, *position)
        points[key] = position
    initial = next(iter(points)) if initial is None else initial
    if initial not in points:
        raise ValueError(f"unknown initial checkpoint {initial!r}")
    name = _name(actor.name if name is None else name)
    with _transaction(game):
        result = Checkpoint(actor, game.byte(f"checkpoint_{name}", tuple(points).index(initial)),
                            MappingProxyType(points))
        game._validate(result.respawn())
    return result
