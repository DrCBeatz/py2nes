"""FamiStudio music assets and commands; all importing happens at build time.

The bundled 4.5.1 engine targets the four standard NTSC channels. DPCM,
expansion audio, custom tuning and PAL projects are deliberately rejected.
Portable ``.music.json`` files embed a CA65 export and need no editor at build.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .ir import ActionSpec
from .model import integer


ENGINE_VERSION = "4.5.1"
_FEATURES = frozenset("FAMITRACKER_TEMPO FAMITRACKER_DELAYED_NOTES_OR_CUTS RELEASE_NOTES VOLUME_TRACK VOLUME_SLIDES PITCH_TRACK SLIDE_NOTES NOISE_SLIDE_NOTES VIBRATO ARPEGGIO DUTYCYCLE_EFFECT PHASE_RESET INSTRUMENT_EXTENDED_RANGE".split())


class MusicExportError(RuntimeError):
    """An editor export failed or requires an unsupported sound-engine feature."""


def _assembly_info(assembly: str):
    if not isinstance(assembly, str):
        raise TypeError("music assembly must be text")
    if len(assembly) > 1_000_000:
        raise ValueError("music assembly exceeds 1 MB")
    if "This file is for the FamiStudio Sound Engine" not in assembly:
        raise ValueError("expected a FamiStudio sound engine CA65 music export")
    flags = frozenset(re.findall(r"FAMISTUDIO_USE_(\w+)\s*=\s*1", assembly))
    unsupported = flags - _FEATURES
    if unsupported:
        raise ValueError("unsupported FamiStudio features: " + ", ".join(sorted(unsupported)))
    if re.search(r"FAMISTUDIO_(?:EXP_\w+|CFG_DPCM_SUPPORT)\s*=\s*1", assembly):
        raise ValueError("only standard NES music without DPCM or expansion audio is supported")
    root = re.search(r"^(music_data_\w+):\s*\n\s*\.byte\s+(\d+)\s*$", assembly, re.M)
    if not root:
        raise ValueError("FamiStudio export is missing a music header or song count")
    songs = tuple(re.findall(r"^; \d{2} : (.+)$", assembly, re.M))
    if not 1 <= int(root[2]) <= 17 or len(songs) != int(root[2]):
        raise ValueError("FamiStudio music must contain 1..17 named songs")
    # The editor always emits a sample label, including when it is empty.
    samples = re.search(r"^@samples:\s*\n(.*?)(?=^\w|^@|\Z)", assembly, re.M | re.S)
    if samples and re.search(r"\.(?:byte|word)", samples[1]):
        raise ValueError("DPCM sample mappings are not supported")
    for line in assembly.splitlines():
        code = line.split(";", 1)[0].strip()
        if not code or re.fullmatch(r"(?:music_data_\w+|@\w+):", code):
            continue
        if code.startswith((".byte ", ".word ", ".export ", ".global FAMISTUDIO_DPCM_PTR")):
            continue
        raise ValueError("unsupported directive in FamiStudio CA65 export: " + code)
    return root[1], songs, flags


@dataclass(frozen=True)
class Music:
    """Immutable, self-contained FamiStudio CA65 export, including named songs."""
    assembly: str

    def __post_init__(self):
        _assembly_info(self.assembly)

    @property
    def songs(self) -> tuple[str, ...]:
        return _assembly_info(self.assembly)[1]

    @property
    def features(self) -> frozenset[str]:
        return _assembly_info(self.assembly)[2]

    def song_index(self, song: str | int) -> int:
        if isinstance(song, str):
            try:
                return self.songs.index(song)
            except ValueError:
                raise ValueError(f"unknown music song {song!r}; available: {', '.join(self.songs)}") from None
        return integer(song, "song", 0, len(self.songs) - 1)

    def save(self, path: str | Path) -> Path:
        """Write a portable asset for builds that do not have FamiStudio installed."""
        target = Path(path)
        target.write_text(json.dumps({"format": "py3nes-famistudio", "version": 1,
                                     "engine": ENGINE_VERSION, "assembly": self.assembly},
                                    indent=2) + "\n", encoding="utf-8")
        return target


@dataclass(frozen=True)
class PlayMusic(ActionSpec):
    """Play a song; the same active song continues unless ``restart=True``.

    Song loops and endings come from the FamiStudio project. Music persists
    between rooms until another music command changes it.
    """
    music: Music
    song: str | int = 0
    restart: bool = False

    def __post_init__(self):
        if not isinstance(self.music, Music):
            raise TypeError("PlayMusic requires a Music asset from load_famistudio")
        object.__setattr__(self, "song", self.music.song_index(self.song))
        if not isinstance(self.restart, bool):
            raise TypeError("restart must be a bool")


@dataclass(frozen=True)
class StopMusic(ActionSpec):
    """Stop music while allowing sound effects to finish."""


@dataclass(frozen=True)
class PauseMusic(ActionSpec):
    """Mute and freeze music, or resume it; sound effects continue."""
    paused: bool = True

    def __post_init__(self):
        if not isinstance(self.paused, bool):
            raise TypeError("paused must be a bool")


def _dotnet() -> str:
    command = shutil.which("dotnet")
    if command:
        return command
    for path in ("/usr/local/share/dotnet/dotnet", "/opt/homebrew/bin/dotnet"):
        if Path(path).is_file():
            return path
    raise MusicExportError("FamiStudio's .NET runtime was not found; install .NET 8 or use a portable .music.json export")


def famistudio_command(executable=None) -> tuple[str, ...]:
    """Find an editor CLI, or accept an executable/app/DLL path or argv sequence.

    ``FAMISTUDIO`` overrides auto-detection. No shell is used; paths with spaces
    are passed as a single argument. On macOS the app DLL is run using dotnet.
    """
    if executable is None:
        executable = os.environ.get("FAMISTUDIO")
    if executable is None:
        executable = shutil.which("FamiStudio") or shutil.which("famistudio")
    if executable is None:
        for candidate in (Path("/Applications/FamiStudio.app"), Path.home() / "Applications/FamiStudio.app"):
            if candidate.exists():
                executable = candidate
                break
    if executable is None:
        raise MusicExportError("FamiStudio was not found; set FAMISTUDIO to its executable, app or DLL, pass executable=, or load a portable .music.json export")
    if isinstance(executable, (tuple, list)):
        if not executable or not all(isinstance(arg, (str, os.PathLike)) and str(arg) for arg in executable):
            raise TypeError("executable argv must be a non-empty sequence of paths/strings")
        return tuple(map(str, executable))
    path = Path(executable)
    if path.suffix.lower() == ".app":
        path = path / "Contents/MacOS/FamiStudio.dll"
    if path.suffix.lower() == ".dll":
        return (_dotnet(), str(path))
    return (str(path),)


def _run_export(command, source, operation, target, *options):
    try:
        result = subprocess.run([*command, str(source), operation, str(target), *options],
                                capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MusicExportError(f"could not run FamiStudio: {exc}") from exc
    log = result.stdout + result.stderr
    if result.returncode or not target.is_file() or re.search(r"(?:^|\n)\s*Error:", log):
        raise MusicExportError(f"FamiStudio {operation} failed for {source.name}:\n{log.strip()}")
    return log


def _validate_project(text):
    project = next((line for line in text.splitlines() if line.startswith("Project ")), "")
    if not project:
        raise ValueError("expected a FamiStudio project or text project")
    if 'PAL="True"' in project or 'Expansions="' in project:
        raise ValueError("music must use NTSC and standard NES channels without expansions")
    tuning = re.search(r'Tuning="([^"]+)"', project)
    if tuning and tuning[1] != "440":
        raise ValueError("custom tuning is not supported; use 440 Hz tuning")
    if re.search(r"^\s*(?:DPCMSample|DPCMMapping)\b", text, re.M):
        raise ValueError("DPCM samples are not supported; use pulse, triangle and noise instruments")


def load_famistudio(path: str | Path, *, executable=None) -> Music:
    """Load a portable .music.json / CA65 .s export, or export a .fms/.txt project.

    Project imports invoke installed FamiStudio immediately, never at runtime.
    Exported files are temporary; the user's source project is never changed.
    The bundled engine matches FamiStudio 4.5.x. Use FamiStudio tempo consistently
    across a game's assets, or FamiTracker tempo consistently; do not mix them.
    """
    source = Path(path).expanduser().resolve()
    suffix = source.suffix.lower()
    if suffix == ".json":
        document = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("format") != "py3nes-famistudio" or document.get("version") != 1 or document.get("engine") != ENGINE_VERSION:
            raise ValueError("unsupported portable music format or engine version")
        return Music(document.get("assembly"))
    if suffix in (".s", ".asm"):
        return Music(source.read_text(encoding="utf-8-sig"))
    if suffix not in (".fms", ".txt"):
        raise ValueError("music input must be a .fms/.txt project, CA65 .s/.asm export, or .music.json asset")
    if not source.is_file():
        raise FileNotFoundError(source)
    command = famistudio_command(executable)
    with tempfile.TemporaryDirectory(prefix="py3nes-music-") as directory:
        root = Path(directory)
        text = root / "project.txt"
        _run_export(command, source, "famistudio-txt-export", text)
        _validate_project(text.read_text(encoding="utf-8-sig"))
        assembly = root / "music.s"
        _run_export(command, source, "famistudio-asm-export", assembly, "-famistudio-asm-format:ca65")
        return Music(assembly.read_text(encoding="utf-8-sig"))


def export_famistudio(source: str | Path, output: str | Path, *, executable=None) -> Music:
    """Export a project to a portable asset and return its immutable description."""
    music = load_famistudio(source, executable=executable)
    music.save(output)
    return music
