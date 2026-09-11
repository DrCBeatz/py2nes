# Little Rooms

An original short score for py3nes, licensed under the project's MIT license.

- **little_rooms.fms**: native editable FamiStudio 4.5.1 project.
- **little_rooms.txt**: equivalent readable FamiStudio text project.
- **little_rooms.music.json**: portable assembly export consumed by the example.

The project contains `Explore` (song 0, looping) and `Victory` (song 1, ending).
It uses standard NTSC channels without DPCM samples or expansion chips.

Open the `.fms` file in FamiStudio, edit, and save. From the project root:

```sh
.venv/bin/python -c 'from py3nes import export_famistudio; export_famistudio("examples/assets/music/little_rooms.fms", "examples/assets/music/little_rooms.music.json")'
.venv/bin/python -m py3nes examples/living_adventure.py -o build/living_adventure.nes
```

Commit the updated native project and portable export together when sharing a
composition. Building the example from the portable export needs only Python,
the images extra, and cc65. FamiStudio is needed when exporting an edited song.

The library auto-detects `/Applications/FamiStudio.app`. For another location,
set `FAMISTUDIO` or pass `executable=` to `export_famistudio`.

The [gameplay guide](../../../docs/gameplay.md#famistudio-music-and-sound-effects)
describes playback commands, supported features, and sound-effect mixing.
