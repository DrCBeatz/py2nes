"""Build Python description scripts with a module-level ``game`` object."""

import argparse
from pathlib import Path
import runpy
import sys

from .build import BuildError
from .game import Game
from .music import MusicExportError
from . import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile a Python Game description into an NES ROM")
    parser.add_argument("--version", action="version", version=f"py3nes {__version__}")
    parser.add_argument("script", type=Path, help="Python file exporting a variable named game")
    parser.add_argument("-o", "--output", type=Path, help="output .nes (or .s with --assembly-only)")
    parser.add_argument("--assembly-only", action="store_true", help="write assembly and linker config without running cc65")
    parser.add_argument("--report", action="store_true", help="print linked ROM, RAM, graphics, and room resource budgets")
    parser.add_argument("--report-json", type=Path, metavar="PATH", help="also write the resource report to PATH")
    args = parser.parse_args(argv)
    if args.assembly_only and (args.report or args.report_json):
        parser.error("resource reports require linking; omit --assembly-only")
    suffix = ".s" if args.assembly_only else ".nes"
    output = args.output or args.script.with_suffix(suffix)
    original_path = sys.path[:]
    try:
        # Support sibling imports as if the description were invoked with python.
        sys.path.insert(0, str(args.script.resolve().parent))
        namespace = runpy.run_path(str(args.script), run_name="__py3nes_build__")
        game = namespace.get("game")
        if not isinstance(game, Game):
            raise ValueError("script must define a module-level 'game = Game(...)'")
        if args.assembly_only:
            print(game.emit_assembly(output))
        else:
            result = game.build(output)
            print(result.rom_path)
            if args.report:
                print(result.report.format())
            if args.report_json:
                report_path = args.report_json.expanduser().resolve()
                protected = (result.rom_path, result.assembly_path, result.config_path,
                             result.map_path, result.labels_path, args.script.resolve())
                if report_path in protected:
                    raise ValueError("--report-json must not overwrite the script or a build artifact")
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(result.report.to_json(), encoding="utf-8")
    except (BuildError, MusicExportError, OSError, ValueError, TypeError) as error:
        print(f"py3nes: {error}", file=sys.stderr)
        return 1
    finally:
        sys.path[:] = original_path
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
