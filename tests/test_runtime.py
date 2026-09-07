"""Execute assembled ROM code, including reset and interrupt handlers.

These integration tests need the optional py65 package and cc65's ca65/ld65
executables. The bus verifies register/data behavior; it is not a NES emulator
and does not establish rendering or instruction-cycle timing correctness.
"""

from pathlib import Path
import re
import shutil
import tempfile
import unittest

try:
    from py65.devices.mpu6502 import MPU
except ImportError:
    MPU = None

from py3nes import Button, Game, Move, SetPosition, SetTile, Tile
from tests.nes_bus import NESBus


HAS_ASSEMBLER = bool(shutil.which("ca65") and shutil.which("ld65"))


@unittest.skipUnless(MPU is not None and HAS_ASSEMBLER, "requires py65 and cc65 (ca65/ld65)")
class CompiledRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py3nes-runtime-")
        cls.addClassCleanup(cls.directory.cleanup)
        game = Game(region="NTSC", mapper="NROM")
        cls.player_rows = (
            "11111111", "10000001", "10222201", "10233201",
            "10233201", "10222201", "10000001", "11111111",
        )
        cls.player_tile = game.tile(Tile.from_rows(cls.player_rows))
        cls.alternate_tile = game.tile(Tile.from_rows(("22222222",) * 8))
        player = game.sprite(tile=cls.player_tile, x=80, y=80)
        clock_sprite = game.sprite(tile=cls.alternate_tile, x=255, y=0)
        game.text("HELLO NES", column=2, row=2)
        game.bind_held(Button.RIGHT, Move(player, dx=1))
        game.bind_held(Button.LEFT, Move(player, dx=-1))
        game.bind_held(Button.UP, Move(player, dy=-1))
        game.bind_held(Button.DOWN, Move(player, dy=1))
        game.bind_pressed(Button.A, Move(player, dx=7))
        game.bind_pressed(Button.B, SetPosition(player, x=12, y=34))
        game.bind_pressed(Button.START, SetTile(player, tile=cls.alternate_tile))
        game.every_frame(Move(clock_sprite, dx=1, dy=-1))
        cls.result = game.build(Path(cls.directory.name) / "runtime.nes")
        cls.rom = cls.result.rom_path.read_bytes()
        cls.labels = {}
        for line in cls.result.labels_path.read_text().splitlines():
            match = re.match(r"\s*al\s+([0-9a-fA-F]+)\s+\.?([^\s]+)", line)
            if match:
                cls.labels[match[2]] = int(match[1], 16)

    def setUp(self):
        self.bus = NESBus(self.rom)
        self.cpu = MPU(memory=self.bus, pc=None)
        self.run_until(lambda: self.cpu.pc == self.labels["main_loop"])

    def run_until(self, condition, maximum=150000):
        for _ in range(maximum):
            if condition():
                return
            self.cpu.step()
        self.fail(f"6502 did not reach expected state; PC=${self.cpu.pc:04X}")

    def variable(self, name):
        return self.bus[self.labels[name]]

    def sprite_data(self, index=0):
        start = 0x200 + index * 4
        return tuple(self.bus[start : start + 4])  # y, tile, attributes, x

    def frame(self, buttons=0):
        self.bus.buttons = int(buttons)
        self.cpu.nmi()
        self.run_until(
            lambda: self.cpu.pc == self.labels["main_loop"]
            and self.variable("frame_ready") == 1
        )

    def interrupt_only(self):
        return_pc, return_sp = self.cpu.pc, self.cpu.sp
        self.cpu.nmi()
        self.run_until(lambda: self.cpu.pc == return_pc and self.cpu.sp == return_sp, maximum=5000)

    def test_rom_structure_vectors_and_generated_artifacts(self):
        self.assertEqual(self.rom[:6], b"NES\x1a\x01\x01")
        self.assertEqual(len(self.rom), 16 + 16384 + 8192)
        self.assertEqual(self.rom[6] >> 4, 0)
        self.assertEqual(self.rom[7] & 0xF0, 0)
        for field in ("rom_path", "assembly_path", "config_path", "map_path", "labels_path"):
            self.assertTrue(getattr(self.result, field).is_file(), field)
        for name in (
            "reset", "nmi", "main_loop", "read_controller", "update_events",
            "controller_held", "controller_pressed", "controller_previous", "frame_ready",
        ):
            self.assertIn(name, self.labels)
        self.assertEqual(self.bus[0xFFFC] | self.bus[0xFFFD] << 8, self.labels["reset"])
        self.assertEqual(self.bus[0xFFFA] | self.bus[0xFFFB] << 8, self.labels["nmi"])
        self.assertEqual(self.bus[0x8000:0xC000], self.bus[0xC000:0x10000])

    def test_reset_initializes_background_palette_chr_and_oam(self):
        self.assertGreaterEqual(self.bus.status_reads, 2)
        self.assertEqual(self.bus.ppuctrl & 0x80, 0x80)
        self.assertEqual(self.bus.ppumask & 0x18, 0x18)
        self.assertEqual(self.bus.scroll, [0, 0])
        palette = [self.bus.ppu_read(0x3F00 + index) for index in range(32)]
        self.assertTrue(any(palette))
        self.assertTrue(all(value <= 0x3F for value in palette))
        text = [self.bus.ppu_read(0x2000 + 2 * 32 + 2 + index) for index in range(9)]
        self.assertEqual(text[2], text[3])  # Repeated L.
        self.assertEqual(text[1], text[7])  # Repeated E.
        background_base = 0x1000 if self.bus.ppuctrl & 0x10 else 0
        for index, tile in enumerate(text):
            pattern = self.bus.chr[background_base + tile * 16 : background_base + (tile + 1) * 16]
            self.assertEqual(any(pattern), index != 5, f"glyph {index}")
        self.assertEqual(self.sprite_data(), (80, self.player_tile, 0, 80))
        self.assertEqual(bytes(self.bus.oam), bytes(self.bus.ram[0x200:0x300]))
        self.assertTrue(all(self.bus.oam[index * 4] >= 0xEF for index in range(2, 64)))
        sprite_base = 0x1000 if self.bus.ppuctrl & 8 else 0
        expected = bytes(
            sum(((int(pixel) >> plane) & 1) << (7 - column) for column, pixel in enumerate(row))
            for plane in range(2) for row in self.player_rows
        )
        offset = sprite_base + self.player_tile * 16
        self.assertEqual(self.bus.chr[offset : offset + 16], expected)

    def test_held_movement_repeats_and_release_stops(self):
        self.frame(Button.RIGHT)
        self.assertEqual(self.sprite_data()[3], 81)
        self.assertEqual(self.variable("controller_held"), 1)
        self.assertEqual(self.variable("controller_pressed"), 1)
        self.frame(Button.RIGHT)
        self.assertEqual(self.sprite_data()[3], 82)
        self.assertEqual(self.variable("controller_pressed"), 0)
        self.frame()
        self.assertEqual(self.sprite_data()[3], 82)
        self.assertEqual(self.variable("controller_held"), 0)
        self.frame(Button.LEFT)
        self.assertEqual(self.sprite_data()[3], 81)

    def test_pressed_action_fires_only_on_new_press(self):
        self.frame(Button.A)
        self.assertEqual(self.sprite_data()[3], 87)
        self.assertEqual(self.variable("controller_pressed"), 0x80)
        self.frame(Button.A)
        self.assertEqual(self.sprite_data()[3], 87)
        self.assertEqual(self.variable("controller_pressed"), 0)
        self.frame()
        self.frame(Button.A)
        self.assertEqual(self.sprite_data()[3], 94)

    def test_combined_buttons_and_vertical_movement(self):
        self.frame(Button.RIGHT | Button.UP)
        self.assertEqual(self.sprite_data()[0], 79)
        self.assertEqual(self.sprite_data()[3], 81)
        self.assertEqual(self.variable("controller_held"), 9)
        self.frame(Button.DOWN | Button.LEFT)
        self.assertEqual(self.sprite_data()[0], 80)
        self.assertEqual(self.sprite_data()[3], 80)
        self.assertEqual(self.variable("controller_pressed"), 6)
        self.frame(Button.SELECT)
        self.assertEqual(self.variable("controller_held"), 0x20)
        self.assertEqual(self.variable("controller_pressed"), 0x20)

    def test_position_and_tile_actions_execute_in_rom(self):
        self.frame(Button.B)
        self.assertEqual(self.sprite_data(), (34, self.player_tile, 0, 12))
        self.frame(Button.START)
        self.assertEqual(self.sprite_data(), (34, self.alternate_tile, 0, 12))

    def test_every_frame_action_wraps_at_byte_boundaries(self):
        self.assertEqual(self.sprite_data(1)[::3], (0, 255))
        self.frame()
        self.assertEqual(self.sprite_data(1)[::3], (255, 0))
        self.frame()
        self.assertEqual(self.sprite_data(1)[::3], (254, 1))

    def test_main_waits_for_frame_before_updating(self):
        self.bus.buttons = int(Button.RIGHT)
        original = self.sprite_data()
        for _ in range(1000):
            self.cpu.step()
        self.assertEqual(self.sprite_data(), original)
        self.frame(Button.RIGHT)
        self.assertEqual(self.sprite_data()[3], original[3] + 1)

    def test_nmi_preserves_registers_and_never_uploads_partial_frame(self):
        self.cpu.a, self.cpu.x, self.cpu.y = 0xA5, 0x5A, 0x37
        self.cpu.p = 0x61
        original = (self.cpu.a, self.cpu.x, self.cpu.y, self.cpu.sp, self.cpu.pc, self.cpu.p & 0xEF)
        self.bus[self.labels["frame_ready"]] = 0
        previous_oam = bytes(self.bus.oam)
        partial_frame = bytes((index * 17 + 23) & 0xFF for index in range(256))
        self.bus.ram[0x200:0x300] = partial_frame
        transfer_count = len(self.bus.dma_transfers)
        self.interrupt_only()
        self.assertEqual(bytes(self.bus.oam), previous_oam)
        self.assertEqual(len(self.bus.dma_transfers), transfer_count)
        self.assertEqual(self.variable("frame_ready"), 0)
        self.assertEqual(
            (self.cpu.a, self.cpu.x, self.cpu.y, self.cpu.sp, self.cpu.pc, self.cpu.p & 0xEF), original
        )
        self.bus[self.labels["frame_ready"]] = 1
        self.interrupt_only()
        self.assertEqual(bytes(self.bus.oam), partial_frame)
        self.assertEqual(len(self.bus.dma_transfers), transfer_count + 1)
        self.assertEqual(self.variable("frame_ready"), 0)
        self.assertEqual(
            (self.cpu.a, self.cpu.x, self.cpu.y, self.cpu.sp, self.cpu.pc, self.cpu.p & 0xEF), original
        )

    def test_nmi_at_every_update_instruction_and_immediately_after_ready_store(self):
        self.bus.buttons = int(Button.RIGHT)
        self.interrupt_only()
        self.run_until(lambda: self.cpu.pc == self.labels["update_events"])
        previous_oam = bytes(self.bus.oam)
        transfer_count = len(self.bus.dma_transfers)
        saw_changed_buffer = False
        for _ in range(500):
            if self.variable("frame_ready"):
                break
            # Interrupt every instruction boundary, including during coordinate
            # writes and immediately before the main loop publishes its buffer.
            self.interrupt_only()
            self.assertEqual(len(self.bus.dma_transfers), transfer_count)
            self.assertEqual(bytes(self.bus.oam), previous_oam)
            saw_changed_buffer |= bytes(self.bus.ram[0x200:0x300]) != previous_oam
            self.cpu.step()
        else:
            self.fail("gameplay did not publish its completed OAM buffer")
        self.assertTrue(saw_changed_buffer)
        self.assertEqual(self.sprite_data()[3], 81)
        self.assertEqual(self.sprite_data(1)[::3], (255, 0))
        completed_buffer = bytes(self.bus.ram[0x200:0x300])

        # The CPU is now on the instruction immediately after STA frame_ready.
        # This NMI must consume the complete buffer and allow the next update.
        self.interrupt_only()
        self.assertEqual(bytes(self.bus.oam), completed_buffer)
        self.assertEqual(len(self.bus.dma_transfers), transfer_count + 1)
        self.assertEqual(self.variable("frame_ready"), 0)
        self.run_until(
            lambda: self.cpu.pc == self.labels["main_loop"]
            and self.variable("frame_ready") == 1
        )
        self.assertEqual(self.sprite_data()[3], 82)


if __name__ == "__main__":
    unittest.main()
