"""FamiStudio integration with compiler-owned RAM and NMI-owned audio state."""
from importlib.resources import files
import re

from .effects import PlaySound, SoundEffect, StopSound, Tone
from .music import Music, PauseMusic, PlayMusic, StopMusic, _assembly_info


def _engine_ram(features):
    # Exact 4.5.1 standard NES configuration: envelopes, channels, tempo, SFX.
    # The rewritten upstream declarations assert this value during assembly.
    size = 55 + 18 + 35 + 11 + 28
    size += 4 if "FAMITRACKER_TEMPO" in features else 6
    size += 3 * ("PITCH_TRACK" in features)
    if "SLIDE_NOTES" in features:
        size += 12 if "NOISE_SLIDE_NOTES" in features else 9
    if "VOLUME_TRACK" in features:
        size += 5 + 8 * ("VOLUME_SLIDES" in features)
    size += 5 * bool(features & {"VIBRATO", "ARPEGGIO"})
    size += 10 * ("FAMITRACKER_DELAYED_NOTES_OR_CUTS" in features)
    if "FAMITRACKER_TEMPO" in features:
        size += "FAMITRACKER_DELAYED_NOTES_OR_CUTS" in features
    size += "PHASE_RESET" in features
    size += 3 * ("DUTYCYCLE_EFFECT" in features)
    return size


def _engine_source(features, ram_size):
    """Embed licensed source/tables; allocate upstream names inside our blocks."""
    root = files("py3nes").joinpath("vendor/famistudio")
    engine = root.joinpath("famistudio_ca65.s").read_text(encoding="utf-8")
    lines = ['; FamiStudio 4.5.1, see py3nes/vendor/famistudio/NOTICE.md and LICENSE.',
             'FAMISTUDIO_CFG_EXTERNAL = 1', 'FAMISTUDIO_CFG_NTSC_SUPPORT = 1',
             'FAMISTUDIO_CFG_SFX_SUPPORT = 1', 'FAMISTUDIO_CFG_SFX_STREAMS = 1',
             '.define FAMISTUDIO_CA65_ZP_SEGMENT ZEROPAGE',
             '.define FAMISTUDIO_CA65_RAM_SEGMENT BSS',
             '.define FAMISTUDIO_CA65_CODE_SEGMENT CODE',
             'fs_ram_offset .set 0', 'fs_zp_offset .set 0']
    lines += [f'FAMISTUDIO_USE_{feature} = 1' for feature in sorted(features)]
    allocation = None
    for line in engine.splitlines():
        if line.startswith('.segment .string(FAMISTUDIO_CA65_RAM_SEGMENT)'):
            allocation = 'ram'
        elif line.startswith('.segment .string(FAMISTUDIO_CA65_ZP_SEGMENT)'):
            allocation = 'zp'
        elif line.startswith('.segment .string(FAMISTUDIO_CA65_CODE_SEGMENT)'):
            allocation = None
        match = re.match(r'(\w+):\s*\.res\s+([^;]+)', line)
        if match and allocation:
            name, count = match.groups()
            lines += [f'{name} = fs_{allocation} + fs_{allocation}_offset',
                      f'fs_{allocation}_offset .set fs_{allocation}_offset + ({count.strip()})']
            continue
        binary = re.search(r'\.incbin "([^"]+)"', line)
        if binary:
            path = root.joinpath(binary[1])
            if path.is_file():
                data = path.read_bytes()
                lines += ['    .byte ' + ', '.join(f'${byte:02X}' for byte in data[i:i+16])
                          for i in range(0, len(data), 16)]
            else:
                lines += ['    .error "unsupported FamiStudio expansion or PAL note table"']
            continue
        lines.append(line)
    lines += [f'.assert fs_ram_offset = {ram_size}, error, "FamiStudio RAM allocation mismatch"',
              '.assert fs_zp_offset = 8, error, "FamiStudio zero page allocation mismatch"',
              '.export famistudio_song_speed, famistudio_sfx_ptr_hi',
              '.segment "CODE"']
    return lines


