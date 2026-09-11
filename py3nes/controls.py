"""Controller conditions and build-time factories for common movement rules."""

from dataclasses import dataclass

from .ir import Condition, If, Set, as_condition
from .model import Button, Event, Trigger


@dataclass(frozen=True, eq=False)
class ButtonDown(Condition):
    """True while one controller button is held in the current game tick."""

    button: Button

    def __post_init__(self):
        if not isinstance(self.button, Button) or self.button not in tuple(Button):
            raise ValueError("ButtonDown needs one Button")


def platformer(game, actor, *, speed=2, acceleration=0.25, friction=0.25,
               jump_speed=5.5, jump_cut=2, buffer_frames=4, coyote_frames=4,
               left=Button.LEFT, right=Button.RIGHT, jump=Button.A,
               enabled=None, animate=True, suspended=None):
    """Build explicit rules for a subpixel actor; Python runs only at build time.

    Opposite directions cancel. Releasing direction applies friction; releasing
    jump limits upward velocity. ``enabled`` can be a runtime condition such as
    ``~won``. Call once per actor, before additional custom movement overrides.
    """
    from .physics import (Actor, Animate, ApproachVelocity, CutJump, Face, Jump,
                          PlayAnimation, Velocity, fixed)

    if not isinstance(actor, Actor):
        raise TypeError("platformer controls need an Actor")
    game._validate(actor)
    if not actor.subpixel:
        raise ValueError("platformer controls need an actor with subpixel=True or fractional gravity")
    fixed(speed, "speed", 0, 8)
    if speed <= 0:
        raise ValueError("platformer speed must be positive")
    if not isinstance(animate, bool):
        raise TypeError("animate must be a bool")
    left_down, right_down, jump_down = ButtonDown(left), ButtonDown(right), ButtonDown(jump)
    if len({left, right, jump}) != 3:
        raise ValueError("platformer left, right, and jump buttons must be distinct")
    moving = (left_down & ~right_down) | (right_down & ~left_down)
    movement = [If(left_down & ~right_down,
                   ApproachVelocity(actor, vx=-speed, acceleration=acceleration),
                   otherwise=(If(right_down & ~left_down,
                                 ApproachVelocity(actor, vx=speed, acceleration=acceleration),
                                 otherwise=(ApproachVelocity(actor, vx=0, acceleration=friction),)),)),
                If(~jump_down, CutJump(actor, max_rise_speed=jump_cut))]
    if actor.facing_left is not None:
        movement.append(If(left_down & ~right_down, Face(actor, "left"),
                           otherwise=(If(right_down & ~left_down, Face(actor, "right")),)))
    clip_names = {clip.name for clip in actor.clips}
    walk_name = "walk" if "walk" in clip_names else "run"
    named_animation = animate and "idle" in clip_names and walk_name in clip_names
    if animate and not named_animation:
        movement += [If(moving, Animate(actor), otherwise=(Animate(actor, False),))]
    jump_action = Jump(actor, speed=jump_speed, buffer_frames=buffer_frames, coyote_frames=coyote_frames)
    if enabled is not None:
        condition = as_condition(enabled)
        stopped = [Velocity(actor, vx=0), Set(actor.jump_buffer, 0)]
        if animate and not named_animation:
            stopped.append(Animate(actor, False))
        movement = [If(condition, *movement, otherwise=tuple(stopped))]
        jump_action = If(condition, jump_action)
    if actor.frozen is not None:
        movement = [If(~actor.frozen, *movement)]
        jump_action = If(~actor.frozen, jump_action)
    if suspended is not None:
        resumed = ~as_condition(suspended)
        movement = [If(resumed, *movement)]
        jump_action = If(resumed, jump_action)
    events = (Event(Trigger.FRAME, tuple(movement)), Event(Trigger.PRESSED, (jump_action,), jump))
    # Invalid settings cannot leave half a controller setup in the game.
    for event in events:
        game._validate(event)
    post_event = None
    if named_animation:
        moving_now = actor.vx.ne(0) | actor.vx_fraction.ne(0)
        selection = If(moving_now, PlayAnimation(actor, walk_name),
                       otherwise=(PlayAnimation(actor, "idle"),))
        if "fall" in clip_names:
            selection = If(~actor.grounded, PlayAnimation(actor, "fall"), otherwise=(selection,))
        if "jump" in clip_names:
            selection = If(actor.vy.lt(0), PlayAnimation(actor, "jump"), otherwise=(selection,))
        active = as_condition(True if enabled is None else enabled) & actor.visible
        if actor.frozen is not None:
            active = active & ~actor.frozen
        if suspended is not None:
            active = active & ~as_condition(suspended)
        post_event = Event(Trigger.FRAME, (If(active, selection),))
        game._validate(post_event)
    registered = tuple(game.add_event(event) for event in events)
    if post_event is not None:
        post_event = game._scoped_event(post_event)
        game._post_events.append(post_event)
        registered += (post_event,)
    return registered
