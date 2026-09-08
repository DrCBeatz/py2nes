"""Model boundaries and assembled 6502 actor behaviour."""

import unittest

from py3nes import Game
from py3nes.ir import If, Set
from py3nes.model import Button
from py3nes.physics import (Actor, Animate, Hide, Hitbox, Metasprite, Overlaps,
                           Show, SpritePart, Teleport, Velocity)
from tests.runtime_harness import HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME, RuntimeHarness


def actor_model(**kwargs):
    defaults = dict(index=0, name="player", frames=(Metasprite((SpritePart(1),)),),
                    oam_start=0, initial_x=40, initial_y=40)
    defaults.update(kwargs)
    return Actor(**defaults)


class PhysicsModelTests(unittest.TestCase):
    def test_actor_has_independent_typed_state_and_screen_bounds(self):
        actor = actor_model()
        self.assertEqual((actor.x.initial, actor.y.initial), (40, 40))
        self.assertEqual(actor.vx.kind, "i8")
        self.assertEqual(actor.grounded.kind, "flag")
        self.assertEqual(actor.visible.initial, 1)
        self.assertEqual(len({v.name for v in actor.variables}), 9)
        for args in ({"initial_y": 0}, {"initial_x": 249}, {"initial_y": 233}):
            with self.assertRaises(ValueError):
                actor_model(**args)

    def test_metasprite_extents_cover_every_frame_and_hitbox(self):
        frames = (Metasprite((SpritePart(1),)),
                  Metasprite((SpritePart(2), SpritePart(3, dx=8, dy=16))))
        actor = actor_model(frames=frames, hitbox=Hitbox(20, 10, 4, 2))
        self.assertEqual((actor.width, actor.height, actor.oam_slots), (24, 24, 2))
        with self.assertRaises(ValueError):
            actor_model(frames=frames, oam_start=63)
        with self.assertRaises(ValueError):
            Metasprite(())
        with self.assertRaises(ValueError):
            SpritePart(1, dx=-1)
        with self.assertRaises(ValueError):
            Hitbox(33, 8)

    def test_actions_reject_invalid_targets_and_values(self):
        actor = actor_model()
        for value in (-9, 9, True):
            with self.assertRaises((TypeError, ValueError)):
                Velocity(actor, vx=value)
        with self.assertRaises(ValueError):
            Velocity(actor)
        with self.assertRaises(ValueError):
            Teleport(actor, 248, 233)
        with self.assertRaises(TypeError):
            Hide(object())
        with self.assertRaises(TypeError):
            Animate(actor, enabled=1)
        with self.assertRaises(TypeError):
            bool(Overlaps(actor, actor))


