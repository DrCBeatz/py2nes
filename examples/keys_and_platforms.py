"""A complete screen: jump, collect three keys, avoid the hazard, reach the door.

Build: python examples/keys_and_platforms.py
Controls: left/right to move; A to jump; Start to restart.
"""

from pathlib import Path

from py3nes import (Add, Animate, Button, Game, Hide, Hitbox, If, Overlaps,
                    PlaySound, Set, SetBackgroundTile, Show, Teleport, Tile,
                    Tone, Velocity, WriteNumber, WriteText)


game = Game()
keys = game.byte("keys")
lives = game.byte("lives", 3)
won = game.flag("won")
lost = game.flag("lost")
taken = [game.flag(f"key{i}_taken") for i in range(3)]
invincible = game.byte("invincible")

brick = game.tile(["22222222", "21112111", "21112111", "22222222",
                   "11211121", "11211121", "22222222", "33333333"])
game.map([[brick] * 32, [brick] * 32], row=28, solid=True)
game.map([[brick] * 6], column=9, row=25, solid=True)
game.map([[brick] * 6], column=17, row=22, solid=True)
game.text("KEYS AND PLATFORMS", column=6, row=2)
game.text("KEYS:0/3        LIVES:3", column=2, row=4)
game.text("D-PAD:MOVE A:JUMP START:RESET", column=2, row=7)

# A 16x16 character is four independent NES sprites, moving as one actor.
def quadrant(rows):
    return game.tile(Tile.from_rows(rows))


head_l = quadrant(["....2222", "...22222", "...23333", "..233133",
                   "..233333", "...23333", "....2222", "...22222"])
head_r = quadrant(["2222....", "22222...", "33332...", "331332..",
                   "333332..", "33332...", "2222....", "22222..."])
feet_l = quadrant(["..222222", "..322222", "...22222", "....2222",
                   "....22..", "...222..", "..1111..", "..1111.."])
feet_r = quadrant(["222222..", "222223..", "22222...", "2222....",
                   "..22....", "..222...", "..1111..", "..1111.."])
step_l = quadrant(["..222222", "..322222", "...22222", "....2222",
                   "...222..", "..222...", ".1111...", "........"])
step_r = quadrant(["222222..", "222223..", "22222...", "2222....",
                   "..222...", "...222..", "...1111.", "........"])
idle = game.metasprite([[head_l, head_r], [feet_l, feet_r]])
walk = game.metasprite([[head_l, head_r], [step_l, step_r]])
player = game.actor(name="player", frames=[idle, walk], x=24, y=208,
                    hitbox=Hitbox(12, 16, offset_x=2), gravity=1,
                    max_fall_speed=5, frame_ticks=6)

key_tile = game.tile([".111....", "11211...", ".111....", "..1.....",
                      "..111...", "..1.....", "..111...", "........"])
collectibles = [game.actor(name=f"key{i}", tile=key_tile, x=x, y=y, collides=False)
                for i, (x, y) in enumerate(((48, 216), (88, 192), (152, 168)))]

door_l = quadrant(["11111111", "12222222", "12333333", "12322222",
                   "12322222", "12322222", "12322222", "12322222"])
door_r = quadrant(["11111111", "22222221", "33333321", "22222321",
                   "22222321", "22211321", "22211321", "22222321"])
door = game.actor(name="door", tile=game.metasprite([[door_l, door_r], [door_l, door_r]]),
                  x=232, y=208, collides=False)
hazard_tile = game.tile(["3..33..3", "33333333", ".311113.", ".313313.",
                         ".311113.", ".333333.", "3.3..3.3", "..3..3.."])
hazard = game.actor(name="hazard", tile=hazard_tile, x=192, y=216, collides=False)

jump_sound = Tone(660, frames=5, volume=8)
key_sound = Tone(988, frames=8, volume=10)
hit_sound = Tone(110, frames=12, volume=8)
win_sound = Tone(1320, frames=24, volume=10)

playing = ~won & ~lost
# Input rules run in registration order before physics. Release stops horizontal motion.
game.every_frame(Velocity(player, vx=0), Animate(player, False),
                 If(invincible.gt(0), Add(invincible, -1)))
game.bind_held(Button.RIGHT, If(playing, Velocity(player, vx=2), Animate(player)))
game.bind_held(Button.LEFT, If(playing, Velocity(player, vx=-2), Animate(player)))
game.bind_pressed(Button.A, If(playing & player.grounded,
                              Velocity(player, vy=-8), PlaySound(jump_sound)))
game.every_frame(If(playing,
    If(hazard.vx.eq(0) | hazard.x.le(168), Velocity(hazard, vx=1)),
    If(hazard.x.ge(208), Velocity(hazard, vx=-1)),
    otherwise=(Velocity(hazard, vx=0),)))

# Check collection after movement so the hitboxes match this tick's positions.
for flag, key in zip(taken, collectibles):
    game.after_physics(If(playing & ~flag & Overlaps(player, key),
                          Set(flag, True), Add(keys, 1), Hide(key), PlaySound(key_sound)))

game.after_physics(If(playing & invincible.eq(0) & Overlaps(player, hazard),
    Add(lives, -1), Set(invincible, 60), Teleport(player, 24, 208), PlaySound(hit_sound),
    If(lives.eq(0), Set(lost, True), WriteText("GAME OVER. START", 6, 10, width=20))))

game.after_physics(If(playing & keys.eq(3) & Overlaps(player, door),
    Set(won, True), Velocity(player, vx=0, vy=0),
    WriteText("YOU WIN! PRESS START", 6, 10, width=20), PlaySound(win_sound)))

# A changing background marker above the exit, independent of collision data.
game.after_physics(SetBackgroundTile(0, 30, 25),
    If(keys.eq(3), SetBackgroundTile(key_tile, 30, 25)),
    WriteNumber(keys, column=7, row=4, digits=1),
    WriteNumber(lives, column=24, row=4, digits=1))

reset = [Set(keys, 0), Set(lives, 3), Set(won, False), Set(lost, False),
         Set(invincible, 0), Teleport(player, 24, 208), Teleport(hazard, 192, 216),
         Set(player.frame, 0), WriteText("", 6, 10, width=20)]
for flag, key in zip(taken, collectibles):
    reset += [Set(flag, False), Show(key)]
game.bind_pressed(Button.START, *reset)

if __name__ == "__main__":
    result = game.build(Path(__file__).resolve().parents[1] / "build" / "keys_and_platforms.nes")
    print(f"ROM: {result.rom_path}")
    print(f"Assembly: {result.assembly_path}")
