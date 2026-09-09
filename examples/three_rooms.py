"""A three-room adventure with inventory and a persistent collectible.

Build: python examples/three_rooms.py
Controls: left/right to move, A to jump, Up at a door, Start to restart.
Visit the garden, collect its key, return to the hall, and unlock the tower.
"""

from pathlib import Path

from py3nes import (Animate, Button, ChangeRoom, Game, Hide, Hitbox, If,
                    Overlaps, PlaySound, Set, SetBackgroundTile, Tone, Velocity,
                    WriteNumber, WriteText)


game = Game()
inventory = game.byte("keys")              # Shared by every room.
won = game.flag("won")
hall = game.room("hall")
garden = game.room("garden")
tower = game.room("tower")
key_taken = garden.flag("key_taken", persistent=True)

# Assets belong to the whole game. Python factories reuse them in each room.
brick = game.tile(["22222222", "21112111", "21112111", "22222222",
                   "11211121", "11211121", "22222222", "33333333"])
grass = game.tile(["11111111", "12121121", "22222222", "22322232",
                   "22222222", "32223222", "22222222", "33333333"])
stone = game.tile(["33333333", "32222223", "32222223", "33333333",
                   "22232222", "22232222", "22232222", "33333333"])
head_l = game.tile(["....2222", "...22222", "...23333", "..233133",
                    "..233333", "...23333", "....2222", "...22222"])
head_r = game.tile(["2222....", "22222...", "33332...", "331332..",
                    "333332..", "33332...", "2222....", "22222..."])
feet_l = game.tile(["..222222", "..322222", "...22222", "....2222",
                    "....22..", "...222..", "..1111..", "..1111.."])
feet_r = game.tile(["222222..", "222223..", "22222...", "2222....",
                    "..22....", "..222...", "..1111..", "..1111.."])
step_l = game.tile(["..222222", "..322222", "...22222", "....2222",
                    "...222..", "..222...", ".1111...", "........"])
step_r = game.tile(["222222..", "222223..", "22222...", "2222....",
                    "..222...", "...222..", "...1111.", "........"])
standing = game.metasprite([[head_l, head_r], [feet_l, feet_r]])
walking = game.metasprite([[head_l, head_r], [step_l, step_r]])
key_tile = game.tile([".111....", "11211...", ".111....", "..1.....",
                      "..111...", "..1.....", "..111...", "........"])
door_l = game.tile(["11111111", "12222222", "12333333", "12322222",
                    "12322222", "12322222", "12322222", "12322222"])
door_r = game.tile(["11111111", "22222221", "33333321", "22222321",
                    "22222321", "22211321", "22211321", "22222321"])
door_graphic = game.metasprite([[door_l, door_r], [door_l, door_r]])
jump_sound = Tone(660, frames=5, volume=8)
key_sound = Tone(988, frames=8, volume=10)
win_sound = Tone(1320, frames=24, volume=10)


