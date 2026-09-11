from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from py3nes import Game
from py3nes.__main__ import main
from py3nes.build import BuildResult
from py3nes.resources import ResourceUsage


class ResourceAPITests(unittest.TestCase):
    def test_existing_build_result_constructor_remains_valid(self):
        result = BuildResult(*(Path(name) for name in ("game.nes", "game.s", "game.cfg", "game.map", "game.lbl")))
        self.assertIsNone(result.report)
        self.assertIsNone(result.report_path)
        usage = ResourceUsage(3000, 4000)
        self.assertEqual((usage.free, usage.percent), (1000, 75.0))

    def test_assembly_only_report_explains_link_requirement(self):
        errors = io.StringIO()
        with redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
            main(["does-not-exist.py", "--assembly-only", "--report"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("reports require linking", errors.getvalue())


@unittest.skipUnless(shutil.which("ca65") and shutil.which("ld65"), "requires cc65")
class ResourceBuildTests(unittest.TestCase):
    def test_report_counts_linked_segments_without_ff_padding(self):
        game = Game()
        game.byte("counter")
        game.actor(tile=1)
        with tempfile.TemporaryDirectory() as directory:
            result = game.build(Path(directory) / "game.nes")
            report = result.report
            self.assertIsNotNone(report)
            segment_text = result.map_path.read_text().split("Segment list:")[1]
            sizes = {}
            for name in ("CODE", "RODATA", "VECTORS", "BSS", "ZEROPAGE"):
                match = re.search(rf"^{name}\s+\w+\s+\w+\s+(\w+)", segment_text, re.M)
                sizes[name] = int(match[1], 16)
            self.assertEqual(report.prg.used, sizes["CODE"] + sizes["RODATA"] + sizes["VECTORS"])
            self.assertEqual(report.prg.capacity, 16384)
            self.assertGreater(report.prg.free, 8000)
            self.assertEqual(report.work_ram.used, sizes["BSS"])
            self.assertEqual(report.zero_page.used, sizes["ZEROPAGE"])
            self.assertEqual((report.work_ram.capacity, report.zero_page.capacity), (1280, 256))
            self.assertEqual((report.stack_reserved_bytes, report.oam_reserved_bytes), (256, 256))
            self.assertEqual((report.tiles.used, report.tiles.capacity, report.chr_rom_bytes), (64, 256, 8192))
            self.assertEqual(json.loads(result.report_path.read_text()), report.to_dict())

    def test_room_report_describes_stored_data_and_allocated_sprite_slots(self):
        game = Game()
        first, second = game.room("first"), game.room("second")
        first.actor(tile=game.metasprite([[1, 2], [3, 4]]))
        first.sprite(tile=1)
        second.sprite(tile=2)
        with tempfile.TemporaryDirectory() as directory:
            report = game.build(Path(directory) / "rooms.nes").report
            self.assertEqual(report.prg.capacity, 32768)
            self.assertEqual([room.oam_slots for room in report.rooms], [5, 1])
            self.assertEqual([room.actors for room in report.rooms], [1, 0])
            self.assertEqual([room.initial_oam_bytes for room in report.rooms], [20, 4])
            self.assertEqual([room.collision_bytes for room in report.rooms], [120, 120])
            self.assertTrue(all(room.nametable_encoding == "rle" for room in report.rooms))
            self.assertTrue(all(room.nametable_bytes < 100 for room in report.rooms))
            self.assertIn("Room first", report.format())

    def test_cli_reports_usage_and_writes_json_without_changing_default_output(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            script = folder / "scene.py"
            script.write_text("from py3nes import Game\ngame = Game()\n")
            report_json = folder / "budgets" / "report.json"
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main([str(script), "--report", "--report-json", str(report_json)]), 0)
            self.assertIn("PRG ROM:", output.getvalue())
            self.assertEqual(json.loads(report_json.read_text())["prg"]["capacity"], 16384)
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main([str(script)]), 0)
            self.assertEqual(output.getvalue().strip(), str(script.with_suffix(".nes").resolve()))

    def test_cli_report_cannot_overwrite_source_or_rom(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "scene.py"
            source = "from py3nes import Game\ngame = Game()\n"
            script.write_text(source)
            for destination in (script, script.with_suffix(".nes")):
                with self.subTest(destination=destination), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(main([str(script), "--report-json", str(destination)]), 1)
                self.assertEqual(script.read_text(), source)
                self.assertEqual(script.with_suffix(".nes").read_bytes()[:4], b"NES\x1a")


if __name__ == "__main__":
    unittest.main()
