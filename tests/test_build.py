from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from py3nes import BuildError, Button, Game, Move
from py3nes.__main__ import main


class AssemblyTests(unittest.TestCase):
    def test_source_is_deterministic_and_needs_no_build_tools(self):
        game = Game()
        game.text("HELLO NES", column=2, row=2)
        with patch("py3nes.build.shutil.which", return_value=None):
            self.assertEqual(game.to_assembly(), game.to_assembly())
            with tempfile.TemporaryDirectory() as directory:
                source = game.emit_assembly(Path(directory) / "nested" / "demo.s")
                self.assertTrue(source.is_file())
                self.assertTrue(source.with_suffix(".cfg").is_file())

    def test_missing_tool_has_actionable_error(self):
        with patch("py3nes.build.shutil.which", return_value=None):
            with self.assertRaisesRegex(BuildError, "Install cc65"):
                Game().build("unused.nes")

    def test_output_suffix_is_validated(self):
        with self.assertRaisesRegex(ValueError, "suffix"):
            Game().build("wrong.bin")
        with self.assertRaisesRegex(ValueError, "suffix"):
            Game().emit_assembly("wrong.bin")

    def test_cli_loads_scene_and_sibling_import_without_running_main_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "scene_helper.py").write_text("TITLE = 'HELLO NES'\n")
            script = folder / "scene.py"
            script.write_text(
                "from py3nes import Game\nfrom scene_helper import TITLE\n"
                "game = Game()\ngame.text(TITLE)\n"
                "if __name__ == '__main__':\n    raise RuntimeError('built twice')\n"
            )
            output = folder / "scene.s"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(script), "--assembly-only", "-o", str(output)]), 0)
            self.assertTrue(output.exists())
            self.assertTrue(output.with_suffix(".cfg").exists())

    def test_cli_reports_missing_game(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "scene.py"
            script.write_text("name = 'no game'\n")
            errors = io.StringIO()
            with redirect_stderr(errors):
                self.assertEqual(main([str(script), "--assembly-only"]), 1)
            self.assertIn("module-level", errors.getvalue())


@unittest.skipUnless(shutil.which("ca65") and shutil.which("ld65"), "requires cc65")
class CompilerTests(unittest.TestCase):
    def test_reproducible_rom_and_paths_with_shell_metacharacters(self):
        game = Game()
        game.text("COMPILER TEST")
        with tempfile.TemporaryDirectory() as directory:
            first = game.build(Path(directory) / "space `name` $(literal)" / "demo.nes")
            second = game.build(Path(directory) / "other.nes")
            self.assertEqual(first.rom_path.read_bytes(), second.rom_path.read_bytes())
            self.assertEqual(len(first.rom_path.read_bytes()), 24592)

    def test_long_event_uses_safe_branches(self):
        game = Game()
        sprite = game.sprite(tile=1)
        game.bind_held(Button.RIGHT, *(Move(sprite, dx=1) for _ in range(100)))
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(game.build(Path(directory) / "long.nes").rom_path.exists())

    def test_linker_overflow_preserves_last_good_rom(self):
        game = Game()
        sprite = game.sprite(tile=1)
        with tempfile.TemporaryDirectory() as directory:
            rom = Path(directory) / "demo.nes"
            game.build(rom)
            original = rom.read_bytes()
            game.every_frame(*(Move(sprite, dx=1) for _ in range(2500)))
            with self.assertRaisesRegex(BuildError, "failed"):
                game.build(rom)
            self.assertEqual(rom.read_bytes(), original)
            self.assertTrue(rom.with_suffix(".s").exists())
            self.assertFalse(list(rom.parent.glob(".py3nes-*")))


if __name__ == "__main__":
    unittest.main()
