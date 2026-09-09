"""Interrupt actual room-loading machine code between individual instructions.

This verifies register and PPU ownership, not cycle-accurate video timing. The
test bus reports vblank continuously; explicit NMIs exercise concurrency paths.
"""

import unittest

from py3nes import (Button, ChangeRoom, Game, PlaySound, SetBackgroundTile,
                    Tone, WriteText)
from py3nes.assets import encode_text
from tests.nes_bus import NESBus
from tests.runtime_harness import HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME, RuntimeHarness


class ObservedBus(NESBus):
    def __init__(self, rom):
        super().__init__(rom)
        self.io_reads = []
        self.io_writes = []
        self.data_writes = []

    def __getitem__(self, address):
        if isinstance(address, int) and 0x2000 <= address < 0x4020:
            self.io_reads.append(address)
        return super().__getitem__(address)

    def __setitem__(self, address, value):
        if 0x2000 <= address < 0x4020:
            self.io_writes.append((address, value & 255))
        if 0x2000 <= address < 0x4000 and address & 7 == 7:
            self.data_writes.append((self.ppuaddr, value & 255, self.ppumask))
        super().__setitem__(address, value)

    @classmethod
    def observe(cls, run):
        bus = cls(run.rom)
        bus.__dict__.update(run.bus.__dict__)
        run.bus = bus
        run.cpu.memory = bus
        return bus


