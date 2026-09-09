# Adventure artwork

`tiles.png` is an editable indexed PNG containing the original graphics from
[`examples/three_rooms.py`](../../three_rooms.py). It is 64×24 pixels: eight
columns and three rows of 8×8 tiles, with no spacing or border. `tiles.tsj` is
the external Tiled JSON tileset that references it. Both are covered by the
repository's MIT license.

| Tile row | Column 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Brick | Grass | Stone | Key | Door left | Door right | Blank | Blank |
| 1 | Head left | Head right | Head left | Head right | Door left | Door right | Blank | Blank |
| 2 | Foot left | Foot right | Step left | Step right | Door left | Door right | Blank | Blank |

The standing player occupies `sheet.region(0, 1, 2, 2)`; the stepping player is
`sheet.region(2, 1, 2, 2)`. The 16×16 door uses `sheet.region(4, 1, 2, 2)`.
In Tiled, local tile IDs run left to right, then top to bottom, starting at zero.
Map global IDs add the tileset's `firstgid`, usually 1.

Preserve indexed color when saving artwork. Palette index 0 is transparent;
indexes 1–3 are visible pixel values. The PNG's preview palette is:

| Pixel value | Preview color |
| --- | --- |
| 0 | Transparent black, `#00000000` |
| 1 | White, `#ECEEEC` |
| 2 | Blue, `#4C9AEC` |
| 3 | Brown, `#A84000` |

These RGB colors help display the sheet in an editor. The NES colors in the
compiled game come from `Game(palette=...)`, together with the background or
sprite's chosen subpalette. PNG pixel values remain the same across subpalettes.
An NES background uses its universal backdrop color where pixel value 0 occurs;
that pixel is transparent on a hardware sprite.

Use a pencil tool without antialiasing. If your editor exports RGB/RGBA instead
of indexed PNG, pass this exact mapping to `load_png` and `load_tiled`:

```python
colors = ["#00000000", "#ECEEEC", "#4C9AEC", "#A84000"]
```

Partially transparent and unmapped colors are rejected. Fully transparent pixels
map to zero regardless of their hidden RGB values. Repeated graphics in this
sheet share a CHR tile after registration, so the duplicated head and door tiles
make animation frames convenient without consuming duplicate ROM tiles.

## Editing the adventure in Tiled

Open `hall.tmj`, `garden.tmj`, or `tower.tmj` in Tiled. Their external tileset
already points to `tiles.tsj` and `tiles.png`; keep these files together.

1. Paint visible platforms on the `background` tile layer. Its `palette`
   property selects the NES background palette: hall 0, garden 2, tower 3.
2. Select the hidden `collision` layer to paint or erase solid cells. Any
   nonempty tile is solid. When moving a platform, update both layers; artwork
   alone does not create collision. Toggle layer visibility while editing if
   helpful; the importer reads collision even when that layer is hidden.
3. Move `player`, `key`, and door objects on the `objects` layer. Their names
   identify them in Python; their classes select the factory that constructs
   them. Select a player to tune its `gravity`, `max_fall_speed`, `speed`,
   `acceleration`, `friction`, and `jump_speed` properties.
4. Spawn points select an actor through their `actor` property. Exit rectangles
   select the destination with `room` and `spawn`. Move a doorway's visible
   door object and its matching exit rectangle together. The tower's final
   exit uses an overlap rule on its door actor in Python.

Keep the map finite and orthogonal, with 8×8 tiles and JSON array tile data.
Save, then rebuild from the repository directory:

```sh
python -m py3nes examples/visual_adventure.py -o build/visual_adventure.nes
```

The Python factories interpret the objects; custom properties are data and do
not execute Python. Collection, inventory, the locked tower, and victory remain
explicit rules in `visual_adventure.py`.
