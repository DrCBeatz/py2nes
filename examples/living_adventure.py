"""An adventure with behaviors, conversations, checkpoints, and FamiStudio music.

Build: python -m py3nes examples/living_adventure.py -o build/living_adventure.nes
Controls: arrows move, A jumps/confirms, B talks/attacks, Up enters doors,
Start begins a new game. Dialogue choices use Up/Down then A.
"""

from pathlib import Path

from py3nes import (Add, AnimationClip, Button, ButtonPressed, ChangeRoom, Choice,
                    Do, Game, Hide, Hitbox, If, Overlaps, PlayAnimation, PlayMusic,
                    PlaySound, Set, SoundEffect, Tone, Velocity, Wait, WriteNumber,
                    WriteText, load_famistudio, load_png)


ASSETS = Path(__file__).resolve().parent / "assets"
game = Game()
keys = game.byte("keys")
won = game.flag("won")
deaths = game.byte("deaths")
rooms = {name: game.room(name) for name in ("hall", "garden", "tower")}
hall, garden, tower = (rooms[name] for name in ("hall", "garden", "tower"))
key_taken = garden.flag("key_taken", persistent=True)
art = load_png(ASSETS / "adventure" / "tiles.png")
standing = game.metasprite(art.region(0, 1, 2, 2))
walking = game.metasprite(art.region(2, 1, 2, 2))
hurt_pose = game.metasprite(art.region(0, 1, 2, 2), palette=3)
guard_standing = game.metasprite(art.region(0, 1, 2, 2), palette=1)
guard_walking = game.metasprite(art.region(2, 1, 2, 2), palette=1)
friend_pose = game.metasprite(art.region(0, 1, 2, 2), palette=2)
door_graphic = game.metasprite(art.region(4, 1, 2, 2))
key_tile = game.tile(art.tile(3, 0))
music = load_famistudio(ASSETS / "music" / "little_rooms.music.json")
pickup_sound = SoundEffect((Tone(660, frames=3), Tone(880, frames=3), Tone(1320, frames=5)), priority=2)
hurt_sound = SoundEffect((Tone(220, frames=4), Tone(165, frames=5, volume=7)), priority=3)


def make_player(room, placement):
    settings = placement.properties
    return room.actor(name=placement.name, x=placement.x, y=placement.y,
        animations={"idle": AnimationClip([standing]),
                    "walk": AnimationClip([standing, walking], frame_ticks=6),
                    "jump": AnimationClip([walking], loop=False),
                    "hurt": AnimationClip([hurt_pose], loop=False)},
        hitbox=Hitbox(12, 16, offset_x=2), gravity=settings.get("gravity", .25),
        max_fall_speed=settings.get("max_fall_speed", 5), subpixel=True, freezable=True)


def make_door(room, placement):
    return room.actor(name=placement.name, x=placement.x, y=placement.y,
                      tile=door_graphic, collides=False)


def make_key(room, placement):
    return room.actor(name=placement.name, x=placement.x, y=placement.y,
                      tile=key_tile, collides=False)


factories = {"player": make_player, "door": make_door, "key": make_key}
imported = {name: room.import_tiled(ASSETS / "adventure" / f"{name}.tmj", actor_factories=factories)
            for name, room in rooms.items()}
players = {name: result.actors["player"] for name, result in imported.items()}
for name, room in rooms.items():
    player = players[name]
    room.platformer(player, speed=2.25, acceleration=.25, friction=.375,
                    jump_speed=5.5, jump_cut=2, buffer_frames=5, coyote_frames=4,
                    enabled=~won & ~player.frozen, animate=False)
    room.text({"hall": "THE CROSSROADS", "garden": "THE GUARDED GARDEN", "tower": "THE OPEN TOWER"}[name],
              column=6, row=2)
    room.text("KEYS:0  HP:3  DEATHS:0", column=2, row=4)
    room.text("A:JUMP  B:TALK / ATTACK", column=2, row=6)
    room.text("UP:DOOR  START:NEW GAME", column=2, row=8)
    room.on_enter(PlayMusic(music), WriteNumber(keys, 7, 4, digits=1), WriteNumber(deaths, 23, 4, digits=1))
    room.after_physics(WriteNumber(keys, 7, 4, digits=1), WriteNumber(deaths, 23, 4, digits=1))

