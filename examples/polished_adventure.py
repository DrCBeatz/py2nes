"""Game modes, recoil, and directional attacks in the three-room adventure.

Build: python -m py3nes examples/polished_adventure.py -o build/polished_adventure.nes --report
Start begins/pauses/resumes. Left/right move; A jumps; B swings; Up talks/enters.
Defeat the guard with two swings, collect the key, and unlock the tower.
"""

from pathlib import Path

from py3nes import (Add, AnimationClip, Button, ChangeRoom, Choice, Do, Game, Hide,
                    Hitbox, If, Metasprite, Overlaps, PlayAnimation, PlayMusic,
                    PlaySound, Set, SoundEffect, SpritePart, Tile, Tone, Velocity,
                    Wait, WriteNumber, WriteText, load_famistudio, load_png)


ASSETS = Path(__file__).resolve().parent / "assets"
game = Game()
title = game.mode("title")
playing = game.mode("playing", gameplay=True)
paused = game.mode("paused", pause_music=True)
game_over = game.mode("game_over", pause_music=True)
victory = game.mode("victory")
game.start_mode(title)
keys = game.byte("keys")
lives = game.byte("lives", 3)
new_run = game.flag("new_run", True)
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
slash_tile = game.tile(Tile.from_rows([
    "..2222..", "..3133..", "..3333..", "..2222..",
    "11111111", "....11..", "....1...", "........",
]))
strike = Metasprite((standing.parts[0], SpritePart(slash_tile, dx=8),
                     walking.parts[2], walking.parts[3]))
door_graphic = game.metasprite(art.region(4, 1, 2, 2))
key_tile = game.tile(art.tile(3, 0))
music = load_famistudio(ASSETS / "music" / "little_rooms.music.json")
pickup = SoundEffect((Tone(660, frames=3), Tone(880, frames=3), Tone(1320, frames=5)), priority=2)
hurt_sound = SoundEffect((Tone(220, frames=4), Tone(165, frames=5, volume=7)), priority=3)
swing_sound = SoundEffect((Tone(880, frames=2, volume=6), Tone(440, frames=2, volume=4)), priority=1)


def make_player(room, placement):
    settings = placement.properties
    return room.actor(name=placement.name, x=placement.x, y=placement.y,
        animations={"idle": AnimationClip([standing]),
                    "walk": AnimationClip([standing, walking], frame_ticks=6),
                    "jump": AnimationClip([walking], loop=False),
                    "hurt": AnimationClip([hurt_pose], loop=False),
                    "attack": AnimationClip([strike, standing], frame_ticks=4, loop=False)},
        hitbox=Hitbox(12, 16, offset_x=2), gravity=settings.get("gravity", .25),
        max_fall_speed=settings.get("max_fall_speed", 5), subpixel=True, freezable=True)


def make_door(room, placement):
    return room.actor(name=placement.name, x=placement.x, y=placement.y, tile=door_graphic, collides=False)


def make_key(room, placement):
    return room.actor(name=placement.name, x=placement.x, y=placement.y, tile=key_tile, collides=False)


factories = {"player": make_player, "door": make_door, "key": make_key}
imported = {name: room.import_tiled(ASSETS / "adventure" / f"{name}.tmj", actor_factories=factories)
            for name, room in rooms.items()}
players = {name: result.actors["player"] for name, result in imported.items()}
for name, room in rooms.items():
    room.text({"hall": "THE CROSSROADS", "garden": "THE GUARDED GARDEN", "tower": "THE OPEN TOWER"}[name], column=6, row=2)
    room.text("KEYS:0 HP:3 LIVES:3", column=2, row=4)
    room.text("A:JUMP B:SWING UP:USE", column=2, row=6)
    room.text("START:PAUSE / RESUME", column=2, row=8)
    room.on_enter(PlayMusic(music), WriteNumber(keys, 7, 4, digits=1), WriteNumber(lives, 20, 4, digits=1))
    room.after_physics(WriteNumber(keys, 7, 4, digits=1), WriteNumber(lives, 20, 4, digits=1))

# Mode entry runs once; ordinary room rules and physics run only while playing.
title.on_enter(WriteText("THE GARDEN GATE", 2, 17, width=28),
               WriteText("PRESS START TO PLAY", 2, 19, width=28))
paused.on_enter(WriteText("PAUSED", 2, 19, width=28))
game_over.on_enter(WriteText("GAME OVER", 2, 17, width=28),
                   WriteText("START:TRY AGAIN", 2, 19, width=28),
                   WriteNumber(lives, 20, 4, digits=1), WriteText("0", 12, 4))
playing.on_enter(
    If(new_run, Set(new_run, False), Set(keys, 0), Set(lives, 3), Set(key_taken, False),
       ChangeRoom(hall, spawn="start")),
    WriteText("", 2, 17, width=28), WriteText("", 2, 19, width=28))
for mode in (title, game_over, victory):
    game.bind_pressed(Button.START, Set(new_run, True), playing.change(), scope=mode)
game.bind_pressed(Button.START, paused.change(), scope=playing)
game.bind_pressed(Button.START, playing.change(), scope=paused)

