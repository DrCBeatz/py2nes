"""A small NES bus for running generated 6502 code in py65.

This models memory-mapped register effects, not PPU rendering or cycle timing.
PPUSTATUS always reports vblank so reset's synchronization waits can finish.
Tests explicitly deliver NMIs and inspect the resulting CPU, PPU, and OAM data.
"""


class NESBus:
    def __init__(self, rom: bytes):
        if len(rom) < 16 or rom[:4] != b"NES\x1a" or rom[4] not in (1, 2) or rom[5] != 1:
            raise ValueError("Tests require an iNES NROM ROM with CHR ROM")
        if rom[6] & 0xF4 or rom[7] & 0xF0:
            raise ValueError("Tests require mapper 0 without a trainer")
        prg_size = rom[4] * 16384
        self.prg = rom[16 : 16 + prg_size]
        self.chr = rom[16 + prg_size : 16 + prg_size + 8192]
        self.vertical_mirroring = bool(rom[6] & 1)
        self.ram = bytearray(2048)
        self.ppu_memory = bytearray(16384)
        self.ppu_memory[:8192] = self.chr
        self.oam = bytearray(256)
        self.ppuctrl = 0
        self.ppumask = 0
        self.ppuaddr = 0
        self.oamaddr = 0
        self.address_latch = False
        self.scroll = [0, 0]
        self.status_reads = 0
        self.dma_transfers = []
        self.buttons = 0
        self.controller_strobe = False
        self.controller_latch = 0
        self.controller_index = 0

    def _ppu_address(self, address):
        address &= 0x3FFF
        if 0x2000 <= address < 0x3F00:
            offset = (address - 0x2000) % 0x1000
            table, tile = divmod(offset, 0x400)
            physical = table % 2 if self.vertical_mirroring else table // 2
            return 0x2000 + physical * 0x400 + tile
        if address >= 0x3F00:
            palette = (address - 0x3F00) % 32
            if palette in (0x10, 0x14, 0x18, 0x1C):
                palette -= 0x10
            return 0x3F00 + palette
        return address

    def ppu_read(self, address):
        return self.ppu_memory[self._ppu_address(address)]

    def __getitem__(self, address):
        if isinstance(address, slice):
            return [self[index] for index in range(*address.indices(65536))]
        address &= 0xFFFF
        if address < 0x2000:
            return self.ram[address % 2048]
        if address < 0x4000:
            register = address & 7
            if register == 2:
                self.status_reads += 1
                self.address_latch = False
                return 0x80
            if register == 4:
                return self.oam[self.oamaddr]
            if register == 7:
                value = self.ppu_read(self.ppuaddr)
                self.ppuaddr = (self.ppuaddr + (32 if self.ppuctrl & 4 else 1)) & 0x3FFF
                return value
            return 0
        if address == 0x4016:
            if self.controller_strobe:
                return (self.buttons >> 7) & 1
            if self.controller_index >= 8:
                return 1
            value = (self.controller_latch >> (7 - self.controller_index)) & 1
            self.controller_index += 1
            return value
        if address >= 0x8000:
            return self.prg[(address - 0x8000) % len(self.prg)]
        return 0

    def __setitem__(self, address, value):
        address &= 0xFFFF
        value &= 0xFF
        if address < 0x2000:
            self.ram[address % 2048] = value
        elif address < 0x4000:
            register = address & 7
            if register == 0:
                self.ppuctrl = value
            elif register == 1:
                self.ppumask = value
            elif register == 3:
                self.oamaddr = value
            elif register == 4:
                self.oam[self.oamaddr] = value
                self.oamaddr = (self.oamaddr + 1) & 0xFF
            elif register == 5:
                self.scroll[int(self.address_latch)] = value
                self.address_latch = not self.address_latch
            elif register == 6:
                if not self.address_latch:
                    self.ppuaddr = (value & 0x3F) << 8
                else:
                    self.ppuaddr = (self.ppuaddr & 0x3F00) | value
                self.address_latch = not self.address_latch
            elif register == 7:
                target = self._ppu_address(self.ppuaddr)
                if target >= 0x2000:  # Pattern tables are CHR ROM.
                    self.ppu_memory[target] = value
                self.ppuaddr = (self.ppuaddr + (32 if self.ppuctrl & 4 else 1)) & 0x3FFF
        elif address == 0x4014:
            transferred = bytes(self[(value << 8) + index] for index in range(256))
            for index, byte in enumerate(transferred):
                self.oam[(self.oamaddr + index) & 0xFF] = byte
            self.dma_transfers.append(transferred)
        elif address == 0x4016:
            strobe = bool(value & 1)
            if strobe or self.controller_strobe:
                self.controller_latch = self.buttons
                self.controller_index = 0
            self.controller_strobe = strobe
