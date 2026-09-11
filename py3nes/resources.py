"""Linked cartridge budgets and the authoring resources behind them."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re

from .compression import initial_oam, nametable_storage


@dataclass(frozen=True)
class ResourceUsage:
    used: int
    capacity: int

    @property
    def free(self) -> int:
        return self.capacity - self.used

    @property
    def percent(self) -> float:
        return self.used * 100 / self.capacity

    def to_dict(self) -> dict:
        return {"used": self.used, "capacity": self.capacity, "free": self.free}


@dataclass(frozen=True)
class RoomUsage:
    name: str
    actors: int
    oam_slots: int
    nametable_bytes: int
    nametable_encoding: str
    collision_bytes: int
    initial_oam_bytes: int

    def to_dict(self) -> dict:
        return dict(vars(self))


@dataclass(frozen=True)
class ResourceReport:
    """Actual linker sizes, plus optional metadata from the Game description.

    ``prg`` includes code, data and six interrupt-vector bytes. The stack and
    OAM occupy separate reserved pages, not the work-RAM or zero-page budgets.
    Tile slots refer to the shared 4 KiB pattern table, duplicated in CHR ROM.
    """

    prg: ResourceUsage
    work_ram: ResourceUsage
    zero_page: ResourceUsage
    chr_rom_bytes: int
    code_bytes: int
    rodata_bytes: int
    vector_bytes: int
    tiles: ResourceUsage | None = None
    rooms: tuple[RoomUsage, ...] = ()
    stack_reserved_bytes: int = 256
    oam_reserved_bytes: int = 256

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "prg": {**self.prg.to_dict(), "code_bytes": self.code_bytes,
                    "rodata_bytes": self.rodata_bytes, "vector_bytes": self.vector_bytes},
            "work_ram": self.work_ram.to_dict(), "zero_page": self.zero_page.to_dict(),
            "chr_rom_bytes": self.chr_rom_bytes,
            "tiles": self.tiles.to_dict() if self.tiles is not None else None,
            "stack_reserved_bytes": self.stack_reserved_bytes,
            "oam_reserved_bytes": self.oam_reserved_bytes,
            "rooms": [room.to_dict() for room in self.rooms],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    def format(self) -> str:
        def usage(label, resource):
            return (f"{label}: {resource.used:,} / {resource.capacity:,} bytes "
                    f"({resource.percent:.1f}%; {resource.free:,} free)")
        lines = [usage("PRG ROM", self.prg),
                 f"  Code {self.code_bytes:,}; read-only data {self.rodata_bytes:,}; vectors {self.vector_bytes}",
                 usage("Work RAM", self.work_ram), usage("Zero page", self.zero_page)]
        if self.tiles is not None:
            lines.append(f"Graphics: {self.tiles.used} / {self.tiles.capacity} tile slots "
                         f"({self.tiles.free} free); {self.chr_rom_bytes:,}-byte CHR ROM")
        else:
            lines.append(f"CHR ROM: {self.chr_rom_bytes:,} bytes")
        for room in self.rooms:
            lines.append(f"Room {room.name}: {room.actors} actors, {room.oam_slots}/64 sprite slots; "
                         f"background {room.nametable_bytes} bytes ({room.nametable_encoding}), "
                         f"collision {room.collision_bytes}, initial OAM {room.initial_oam_bytes}")
        lines.append("Stack and OAM reserve 256 bytes each separately; stack depth and sprites per scanline are not measured.")
        return "\n".join(lines)


def describe_game(game) -> dict:
    """Capture authoring information which cannot be recovered from an ld65 map."""
    scopes = game.rooms or (game,)
    has_physics = any(scope.actors for scope in scopes)
    rooms = []
    for scope in scopes:
        if game.rooms:
            background, compressed = nametable_storage(scope.nametable())
            oam_bytes = len(initial_oam(scope.sprites))
        else:
            background, compressed = scope.nametable(), False
            oam_bytes = 256
        rooms.append(RoomUsage(
            name=getattr(scope, "name", "default"), actors=len(scope.actors),
            oam_slots=scope._oam_used, nametable_bytes=len(background),
            nametable_encoding="rle" if compressed else "raw",
            collision_bytes=120 if has_physics else 0, initial_oam_bytes=oam_bytes,
        ).to_dict())
    return {"tile_count": len(game._tiles), "rooms": rooms}


def linked_report(map_text: str, rom: bytes, resources: dict | None = None) -> ResourceReport:
    """Read exact segment sizes from the linker's segment list, ignoring fill."""
    parts = map_text.split("Segment list:", 1)
    if len(parts) != 2:
        raise ValueError("linker map is missing its segment list")
    segment_text = parts[1].split("Exports list", 1)[0]
    segments = {}
    for line in segment_text.splitlines():
        match = re.fullmatch(r"\s*(\w+)\s+([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)\s*", line)
        if match:
            segments[match[1]] = int(match[4], 16)
    if not {"CODE", "RODATA", "VECTORS", "CHARS"} <= segments.keys():
        raise ValueError("linker map is missing required cartridge segments")
    resources = resources or {}
    code, data, vectors = (segments[name] for name in ("CODE", "RODATA", "VECTORS"))
    return ResourceReport(
        prg=ResourceUsage(code + data + vectors, rom[4] * 16384),
        work_ram=ResourceUsage(segments.get("BSS", 0), 1280),
        zero_page=ResourceUsage(segments.get("ZEROPAGE", 0), 256),
        chr_rom_bytes=segments["CHARS"], code_bytes=code, rodata_bytes=data, vector_bytes=vectors,
        tiles=ResourceUsage(resources["tile_count"], 256) if "tile_count" in resources else None,
        rooms=tuple(RoomUsage(**room) for room in resources.get("rooms", ())),
    )
