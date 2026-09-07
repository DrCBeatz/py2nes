"""Invoke the cc65 assembler and linker without a shell."""

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile


class BuildError(RuntimeError):
    """The assembler/linker is missing, failed, or produced an invalid image."""


@dataclass(frozen=True)
class BuildResult:
    rom_path: Path
    assembly_path: Path
    config_path: Path
    map_path: Path
    labels_path: Path


def emit_assembly(source: str, config: str, path: str | Path) -> Path:
    assembly = Path(path).expanduser().resolve()
    if assembly.suffix.lower() not in (".s", ".asm"):
        raise ValueError("assembly output must use a .s or .asm suffix")
    assembly.parent.mkdir(parents=True, exist_ok=True)
    assembly.write_text(source, encoding="utf-8")
    assembly.with_suffix(".cfg").write_text(config, encoding="utf-8")
    return assembly


def compile_rom(source: str, config: str, output: str | Path, *,
                ca65: str = "ca65", ld65: str = "ld65") -> BuildResult:
    rom = Path(output).expanduser().resolve()
    if rom.suffix.lower() != ".nes":
        raise ValueError("ROM output must use a .nes suffix")
    for tool in (ca65, ld65):
        if shutil.which(tool) is None:
            raise BuildError(f"{tool!r} was not found. Install cc65 (macOS: brew install cc65; Debian/Ubuntu: apt install cc65), or pass ca65/ld65 executable paths to build().")
    assembly = emit_assembly(source, config, rom.with_suffix(".s"))
    result = BuildResult(rom, assembly, rom.with_suffix(".cfg"),
                         rom.with_suffix(".map"), rom.with_suffix(".lbl"))
    # Link to a temporary file; a failed build must not truncate an existing ROM.
    with tempfile.TemporaryDirectory(prefix=".py3nes-", dir=rom.parent) as directory:
        temp = Path(directory)
        obj, binary = temp / "game.o", temp / "game.nes"
        map_file, labels = temp / "game.map", temp / "game.lbl"
        commands = [
            [str(ca65), "-g", "-o", str(obj), str(assembly)],
            [str(ld65), "-C", str(result.config_path), "-m", str(map_file),
             "-Ln", str(labels), "-o", str(binary), str(obj)],
        ]
        for command in commands:
            try:
                process = subprocess.run(command, capture_output=True, text=True, timeout=60)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise BuildError(f"Could not run {command[0]}: {error}") from error
            if process.returncode:
                diagnostic = (process.stderr + process.stdout).strip()
                raise BuildError(f"{command[0]} failed (exit {process.returncode}):\n{diagnostic}\nGenerated assembly: {assembly}")
        data = binary.read_bytes()
        if len(data) != 16 + 16384 + 8192 or data[:6] != b"NES\x1a\x01\x01":
            raise BuildError("Linker produced an invalid NROM-128 image")
        map_file.replace(result.map_path)
        labels.replace(result.labels_path)
        binary.replace(rom)
    return result
