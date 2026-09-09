"""Draw the art and edit the rooms visually; describe the game rules in Python.

Install: python -m pip install -e '.[images]'
Build: python -m py3nes examples/visual_adventure.py -o build/visual_adventure.nes
Edit: assets/adventure/tiles.png and the hall/garden/tower.tmj files in Tiled.
Controls: left/right move, hold A for a higher jump, Up enters doors, Start resets.
"""

from pathlib import Path

from py3nes import (Button, ChangeRoom, Game, Hide, Hitbox, If, Overlaps,
                    PlaySound, Set, Tone, Velocity, WriteNumber, WriteText, load_png)


ASSETS = Path(__file__).resolve().parent / "assets" / "adventure"
game = Game()
keys = game.byte("keys")
won = game.flag("won")
rooms = {name: game.room(name) for name in ("hall", "garden", "tower")}
hall, garden, tower = (rooms[name] for name in ("hall", "garden", "tower"))
key_taken = garden.flag("key_taken", persistent=True)
lock_explained = hall.flag("lock_explained")

# PNG indices select pixel values; game.palette selects the hardware colors.
art = load_png(ASSETS / "tiles.png")
standing = game.metasprite(art.region(0, 1, 2, 2))
walking = game.metasprite(art.region(2, 1, 2, 2))
door_graphic = game.metasprite(art.region(4, 1, 2, 2))
key_tile = game.tile(art.tile(3, 0))
jump_sound = Tone(660, frames=5, volume=8)


def make_player(room, placement):
    """Tiled properties tune motion; the factory decides what 'player' means."""
    settings = placement.properties
    actor = room.actor(name=placement.name, x=placement.x, y=placement.y,
                       frames=[standing, walking], hitbox=Hitbox(12, 16, offset_x=2),
                       gravity=settings.get("gravity", 0.25),
                       max_fall_speed=settings.get("max_fall_speed", 5),
                       frame_ticks=6, subpixel=True)
    room.platformer(actor, speed=settings.get("speed", 2.25),
                    acceleration=settings.get("acceleration", 0.25),
                    friction=settings.get("friction", 0.375),
                    jump_speed=settings.get("jump_speed", 5.5),
                    jump_cut=2, buffer_frames=5, coyote_frames=4, enabled=~won)
    room.bind_pressed(Button.A, If(~won & actor.grounded, PlaySound(jump_sound)))
    return actor


def make_door(room, placement):
    return room.actor(name=placement.name, x=placement.x, y=placement.y,
                      tile=door_graphic, collides=False)


def make_key(room, placement):
    return room.actor(name=placement.name, x=placement.x, y=placement.y,
                      tile=key_tile, collides=False)


factories = {"player": make_player, "door": make_door, "key": make_key}
imported = {name: room.import_tiled(ASSETS / f"{name}.tmj", actor_factories=factories)
            for name, room in rooms.items()}
players = {name: result.actors["player"] for name, result in imported.items()}
titles = {"hall": "THE CROSSROADS", "garden": "THE KEY GARDEN", "tower": "THE OPEN TOWER"}
for name, room in rooms.items():
    room.text(titles[name], column=9, row=2)
    room.text("KEYS:0     UP:ENTER DOOR", column=2, row=4)
    room.text("HOLD A:HIGH JUMP", column=2, row=6)
    room.text("START:NEW GAME", column=2, row=8)
    room.on_enter(WriteNumber(keys, 7, 4, digits=1))
    room.after_physics(WriteNumber(keys, 7, 4, digits=1))

# The imported exit rectangles and their destinations are editable in Tiled.
# Plain exits can register their rules directly; the hall's tower exit is locked.
imported["garden"].bind_exits(players["garden"], rooms)
imported["tower"].bind_exits(players["tower"], rooms)
hall_player = players["hall"]
to_garden = imported["hall"].exits["to_garden"]
to_tower = imported["hall"].exits["to_tower"]


def destination(exit):
    return ChangeRoom(rooms[exit.properties["room"]], spawn=exit.properties.get("spawn"))


hall.bind_pressed(Button.UP,
    If(to_garden.contains(hall_player), destination(to_garden)),
    If(to_tower.contains(hall_player),
       If(keys.gt(0), destination(to_tower),
          otherwise=(If(~lock_explained, Set(lock_explained, True),
                        WriteText("FIND THE GARDEN KEY", 6, 19, width=20),
                        PlaySound(Tone(165, frames=8, volume=8))),))))
hall.text("GARDEN", column=1, row=24)
hall.text("TOWER", column=26, row=24)
hall.text_box("FIND THE GARDEN KEY. RETURN HERE TO OPEN THE TOWER.",
              column=4, row=12, width=24)
hall.on_enter(If(keys.gt(0), WriteText("TOWER UNLOCKED", 8, 19, width=16)))

key = imported["garden"].actors["key"]
garden.text("HALL", column=1, row=24)
garden.text_box("HOLD A TO REACH THE KEY. RETURN THROUGH THE LEFT DOOR.",
                column=4, row=12, width=24)
garden.on_enter(If(key_taken, Hide(key), WriteText("KEY ALREADY COLLECTED", 5, 19)))
garden.after_physics(If(~key_taken & Overlaps(players["garden"], key),
    Set(key_taken, True), Set(keys, 1), Hide(key), PlaySound(Tone(988, frames=8, volume=10)),
    WriteNumber(keys, 7, 4, digits=1), WriteText("KEY FOUND! RETURN LEFT", 5, 19)))

tower.text("HALL", column=1, row=24)
tower.text("EXIT", column=27, row=24)
tower.text_box("YOUR KEY OPENED THE TOWER. REACH THE EXIT AND PRESS UP.",
               column=4, row=12, width=24)
tower.bind_pressed(Button.UP, If(~won & Overlaps(players["tower"], imported["tower"].actors["final_exit"]),
    Set(won, True), Velocity(players["tower"], vx=0, vy=0),
    WriteText("YOU WIN! PRESS START", 6, 19, width=20), PlaySound(Tone(1320, frames=24, volume=10))))

game.bind_pressed(Button.START, Set(keys, 0), Set(won, False), Set(key_taken, False),
                  ChangeRoom(hall, spawn="start"))
game.start(hall, spawn="start")

if __name__ == "__main__":
    result = game.build(ASSETS.parents[2] / "build" / "visual_adventure.nes")
    print(f"ROM: {result.rom_path}")
