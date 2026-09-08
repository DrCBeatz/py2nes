"""Bounded NMI VRAM transfers and pulse-channel code generation.

Main stages complete requests while frame_ready is zero. NMI consumes requests
only after the main loop publishes them. A maximum of 16 tile writes per NMI
leaves headroom for OAM DMA within NTSC vertical blank. Large batches keep
frame_ready set until drained, applying backpressure instead of losing writes.
"""

from .effects import PlaySound, SetBackgroundTile, StopSound, WriteNumber, WriteText


MAX_TILE_WRITES = 64
TILES_PER_VBLANK = 16


class EffectsRuntime:
    def __init__(self, compiler, actions):
        self.compiler = compiler
        actions = tuple(actions)
        self.display = any(isinstance(a, (WriteText, WriteNumber, SetBackgroundTile)) for a in actions)
        self.numbers = any(isinstance(a, WriteNumber) for a in actions)
        self.audio = any(isinstance(a, (PlaySound, StopSound)) for a in actions)
        self.init = []
        self.begin_frame = []
        self.update = []
        self.nmi_always = []
        self.nmi = []
        self.routines = []
        self.rodata = []
        self.queue_length = None
        if self.display:
            self.queue = compiler.reserve("fx_vram_queue", 256)
            self.queue_length = compiler.reserve("fx_vram_length")
            self.queue_cursor = compiler.reserve("fx_vram_cursor")
            self.begin_frame += ["    lda #$00", f"    sta {self.queue_length}", f"    sta {self.queue_cursor}"]
            self.nmi += ["    jsr fx_drain_vram"]
            self.routines += self._vram_routine()
        if self.numbers:
            self.digits = compiler.reserve("fx_digits", 3)
            self.routines += self._digits_routine()
        if self.audio:
            for name in ("pending", "control", "low", "high", "frames", "remaining"):
                setattr(self, f"sound_{name}", compiler.reserve(f"fx_sound_{name}"))
            # This countdown is safe even when main is interrupted while
            # constructing a request: it only touches NMI-owned state.
            self.nmi_always += ["    jsr fx_tick_sound"]
            self.nmi[:0] = ["    jsr fx_commit_sound"]
            self.routines += self._audio_routines()

    def emit_action(self, action):
        if isinstance(action, WriteText):
            return self._text(action)
        if isinstance(action, WriteNumber):
            lines = self.compiler.load(action.value) + ["    jsr fx_number_digits"]
            for offset in range(action.digits):
                digit = 3 - action.digits + offset
                lines += self._append(0x2000 + action.row * 32 + action.column + offset,
                                      [f"    lda {self.digits} + {digit}", "    clc", "    adc #$10"])
            return lines
        if isinstance(action, SetBackgroundTile):
            return self._append(0x2000 + action.row * 32 + action.column,
                                [f"    lda #${action.tile:02X}"])
        if isinstance(action, PlaySound):
            tone = action.tone
            lines = []
            for field, value in (("control", tone.control), ("low", tone.timer & 255),
                                 ("high", tone.timer >> 8), ("frames", tone.frames)):
                lines += [f"    lda #${value:02X}", f"    sta {getattr(self, 'sound_' + field)}"]
            return lines + ["    lda #$01", f"    sta {self.sound_pending}"]
        if isinstance(action, StopSound):
            return ["    lda #$02", f"    sta {self.sound_pending}"]
        return None

    def _append(self, address, value_lines):
        return [f"    ldx {self.queue_length}", f"    lda #${address >> 8:02X}",
                f"    sta {self.queue},x", "    inx", f"    lda #${address & 255:02X}",
                f"    sta {self.queue},x", "    inx", *value_lines,
                f"    sta {self.queue},x", "    inx", f"    stx {self.queue_length}"]

    def _text(self, action):
        if not action.width:
            return []
        data = self.compiler.unique("fx_text")
        loop = self.compiler.unique("fx_text_copy")
        self.rodata += [f"{data}:", "    .byte " + ", ".join(f"${v:02X}" for v in action.tiles)]
        start = 0x2000 + action.row * 32 + action.column
        # Each line fits one nametable row, hence cannot cross a 256-byte page.
        return [f"    ldx {self.queue_length}", "    ldy #$00", f"{loop}:",
                f"    lda #${start >> 8:02X}", f"    sta {self.queue},x", "    inx",
                "    tya", "    clc", f"    adc #${start & 255:02X}", f"    sta {self.queue},x", "    inx",
                f"    lda {data},y", f"    sta {self.queue},x", "    inx", "    iny",
                f"    cpy #${action.width:02X}", f"    bne {loop}", f"    stx {self.queue_length}"]

    def _vram_routine(self):
        return ["", "; NMI only: <=16 * ~52 cycles, plus OAM DMA and interrupt overhead.",
                "fx_drain_vram:", f"    ldx {self.queue_cursor}", f"    cpx {self.queue_length}",
                "    beq fx_vram_done", f"    ldy #${TILES_PER_VBLANK:02X}", "    bit PPUSTATUS",
                "fx_vram_next:", f"    lda {self.queue},x", "    sta PPUADDR", "    inx",
                f"    lda {self.queue},x", "    sta PPUADDR", "    inx",
                f"    lda {self.queue},x", "    sta PPUDATA", "    inx",
                f"    cpx {self.queue_length}", "    beq fx_vram_done", "    dey", "    bne fx_vram_next",
                f"    stx {self.queue_cursor}", "    rts", "fx_vram_done:", "    lda #$00",
                f"    sta {self.queue_length}", f"    sta {self.queue_cursor}", "    rts"]

    def _digits_routine(self):
        return ["", "; Main only: A is an unsigned byte; output hundreds, tens, ones.",
                "fx_number_digits:", "    ldx #$00", "fx_number_hundreds:",
                "    cmp #$64", "    bcc fx_number_hundreds_done", "    sbc #$64", "    inx",
                "    jmp fx_number_hundreds", "fx_number_hundreds_done:", f"    stx {self.digits}",
                "    ldx #$00", "fx_number_tens:", "    cmp #$0A", "    bcc fx_number_tens_done",
                "    sbc #$0A", "    inx", "    jmp fx_number_tens", "fx_number_tens_done:",
                f"    stx {self.digits} + 1", f"    sta {self.digits} + 2", "    rts"]

    def _audio_routines(self):
        # https://www.nesdev.org/wiki/APU_Pulse and /APU_Sweep: sweep $08
        # avoids the shift-zero positive target overflow muting low notes.
        return ["", "; NMI owns hardware audio and remaining duration; main owns requests.",
                "fx_tick_sound:", f"    lda {self.sound_remaining}", "    beq fx_sound_tick_done",
                f"    dec {self.sound_remaining}", "    bne fx_sound_tick_done", "    lda #$30",
                "    sta $4000", "fx_sound_tick_done:", "    rts", "fx_commit_sound:",
                f"    lda {self.sound_pending}", "    beq fx_sound_commit_done", "    cmp #$02",
                "    beq fx_sound_stop", "    lda #$01", "    sta APUSTATUS",
                f"    lda {self.sound_control}", "    sta $4000", "    lda #$08", "    sta $4001",
                f"    lda {self.sound_low}", "    sta $4002", f"    lda {self.sound_high}", "    sta $4003",
                f"    lda {self.sound_frames}", f"    sta {self.sound_remaining}", "    jmp fx_sound_committed",
                "fx_sound_stop:", "    lda #$30", "    sta $4000", "    lda #$00", f"    sta {self.sound_remaining}",
                "fx_sound_committed:", "    lda #$00", f"    sta {self.sound_pending}",
                "fx_sound_commit_done:", "    rts"]