class MusicRuntime:
    def __init__(self, compiler, actions):
        self.compiler = compiler
        self.assets = tuple(dict.fromkeys(a.music for a in actions if isinstance(a, PlayMusic)))
        self.features = frozenset(f for asset in self.assets for f in asset.features)
        modes = {"FAMITRACKER_TEMPO" in asset.features for asset in self.assets}
        if len(modes) > 1:
            raise ValueError("a game cannot mix FamiStudio and FamiTracker music tempo modes")
        if len(self.assets) > 255:
            raise ValueError("a game may use at most 255 music assets")
        self.ram_size = _engine_ram(self.features)
        compiler.reserve("fs_ram", self.ram_size)
        compiler.reserve("fs_zp", 8, zp=True)
        for name in ("commit", "command", "asset", "song", "restart", "current", "current_song",
                     "sound_pending", "sound_index", "sound_request_priority", "sound_priority"):
            setattr(self, name, compiler.reserve("fx_music_" + name))
        self.has_modes = bool(compiler.modes)
        if self.has_modes:
            self.manual_paused = compiler.reserve("fx_music_manual_paused")
            self.mode_paused = compiler.reserve("fx_music_mode_paused")
        self.sound_effects = tuple(dict.fromkeys(a.tone for a in actions if isinstance(a, PlaySound)))
        if len(self.sound_effects) > 128:
            raise ValueError("music supports at most 128 distinct sound effects")
        self.init = ["    lda #255", f"    sta {self.current}", f"    sta {self.current_song}",
                     "    lda #1", "    ldx #<fx_music_data_0", "    ldy #>fx_music_data_0",
                     "    jsr famistudio_init", "    ldx #<fx_music_sfx", "    ldy #>fx_music_sfx",
                     "    jsr famistudio_sfx_init"]
        self.nmi_commit = ["    lda #1", f"    sta {self.commit}"]
        self.nmi_tail = ["    jsr fx_music_frame"]
        self.room_reset = ["    lda #0", f"    sta {self.command}", f"    sta {self.commit}",
                           f"    sta {self.sound_pending}", f"    sta {self.sound_priority}",
                           "    ldx #FAMISTUDIO_SFX_CH0", "    jsr famistudio_sfx_clear_channel"]
        self.rodata = self._data()
        self.routines = self._routines() + _engine_source(self.features, self.ram_size)

    def emit_action(self, action):
        if isinstance(action, PlayMusic):
            asset = self.assets.index(action.music)
            return [f"    lda #{asset}", f"    sta {self.asset}", f"    lda #{action.song}",
                    f"    sta {self.song}", f"    lda #{int(action.restart)}", f"    sta {self.restart}",
                    "    lda #1", f"    sta {self.command}"]
        if isinstance(action, (StopMusic, PauseMusic)):
            command = 2 if isinstance(action, StopMusic) else 3 if action.paused else 4
            return [f"    lda #{command}", f"    sta {self.command}"]
        if isinstance(action, PlaySound):
            priority = action.tone.priority if isinstance(action.tone, SoundEffect) else 0
            accept, done = self.compiler.unique("music_sfx_accept"), self.compiler.unique("music_sfx_skip")
            return [f"    lda {self.sound_pending}", "    cmp #1", f"    bne {accept}",
                    f"    lda #{priority}", f"    cmp {self.sound_request_priority}", f"    bcc {done}",
                    f"{accept}:", f"    lda #{priority}", f"    sta {self.sound_request_priority}",
                    f"    lda #{self.sound_effects.index(action.tone)}", f"    sta {self.sound_index}",
                    "    lda #1", f"    sta {self.sound_pending}", f"{done}:"]
        if isinstance(action, StopSound):
            return ["    lda #2", f"    sta {self.sound_pending}"]
        return None

    def _routines(self):
        # PPU/OAM uploads and scroll restoration precede this entire routine.
        # Main never calls the engine except while NMI is disabled/room-locked.
        hold_commit = (["    lda rt_mode_pause_music", f"    sta {self.mode_paused}"]
                       if self.has_modes else [])
        effective_pause = ([f"    lda {self.manual_paused}", f"    ora {self.mode_paused}",
                            "    jsr famistudio_music_pause"] if self.has_modes else [])
        resume = (["    lda #0", f"    sta {self.manual_paused}"] if self.has_modes
                  else ["    lda #0", "    jsr famistudio_music_pause"])
        pause = (["    lda #1", f"    sta {self.manual_paused}"] if self.has_modes
                 else ["    lda #1", "    jsr famistudio_music_pause"])
        return [".export fx_music_frame", "fx_music_frame:", f"    lda {self.commit}",
                "    beq fx_music_update", "    lda #0", f"    sta {self.commit}",
                *hold_commit,
                "    jsr fx_music_commands", "    jsr fx_music_commit_sound",
                "fx_music_update:", *effective_pause, "    jsr famistudio_update", "    rts",
                "fx_music_commands:", f"    lda {self.command}", "    beq fx_music_commit_done",
                "    cmp #1", "    beq fx_music_play", "    cmp #2", "    beq fx_music_stop",
                "    cmp #3", "    beq fx_music_pause", *resume,
                "    jmp fx_music_committed", "fx_music_pause:", *pause,
                "    jmp fx_music_committed", "fx_music_stop:", "    jsr famistudio_music_stop",
                "    lda #255", f"    sta {self.current}", "    jmp fx_music_committed",
                "fx_music_play:", f"    lda {self.asset}", f"    cmp {self.current}",
                "    bne fx_music_load", f"    lda {self.restart}", "    bne fx_music_start",
                f"    lda {self.song}", f"    cmp {self.current_song}", "    bne fx_music_start",
                "    lda famistudio_song_speed", "    and #$7F", "    bne fx_music_committed",
                "    jmp fx_music_start", "fx_music_load:", f"    lda {self.asset}",
                f"    sta {self.current}", "    tax", "    lda fx_music_data_hi,x", "    tay",
                "    lda fx_music_data_lo,x", "    tax", "    lda #1", "    jsr famistudio_init",
                # init() resets music/APU but leaves independent SFX initialized.
                "fx_music_start:",
                *(["    lda #0", f"    sta {self.manual_paused}"] if self.has_modes else []),
                f"    lda {self.song}", f"    sta {self.current_song}",
                "    jsr famistudio_music_play", "fx_music_committed:", "    lda #0",
                f"    sta {self.command}", "fx_music_commit_done:", "    rts",
                "fx_music_commit_sound:", f"    lda {self.sound_pending}", "    beq fx_music_sound_done",
                "    cmp #2", "    beq fx_music_sound_stop", "    lda famistudio_sfx_ptr_hi",
                "    beq fx_music_sound_start", f"    lda {self.sound_request_priority}",
                f"    cmp {self.sound_priority}", "    bcc fx_music_sound_committed",
                "fx_music_sound_start:", f"    lda {self.sound_request_priority}", f"    sta {self.sound_priority}",
                f"    lda {self.sound_index}", "    ldx #FAMISTUDIO_SFX_CH0", "    jsr famistudio_sfx_play",
                "    jmp fx_music_sound_committed", "fx_music_sound_stop:", "    ldx #FAMISTUDIO_SFX_CH0",
                "    jsr famistudio_sfx_clear_channel", "    lda #0", f"    sta {self.sound_priority}",
                "fx_music_sound_committed:", "    lda #0", f"    sta {self.sound_pending}",
                "fx_music_sound_done:", "    rts"]

    def _data(self):
        lines = ["fx_music_data_lo:", "    .byte " + ", ".join(f"<fx_music_data_{i}" for i in range(len(self.assets))),
                 "fx_music_data_hi:", "    .byte " + ", ".join(f">fx_music_data_{i}" for i in range(len(self.assets)))]
        for index, music in enumerate(self.assets):
            original = _assembly_info(music.assembly)[0]
            for line in music.assembly.splitlines():
                if line.strip().startswith((".export ", ".global ")):
                    continue
                lines.append(line.replace(original, f"fx_music_data_{index}"))
        lines += ["fx_music_sfx:", "    .word fx_music_sfx_list", "fx_music_sfx_list:"]
        lines += [f"    .word fx_music_sfx_{i}" for i in range(len(self.sound_effects))]
        # sfx_init only reads the list pointer, so an empty list is valid.
        for index, effect in enumerate(self.sound_effects):
            data = []
            for tone in effect.tones if isinstance(effect, SoundEffect) else (effect,):
                data += [0x80, tone.control, 0x81, tone.timer & 255, 0x82, tone.timer >> 8]
                frames = tone.frames
                while frames:
                    wait = min(127, frames)
                    data.append(wait)
                    frames -= wait
            # EOF still mixes its buffer once, so clear volume before ending.
            data += [0x80, 0x30, 0]
            lines += [f"fx_music_sfx_{index}:"]
            lines += ['    .byte ' + ', '.join(f'${byte:02X}' for byte in data[i:i+16])
                      for i in range(0, len(data), 16)]
        return lines