friend = hall.actor(name="guide", tile=friend_pose, x=152, y=208, collides=False)
hall_player = players["hall"]
conversation = hall.dialogue("guide_chat", (
    "WELCOME! THE GARDEN KEY OPENS THE TOWER.",
    "JUMP TO THE KEY LEDGE. B ATTACKS THE GUARD WHEN YOU TOUCH IT.",
), column=2, row=11, width=28, height=5, freeze=(hall_player,),
    choices=(Choice("READY", PlaySound(pickup_sound)), Choice("I WILL EXPLORE")))
thanks = hall.dialogue("guide_thanks", (
    "YOU FOUND THE KEY! THE TOWER DOOR IS ON THE RIGHT.",
), column=2, row=17, width=28, height=2, freeze=(hall_player,))
hall.bind_pressed(Button.B,
    If(hall_player.x.ge(128) & hall_player.x.le(176) & ~won,
       If(keys.eq(0), conversation.start(), otherwise=(thanks.start(),))))
hall.text("GARDEN", column=1, row=24)
hall.text("B:GUIDE", column=17, row=24)
hall.text("TOWER", column=26, row=24)


def destination(exit):
    return ChangeRoom(rooms[exit.properties["room"]], spawn=exit.properties.get("spawn"))


for name, room in rooms.items():
    player = players[name]
    for exit in imported[name].exits.values():
        unlocked = keys.gt(0) if name == "hall" and exit.properties["room"] == "tower" else True
        room.bind_pressed(Button.UP, If(~player.frozen & ~won & exit.contains(player),
                                       If(unlocked, destination(exit))))

garden_player = players["garden"]
checkpoint = garden.checkpoint(garden_player, points={"entrance": (40, 208), "ledge": (128, 184)}, initial="entrance")
health = garden.health(garden_player, points=3, invulnerability_frames=45,
                       on_hurt=(PlaySound(hurt_sound),), enabled=~garden_player.frozen)
guard = garden.actor(name="guard", x=144, y=208,
    animations={"walk": AnimationClip([guard_standing, guard_walking], frame_ticks=8)},
    hitbox=Hitbox(12, 16, offset_x=2), gravity=.25, subpixel=True)
guard_health = garden.health(guard, points=1)
garden.patrol(guard, left=112, right=200, speed=.75, animation="walk", enabled=guard_health.alive)
garden.after_physics(If(Overlaps(garden_player, guard),
    If(ButtonPressed(Button.B), guard_health.damage(),
       otherwise=(health.damage(on_death=(checkpoint.respawn(), health.restore(), Add(deaths, 1))),))))
garden.after_physics(WriteNumber(health.points, 13, 4, digits=1))
key = imported["garden"].actors["key"]
garden.on_enter(If(key_taken, Hide(key)))
garden.after_physics(If(~key_taken & Overlaps(garden_player, key),
    Set(key_taken, True), Set(keys, 1), Hide(key), checkpoint.activate("ledge"),
    PlaySound(pickup_sound), WriteText("KEY + CHECKPOINT!", 5, 17, width=22)))
garden.text("B:ATTACK THE GUARD", column=3, row=11)
garden.text("THE KEY SETS A CHECKPOINT", column=2, row=13)
garden.text("HALL", column=1, row=24)

for name, room in rooms.items():
    player = players[name]
    normal = If(player.grounded,
        If(player.vx.ne(0) | player.vx_fraction.ne(0), PlayAnimation(player, "walk"),
           otherwise=(PlayAnimation(player, "idle"),)),
        otherwise=(PlayAnimation(player, "jump"),))
    animation = If(health.invulnerability.gt(0), PlayAnimation(player, "hurt"), otherwise=(normal,)) if name == "garden" else normal
    room.after_physics(If(~player.frozen, animation))

tower.text("HALL", column=1, row=24)
tower.text("EXIT", column=27, row=24)
tower.text("REACH THE EXIT AND PRESS UP", column=2, row=12)
ending = tower.sequence("ending",
    Do(PlayMusic(music, song=1), WriteText("THE TOWER IS OPEN!", 5, 15, width=22)),
    Wait(45), Do(WriteText("YOU WIN! PRESS START", 5, 17, width=22)),
    freeze=(players["tower"],))
tower.bind_pressed(Button.UP, If(~won & Overlaps(players["tower"], imported["tower"].actors["final_exit"]),
    Set(won, True), Velocity(players["tower"], vx=0, vy=0), ending.start()))

game.bind_pressed(Button.START, Set(keys, 0), Set(won, False), Set(key_taken, False), Set(deaths, 0),
                  ChangeRoom(hall, spawn="start"))
game.start(hall, spawn="start")

if __name__ == "__main__":
    result = game.build(ASSETS.parents[1] / "build" / "living_adventure.nes")
    print(f"ROM: {result.rom_path}")
