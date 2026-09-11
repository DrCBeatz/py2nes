# Cartridge resources and generated data

Build with `--report` to see the actual linked cartridge budgets:

```sh
python -m py3nes examples/living_adventure.py -o build/living_adventure.nes --report
```

Every successful build also writes `build/living_adventure.report.json` beside
the ROM, assembly, linker map, and labels. `--report-json path/to/report.json`
writes an additional copy for another tool. Reports require a linked ROM and
cannot be combined with `--assembly-only`. Normal CLI output remains the ROM
path when neither report option is supplied.

The Python result exposes the same measurements:

```python
result = game.build("build/demo.nes")
print(result.report.format())
print(result.report.prg.free)
print(result.report.work_ram.used)
print(result.report.tiles.free)
print(result.report_path)
```

`ResourceReport.to_dict()` and `.to_json()` provide the versioned JSON form;
the current `schema_version` is 1. `ResourceUsage` has `used`, `capacity`, `free`,
and `percent` attributes. A linked report includes:

- **PRG ROM:** actual code, read-only data, and six vector bytes, against the
  16 KiB single-scene or 32 KiB named-room limit. Padding in the `.nes` file is
  excluded. Empty space shown as `$FF` in a ROM viewer is not necessarily data.
- **Work RAM and zero page:** actual linker allocation, including any audio
  engine allocation, against 1,280 and 256 bytes respectively. Actor state for
  every room contributes to work RAM, even when its room is inactive.
- **Graphics:** registered tiles against the shared 256-tile capacity, including
  the 64 predefined font tiles. Each tile is 16 bytes. The 4 KiB pattern table
  is duplicated into the 8 KiB CHR ROM for compatibility with either PPU table.
- **Rooms:** actor count, allocated hardware sprite slots, stored background
  bytes, collision bytes, and initial OAM data. Rooms reuse the same 64 sprite
  slots; slots are not added across rooms. Every frame of an actor shares its
  reserved slots, based on its largest frame.

The NES stack and OAM buffer each have a separate reserved 256-byte page.
Neither is added to the work-RAM usage. This report does not measure peak stack
depth, CPU time, or the number of sprites covering a particular scanline.
The hardware limit of eight sprites per scanline still applies, even if the
whole room uses fewer than 64 sprite slots.

## Smaller ROM data

Public `nametable()`, `collision_data()`, and `chr_data()` results retain their
existing byte formats. The compiler makes three storage choices internally:

1. **Room backgrounds use literal/repeat packets when worthwhile.** The room
   loader unpacks directly into PPU memory while rendering is disabled. No
   background decompression runs during gameplay and no RAM buffer is added.
   A screen must save at least 80 bytes to use this format, paying for the
   shared decoder even when only one room compresses. Other screens remain raw.
2. **Static collision uses one bit per tile.** A 32 by 30 grid takes 120 ROM
   bytes instead of 960. Physics reads the packed bits directly with the same
   pixel sweep and hitbox rules; collision data is still immutable at runtime.
3. **Initial room OAM stores only its populated prefix.** The loader fills the
   remaining bytes with `$FF` and renders actors into their assigned slots.
   Actor-only rooms need no initial OAM ROM bytes. Full static sprite layouts
   retain all 256 bytes.

These optimizations leave cartridge capacity unchanged. They free space for
more code and content within NROM. On the unchanged v0.5 adventure, linked PRG
usage drops from 30,819 to 24,995 bytes, freeing 5,824 bytes without additional
work RAM or zero-page storage. Later changes to the example can change its
reported size; the linked report is the source of truth for each build.
