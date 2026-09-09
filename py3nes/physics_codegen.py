"""6502 actor physics. Main-loop scratch is never touched by NMI.

The shared collision routine checks every tile under a hitbox, and movement
advances one pixel at a time, so even an eight-pixel step cannot cross a wall.
"""

from textwrap import dedent

from .physics import Actor, Animate, Hide, Overlaps, Show, Teleport, Velocity


def _lines(source):
    return dedent(source).strip().splitlines()


class PhysicsRuntime:
    def __init__(self, compiler, actors, collision, rooms=()):
        self.compiler = compiler
        self.actors = tuple(actors)
        self.rooms = tuple(rooms)
        self._actor_rooms = {
            id(actor): index
            for index, room in enumerate(self.rooms)
            for actor in room.actors
        }
        if self.rooms and any(id(actor) not in self._actor_rooms for actor in self.actors):
            raise ValueError("every actor must belong to a named room")
        if len(collision) != 960:
            raise ValueError("collision grid must contain exactly 960 bytes")
        self.collision = bytes(bool(value) for value in collision)
        self.init = []
        self.before_events = []
        self.update = []
        self.render = []
        self.routines = []
        self.rodata = []
        if not self.actors:
            return
        for name in ("x", "y", "vx", "vy", "grounded", "offx", "offy", "w", "h",
                     "maxx", "maxy", "gravity", "fall", "solid", "steps", "direction",
                     "old", "row", "lastrow", "col", "firstcol", "lastcol", "edge",
                     "edge_hi", "edge_other"):
            label = compiler.reserve("phys_" + name)
            if label != "phys_" + name:
                raise ValueError("compiler.reserve must preserve physics scratch labels")
        compiler.reserve("phys_ptr", size=2, zp=True)
        if self.rooms:
            # The room loader changes this pointer while rendering is disabled.
            compiler.reserve("phys_collision_base", size=2, zp=True)
        self.init = ["    jsr physics_initial_ground", "    jsr render_actors_initial"]
        self.update = ["    jsr physics_update"]
        self.render = ["    jsr render_actors"]
        self.routines = self._dispatch() + self._common() + self._render()
        if self.rooms:
            for index, room in enumerate(self.rooms):
                collision = room.collision_data()
                if len(collision) != 960:
                    raise ValueError("collision grid must contain exactly 960 bytes")
                self._collision_table(f"room_{index}_collision", collision)
        else:
            self._collision_table("physics_collision", self.collision)
            for suffix, operator in (("lo", "<"), ("hi", ">")):
                self.rodata.extend([f"physics_rows_{suffix}:",
                    "    .byte " + ", ".join(f"{operator}(physics_collision + {row * 32})" for row in range(30))])

    def _collision_table(self, label, collision):
        self.rodata.append(f"{label}:")
        for offset in range(0, 960, 32):
            self.rodata.append("    .byte " + ", ".join(str(int(bool(v))) for v in collision[offset:offset + 32]))

    def _active_room(self, actor, skip):
        """Skip an inactive room with an absolute jump, even for large actors."""
        if not self.rooms:
            return []
        active = self.compiler.unique("actor_room_active")
        return ["    lda rt_room", f"    cmp #{self._actor_rooms[id(actor)]}",
                f"    beq {active}", f"    jmp {skip}", f"{active}:"]

    def _var(self, actor, key):
        if not any(actor is candidate for candidate in self.actors):
            raise ValueError("actor belongs to another game")
        return self.compiler.var(getattr(actor, key))

    def _state_in(self, actor):
        lines = []
        for key in ("x", "y", "vx", "vy", "grounded"):
            lines += [f"    lda {self._var(actor, key)}", f"    sta phys_{key}"]
        for key, value in (("offx", actor.hitbox.offset_x), ("offy", actor.hitbox.offset_y),
                ("w", actor.hitbox.width), ("h", actor.hitbox.height),
                ("maxx", 256 - actor.width), ("maxy", 240 - actor.height),
                ("gravity", actor.gravity), ("fall", actor.max_fall_speed),
                ("solid", int(actor.collides))):
            lines += [f"    lda #${value:02X}", f"    sta phys_{key}"]
        return lines

    def _dispatch(self):
        lines = [".export physics_update, render_actors", "physics_update:"]
        for actor in self.actors:
            skip = self.compiler.unique("physics_actor_skip")
            active = self.compiler.unique("physics_actor_active")
            lines += self._active_room(actor, skip)
            lines += [f"    lda {self._var(actor, 'visible')}", f"    bne {active}",
                      f"    jmp {skip}", f"{active}:"]
            lines += self._state_in(actor) + ["    jsr physics_tick"]
            for key in ("x", "y", "vx", "vy", "grounded"):
                lines += [f"    lda phys_{key}", f"    sta {self._var(actor, key)}"]
            lines += [f"{skip}:"]
        lines += ["    rts", "physics_initial_ground:"]
        for actor in self.actors:
            skip = self.compiler.unique("physics_ground_skip") if self.rooms else None
            lines += self._active_room(actor, skip)
            lines += self._state_in(actor) + ["    jsr physics_support", "    lda phys_grounded",
                                              f"    sta {self._var(actor, 'grounded')}"]
            if skip is not None:
                lines += [f"{skip}:"]
        return lines + ["    rts"]

    def emit_action(self, action):
        if not isinstance(action, (Velocity, Teleport, Show, Hide, Animate)):
            return None
        actor = action.actor
        self._var(actor, "x")  # Validate game ownership even for an empty update.
        if isinstance(action, Velocity):
            lines = []
            for key in ("vx", "vy"):
                value = getattr(action, key)
                if value is not None:
                    if isinstance(value, int):
                        lines += [f"    lda #${value & 255:02X}"]
                    else:
                        lines += self.compiler.load(value)
                        clamp = "physics_clamp_velocity" if getattr(value, "kind", "u8") == "i8" else "physics_clamp_unsigned"
                        lines += [f"    jsr {clamp}"]
                    lines += [f"    sta {self._var(actor, key)}"]
            return lines
        if isinstance(action, Teleport):
            return [f"    lda #${action.x:02X}", f"    sta {self._var(actor, 'x')}",
                    f"    lda #${action.y:02X}", f"    sta {self._var(actor, 'y')}",
                    "    lda #$00", f"    sta {self._var(actor, 'vx')}",
                    f"    sta {self._var(actor, 'vy')}", f"    sta {self._var(actor, 'grounded')}"]
        if isinstance(action, Animate):
            return [f"    lda #{int(action.enabled)}", f"    sta {self._var(actor, 'animation_enabled')}"]
        return [f"    lda #{int(isinstance(action, Show))}", f"    sta {self._var(actor, 'visible')}"]

    def emit_condition(self, condition, false_label):
        if not isinstance(condition, Overlaps):
            return None
        lines = []
        for actor in (condition.first, condition.second):
            self._var(actor, "visible")
            lines += self._active_room(actor, false_label)
            visible = self.compiler.unique("overlap_visible")
            lines += [f"    lda {self._var(actor, 'visible')}", f"    bne {visible}",
                      f"    jmp {false_label}", f"{visible}:"]
        for key, offset, dimension in (("x", "offset_x", "width"), ("y", "offset_y", "height")):
            for first, second in ((condition.first, condition.second), (condition.second, condition.first)):
                okay = self.compiler.unique("overlap_axis")
                high_okay = self.compiler.unique("overlap_high")
                # Nine-bit endpoints prevent wrapped overlaps if an event has
                # directly assigned an out-of-bounds coordinate before physics.
                lines += [f"    lda {self._var(first, key)}", "    clc",
                          f"    adc #{getattr(first.hitbox, offset)}", "    sta phys_edge",
                          "    lda #0", "    adc #0", "    sta phys_edge_hi",
                          f"    lda {self._var(second, key)}", "    clc",
                          f"    adc #{getattr(second.hitbox, offset) + getattr(second.hitbox, dimension) - 1}",
                          "    sta phys_edge_other", "    lda #0", "    adc #0",
                          "    cmp phys_edge_hi", f"    bcs {high_okay}", f"    jmp {false_label}",
                          f"{high_okay}:", f"    bne {okay}", "    lda phys_edge_other",
                          "    cmp phys_edge", f"    bcs {okay}", f"    jmp {false_label}", f"{okay}:"]
        return lines

    def _render(self):
        lines = ["render_actors:"]
        for actor in self.actors:
            if len(actor.frames) == 1:
                continue
            skip = self.compiler.unique("animation_skip")
            lines += self._active_room(actor, skip)
            lines += [f"    lda {self._var(actor, 'visible')}", f"    beq {skip}",
                      f"    lda {self._var(actor, 'animation_enabled')}", f"    beq {skip}",
                      f"    inc {self._var(actor, 'frame_timer')}",
                      f"    lda {self._var(actor, 'frame_timer')}", f"    cmp #{actor.frame_ticks}",
                      f"    bcc {skip}", "    lda #0", f"    sta {self._var(actor, 'frame_timer')}",
                      f"    inc {self._var(actor, 'frame')}", f"    lda {self._var(actor, 'frame')}",
                      f"    cmp #{len(actor.frames)}", f"    bcc {skip}", "    lda #0",
                      f"    sta {self._var(actor, 'frame')}", f"{skip}:"]
        lines += ["render_actors_initial:"]
        for actor in self.actors:
            end = self.compiler.unique("render_actor_end")
            visible = self.compiler.unique("render_actor_visible")
            # Rooms reuse OAM slots. An inactive actor must not even hide them.
            lines += self._active_room(actor, end)
            lines += ["    lda #$FF"]
            for i in range(actor.oam_slots):
                lines += [f"    sta ${0x200 + (actor.oam_start + i) * 4:04X}"]
            lines += [f"    lda {self._var(actor, 'visible')}", f"    bne {visible}",
                      f"    jmp {end}", f"{visible}:"]
            frame_labels = [self.compiler.unique("render_frame") for _ in actor.frames]
            for index, label in enumerate(frame_labels[1:], 1):
                next_check = self.compiler.unique("render_next_frame")
                lines += [f"    lda {self._var(actor, 'frame')}", f"    cmp #{index}",
                          f"    bne {next_check}", f"    jmp {label}", f"{next_check}:"]
            lines += [f"    jmp {frame_labels[0]}"]
            for label, frame in zip(frame_labels, actor.frames):
                lines += [f"{label}:"]
                for index, part in enumerate(frame.parts):
                    skip = self.compiler.unique("render_part_skip")
                    base = 0x200 + (actor.oam_start + index) * 4
                    # A raw Set may have changed coordinates after physics. Clip
                    # whole sprite parts so arithmetic never wraps onto screen.
                    lines += [f"    lda {self._var(actor, 'x')}", "    clc", f"    adc #{part.dx}",
                              f"    bcs {skip}", "    cmp #249", f"    bcs {skip}",
                              f"    sta ${base + 3:04X}", f"    lda {self._var(actor, 'y')}",
                              "    clc", f"    adc #{part.dy}", f"    bcs {skip}", f"    beq {skip}",
                              "    cmp #233", f"    bcs {skip}", "    sec", "    sbc #1",
                              f"    sta ${base:04X}", f"    lda #${part.tile:02X}",
                              f"    sta ${base + 1:04X}", f"    lda #${part.attributes:02X}",
                              f"    sta ${base + 2:04X}", f"{skip}:"]
                lines += [f"    jmp {end}"]
            lines += [f"{end}:"]
        return lines + ["    rts"]

    def _common(self):
        source = '''
            ; Signed velocities are saturated to -8..8 pixels per tick.
            physics_clamp_velocity:
                cmp #$80
                bcc physics_clamp_unsigned
                cmp #$F8
                bcs physics_clamp_done
                lda #$F8
                rts
            physics_clamp_unsigned:
                cmp #9
                bcc physics_clamp_done
                lda #8
            physics_clamp_done:
                rts

            physics_tick:
                ; Clamp positions even if gameplay directly assigned coordinates.
                lda phys_x
                cmp phys_maxx
                bcc physics_bound_x
                lda phys_maxx
                sta phys_x
            physics_bound_x:
                lda phys_y
                bne physics_nonzero_y
                lda #1
            physics_nonzero_y:
                cmp phys_maxy
                bcc physics_bound_y
                lda phys_maxy
            physics_bound_y:
                sta phys_y
                lda phys_vx
                jsr physics_clamp_velocity
                sta phys_vx
                lda phys_vy
                jsr physics_clamp_velocity
                sta phys_vy
                lda phys_gravity
                beq physics_no_gravity
                clc
                adc phys_vy
                bmi physics_store_gravity
                cmp phys_fall
                bcc physics_store_gravity
                lda phys_fall
            physics_store_gravity:
                sta phys_vy
            physics_no_gravity:
                jsr physics_horizontal
                jsr physics_vertical
                jsr physics_support
                rts

            physics_horizontal:
                lda phys_vx
                beq physics_horizontal_done
                lda #1
                sta phys_direction
                lda phys_vx
                bpl physics_horizontal_steps
                lda #$FF
                sta phys_direction
                lda phys_vx
                eor #$FF
                clc
                adc #1
            physics_horizontal_steps:
                sta phys_steps
            physics_horizontal_loop:
                lda phys_x
                sta phys_old
                lda phys_direction
                bmi physics_left
                lda phys_x
                cmp phys_maxx
                bcs physics_horizontal_stop
                inc phys_x
                jmp physics_horizontal_test
            physics_left:
                lda phys_x
                beq physics_horizontal_stop
                dec phys_x
            physics_horizontal_test:
                jsr physics_collision_test
                bne physics_horizontal_hit
                dec phys_steps
                bne physics_horizontal_loop
            physics_horizontal_done:
                rts
            physics_horizontal_hit:
                lda phys_old
                sta phys_x
            physics_horizontal_stop:
                lda #0
                sta phys_vx
                rts

            physics_vertical:
                lda phys_vy
                beq physics_vertical_done
                lda #1
                sta phys_direction
                lda phys_vy
                bpl physics_vertical_steps
                lda #$FF
                sta phys_direction
                lda phys_vy
                eor #$FF
                clc
                adc #1
            physics_vertical_steps:
                sta phys_steps
            physics_vertical_loop:
                lda phys_y
                sta phys_old
                lda phys_direction
                bmi physics_up
                lda phys_y
                cmp phys_maxy
                bcs physics_vertical_stop
                inc phys_y
                jmp physics_vertical_test
            physics_up:
                lda phys_y
                cmp #1
                beq physics_vertical_stop
                dec phys_y
            physics_vertical_test:
                jsr physics_collision_test
                bne physics_vertical_hit
                dec phys_steps
                bne physics_vertical_loop
            physics_vertical_done:
                rts
            physics_vertical_hit:
                lda phys_old
                sta phys_y
            physics_vertical_stop:
                lda #0
                sta phys_vy
                rts

            physics_support:
                lda #0
                sta phys_grounded
                lda phys_vy
                bmi physics_support_done
                lda phys_y
                cmp phys_maxy
                bcs physics_supported
                inc phys_y
                jsr physics_collision_test
                dec phys_y
                cmp #0
                beq physics_support_done
            physics_supported:
                lda #1
                sta phys_grounded
            physics_support_done:
                rts

            ; Return A=1 if any covered solid tile, otherwise A=0.
            ; The caller ensures the entire hitbox is inside the visible screen.
            physics_collision_test:
                lda phys_solid
                bne physics_collision_enabled
                rts
            physics_collision_enabled:
                lda phys_x
                clc
                adc phys_offx
                sta phys_col
                lsr a
                lsr a
                lsr a
                sta phys_firstcol
                lda phys_col
                clc
                adc phys_w
                sec
                sbc #1
                lsr a
                lsr a
                lsr a
                sta phys_lastcol
                lda phys_y
                clc
                adc phys_offy
                sta phys_row
                clc
                adc phys_h
                sec
                sbc #1
                lsr a
                lsr a
                lsr a
                sta phys_lastrow
                lda phys_row
                lsr a
                lsr a
                lsr a
                sta phys_row
            physics_collision_row:
                ldx phys_row
                lda physics_rows_lo,x
                sta phys_ptr
                lda physics_rows_hi,x
                sta phys_ptr+1
                ldy phys_firstcol
            physics_collision_column:
                lda (phys_ptr),y
                bne physics_collision_hit
                cpy phys_lastcol
                beq physics_collision_next_row
                iny
                jmp physics_collision_column
            physics_collision_next_row:
                lda phys_row
                cmp phys_lastrow
                beq physics_collision_clear
                inc phys_row
                jmp physics_collision_row
            physics_collision_clear:
                lda #0
                rts
            physics_collision_hit:
                lda #1
                rts
        '''
        if self.rooms:
            source = source.replace('''                ldx phys_row
                lda physics_rows_lo,x
                sta phys_ptr
                lda physics_rows_hi,x
                sta phys_ptr+1''', '''                ; Full 16-bit base + row * 32, including page carries.
                lda phys_row
                lsr a
                lsr a
                lsr a
                sta phys_ptr+1
                lda phys_row
                asl a
                asl a
                asl a
                asl a
                asl a
                clc
                adc phys_collision_base
                sta phys_ptr
                lda phys_ptr+1
                adc phys_collision_base+1
                sta phys_ptr+1''')
        return _lines(source)
