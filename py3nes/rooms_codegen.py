"""Room dispatch and complete screen replacement during forced blank.

Gameplay requests a transition, then stops the current tick. Main owns the PPU
while rt_room_loading is set: NMI preserves registers but touches no display or
sound state. Room entry resets local state, applies a spawn, and runs entry rules
before resuming rendering at vertical blank. Inventory is ordinary runtime RAM;
there is no battery-backed persistence across emulator resets.
"""

from .codegen import _byte_lines
from .compression import initial_oam, nametable_storage


class RoomsRuntime:
    def __init__(self, compiler, rooms, start_room=0, start_spawn=None):
        self.compiler = compiler
        self.rooms = tuple(rooms)
        self.nametables = {room.index: nametable_storage(room.nametable()) for room in self.rooms}
        self.oam = {room.index: initial_oam(room.sprites) for room in self.rooms}
        compiler.reserve("rt_room_load_ptr", size=2, zp=True)
        start = self.rooms[start_room]
        spawn = 255 if start_spawn is None else tuple(start.spawns).index(start_spawn)
        self.init = [f"    lda #{start_room}", "    sta rt_room_next",
                     f"    lda #{spawn}", "    sta rt_room_spawn", "    jsr room_load"]
        self.routines = self._loader()
        self.rodata = []
        for room in self.rooms:
            data, compressed = self.nametables[room.index]
            self.rodata += [f"; {room.name}: nametable {'RLE' if compressed else 'raw'}, {len(data)} bytes",
                            f"room_{room.index}_nametable:", *_byte_lines(data)]
            if self.oam[room.index]:
                self.rodata += [f"room_{room.index}_oam:", *_byte_lines(self.oam[room.index])]

    def events(self, global_events, attribute, label):
        compiler = self.compiler
        lines = [f".export {label}", f"{label}:", f"    jsr {label}_global",
                 "    lda rt_room_pending",
                 *(["    ora rt_mode_pending"] if compiler.mode_runtime else []),
                 f"    beq {label}_dispatch", "    rts",
                 f"{label}_dispatch:"]
        for room in self.rooms:
            next_room = compiler.unique("dispatch_next")
            lines += ["    lda rt_room", f"    cmp #{room.index}", f"    bne {next_room}",
                      f"    jmp {label}_room_{room.index}", f"{next_room}:"]
        lines += ["    rts", *compiler.events(global_events, label + "_global")]
        for room in self.rooms:
            lines += compiler.events(getattr(room, attribute), f"{label}_room_{room.index}")
        return lines

    def _loader(self):
        c = self.compiler
        fx = c.effects
        lines = [".export room_transition, room_load", "room_transition:",
                 "    lda #1", "    sta rt_room_loading",
                 # Wait for a fresh vblank before turning off rendering.
                 "    bit PPUSTATUS", "room_wait_blank:", "    bit PPUSTATUS",
                 "    bpl room_wait_blank", "    lda #0", "    sta PPUMASK",
                 "    jsr room_load",
                 "    bit PPUSTATUS", "room_wait_resume:", "    bit PPUSTATUS",
                 "    bpl room_wait_resume", "    lda #0", "    sta OAMADDR",
                 "    lda #2", "    sta OAMDMA", "    lda #0",
                 "    sta PPUSCROLL", "    sta PPUSCROLL",
                 "    lda #$1E", "    sta PPUMASK",
                 "    lda #0", "    sta rt_room_loading", "    rts",
                 "room_load:", "    lda rt_room_next", "    sta rt_room",
                 "    lda #0", "    sta rt_room_pending", *fx.begin_frame]
        lines += fx.room_reset
        for room in self.rooms:
            index = room.index
            next_room = c.unique("load_next_room")
            lines += ["    lda rt_room", f"    cmp #{index}", f"    beq room_load_{index}",
                      f"    jmp {next_room}", f"room_load_{index}:"]
            lines += [f"    lda #<room_{index}_nametable", "    sta rt_room_load_ptr",
                      f"    lda #>room_{index}_nametable", "    sta rt_room_load_ptr+1",
                      "    jsr room_unpack_nametable" if self.nametables[index][1]
                      else "    jsr room_copy_nametable"]
            lines += ["    ldx #0"]
            prefix_size = len(self.oam[index])
            if prefix_size:
                loop = c.unique("room_oam")
                lines += [f"{loop}:", f"    lda room_{index}_oam,x", "    sta $0200,x", "    inx"]
                if prefix_size < 256:
                    lines += [f"    cpx #{prefix_size}"]
                lines += [f"    bne {loop}"]
            if prefix_size < 256:
                clear = c.unique("room_oam_clear")
                lines += ["    lda #$FF", f"{clear}:", "    sta $0200,x", "    inx", f"    bne {clear}"]
            if c.physics:
                lines += [f"    lda #<room_{index}_collision", "    sta phys_collision_base",
                          f"    lda #>room_{index}_collision", "    sta phys_collision_base+1"]
            for variable in room.reset_variables:
                lines += [f"    lda #${variable.initial & 255:02X}", f"    sta {c.var(variable)}"]
            for spawn_index, spawn in enumerate(room.spawns.values()):
                skip = c.unique("spawn_next")
                lines += ["    lda rt_room_spawn", f"    cmp #{spawn_index}", f"    bne {skip}",
                          f"    lda #{spawn.x}", f"    sta {c.var(spawn.actor.x)}",
                          f"    lda #{spawn.y}", f"    sta {c.var(spawn.actor.y)}", f"{skip}:"]
            lines += [f"    jsr room_enter_{index}", "    jmp room_load_finish", f"{next_room}:"]
        lines += ["room_load_finish:"]
        if c.physics:
            lines += ["    jsr physics_initial_ground", "    jsr render_actors_initial"]
        if fx.display:
            # Rendering is off; fully apply entry writes before showing the room.
            lines += ["room_flush_entry:", "    jsr fx_drain_vram",
                      f"    lda {fx.queue_length}", "    bne room_flush_entry"]
        lines += ["    rts"]
        if any(not compressed for _, compressed in self.nametables.values()):
            lines += ["room_copy_nametable:", "    bit PPUSTATUS",
                      "    lda #$20", "    sta PPUADDR", "    lda #0", "    sta PPUADDR",
                      "    ldx #4", "    ldy #0", "room_copy_byte:",
                      "    lda (rt_room_load_ptr),y", "    sta PPUDATA", "    iny",
                      "    bne room_copy_byte", "    inc rt_room_load_ptr+1", "    dex",
                      "    bne room_copy_byte", "    rts"]
        if any(compressed for _, compressed in self.nametables.values()):
            lines += [
                "; Main owns the PPU during room loading; unpack directly to VRAM.",
                "room_unpack_nametable:", "    bit PPUSTATUS",
                "    lda #$20", "    sta PPUADDR", "    lda #0", "    sta PPUADDR", "    tay",
                "room_unpack_packet:", "    jsr room_unpack_read", "    beq room_unpack_done",
                "    bmi room_unpack_repeat", "    tax",
                "room_unpack_literal:", "    jsr room_unpack_read", "    sta PPUDATA", "    dex",
                "    bne room_unpack_literal", "    jmp room_unpack_packet",
                "room_unpack_repeat:", "    and #$7F", "    tax", "    inx", "    jsr room_unpack_read",
                "room_unpack_run:", "    sta PPUDATA", "    dex", "    bne room_unpack_run",
                "    jmp room_unpack_packet", "room_unpack_done:", "    rts",
                "; Read one source byte, preserving X/Y and returning A's N/Z flags.",
                "room_unpack_read:", "    lda (rt_room_load_ptr),y", "    inc rt_room_load_ptr",
                "    bne room_unpack_read_done", "    inc rt_room_load_ptr+1",
                "room_unpack_read_done:", "    cmp #0", "    rts",
            ]
        for room in self.rooms:
            lines += c.events(room.enter_events, f"room_enter_{room.index}", scoped=False)
        return lines