@unittest.skipUnless(HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME)
class PhysicsRuntimeTests(unittest.TestCase):
    def test_gravity_floor_and_grounded_jump(self):
        game = Game()
        game.map([[1] * 32], row=15, solid=True)
        player = game.actor(tile=1, name="player", x=40, y=90, gravity=1)
        game.bind_pressed(Button.A, If(player.grounded, Velocity(player, vy=-6)))
        with RuntimeHarness(game) as run:
            for _ in range(20):
                run.frame()
            self.assertEqual(run.variable(player.y.name), 112)
            self.assertEqual(run.variable(player.vy.name, signed=True), 0)
            self.assertEqual(run.variable(player.grounded.name), 1)
            run.frame(Button.A)
            self.assertEqual(run.variable(player.y.name), 107)
            self.assertEqual(run.variable(player.vy.name, signed=True), -5)
            self.assertEqual(run.variable(player.grounded.name), 0)
            run.frame()
            run.frame(Button.A)
            self.assertEqual(run.variable(player.vy.name, signed=True), -3)
            self.assertEqual(run.sprite_data()[0], run.variable(player.y.name) - 1)

    def test_pixel_sweep_walls_and_ceiling_at_maximum_speed(self):
        game = Game()
        game.map([[1] for _ in range(20)], column=10, row=2, solid=True)
        game.map([[1] * 10], column=0, row=5, solid=True)
        player = game.actor(tile=1, name="player", x=69, y=51)
        game.bind_held(Button.RIGHT, Velocity(player, vx=8))
        game.bind_held(Button.A, Velocity(player, vy=-8))
        with RuntimeHarness(game) as run:
            run.frame(Button.RIGHT)
            self.assertEqual(run.variable(player.x.name), 72)
            self.assertEqual(run.variable(player.vx.name, signed=True), 0)
            run.frame(Button.A)
            self.assertEqual(run.variable(player.y.name), 48)
            self.assertEqual(run.variable(player.vy.name, signed=True), 0)

    def test_left_and_upper_screen_bounds_do_not_wrap(self):
        game = Game()
        player = game.actor(tile=1, name="player", x=3, y=4)
        game.every_frame(Velocity(player, vx=-8, vy=-8))
        with RuntimeHarness(game) as run:
            run.frame()
            self.assertEqual((run.variable(player.x.name), run.variable(player.y.name)), (0, 1))
            self.assertEqual((run.variable(player.vx.name), run.variable(player.vy.name)), (0, 0))
            self.assertEqual(run.sprite_data()[0], 0)

    def test_offset_hitbox_and_interior_solid_tile(self):
        game = Game()
        game.map([[1]], column=7, row=10, solid=True)
        player = game.actor(tile=1, name="player", x=40, y=68, hitbox=Hitbox(24, 8, 4, 2))
        game.every_frame(Velocity(player, vy=8))
        with RuntimeHarness(game) as run:
            run.frame()
            self.assertEqual(run.variable(player.y.name), 70)
            self.assertEqual(run.variable(player.grounded.name), 1)

    def test_grounded_is_available_before_first_button_event(self):
        game = Game()
        game.map([[1] * 32], row=15, solid=True)
        player = game.actor(tile=1, name="player", x=40, y=112, gravity=1)
        game.bind_pressed(Button.A, If(player.grounded, Velocity(player, vy=-6)))
        with RuntimeHarness(game) as run:
            self.assertEqual(run.variable(player.grounded.name), 1)
            run.frame(Button.A)
            self.assertEqual(run.variable(player.y.name), 107)

    def test_noncolliding_actor_passes_platform_but_stays_onscreen(self):
        game = Game()
        game.map([[1] * 32], row=15, solid=True)
        player = game.actor(tile=1, name="player", x=248, y=110, collides=False)
        game.every_frame(Velocity(player, vx=8, vy=8))
        with RuntimeHarness(game) as run:
            run.frame()
            self.assertEqual(run.variable(player.y.name), 118)
            self.assertEqual(run.variable(player.x.name), 248)
            for _ in range(20):
                run.frame()
            self.assertEqual(run.variable(player.y.name), 232)
            self.assertEqual(run.variable(player.grounded.name), 1)
            self.assertEqual(run.sprite_data()[0], 231)

    def test_overlaps_touching_edges_hidden_actors_and_offsets(self):
        game = Game()
        first = game.actor(tile=1, name="first", x=32, y=40, hitbox=Hitbox(4, 4, 2, 2))
        second = game.actor(tile=2, name="second", x=38, y=42, hitbox=Hitbox(4, 4))
        touching = game.flag("touching")
        game.every_frame(If(Overlaps(first, second), Set(touching, True), otherwise=(Set(touching, False),)))
        game.bind_pressed(Button.LEFT, Teleport(second, x=37, y=42))
        game.bind_pressed(Button.B, Hide(second))
        with RuntimeHarness(game) as run:
            run.frame()
            self.assertEqual(run.variable("touching"), 0)
            run.frame(Button.LEFT)
            # Button events follow the registered frame event; observe next tick.
            run.frame()
            self.assertEqual(run.variable("touching"), 1)
            run.frame(Button.B)
            run.frame()
            self.assertEqual(run.variable("touching"), 0)
            self.assertEqual(run.sprite_data(second.oam_start)[0], 255)

    def test_teleport_resets_velocity_and_hidden_actor_pauses_physics(self):
        game = Game()
        player = game.actor(tile=1, name="player", x=40, y=40, gravity=1)
        game.bind_pressed(Button.A, Teleport(player, 100, 100))
        game.bind_pressed(Button.B, Hide(player))
        game.bind_pressed(Button.START, Show(player))
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            self.assertEqual(run.variable(player.x.name), 100)
            self.assertEqual(run.variable(player.y.name), 101)
            run.frame(Button.B)
            for _ in range(5):
                run.frame()
            self.assertEqual(run.variable(player.y.name), 101)
            self.assertEqual(run.sprite_data()[0], 255)
            run.frame(Button.START)
            self.assertEqual(run.variable(player.y.name), 103)

    def test_velocity_expressions_saturate_according_to_signedness(self):
        game = Game()
        player = game.actor(tile=1, name="player", x=100, y=100)
        signed = game.signed_byte("signed_speed", initial=-120)
        unsigned = game.variable("unsigned_speed", initial=255)
        game.every_frame(Velocity(player, vx=signed, vy=unsigned))
        with RuntimeHarness(game) as run:
            run.frame()
            self.assertEqual((run.variable(player.x.name), run.variable(player.y.name)), (92, 108))
            self.assertEqual(run.variable(player.vx.name, signed=True), -8)
            self.assertEqual(run.variable(player.vy.name, signed=True), 8)

    def test_animation_renders_parts_and_hides_unused_slots(self):
        game = Game()
        wide = Metasprite((SpritePart(2, palette=1), SpritePart(3, dx=8, flip_horizontal=True)))
        narrow = Metasprite((SpritePart(4, dy=8, flip_vertical=True),))
        player = game.actor(frames=(wide, narrow), name="player", x=40, y=40, frame_ticks=2)
        game.bind_pressed(Button.B, Animate(player, False))
        with RuntimeHarness(game) as run:
            self.assertEqual(run.sprite_data(0), (39, 2, 1, 40))
            self.assertEqual(run.sprite_data(1), (39, 3, 64, 48))
            run.frame()
            self.assertEqual(run.sprite_data(0)[1], 2)
            run.frame()
            self.assertEqual(run.sprite_data(0), (47, 4, 128, 40))
            self.assertEqual(run.sprite_data(1)[0], 255)
            run.frame(Button.B)
            for _ in range(4):
                run.frame()
            self.assertEqual(run.variable(player.frame.name), 1)
            self.assertEqual(run.sprite_data(0)[1], 4)

    def test_direct_coordinate_assignments_are_clamped_before_movement(self):
        game = Game()
        graphic = Metasprite((SpritePart(1), SpritePart(2, dx=8, dy=8)))
        player = game.actor(tile=graphic, name="player", x=40, y=40)
        game.every_frame(Set(player.x, 255), Set(player.y, 0))
        with RuntimeHarness(game) as run:
            run.frame()
            self.assertEqual((run.variable(player.x.name), run.variable(player.y.name)), (240, 1))
            self.assertEqual(run.sprite_data(0), (0, 1, 0, 240))
            self.assertEqual(run.sprite_data(1), (8, 2, 0, 248))

    def test_post_physics_coordinate_assignments_clip_without_wrapping(self):
        game = Game()
        graphic = Metasprite((SpritePart(1), SpritePart(2, dx=8, dy=8)))
        player = game.actor(tile=graphic, name="player", x=40, y=40)
        game.after_physics(Set(player.x, 250), Set(player.y, 250))
        with RuntimeHarness(game) as run:
            run.frame()
            self.assertEqual(run.sprite_data(0)[0], 255)
            self.assertEqual(run.sprite_data(1)[0], 255)

    def test_overlap_endpoints_do_not_wrap_after_direct_coordinate_assignment(self):
        game = Game()
        first = game.actor(tile=1, x=40, y=40, hitbox=Hitbox(4, 4, 10, 0))
        second = game.actor(tile=1, x=4, y=40)
        touching = game.flag("touching")
        game.every_frame(Set(first.x, 250),
                         If(Overlaps(first, second), Set(touching, True)))
        with RuntimeHarness(game) as run:
            run.frame()
            self.assertEqual(run.variable("touching"), 0)

    def test_solid_map_is_separate_from_visual_overlays(self):
        game = Game()
        game.map([[1]], column=2, row=3, solid=True)
        game.map([[0]], column=2, row=3)
        self.assertEqual(game.collision_data()[3 * 32 + 2], 1)
        game.map([[1]], column=2, row=3, solid=False)
        self.assertEqual(game.collision_data()[3 * 32 + 2], 0)

    def test_actor_from_another_game_is_rejected(self):
        first, second = Game(), Game()
        actor = first.actor(tile=1)
        with self.assertRaises(ValueError):
            second.every_frame(Hide(actor))


if __name__ == "__main__":
    unittest.main()