def make_room(room, title, floor, x=24):
    room.map([[floor] * 32, [floor] * 32], row=28, solid=True)
    room.text(title, column=(32 - len(title)) // 2, row=2)
    room.text("KEYS:0     UP:ENTER DOOR", column=2, row=4)
    room.text("LEFT/RIGHT:MOVE A:JUMP", column=2, row=6)
    room.text("START:NEW GAME", column=2, row=8)
    player = room.actor(name="player", frames=[standing, walking], x=x, y=208,
                        hitbox=Hitbox(12, 16, offset_x=2), gravity=1,
                        max_fall_speed=5, frame_ticks=6)
    # Even persistent room flags reset only when we explicitly ask them to.
    room.bind_pressed(Button.START, Set(inventory, 0), Set(won, False),
                      Set(key_taken, False), ChangeRoom(hall, spawn="start"))
    room.every_frame(Velocity(player, vx=0), Animate(player, False))
    room.bind_held(Button.RIGHT, If(~won, Velocity(player, vx=2), Animate(player)))
    room.bind_held(Button.LEFT, If(~won, Velocity(player, vx=-2), Animate(player)))
    room.bind_pressed(Button.A, If(~won & player.grounded,
                                  Velocity(player, vy=-8), PlaySound(jump_sound)))
    room.on_enter(WriteNumber(inventory, column=7, row=4, digits=1))
    room.after_physics(WriteNumber(inventory, column=7, row=4, digits=1))
    return player


def door(room, name, x):
    return room.actor(name=name, tile=door_graphic, x=x, y=208, collides=False)


hall_player = make_room(hall, "THE CROSSROADS", brick, x=120)
garden_player = make_room(garden, "THE KEY GARDEN", grass)
tower_player = make_room(tower, "THE OPEN TOWER", stone)
hall.spawn("start", hall_player, x=120, y=208)
hall.spawn("from_garden", hall_player, x=40, y=208)
hall.spawn("from_tower", hall_player, x=200, y=208)
garden.spawn("entrance", garden_player, x=40, y=208)
tower.spawn("entrance", tower_player, x=40, y=208)

garden_door = door(hall, "garden_door", 16)
tower_door = door(hall, "tower_door", 224)
hall.text("GARDEN", column=1, row=24)
hall.text("TOWER", column=26, row=24)
hall.text_box("FIND THE GARDEN KEY. RETURN HERE TO OPEN THE TOWER.",
              column=4, row=12, width=24)
# This flag resets whenever we re-enter the hall. It only suppresses repeated
# locked-door messages during the current visit, unlike the persistent key.
lock_explained = hall.flag("lock_explained")
hall.on_enter(If(inventory.gt(0), WriteText("TOWER UNLOCKED", 8, 19, width=16)))
hall.bind_pressed(Button.UP,
    If(Overlaps(hall_player, garden_door), ChangeRoom(garden, spawn="entrance")),
    If(Overlaps(hall_player, tower_door),
       If(inventory.gt(0), ChangeRoom(tower, spawn="entrance"),
          otherwise=(If(~lock_explained, Set(lock_explained, True),
                        WriteText("FIND THE GARDEN KEY", 6, 19, width=20),
                        PlaySound(Tone(165, frames=8, volume=8))),))))

garden_return = door(garden, "return_door", 16)
garden.text("HALL", column=1, row=24)
garden.text_box("JUMP ONTO THE LEDGE. TAKE THE KEY BACK TO THE HALL.",
                column=4, row=12, width=24)
garden.map([[grass] * 16], column=9, row=25, solid=True)
garden.map([[grass] * 5], column=25, row=22, solid=True)
key = garden.actor(name="key", tile=key_tile, x=164, y=192, collides=False)
garden.on_enter(If(key_taken, Hide(key), WriteText("KEY ALREADY COLLECTED", 5, 19)))
garden.bind_pressed(Button.UP, If(Overlaps(garden_player, garden_return),
                                 ChangeRoom(hall, spawn="from_garden")))
garden.after_physics(If(~key_taken & Overlaps(garden_player, key),
    Set(key_taken, True), Set(inventory, 1), Hide(key), PlaySound(key_sound),
    WriteNumber(inventory, column=7, row=4, digits=1),
    WriteText("KEY FOUND! RETURN LEFT", 5, 19)))

tower_return = door(tower, "return_door", 16)
final_exit = door(tower, "final_exit", 224)
tower.text("HALL", column=1, row=24)
tower.text("EXIT", column=27, row=24)
tower.text_box("YOUR KEY OPENED THE TOWER. REACH THE EXIT AND PRESS UP.",
               column=4, row=12, width=24)
tower.map([[stone] * 6], column=12, row=25, solid=True)
tower.on_enter(SetBackgroundTile(key_tile, 29, 25))
tower.bind_pressed(Button.UP,
    If(~won & Overlaps(tower_player, tower_return), ChangeRoom(hall, spawn="from_tower")),
    If(~won & Overlaps(tower_player, final_exit),
       Set(won, True), Velocity(tower_player, vx=0, vy=0),
       WriteText("YOU WIN! PRESS START", 6, 19, width=20), PlaySound(win_sound)))

game.start(hall, spawn="start")

if __name__ == "__main__":
    result = game.build(Path(__file__).resolve().parents[1] / "build" / "three_rooms.nes")
    print(f"ROM: {result.rom_path}")
    print(f"Assembly: {result.assembly_path}")
