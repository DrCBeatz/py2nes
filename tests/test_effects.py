"""Validate display/audio descriptions and execute their assembled 6502 code."""

from pathlib import Path
import re
import shutil
import tempfile
import unittest

from py3nes import Button, Game
from py3nes.assets import encode_text
from py3nes.effects import PlaySound, SetBackgroundTile, StopSound, Tone, WriteNumber, WriteText, write_count
from py3nes.ir import If
from tests.nes_bus import NESBus

try:
    from py65.devices.mpu6502 import MPU
except ImportError:
    MPU = None


class EffectDescriptionTests(unittest.TestCase):
    def test_text_uppercases_pads_and_checks_screen_bounds(self):
        text = WriteText("hi", column=27, row=29, width=5)
        self.assertEqual(text.tiles, encode_text("HI   "))
        self.assertEqual(write_count(text), 5)
        self.assertEqual(WriteText("", column=0, row=0).tiles, ())
        for kwargs in ({"text": "OVERFLOW", "column": 30, "row": 0},
                       {"text": "TOO LONG", "column": 0, "row": 0, "width": 2},
                       {"text": "A\nB", "column": 0, "row": 0},
                       {"text": "A", "column": 0, "row": 30}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                WriteText(**kwargs)

    def test_numeric_width_and_background_coordinates(self):
        self.assertEqual(write_count(WriteNumber(255, column=29, row=0)), 3)
        for digits in (0, 4):
            with self.assertRaises(ValueError):
                WriteNumber(1, column=0, row=0, digits=digits)
        with self.assertRaises(ValueError):
            WriteNumber(1, column=30, row=0)
        with self.assertRaises(ValueError):
            SetBackgroundTile(256, column=0, row=0)

    def test_tone_quantization_and_validation(self):
        tone = Tone(frequency=440, frames=12, volume=10, duty=2)
        self.assertEqual(tone.timer, 253)
        self.assertEqual(tone.control, 0xBA)
        for kwargs in ({"frequency": 1}, {"frequency": 20000}, {"frames": 0},
                       {"frames": 256}, {"volume": 16}, {"duty": 4}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Tone(**kwargs)
        with self.assertRaises(TypeError):
            PlaySound(440)

    def test_queue_budget_rejects_all_possible_events_over_capacity(self):
        game = Game()
        game.bind_pressed(Button.A, WriteText("A" * 32, column=0, row=0))
        game.bind_pressed(Button.B, WriteText("B" * 32, column=0, row=1))
        game.every_frame(SetBackgroundTile(0, column=0, row=2))
        with self.assertRaisesRegex(ValueError, "64|budget|writes"):
            game.to_assembly()

    def test_queue_budget_uses_larger_branch_and_includes_post_events(self):
        game = Game()
        flag = game.flag("show")
        game.every_frame(If(flag, WriteText("A" * 32, column=0, row=0),
                            otherwise=(WriteText("B" * 32, column=0, row=0),)))
        game.after_physics(WriteText("C" * 32, column=0, row=1))
        self.assertIn("fx_drain_vram", game.to_assembly())
        game.after_physics(SetBackgroundTile(0, column=0, row=2))
        with self.assertRaisesRegex(ValueError, "64|budget|writes"):
            game.to_assembly()


class TracingBus(NESBus):
    def __init__(self, rom):
        self.ppu_writes = []
        self.audio_writes = []
        super().__init__(rom)

    def __setitem__(self, address, value):
        if 0x2000 <= address < 0x4000 and address & 7 == 7:
            self.ppu_writes.append((self.ppuaddr, value & 255))
        if address in (0x4000, 0x4001, 0x4002, 0x4003, 0x4015):
            self.audio_writes.append((address, value & 255))
        super().__setitem__(address, value)


@unittest.skipUnless(MPU and shutil.which("ca65") and shutil.which("ld65"), "requires py65 and cc65")
class CompiledEffectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py3nes-effects-")
        cls.addClassCleanup(cls.directory.cleanup)
        queue = Game()
        cls.first_tone = Tone(frequency=440, frames=3)
        cls.second_tone = Tone(frequency=880, frames=5, duty=1, volume=7)
        queue.bind_pressed(Button.A, PlaySound(cls.first_tone),
                           WriteText("A" * 32, column=0, row=0),
                           WriteText("B" * 32, column=0, row=1))
        queue.bind_pressed(Button.B, PlaySound(cls.second_tone))
        queue.bind_pressed(Button.SELECT, StopSound())
        numbers = Game()
        value = numbers.byte("score", initial=255)
        numbers.bind_pressed(Button.A, WriteNumber(value, column=2, row=4),
                             WriteNumber(value, column=2, row=5, digits=2),
                             WriteNumber(value, column=2, row=6, digits=1),
                             WriteText("hi", column=20, row=29, width=5),
                             SetBackgroundTile(1, column=31, row=29))
        cls.fixtures = {}
        for name, game in (("queue", queue), ("numbers", numbers)):
            result = game.build(Path(cls.directory.name) / f"{name}.nes")
            labels = {}
            for line in result.labels_path.read_text().splitlines():
                match = re.match(r"\s*al\s+([0-9a-fA-F]+)\s+\.?([^\s]+)", line)
                if match:
                    labels[match[2]] = int(match[1], 16)
            cls.fixtures[name] = (result.rom_path.read_bytes(), labels)

    def start(self, fixture="queue"):
        rom, self.labels = self.fixtures[fixture]
        self.bus = TracingBus(rom)
        self.cpu = MPU(memory=self.bus, pc=None)
        self.run_until(lambda: self.cpu.pc == self.labels["main_loop"])
        self.bus.ppu_writes.clear()
        self.bus.audio_writes.clear()

    def run_until(self, condition, maximum=150000):
        for _ in range(maximum):
            if condition():
                return
            self.cpu.step()
        self.fail(f"6502 did not reach expected state; PC=${self.cpu.pc:04X}")

    def memory(self, name):
        return self.bus[self.labels[name]]

    def nmi(self):
        pc, sp = self.cpu.pc, self.cpu.sp
        cycles = self.cpu.processorCycles
        self.cpu.nmi()
        self.run_until(lambda: self.cpu.pc == pc and self.cpu.sp == sp, maximum=5000)
        return self.cpu.processorCycles - cycles

    def update(self, buttons):
        self.bus.buttons = int(buttons)
        self.run_until(lambda: self.cpu.pc == self.labels["main_loop"] and self.memory("frame_ready"))

    def prepare(self, buttons=Button.A, fixture="queue"):
        self.start(fixture)
        self.nmi()
        self.update(buttons)

    def test_queue_drains_sixteen_per_blank_and_stalls_main_until_complete(self):
        self.prepare()
        self.assertEqual(self.memory("fx_vram_length"), 192)
        self.assertEqual(self.bus.ppu_writes, [])
        for frame in range(4):
            before = len(self.bus.ppu_writes)
            cycles = self.nmi()
            self.assertEqual(len(self.bus.ppu_writes) - before, 16)
            # py65 excludes DMA suspension; add worst-case 514 CPU cycles.
            self.assertLess(cycles + 514, 1800)
            self.assertEqual(self.memory("frame_ready"), int(frame < 3))
            if frame < 3:
                for _ in range(100):
                    self.cpu.step()
                self.assertEqual(self.memory("fx_vram_length"), 192)
        self.assertEqual(self.memory("fx_vram_length"), 0)
        self.assertEqual(self.memory("fx_vram_cursor"), 0)
        self.assertEqual([self.bus.ppu_read(0x2000 + i) for i in range(64)],
                         list(encode_text("A" * 32 + "B" * 32)))

    def test_every_byte_value_formats_to_decimal_tiles_and_keeps_low_digits(self):
        self.start("numbers")
        for value in range(256):
            with self.subTest(value=value):
                self.bus[self.labels["v_score"]] = value
                self.bus[self.labels["controller_previous"]] = 0
                self.bus[self.labels["controller_held"]] = 0
                self.bus[self.labels["frame_ready"]] = 0
                self.update(Button.A)
                self.nmi()
                for row, digits in ((4, 3), (5, 2), (6, 1)):
                    expected = encode_text(f"{value:03d}"[-digits:])
                    actual = tuple(self.bus.ppu_read(0x2000 + row * 32 + 2 + i) for i in range(digits))
                    self.assertEqual(actual, expected)
        self.assertEqual(tuple(self.bus.ppu_read(0x2000 + 29 * 32 + 20 + i) for i in range(5)),
                         encode_text("HI   "))
        self.assertEqual(self.bus.ppu_read(0x2000 + 29 * 32 + 31), 1)
        self.assertEqual(self.bus.scroll, [0, 0])

    def test_interrupted_requests_are_invisible_until_main_publishes(self):
        self.start()
        self.nmi()
        self.bus.buttons = int(Button.A)
        self.run_until(lambda: self.cpu.pc == self.labels["update_events"])
        for _ in range(2500):
            if self.memory("frame_ready"):
                break
            registers = (self.cpu.a, self.cpu.x, self.cpu.y, self.cpu.p & 0xEF)
            self.nmi()
            self.assertEqual((self.cpu.a, self.cpu.x, self.cpu.y, self.cpu.p & 0xEF), registers)
            self.assertEqual(self.bus.ppu_writes, [])
            self.assertEqual(self.bus.audio_writes, [])
            self.cpu.step()
        else:
            self.fail("main did not finish constructing the update")
        self.nmi()
        self.assertEqual(len(self.bus.ppu_writes), 16)
        self.assertIn((0x4002, self.first_tone.timer & 255), self.bus.audio_writes)

    def test_sound_expires_in_video_frames_while_graphics_queue_stalls_main(self):
        self.prepare()
        self.nmi()
        tone = self.first_tone
        self.assertEqual(self.bus.audio_writes, [(0x4015, 1), (0x4000, tone.control),
                                               (0x4001, 8), (0x4002, tone.timer & 255),
                                               (0x4003, tone.timer >> 8)])
        self.assertEqual(self.memory("fx_sound_remaining"), 3)
        self.nmi()
        self.assertEqual(self.memory("fx_sound_remaining"), 2)
        self.nmi()
        self.assertEqual(self.memory("fx_sound_remaining"), 1)
        self.nmi()
        self.assertEqual(self.memory("fx_sound_remaining"), 0)
        self.assertEqual(self.bus.audio_writes[-1], (0x4000, 0x30))
        self.assertEqual(sum(address == 0x4003 for address, _ in self.bus.audio_writes), 1)

    def test_sound_replacement_and_stop(self):
        self.prepare(Button.B)
        self.nmi()
        self.assertEqual(self.memory("fx_sound_remaining"), self.second_tone.frames)
        self.update(Button.SELECT)
        self.nmi()
        self.assertEqual(self.memory("fx_sound_remaining"), 0)
        self.assertEqual(self.bus.audio_writes[-1], (0x4000, 0x30))
        self.update(Button.B)
        self.nmi()
        self.assertEqual(self.memory("fx_sound_remaining"), self.second_tone.frames)
        self.update(Button.A)
        self.nmi()
        self.assertEqual(self.memory("fx_sound_remaining"), self.first_tone.frames)
        self.assertEqual(self.bus.audio_writes[-1], (0x4003, self.first_tone.timer >> 8))


if __name__ == "__main__":
    unittest.main()
