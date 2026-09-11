"""Small pulse sequencer for games that do not include the music engine."""
from .effects import PlaySound, SoundEffect, StopSound


class PulseSequenceRuntime:
    def __init__(self, compiler, actions):
        self.compiler = compiler
        self.effects = tuple(dict.fromkeys(a.tone for a in actions if isinstance(a, PlaySound)))
        self.pointer = compiler.reserve("fx_sequence_ptr", 2, zp=True)
        for name in ("pending", "request_lo", "request_hi", "request_priority", "priority", "remaining"):
            setattr(self, name, compiler.reserve("fx_sequence_" + name))
        self.init = []
        self.nmi_always = ["    jsr fx_sequence_tick"]
        self.nmi = ["    jsr fx_sequence_commit"]
        self.nmi_tail = []
        self.room_reset = ["    lda #0", "    sta APUSTATUS", f"    sta {self.pending}",
                           f"    sta {self.pointer}+1", f"    sta {self.remaining}"]
        self.routines = self._routines()
        self.rodata = []
        for index, effect in enumerate(self.effects):
            self.rodata += [f"fx_sequence_data_{index}:"]
            for tone in effect.tones if isinstance(effect, SoundEffect) else (effect,):
                self.rodata += [f"    .byte {tone.frames}, {tone.control}, {tone.timer & 255}, {tone.timer >> 8}"]
            self.rodata += ["    .byte 0"]

    def emit_action(self, action):
        if isinstance(action, PlaySound):
            priority = action.tone.priority if isinstance(action.tone, SoundEffect) else 0
            accept, done = self.compiler.unique("sfx_accept"), self.compiler.unique("sfx_skip")
            index = self.effects.index(action.tone)
            return [f"    lda {self.pending}", "    cmp #1", f"    bne {accept}",
                    f"    lda #{priority}", f"    cmp {self.request_priority}", f"    bcc {done}",
                    f"{accept}:", f"    lda #{priority}", f"    sta {self.request_priority}",
                    f"    lda #<fx_sequence_data_{index}", f"    sta {self.request_lo}",
                    f"    lda #>fx_sequence_data_{index}", f"    sta {self.request_hi}",
                    "    lda #1", f"    sta {self.pending}", f"{done}:"]
        if isinstance(action, StopSound):
            return ["    lda #2", f"    sta {self.pending}"]
        return None

    def _routines(self):
        return ["fx_sequence_tick:", f"    lda {self.remaining}", "    beq fx_sequence_done",
                f"    dec {self.remaining}", "    bne fx_sequence_done", "    jmp fx_sequence_next",
                "fx_sequence_commit:", f"    lda {self.pending}", "    beq fx_sequence_done",
                "    cmp #2", "    beq fx_sequence_stop_command", f"    lda {self.remaining}",
                "    beq fx_sequence_start", f"    lda {self.request_priority}", f"    cmp {self.priority}",
                "    bcc fx_sequence_committed", "fx_sequence_start:",
                f"    lda {self.request_priority}", f"    sta {self.priority}",
                f"    lda {self.request_lo}", f"    sta {self.pointer}",
                f"    lda {self.request_hi}", f"    sta {self.pointer}+1",
                "    lda #1", "    sta APUSTATUS", "    lda #8", "    sta $4001",
                "    jsr fx_sequence_next", "fx_sequence_committed:", "    lda #0",
                f"    sta {self.pending}", "fx_sequence_done:", "    rts",
                "fx_sequence_stop_command:", "    lda #0", f"    sta {self.pending}",
                "fx_sequence_stop:", "    lda #0", f"    sta {self.remaining}",
                f"    sta {self.pointer}+1", "    lda #$30", "    sta $4000", "    rts",
                "fx_sequence_next:", "    ldy #0", f"    lda ({self.pointer}),y", "    beq fx_sequence_stop",
                f"    sta {self.remaining}", "    iny", f"    lda ({self.pointer}),y", "    sta $4000",
                "    iny", f"    lda ({self.pointer}),y", "    sta $4002", "    iny",
                f"    lda ({self.pointer}),y", "    sta $4003", f"    lda {self.pointer}",
                "    clc", "    adc #4", f"    sta {self.pointer}", "    bcc fx_sequence_done",
                f"    inc {self.pointer}+1", "    rts"]
