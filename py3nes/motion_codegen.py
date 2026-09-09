"""Optional 8.8 motion layered over the shared one-pixel collision sweep."""

from textwrap import dedent

from .physics import ApproachVelocity, CutJump, Jump, Velocity, fixed


class MotionRuntime:
    def __init__(self, physics):
        self.physics = physics
        self.compiler = physics.compiler
        for key in ("xf", "yf", "vxf", "vyf", "vxh", "vyh", "gravity_lo", "gravity_hi",
                    "fall_lo", "fall_hi", "hitx", "hity", "value_lo", "value_hi",
                    "target_lo", "target_hi", "step_lo", "step_hi"):
            self.compiler.reserve("motion_" + key)

    def var(self, actor, key):
        return self.physics._var(actor, key)

    def state_in(self, actor):
        lines = []
        for key, scratch in (("x_fraction", "xf"), ("y_fraction", "yf"),
                             ("vx_fraction", "vxf"), ("vy_fraction", "vyf")):
            lines += [f"    lda {self.var(actor, key)}", f"    sta motion_{scratch}"]
        for key, value in (("gravity", actor.gravity), ("fall", actor.max_fall_speed)):
            n = fixed(value, key, 0, 8)
            lines += [f"    lda #{n & 255}", f"    sta motion_{key}_lo",
                      f"    lda #{n >> 8}", f"    sta motion_{key}_hi"]
        return lines

    def state_out(self, actor):
        lines = []
        for key, scratch in (("x_fraction", "xf"), ("y_fraction", "yf"),
                             ("vx_fraction", "vxf"), ("vy_fraction", "vyf")):
            lines += [f"    lda motion_{scratch}", f"    sta {self.var(actor, key)}"]
        return lines

    def _store_velocity(self, actor, key, value):
        n = fixed(value, key)
        return [f"    lda #${(n >> 8) & 255:02X}", f"    sta {self.var(actor, key)}",
                f"    lda #${n & 255:02X}", f"    sta {self.var(actor, key + '_fraction')}"]

    def emit_action(self, action):
        if not isinstance(action, (ApproachVelocity, Jump, CutJump, Velocity)):
            return None
        actor = action.actor
        if not actor.subpixel:
            return None
        self.var(actor, "x")
        if isinstance(action, Velocity):
            lines = []
            for key in ("vx", "vy"):
                value = getattr(action, key)
                if value is None:
                    continue
                if isinstance(value, (int, float)):
                    lines += self._store_velocity(actor, key, value)
                else:
                    clamp = "physics_clamp_velocity" if value.kind == "i8" else "physics_clamp_unsigned"
                    lines += self.compiler.load(value) + [f"    jsr {clamp}",
                              f"    sta {self.var(actor, key)}", "    lda #0",
                              f"    sta {self.var(actor, key + '_fraction')}"]
            return lines
        if isinstance(action, Jump):
            n = fixed(-action.speed, "jump speed")
            return [f"    lda #{action.buffer_frames + 1}", f"    sta {self.var(actor, 'jump_buffer')}",
                    f"    lda #{action.coyote_frames}", f"    sta {self.var(actor, 'jump_coyote')}",
                    f"    lda #${(n >> 8) & 255:02X}", f"    sta {self.var(actor, 'jump_speed')}",
                    f"    lda #${n & 255:02X}", f"    sta {self.var(actor, 'jump_fraction')}"]
        if isinstance(action, CutJump):
            # Signed 16-bit compare: XOR the sign bit of each high byte.
            n = fixed(-action.max_rise_speed, "max_rise_speed")
            cut = self.compiler.unique("jump_cut")
            done = self.compiler.unique("jump_cut_done")
            return [f"    lda {self.var(actor, 'vy')}", "    eor #$80",
                    f"    cmp #${((n >> 8) & 255) ^ 128:02X}", f"    bcc {cut}",
                    f"    bne {done}", f"    lda {self.var(actor, 'vy_fraction')}",
                    f"    cmp #${n & 255:02X}", f"    bcs {done}", f"{cut}:",
                    *self._store_velocity(actor, "vy", -action.max_rise_speed), f"{done}:"]
        lines = []
        step = fixed(action.acceleration, "acceleration", 0, 8)
        for key in ("vx", "vy"):
            value = getattr(action, key)
            if value is None:
                continue
            n = fixed(value, key)
            lines += [f"    lda {self.var(actor, key)}", "    sta motion_value_hi",
                      f"    lda {self.var(actor, key + '_fraction')}", "    sta motion_value_lo",
                      f"    lda #${(n >> 8) & 255:02X}", "    sta motion_target_hi",
                      f"    lda #${n & 255:02X}", "    sta motion_target_lo",
                      f"    lda #{step >> 8}", "    sta motion_step_hi",
                      f"    lda #{step & 255}", "    sta motion_step_lo",
                      "    jsr motion_approach", "    lda motion_value_hi",
                      f"    sta {self.var(actor, key)}", "    lda motion_value_lo",
                      f"    sta {self.var(actor, key + '_fraction')}"]
        return lines

    def jump_attempt(self, actor):
        """Try pending input before physics and again on the landing tick."""
        done = self.compiler.unique("jump_attempt_done")
        take = self.compiler.unique("jump_take")
        return [f"    lda {self.var(actor, 'jump_buffer')}", f"    beq {done}",
                f"    lda {self.var(actor, 'grounded')}", f"    bne {take}",
                f"    lda {self.var(actor, 'jump_coyote')}",
                f"    cmp {self.var(actor, 'air_frames')}", f"    bcc {done}",
                f"{take}:", f"    lda {self.var(actor, 'jump_speed')}",
                f"    sta {self.var(actor, 'vy')}", f"    lda {self.var(actor, 'jump_fraction')}",
                f"    sta {self.var(actor, 'vy_fraction')}", "    lda #0",
                f"    sta {self.var(actor, 'jump_buffer')}", f"    sta {self.var(actor, 'grounded')}",
                f"    sta {self.var(actor, 'y_fraction')}", "    lda #255",
                f"    sta {self.var(actor, 'air_frames')}", f"{done}:"]

    def after_tick(self, actor):
        airborne = self.compiler.unique("motion_airborne")
        done = self.compiler.unique("motion_air_done")
        expired = self.compiler.unique("motion_buffer_done")
        return [f"    lda {self.var(actor, 'grounded')}", f"    beq {airborne}",
                "    lda #0", f"    sta {self.var(actor, 'air_frames')}", f"    jmp {done}",
                f"{airborne}:", f"    lda {self.var(actor, 'air_frames')}", "    cmp #255",
                f"    beq {done}", f"    inc {self.var(actor, 'air_frames')}", f"{done}:",
                *self.jump_attempt(actor), f"    lda {self.var(actor, 'jump_buffer')}",
                f"    beq {expired}", f"    dec {self.var(actor, 'jump_buffer')}", f"{expired}:"]

    def routines(self):
        source = '''
            motion_tick:
                ; Coordinates remain integer pixels plus an unsigned fraction.
                lda phys_x
                cmp phys_maxx
                bcc motion_bound_x
                lda phys_maxx
                sta phys_x
                lda #0
                sta motion_xf
            motion_bound_x:
                lda phys_y
                bne motion_nonzero_y
                lda #1
                sta phys_y
                lda #0
                sta motion_yf
            motion_nonzero_y:
                lda phys_y
                cmp phys_maxy
                bcc motion_bound_y
                lda phys_maxy
                sta phys_y
                lda #0
                sta motion_yf
            motion_bound_y:
                lda phys_vx
                jsr physics_clamp_velocity
                cmp phys_vx
                beq motion_clamp_x_unchanged
                sta phys_vx
                lda #0
                sta motion_vxf
            motion_clamp_x_unchanged:
                lda phys_vx
                cmp #8
                bne motion_clamp_y
                lda #0
                sta motion_vxf
            motion_clamp_y:
                lda phys_vy
                jsr physics_clamp_velocity
                cmp phys_vy
                beq motion_clamp_y_unchanged
                sta phys_vy
                lda #0
                sta motion_vyf
            motion_clamp_y_unchanged:
                lda phys_vy
                cmp #8
                bne motion_gravity
                lda #0
                sta motion_vyf
            motion_gravity:
                lda motion_gravity_lo
                ora motion_gravity_hi
                beq motion_no_gravity
                lda motion_vyf
                clc
                adc motion_gravity_lo
                sta motion_vyf
                lda phys_vy
                adc motion_gravity_hi
                sta phys_vy
                bmi motion_no_gravity
                cmp motion_fall_hi
                bcc motion_no_gravity
                bne motion_terminal
                lda motion_vyf
                cmp motion_fall_lo
                bcc motion_no_gravity
            motion_terminal:
                lda motion_fall_hi
                sta phys_vy
                lda motion_fall_lo
                sta motion_vyf
            motion_no_gravity:
                lda #0
                sta motion_hitx
                sta motion_hity
                lda phys_vx
                sta motion_vxh
                lda phys_vy
                sta motion_vyh
                ; Carry from each fraction addition is the extra integer pixel.
                lda motion_xf
                clc
                adc motion_vxf
                sta motion_xf
                lda phys_vx
                adc #0
                sta phys_vx
                jsr physics_horizontal
                ; A fractional right edge also touches the next pixel. Without
                ; this probe a slow actor could retain velocity against a wall.
                lda motion_xf
                beq motion_horizontal_complete
                lda phys_x
                cmp phys_maxx
                bcs motion_fractional_wall
                inc phys_x
                jsr physics_collision_test
                dec phys_x
                cmp #0
                beq motion_horizontal_complete
            motion_fractional_wall:
                lda #1
                sta motion_hitx
                lda #0
                sta phys_vx
            motion_horizontal_complete:
                lda motion_hitx
                bne motion_wall_x
                lda motion_vxh
                sta phys_vx
                jmp motion_step_y
            motion_wall_x:
                lda #0
                sta motion_xf
                sta motion_vxf
            motion_step_y:
                lda motion_yf
                clc
                adc motion_vyf
                sta motion_yf
                lda phys_vy
                adc #0
                sta phys_vy
                jsr physics_vertical
                lda motion_hity
                bne motion_wall_y
                lda motion_vyh
                sta phys_vy
                jmp motion_support
            motion_wall_y:
                lda #0
                sta motion_yf
                sta motion_vyf
            motion_support:
                jsr physics_support
                ; Snap fractional downward motion to a supporting floor.
                lda phys_grounded
                beq motion_done
                lda #0
                sta phys_vy
                sta motion_vyf
                sta motion_yf
            motion_done:
                rts

            ; Compare signed 16-bit value against target; carry means >=.
            motion_compare:
                lda motion_target_hi
                eor #$80
                sta motion_compare_scratch
                lda motion_value_hi
                eor #$80
                cmp motion_compare_scratch
                bne motion_compare_done
                lda motion_value_lo
                cmp motion_target_lo
            motion_compare_done:
                rts
            motion_approach:
                ; Raw Set actions may assign an out-of-range integer byte.
                lda motion_value_hi
                jsr physics_clamp_velocity
                cmp motion_value_hi
                bne motion_approach_clamp
                cmp #8
                bne motion_approach_clamped
            motion_approach_clamp:
                sta motion_value_hi
                lda #0
                sta motion_value_lo
            motion_approach_clamped:
                jsr motion_compare
                bcs motion_approach_down
                lda motion_value_lo
                clc
                adc motion_step_lo
                sta motion_value_lo
                lda motion_value_hi
                adc motion_step_hi
                sta motion_value_hi
                jsr motion_compare
                bcc motion_approach_done
                jmp motion_approach_target
            motion_approach_down:
                lda motion_value_lo
                sec
                sbc motion_step_lo
                sta motion_value_lo
                lda motion_value_hi
                sbc motion_step_hi
                sta motion_value_hi
                jsr motion_compare
                bcs motion_approach_done
            motion_approach_target:
                lda motion_target_lo
                sta motion_value_lo
                lda motion_target_hi
                sta motion_value_hi
            motion_approach_done:
                rts
        '''
        # Keep the callable compare label distinct from its one-byte scratch.
        source = source.replace("motion_compare_scratch", "motion_compare_byte")
        self.compiler.reserve("motion_compare_byte")
        return dedent(source).strip().splitlines()
