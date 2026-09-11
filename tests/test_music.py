"""Import contracts and assembled audio integration, including NMI ownership."""
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from py3nes import Button, ChangeRoom, Game, If, PlaySound, Set, SoundEffect, StopSound, Tone, WriteText
from py3nes.music import (Music, MusicExportError, PauseMusic, PlayMusic, StopMusic,
                          export_famistudio, famistudio_command, load_famistudio)
from tests.nes_bus import NESBus
from tests.runtime_harness import HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME, RuntimeHarness

ASSETS = Path(__file__).resolve().parents[1] / "examples/assets/music"


def sample():
    return load_famistudio(ASSETS / "little_rooms.music.json")


class MusicAssetTests(unittest.TestCase):
    def test_portable_export_round_trip_is_immutable_and_does_not_invoke_editor(self):
        with patch("subprocess.run", side_effect=AssertionError("editor invoked")):
            music = sample()
            self.assertEqual(music.songs, ("Explore", "Victory"))
            self.assertEqual(music.features, frozenset())
            self.assertEqual(PlayMusic(music, "Victory").song, 1)
            with tempfile.TemporaryDirectory() as directory:
                path = music.save(Path(directory) / "song.music.json")
                self.assertEqual(load_famistudio(path), music)
                raw = Path(directory) / "song.s"
                raw.write_text(music.assembly)
                self.assertEqual(load_famistudio(raw), music)
            with self.assertRaises(FrozenInstanceError):
                music.assembly = "changed"

    def test_song_validation_and_command_types(self):
        music = sample()
        for song in ("Missing", -1, 2, True):
            with self.subTest(song=song), self.assertRaises((ValueError, TypeError)):
                PlayMusic(music, song)
        for construct in (lambda: PlayMusic("song"), lambda: PlayMusic(music, restart=1),
                          lambda: PauseMusic(1), lambda: SoundEffect(()),
                          lambda: SoundEffect((Tone(),), priority=256)):
            with self.assertRaises((ValueError, TypeError)):
                construct()

    def test_portable_schema_and_unsupported_assembly_rejected(self):
        music = sample()
        for assembly in ("lda #1", music.assembly.replace(".byte 2", ".byte 3", 1),
                         music.assembly + '\n.include "other.s"\n',
                         music.assembly.replace("@samples:\n", "@samples:\n    .byte 1,2,3\n"),
                         "; FAMISTUDIO_EXP_VRC6 = 1\n" + music.assembly,
                         "; FAMISTUDIO_USE_DELTA_COUNTER = 1\n" + music.assembly):
            with self.subTest(assembly=assembly[:60]), self.assertRaises(ValueError):
                Music(assembly)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.music.json"
            for document in ({}, {"format": "py3nes-famistudio", "version": 99}, []):
                path.write_text(json.dumps(document))
                with self.assertRaises(ValueError):
                    load_famistudio(path)

    def test_editor_override_handles_spaces_and_argv_without_shell(self):
        self.assertEqual(famistudio_command(("editor path", "--option")), ("editor path", "--option"))
        with patch.dict("os.environ", {"FAMISTUDIO": "/an editor/FamiStudio"}):
            self.assertEqual(famistudio_command(), ("/an editor/FamiStudio",))
        with patch("py3nes.music._dotnet", return_value="dotnet"):
            self.assertEqual(famistudio_command("/Applications/FamiStudio.app"),
                             ("dotnet", "/Applications/FamiStudio.app/Contents/MacOS/FamiStudio.dll"))
        with self.assertRaises(TypeError):
            famistudio_command([])

    def test_missing_editor_is_actionable_and_does_not_touch_source(self):
        source = ASSETS / "little_rooms.fms"
        before = source.read_bytes()
        with self.assertRaisesRegex(MusicExportError, "could not run FamiStudio"):
            load_famistudio(source, executable="/missing/editor")
        self.assertEqual(source.read_bytes(), before)

    def test_project_validation_rejects_unsupported_hardware_and_tuning(self):
        from py3nes.music import _validate_project
        for text in ('Project PAL="True"', 'Project Expansions="VRC6"',
                     'Project Tuning="432"', 'Project\n\tDPCMSample Name="kick"',
                     'Project TempoMode="FamiStudio"\n\tDPCMMapping Note="C4"'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                _validate_project(text)

    def test_stop_pause_without_any_music_are_valid_noops(self):
        game = Game()
        game.bind_pressed(Button.A, StopMusic(), PauseMusic(False))
        self.assertNotIn("famistudio_update", game.to_assembly())


class AudioBus(NESBus):
    def __setitem__(self, address, value):
        if 0x4000 <= address <= 0x4015 or 0x2000 <= address < 0x4000:
            self.writes.append((self.cpu.processorCycles, address, value & 255))
        super().__setitem__(address, value)


def trace(runtime):
    runtime.bus.__class__ = AudioBus
    runtime.bus.writes = []
    runtime.bus.cpu = runtime.cpu
    return runtime.bus.writes


@unittest.skipUnless(HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME)
class CompiledMusicTests(unittest.TestCase):
    def game(self):
        game = Game()
        music = sample()
        game.bind_pressed(Button.START, PlayMusic(music, "Explore"))
        game.bind_pressed(Button.SELECT, PlayMusic(music, "Victory"))
        game.bind_pressed(Button.UP, PauseMusic())
        game.bind_pressed(Button.DOWN, PauseMusic(False))
        game.bind_pressed(Button.LEFT, StopMusic())
        self.effect = SoundEffect((Tone(1100, frames=2, volume=15),
                                   Tone(1650, frames=3, volume=15)), priority=2)
        game.bind_pressed(Button.A, PlaySound(self.effect))
        game.bind_pressed(Button.B, StopSound())
        return game

    def test_music_plays_four_channels_pauses_resumes_stops_and_one_shot_ends(self):
        with RuntimeHarness(self.game()) as r:
            writes = trace(r)
            r.frame(Button.START)
            r.interrupt()
            self.assertEqual(r.read("fx_music_current"), 0)
            self.assertEqual(r.read("fx_music_current_song"), 0)
            addresses = {address for _, address, _ in writes}
            self.assertTrue({0x4000, 0x4004, 0x4008, 0x400C} <= addresses)
            r.frame(Button.UP)
            r.interrupt()
            self.assertTrue(r.read("famistudio_song_speed") & 0x80)
            for _ in range(4):
                r.interrupt()
            r.frame(Button.DOWN)
            r.interrupt()
            self.assertEqual(r.read("famistudio_song_speed") & 0x80, 0)
            r.frame(Button.LEFT)
            r.interrupt()
            self.assertEqual(r.read("famistudio_song_speed"), 0)
            self.assertEqual(r.read("fx_music_current"), 255)
            r.frame(Button.SELECT)
            r.interrupt()
            self.assertEqual(r.read("fx_music_current_song"), 1)
            for _ in range(130):
                r.interrupt()
            # FamiStudio encodes an ended one-shot as paused speed zero ($80).
            self.assertEqual(r.read("famistudio_song_speed") & 0x7F, 0)

    def test_same_song_continues_and_restart_reinitializes(self):
        music = sample()
        game = Game()
        game.bind_pressed(Button.A, PlayMusic(music))
        game.bind_pressed(Button.B, PlayMusic(music, restart=True))
        with RuntimeHarness(game) as r:
            r.frame(Button.A)
            r.interrupt()
            for _ in range(17):
                r.interrupt()
            # Count calls to upstream play routine rather than mirror music internals.
            def commit_calls(button):
                r.frame(0)
                r.frame(button)
                target = r.labels["famistudio_music_play"]
                pc, sp = r.cpu.pc, r.cpu.sp
                r.cpu.nmi()
                calls = 0
                for _ in range(10000):
                    if r.cpu.pc == pc and r.cpu.sp == sp:
                        return calls
                    calls += r.cpu.pc == target
                    r.cpu.step()
                self.fail("NMI did not return")
            self.assertEqual(commit_calls(Button.A), 0)
            self.assertEqual(commit_calls(Button.B), 1)

    def test_sfx_steps_restore_music_and_stop_preserves_music(self):
        with RuntimeHarness(self.game()) as r:
            writes = trace(r)
            r.frame(Button.START)
            r.interrupt()
            r.frame(Button.A)
            r.interrupt()
            def last(address):
                return next(value for _, register, value in reversed(writes) if register == address)
            self.assertEqual(last(0x4002), self.effect.tones[0].timer & 255)
            r.interrupt()
            self.assertEqual(last(0x4002), self.effect.tones[0].timer & 255)
            r.interrupt()
            self.assertEqual(last(0x4002), self.effect.tones[1].timer & 255)
            for _ in range(3):
                r.interrupt()
            self.assertEqual(r.read("famistudio_sfx_ptr_hi"), 0)
            self.assertNotEqual(last(0x4002), self.effect.tones[1].timer & 255)
            r.frame(0)
            r.frame(Button.A)
            r.interrupt()
            r.frame(Button.B)
            r.interrupt()
            self.assertEqual(r.read("famistudio_sfx_ptr_hi"), 0)
            self.assertNotEqual(r.read("famistudio_song_speed"), 0)

    def test_display_finishes_within_vblank_before_music_and_music_ticks_during_backpressure(self):
        game = self.game()
        game.bind_pressed(Button.RIGHT, WriteText("A" * 32, 0, 0), WriteText("B" * 32, 0, 1))
        with RuntimeHarness(game) as r:
            writes = trace(r)
            r.frame(Button.START | Button.RIGHT)
            largest = 0
            for frame in range(260):
                writes.clear()
                start = r.cpu.processorCycles
                r.interrupt()
                largest = max(largest, r.cpu.processorCycles - start + 514)
                display = [(cycle, address) for cycle, address, _ in writes if address < 0x4000]
                audio = [(cycle, address) for cycle, address, _ in writes if 0x4000 <= address <= 0x4013]
                self.assertLess(max(cycle for cycle, _ in display) - start + 514, 2000)
                self.assertGreater(min(cycle for cycle, _ in audio), max(cycle for cycle, _ in display))
                if frame < 4:
                    self.assertEqual(r.read("frame_ready"), int(frame < 3))
            self.assertLess(largest, 10000)  # Full NTSC frame has about 29,780 CPU cycles.
            self.assertNotEqual(r.read("famistudio_song_speed"), 0)

    def test_interrupting_every_request_instruction_preserves_unpublished_audio_and_scratch(self):
        with RuntimeHarness(self.game()) as r:
            r.frame(Button.START)
            r.interrupt()
            r.bus.buttons = int(Button.A | Button.SELECT)
            r.run_until(lambda: r.cpu.pc == r.labels["update_events"])
            for _ in range(1000):
                if r.read("frame_ready"):
                    break
                registers = (r.cpu.a, r.cpu.x, r.cpu.y, r.cpu.p & 0xEF)
                # This byte belongs to the main expression evaluator.
                r.bus[r.labels["rt_expr_rhs"]] = 123
                r.interrupt()
                self.assertEqual((r.cpu.a, r.cpu.x, r.cpu.y, r.cpu.p & 0xEF), registers)
                self.assertEqual(r.read("rt_expr_rhs"), 123)
                self.assertEqual(r.read("fx_music_current_song"), 0)
                self.assertEqual(r.read("famistudio_sfx_ptr_hi"), 0)
                r.cpu.step()
            else:
                self.fail("main did not finish")
            r.interrupt()
            self.assertEqual(r.read("fx_music_current_song"), 1)
            self.assertNotEqual(r.read("famistudio_sfx_ptr_hi"), 0)

    def test_room_transition_discards_source_audio_requests_but_preserves_music(self):
        game = Game()
        first, second = game.room("first"), game.room("second")
        music = sample()
        first.on_enter(PlayMusic(music))
        first.bind_pressed(Button.A, PlayMusic(music, 1), PlaySound(Tone()), ChangeRoom(second))
        second.on_enter(PlayMusic(music))
        second.bind_pressed(Button.B, PlayMusic(music, 1))
        with RuntimeHarness(game) as r:
            r.interrupt()
            r.frame(Button.A)
            r.interrupt()
            self.assertEqual(r.read("rt_room"), 1)
            self.assertEqual(r.read("fx_music_current_song"), 0)
            self.assertEqual(r.read("famistudio_sfx_ptr_hi"), 0)
            r.frame(Button.B)
            r.interrupt()
            self.assertEqual(r.read("fx_music_current_song"), 1)

    def test_optional_feature_union_allocation_assembles_and_tempo_mix_is_rejected(self):
        music = sample()
        flags = "RELEASE_NOTES VOLUME_TRACK VOLUME_SLIDES PITCH_TRACK SLIDE_NOTES NOISE_SLIDE_NOTES VIBRATO ARPEGGIO DUTYCYCLE_EFFECT PHASE_RESET INSTRUMENT_EXTENDED_RANGE".split()
        enhanced = Music(''.join(f'; FAMISTUDIO_USE_{flag} = 1\n' for flag in flags) + music.assembly)
        game = Game()
        game.bind_pressed(Button.A, PlayMusic(enhanced))
        with tempfile.TemporaryDirectory() as directory:
            game.build(Path(directory) / "features.nes")
        # The FamiTracker marker changes data interpretation and cannot be mixed.
        other = Music('; FAMISTUDIO_USE_FAMITRACKER_TEMPO = 1\n' + music.assembly)
        game.bind_pressed(Button.B, PlayMusic(other))
        with self.assertRaisesRegex(ValueError, "cannot mix"):
            game.to_assembly()


@unittest.skipUnless(HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME)
class CompiledSequenceSoundTests(unittest.TestCase):
    def test_effect_without_music_steps_and_priority_arbitration(self):
        game = Game()
        high = SoundEffect((Tone(660, frames=2), Tone(990, frames=2)), priority=3)
        low = Tone(440, frames=10)
        game.bind_pressed(Button.A, PlaySound(high))
        game.bind_pressed(Button.B, PlaySound(low))
        game.bind_pressed(Button.SELECT, StopSound())
        with RuntimeHarness(game) as r:
            writes = trace(r)
            r.frame(Button.A)
            r.interrupt()
            self.assertEqual(r.read("fx_sequence_priority"), 3)
            r.frame(Button.B)
            r.interrupt()
            self.assertEqual(r.read("fx_sequence_priority"), 3)
            for _ in range(5):
                r.interrupt()
            self.assertEqual(r.read("fx_sequence_remaining"), 0)
            lows = [value for _, address, value in writes if address == 0x4002]
            self.assertIn(high.tones[0].timer & 255, lows)
            self.assertIn(high.tones[1].timer & 255, lows)
            self.assertNotIn(low.timer & 255, lows)
            r.frame(0)
            r.frame(Button.B)
            r.interrupt()
            self.assertEqual(r.read("fx_sequence_remaining"), 10)
            r.frame(Button.SELECT)
            r.interrupt()
            self.assertEqual(r.read("fx_sequence_remaining"), 0)

    def test_natural_expiration_does_not_erase_an_unpublished_request(self):
        game = Game()
        first = SoundEffect((Tone(600, frames=1),))
        second = SoundEffect((Tone(900, frames=7),))
        game.bind_pressed(Button.A, PlaySound(first))
        game.bind_pressed(Button.B, PlaySound(second))
        with RuntimeHarness(game) as r:
            r.frame(Button.A)
            r.interrupt()
            r.bus.buttons = int(Button.B)
            r.run_until(lambda: r.read("fx_sequence_pending") == 1)
            self.assertEqual(r.read("frame_ready"), 0)
            r.interrupt()  # First effect expires during construction of second request.
            self.assertEqual(r.read("fx_sequence_pending"), 1)
            r.run_until(lambda: r.cpu.pc == r.labels["main_loop"] and r.read("frame_ready"))
            r.interrupt()
            self.assertEqual(r.read("fx_sequence_remaining"), 7)


try:
    EDITOR = famistudio_command()
except MusicExportError:
    EDITOR = None


@unittest.skipUnless(EDITOR, "optional: requires installed FamiStudio")
class InstalledFamiStudioTests(unittest.TestCase):
    def test_native_editable_project_exports_same_original_songs(self):
        before = (ASSETS / "little_rooms.fms").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "song.music.json"
            music = export_famistudio(ASSETS / "little_rooms.fms", output, executable=EDITOR)
            self.assertEqual(music, sample())
            self.assertEqual(load_famistudio(output), sample())
        self.assertEqual((ASSETS / "little_rooms.fms").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
