"""Build Python description scripts with a module-level ``game`` object."""

import argparse
from pathlib import Path
import runpy
import sys

from .build import BuildError
from .game import Game


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile a Python Game description into an NES ROM")
    parser.add_argument("--version", action="version", version="py3nes 0.1.0")
    parser.add_argument("script", type=Path, help="Python file exporting a variable named game")
    parser.add_argument("-o", "--output", type=Path, help="output .nes (or .s with --assembly-only)")
    parser.add_argument("--assembly-only", action="store_true", help="write assembly and linker config without running cc65")
    args = parser.parse_args(argv)
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
            print(game.build(output).rom_path)
    except (BuildError, OSError, ValueError, TypeError) as error:
        print(f"py3nes: {error}", file=sys.stderr)
        return 1
    finally:
        sys.path[:] = original_path
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
