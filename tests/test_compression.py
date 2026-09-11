import random
import unittest

from py3nes import Button, ChangeRoom, Game
from py3nes.compression import nametable_storage, pack_collision, pack_runs
from tests.runtime_harness import HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME, RuntimeHarness


class CompressionTests(unittest.TestCase):
    def test_stream_encodes_all_values_packet_boundaries_and_random_input(self):
        randomizer = random.Random(715)
        cases = [b"", bytes(range(256)), bytes([255]) * 129, bytes(1024)]
        cases += [bytes(randomizer.randrange(256) for _ in range(length))
                  for length in (1, 2, 3, 126, 127, 128, 255, 1024)]
        for data in cases:
            with self.subTest(length=len(data), prefix=data[:4]):
                stream = iter(pack_runs(data))
                decoded = bytearray()
                for control in stream:
                    if control == 0:
                        self.assertEqual(list(stream), [])
                        break
                    if control & 128:
                        decoded.extend([next(stream)] * ((control & 127) + 1))
                    else:
                        decoded.extend(next(stream) for _ in range(control))
                self.assertEqual(bytes(decoded), data)

    def test_high_entropy_data_keeps_raw_storage(self):
        data = bytes(range(256)) * 4
        self.assertEqual(nametable_storage(data), (data, False))
        self.assertLess(len(nametable_storage(bytes(1024))[0]), 100)

    def test_collision_bitmap_order_and_last_bit(self):
        source = bytearray(960)
        for index in (0, 7, 8, 31, 959):
            source[index] = 1
        packed = pack_collision(source)
        self.assertEqual(len(packed), 120)
        self.assertEqual((packed[0], packed[1], packed[3], packed[-1]), (0x81, 0x80, 1, 1))
        with self.assertRaisesRegex(ValueError, "960"):
            pack_collision(bytes(959))


@unittest.skipUnless(HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME)
class CompressionRuntimeTests(unittest.TestCase):
    def test_mixed_raw_and_compressed_rooms_preserve_every_background_byte(self):
        game = Game()
        compressed, raw = game.room("compressed"), game.room("raw")
        compressed.text("RUN LENGTH LITERAL PACKETS", column=2, row=2)
        compressed.map([[3] * 32] * 4, row=20, palette=2)
        randomizer = random.Random(36)
        raw.map([[randomizer.randrange(64) for _ in range(32)] for _ in range(30)])
        compressed.bind_pressed(Button.A, ChangeRoom(raw))
        raw.bind_pressed(Button.B, ChangeRoom(compressed))
        with RuntimeHarness(game) as run:
            self.assertEqual([room.nametable_encoding for room in run.result.report.rooms], ["rle", "raw"])
            for room, button in ((compressed, None), (raw, Button.A), (compressed, Button.B)):
                if button is not None:
                    run.frame(button)
                actual = bytes(run.bus.ppu_read(0x2000 + index) for index in range(1024))
                self.assertEqual(actual, room.nametable())

    def test_long_compressed_stream_crosses_source_pages_and_keeps_control_flags(self):
        game = Game()
        room = game.room("mixed")
        randomizer = random.Random(725)
        rows = [[randomizer.randrange(64) for _ in range(32)] for _ in range(20)]
        rows += [[0] * 32 for _ in range(10)]
        room.map(rows)
        encoded, compressed = nametable_storage(room.nametable())
        self.assertTrue(compressed)
        self.assertGreater(len(encoded), 512)
        with RuntimeHarness(game) as run:
            actual = bytes(run.bus.ppu_read(0x2000 + index) for index in range(1024))
            self.assertEqual(actual, room.nametable())

    def test_collision_queries_cover_every_bit_and_rectangles_crossing_packed_bytes(self):
        for named in (False, True):
            with self.subTest(named=named):
                game = Game()
                room = game.room("bitmap") if named else game
                mask = [[((row * 37 + column * 17) % 11) < 3 for column in range(32)] for row in range(30)]
                room.map([[1] * 32] * 30, solid=mask)
                room.actor(tile=1)
                self.assertEqual(len(room.collision_data()), 960, "the public grid stays unpacked")
                with RuntimeHarness(game) as run:
                    def query(x, y, width=8, height=8):
                        for name, value in (("x", x), ("y", y), ("w", width), ("h", height),
                                            ("offx", 0), ("offy", 0), ("solid", 1)):
                            run.bus[run.labels["phys_" + name]] = value
                        return_pc = run.cpu.pc
                        run.cpu.stPushWord((return_pc - 1) & 65535)
                        run.cpu.pc = run.labels["physics_collision_test"]
                        run.run_until(lambda: run.cpu.pc == return_pc)
                        return run.cpu.a
                    for row in range(30):
                        for column in range(32):
                            self.assertEqual(query(column * 8, row * 8), int(mask[row][column]), (row, column))
                    for row in (0, 7, 28):
                        for column in (6, 7, 14, 15, 23, 29):
                            expected = any(mask[r][c] for r in range(row, row + 2) for c in range(column, column + 3))
                            self.assertEqual(query(column * 8, row * 8, 24, 16), int(expected))

    def test_trimmed_oam_preserves_sparse_and_full_static_sprite_layouts(self):
        game = Game()
        sparse, full = game.room("sparse"), game.room("full")
        sparse.actor(tile=game.metasprite([[1, 2], [3, 4]]), x=48, y=48)
        sprite = sparse.sprite(tile=5, x=120, y=120, flip_horizontal=True)
        for index in range(64):
            full.sprite(tile=index, x=index * 4, y=80)
        sparse.bind_pressed(Button.A, ChangeRoom(full))
        full.bind_pressed(Button.B, ChangeRoom(sparse))
        with RuntimeHarness(game) as run:
            self.assertEqual(run.sprite_data(sprite.index), (120, 5, 64, 120))
            self.assertEqual(bytes(run.bus.ram[0x200 + 20:0x300]), bytes([255] * 236))
            run.frame(Button.A)
            self.assertEqual(run.sprite_data(63), (80, 63, 0, 252))
            run.frame(Button.B)
            self.assertEqual(run.sprite_data(sprite.index), (120, 5, 64, 120))
            self.assertEqual(bytes(run.bus.ram[0x200 + 20:0x300]), bytes([255] * 236))


if __name__ == "__main__":
    unittest.main()
