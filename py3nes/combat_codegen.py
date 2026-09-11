"""Lower attack rectangles with biased 16-bit endpoints at screen edges."""

from .combat import AttackOverlaps


def emit_condition(compiler, condition, false_label):
    if not isinstance(condition, AttackOverlaps):
        return None
    if not hasattr(compiler, "_combat_scratch"):
        compiler._combat_scratch = tuple(
            compiler.reserve(name) for name in
            ("combat_edge", "combat_edge_hi", "combat_other")
        )
    edge, high, other = compiler._combat_scratch
    physics = compiler.physics
    lines = []
    for actor in (condition.actor, condition.target):
        lines += physics._active_room(actor, false_label)
        visible = compiler.unique("attack_visible")
        lines += [f"    lda {compiler.var(actor.visible)}", f"    bne {visible}",
                  f"    jmp {false_label}", f"{visible}:"]

    def endpoint(actor, axis, delta, destination):
        # Bias by 256 so negative endpoints remain ordered unsigned words.
        value = 256 + delta
        return [f"    lda {compiler.var(getattr(actor, axis))}", "    clc",
                f"    adc #{value & 255}", f"    sta {destination}",
                f"    lda #{value >> 8}", "    adc #0"]

    def before(first, first_delta, second, second_delta, axis):
        upper = compiler.unique("attack_upper")
        okay = compiler.unique("attack_axis")
        return (endpoint(first, axis, first_delta, edge) + [f"    sta {high}"] +
                endpoint(second, axis, second_delta, other) +
                [f"    cmp {high}", f"    bcs {upper}", f"    jmp {false_label}",
                 f"{upper}:", f"    bne {okay}", f"    lda {other}",
                 f"    cmp {edge}", f"    bcs {okay}", f"    jmp {false_label}", f"{okay}:"])

    actor, target = condition.actor, condition.target
    left, right, done = (compiler.unique("attack_left"), compiler.unique("attack_right"),
                         compiler.unique("attack_x_done"))
    lines += [f"    lda {compiler.var(condition.facing_left)}", f"    beq {right}",
              f"    jmp {left}", f"{right}:"]
    # Inclusive pixel intervals: touching edges with no shared pixel is false.
    start = actor.hitbox.offset_x + actor.hitbox.width
    target_end = target.hitbox.offset_x + target.hitbox.width - 1
    lines += before(actor, start, target, target_end, "x")
    lines += before(target, target.hitbox.offset_x, actor, start + condition.reach - 1, "x")
    lines += [f"    jmp {done}", f"{left}:"]
    start = actor.hitbox.offset_x - condition.reach
    lines += before(actor, start, target, target_end, "x")
    lines += before(target, target.hitbox.offset_x, actor, actor.hitbox.offset_x - 1, "x")
    lines += [f"{done}:"]
    top = actor.hitbox.offset_y + condition.offset_y
    lines += before(actor, top, target,
                    target.hitbox.offset_y + target.hitbox.height - 1, "y")
    lines += before(target, target.hitbox.offset_y, actor, top + condition.height - 1, "y")
    return lines
