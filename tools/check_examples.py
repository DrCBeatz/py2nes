"""Build every example, or run the existing JSNES playthrough checks.

Run with the Python environment containing py3nes[test] and cc65 on PATH.
The emulator checks additionally need:
    npm install --prefix build/emulator jsnes@2.1.0 pngjs@7.0.0
"""

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SMOKE_EXAMPLES = {
    "emulator_smoke.mjs": "hello_nes",
    "platformer_smoke.mjs": "keys_and_platforms",
    "rooms_smoke.mjs": "three_rooms",
    "visual_adventure_smoke.mjs": "visual_adventure",
    "living_adventure_smoke.mjs": "living_adventure",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke-only", action="store_true",
        help="run JSNES checks against ROMs already built in build/",
    )
    args = parser.parse_args()
    if args.smoke_only:
        for script, example in SMOKE_EXAMPLES.items():
            print(f"Checking {example} in JSNES", flush=True)
            subprocess.run(
                ["node", str(ROOT / "tools" / script),
                 str(ROOT / "build" / f"{example}.nes")],
                cwd=ROOT, check=True,
            )
        return

    examples = sorted((ROOT / "examples").glob("*.py"))
    if not examples:
        raise SystemExit("No Python examples found")
    for example in examples:
        print(f"Building {example.name}", flush=True)
        subprocess.run(
            [sys.executable, "-m", "py3nes", str(example), "-o",
             str(ROOT / "build" / f"{example.stem}.nes")],
            cwd=ROOT, check=True,
        )
    print(f"Built {len(examples)} example ROMs.", flush=True)


if __name__ == "__main__":
    main()