@unittest.skipUnless(HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME)
class RoomInterruptTests(unittest.TestCase):
    def test_nmi_preserves_every_loader_instruction_and_partial_ppu_addresses(self):
        game = Game()
        source, target = game.room("source"), game.room("target")
        source.actor(tile=game.metasprite([[1, 2], [3, 4]]), x=32, y=40)
        player = target.actor(tile=5, x=120, y=112)
        old_tone = Tone(frequency=220, frames=20)
        new_tone = Tone(frequency=880, frames=7)
        source.on_enter(PlaySound(old_tone))
        source.bind_pressed(Button.A,
                            WriteText("S" * 32, 0, 2), WriteText("S" * 32, 0, 3),
                            PlaySound(old_tone), ChangeRoom(target))
        target.on_enter(WriteText("D" * 32, 0, 2), WriteText("E" * 32, 0, 3),
                        PlaySound(new_tone))
        with RuntimeHarness(game) as run:
            bus = ObservedBus.observe(run)
            run.interrupt()  # Commit startup audio and release the first tick.
            run.bus.buttons = int(Button.A)
            run.run_until(lambda: run.read("rt_room_loading") == 1)
            self.assertEqual(run.read("fx_vram_length"), 192,
                             "the source has staged a full, unpublished queue")
            bus.data_writes.clear()
            injected, partial_addresses = 0, 0
            for _ in range(20000):
                if run.read("rt_room_loading") == 0:
                    break
                registers = (run.cpu.pc, run.cpu.sp, run.cpu.a, run.cpu.x,
                             run.cpu.y, run.cpu.p & 0xEF)
                ppu = (bus.ppuaddr, bus.address_latch, tuple(bus.scroll),
                       bus.ppumask, len(bus.dma_transfers))
                state = (run.read("fx_vram_length"), run.read("fx_vram_cursor"),
                         run.read("fx_sound_pending"), run.read("fx_sound_remaining"))
                reads, writes = len(bus.io_reads), len(bus.io_writes)
                partial_addresses += int(bus.address_latch)
                run.interrupt()
                self.assertEqual((run.cpu.pc, run.cpu.sp, run.cpu.a, run.cpu.x,
                                  run.cpu.y, run.cpu.p & 0xEF), registers)
                self.assertEqual((bus.ppuaddr, bus.address_latch, tuple(bus.scroll),
                                  bus.ppumask, len(bus.dma_transfers)), ppu)
                self.assertEqual((run.read("fx_vram_length"), run.read("fx_vram_cursor"),
                                  run.read("fx_sound_pending"), run.read("fx_sound_remaining")), state)
                self.assertEqual((len(bus.io_reads), len(bus.io_writes)), (reads, writes),
                                 "NMI must not even read PPUSTATUS while main owns its address latch")
                injected += 1
                run.cpu.step()
            else:
                self.fail("the interrupted room loader did not complete")

            self.assertGreater(injected, 5000)
            self.assertGreater(partial_addresses, 0)
            run.run_until(lambda: run.cpu.pc == run.labels["main_loop"] and run.read("frame_ready"))
            self.assertEqual(run.read("rt_room"), target.index)
            self.assertEqual(len(bus.data_writes), 1024 + 64)
            self.assertTrue(all(mask & 0x18 == 0 for _, _, mask in bus.data_writes))
            self.assertEqual(tuple(bus.ppu_read(0x2040 + i) for i in range(64)),
                             encode_text("D" * 32 + "E" * 32))
            self.assertEqual(run.read("fx_vram_length"), 0)
            self.assertEqual(tuple(bus.oam[:4]), (111, 5, 0, 120))
            self.assertTrue(all(bus.oam[index * 4] == 255 for index in range(1, 64)))
            self.assertEqual(run.variable(player.x.name), 120)
            self.assertEqual(bus.scroll, [0, 0])
            self.assertEqual(bus.ppumask & 0x18, 0x18)
            bus.io_writes.clear()
            run.interrupt()
            self.assertIn((0x4002, new_tone.timer & 255), bus.io_writes)
            self.assertEqual(run.read("fx_sound_remaining"), new_tone.frames)

    def test_published_queue_finishes_before_transition_and_unpublished_queue_is_discarded(self):
        game = Game()
        source, target = game.room("source"), game.room("target")
        source.actor(tile=game.metasprite([[1, 2], [3, 4]]), x=32, y=40)
        target.text("DESTINATION")
        target.actor(tile=5, x=80, y=80)
        stale_tile = game.tile(["33333333"] * 8)
        source.bind_pressed(Button.A, WriteText("A" * 32, 0, 0), WriteText("B" * 31, 0, 1))
        source.bind_pressed(Button.B, SetBackgroundTile(stale_tile, column=31, row=29), ChangeRoom(target))
        with RuntimeHarness(game) as run:
            bus = ObservedBus.observe(run)
            run.frame(Button.A)
            self.assertEqual(run.read("fx_vram_length"), 189)
            self.assertEqual(bus.data_writes, [])
            bus.buttons = int(Button.B)
            for index in range(4):
                run.interrupt()
                self.assertEqual(run.read("rt_room"), source.index)
                self.assertEqual(run.read("frame_ready"), int(index < 3))
                self.assertEqual(len(bus.data_writes), min(63, 16 * (index + 1)))
                if index < 3:
                    for _ in range(30):
                        run.cpu.step()
                    self.assertEqual(run.read("rt_room_loading"), 0)
            run.run_until(lambda: run.cpu.pc == run.labels["main_loop"] and run.read("frame_ready"))
            self.assertEqual(run.read("rt_room"), target.index)
            self.assertEqual([value for _, value, _ in bus.data_writes[:63]],
                             list(encode_text("A" * 32 + "B" * 31)))
            self.assertEqual(len(bus.data_writes), 63 + 1024)
            self.assertFalse(any(value == stale_tile for _, value, _ in bus.data_writes))
            self.assertTrue(all(mask & 0x18 == 0 for _, _, mask in bus.data_writes[63:]))
            self.assertEqual(tuple(bus.oam[:4]), (79, 5, 0, 80))
            self.assertTrue(all(bus.oam[index * 4] == 255 for index in range(1, 64)))
            run.interrupt()
            self.assertEqual(len(bus.data_writes), 63 + 1024,
                             "no source-room updates may leak into a later NMI")


if __name__ == "__main__":
    unittest.main()