hall_player = players["hall"]
hall.actor(name="guide", tile=friend_pose, x=152, y=208, collides=False)
chat = hall.dialogue("guide", (
    "WELCOME! THE GARDEN KEY OPENS THE TOWER.",
    "B SWINGS IN FRONT OF YOU. LAND TWO HITS TO BEAT THE GUARD.",
), column=2, row=11, width=28, height=5, freeze=(hall_player,),
    choices=(Choice("READY", PlaySound(pickup)), Choice("I WILL EXPLORE")))
hall.bind_pressed(Button.UP, If(hall_player.x.ge(128) & hall_player.x.le(176), chat.start()))
hall.text("GARDEN", column=1, row=24)
hall.text("UP:GUIDE", column=16, row=24)
hall.text("TOWER", column=26, row=24)
for name, room in rooms.items():
    player = players[name]
    for exit in imported[name].exits.values():
        unlocked = keys.gt(0) if name == "hall" and exit.properties["room"] == "tower" else True
        room.bind_pressed(Button.UP, If(~player.frozen & exit.contains(player),
            If(unlocked, ChangeRoom(rooms[exit.properties["room"]], spawn=exit.properties.get("spawn")))))

garden_player = players["garden"]
checkpoint = garden.checkpoint(garden_player,
    points={"entrance": (40, 208), "ledge": (128, 184)}, initial="entrance")
health = garden.health(garden_player, points=3, invulnerability_frames=45)
hero_hurt = garden.hurtbox(health, stun_frames=12, knockback=2, lift=1.5,
                          animation="hurt", on_hurt=(PlaySound(hurt_sound),))
guard = garden.actor(name="guard", x=144, y=208,
    animations={"walk": AnimationClip([guard_standing, guard_walking], frame_ticks=8),
                "hurt": AnimationClip([hurt_pose], loop=False)},
    hitbox=Hitbox(12, 16, offset_x=2), gravity=.25, subpixel=True)
guard_health = garden.health(guard, points=2, invulnerability_frames=20)
guard_hurt = garden.hurtbox(guard_health, stun_frames=12, knockback=2, lift=1,
                           animation="hurt", on_hurt=(PlaySound(hurt_sound),))
garden.patrol(guard, left=112, right=200, speed=.75, animation="walk",
               enabled=guard_health.alive, suspended=guard_hurt.stunned)

attacks = {}
for name, room in rooms.items():
    player = players[name]
    attack = room.attack(player, reach=14, height=12, offset_y=2,
        active_frames=8, cooldown_frames=12, animation="attack",
        on_start=(Velocity(player, vx=0), PlaySound(swing_sound)))
    attacks[name] = attack
    suspended = attack.active | hero_hurt.stunned if name == "garden" else attack.active
    room.bind_pressed(Button.B, If(~player.frozen & ~hero_hurt.stunned, attack.start())
                      if name == "garden" else If(~player.frozen, attack.start()))
    room.platformer(player, speed=2.25, acceleration=.25, friction=.375,
        jump_speed=5.5, jump_cut=2, buffer_frames=5, coyote_frames=4,
        suspended=suspended, animate=False)
    normal = If(player.grounded,
        If(player.vx.ne(0) | player.vx_fraction.ne(0), PlayAnimation(player, "walk"),
           otherwise=(PlayAnimation(player, "idle"),)), otherwise=(PlayAnimation(player, "jump"),))
    room.after_physics(If(~player.frozen & ~suspended, normal))

garden.after_physics(attacks["garden"].hit(guard_hurt))
garden.after_physics(If(Overlaps(garden_player, guard), hero_hurt.damage(source=guard,
    on_hurt=(attacks["garden"].cancel(),),
    on_death=(attacks["garden"].cancel(),
              If(lives.gt(1), Add(lives, -1), checkpoint.respawn(), health.restore(),
                 otherwise=(Set(lives, 0), game_over.change())),))))
garden.after_physics(WriteNumber(health.points, 12, 4, digits=1))
key = imported["garden"].actors["key"]
garden.on_enter(If(key_taken, Hide(key)))
garden.after_physics(If(~key_taken & Overlaps(garden_player, key),
    Set(key_taken, True), Set(keys, 1), Hide(key), checkpoint.activate("ledge"), PlaySound(pickup)))
garden.text("B:SWING BEFORE CONTACT", column=2, row=11)
garden.text("KEY = CHECKPOINT", column=2, row=13)
garden.text("HALL", column=1, row=24)
tower.text("HALL", column=1, row=24)
tower.text("EXIT", column=27, row=24)
with game.during(victory):
    ending = game.sequence("ending", Do(WriteText("THE TOWER IS OPEN!", 2, 17, width=28)),
                           Wait(45), Do(WriteText("YOU WIN! PRESS START", 2, 19, width=28)))
victory.on_enter(PlayMusic(music, song="Victory", restart=True), ending.start())
tower.bind_pressed(Button.UP, If(Overlaps(players["tower"], imported["tower"].actors["final_exit"]), victory.change()))
game.start(hall, spawn="start")

if __name__ == "__main__":
    result = game.build(ASSETS.parents[1] / "build" / "polished_adventure.nes")
    print(f"ROM: {result.rom_path}")
