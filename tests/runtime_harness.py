"""Execute a generated ROM on py65's CPU with modeled NES register effects.

This is a CPU integration harness, not a cycle-accurate NES emulator. Callers
provide NMIs explicitly and can inspect RAM, PPU writes, and OAM transfers.
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

from tests.nes_bus import NESBus


HAS_RUNTIME_TOOLS = MPU is not None and bool(shutil.which("ca65") and shutil.which("ld65"))
REQUIRES_RUNTIME = "requires py65 and cc65 (ca65/ld65)"


class RuntimeHarness:
    """Build one Game, boot its ROM, and advance explicit gameplay frames."""

    def __init__(self, game):
        if not HAS_RUNTIME_TOOLS:
            raise unittest.SkipTest(REQUIRES_RUNTIME)
        self._directory = tempfile.TemporaryDirectory(prefix="py3nes-state-")
        try:
            self.result = game.build(Path(self._directory.name) / "game.nes")
            self.rom = self.result.rom_path.read_bytes()
            self.labels = {}
            for line in self.result.labels_path.read_text().splitlines():
                match = re.match(r"\s*al\s+([0-9a-fA-F]+)\s+\.?([^\s]+)", line)
                if match:
                    self.labels[match[2]] = int(match[1], 16)
            self.bus = NESBus(self.rom)
            self.cpu = MPU(memory=self.bus, pc=None)
            self.run_until(lambda: self.cpu.pc == self.labels["main_loop"])
        except BaseException:
            self.close()
            raise

    def close(self):
        self._directory.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def run_until(self, condition, maximum=200000):
        for _ in range(maximum):
            if condition():
                return
            self.cpu.step()
        raise AssertionError(f"6502 did not reach expected state; PC=${self.cpu.pc:04X}")

    def read(self, name):
        """Read an assembly symbol's byte; user variables are named v_<name>."""
        return self.bus[self.labels[name]]

    def variable(self, name, *, signed=False):
        value = self.read("v_" + name)
        return value - 256 if signed and value >= 128 else value

    def sprite_data(self, index=0):
        start = 0x200 + index * 4
        return tuple(self.bus[start:start + 4])

    def frame(self, buttons=0):
        """Finish pending uploads, then execute one fresh gameplay tick.

        A large display queue may need several video frames before the runtime
        permits another tick. Use interrupt() to inspect each individual NMI.
        """
        self.bus.buttons = int(buttons)
        for _ in range(64):
            self.interrupt()
            if self.read("frame_ready") == 0:
                break
        else:
            raise AssertionError("NMI did not finish the pending display queue")
        self.run_until(lambda: self.cpu.pc == self.labels["main_loop"] and self.read("frame_ready") == 1)

    def interrupt(self):
        """Deliver one NMI and stop on return, before the interrupted instruction."""
        return_pc, return_sp = self.cpu.pc, self.cpu.sp
        self.cpu.nmi()
        self.run_until(lambda: self.cpu.pc == return_pc and self.cpu.sp == return_sp, maximum=10000)
