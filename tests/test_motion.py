"""Execute assembled fixed-point movement, buffering and jump controls on a 6502."""

import unittest

from py3nes import Game
from py3nes.ir import If, Set
from py3nes.model import Button
from py3nes.physics import ApproachVelocity, CutJump, Jump, Teleport, Velocity
from py3nes.rooms import ChangeRoom
from tests.runtime_harness import HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME, RuntimeHarness


def value(run, actor, key):
    """Decode the public integer byte and its unsigned fractional companion."""
    return (run.variable(getattr(actor, key).name, signed=key in ("vx", "vy"))
            + run.variable(getattr(actor, key + "_fraction").name) / 256)


class MotionModelTests(unittest.TestCase):
    def test_fractional_parameters_enable_fixed_point_without_changing_legacy_actors(self):
        game = Game()
        old = game.actor(tile=1)
        new = game.actor(tile=1, gravity=0.25, max_fall_speed=0.5)
        self.assertFalse(old.subpixel)
        self.assertEqual(len(old.variables), 9)
        self.assertTrue(new.subpixel)
        self.assertEqual(len(new.variables), 18)
        self.assertEqual(new.vx.kind, "i8")
        self.assertEqual(new.vx_fraction.kind, "u8")
        self.assertEqual(new.air_frames.initial, 255)

    def test_fixed_literals_have_explicit_range_and_precision(self):
        game = Game()
        for bad in (True, 0.1, float("nan"), float("inf"), -0.25, 4.25):
            with self.subTest(gravity=bad), self.assertRaises((ValueError, TypeError)):
                game.actor(tile=1, gravity=bad)
        actor = game.actor(tile=1, subpixel=True)
        for bad in (True, 8.25, -8.25, 0.1, float("nan"), 10 ** 1000):
            with self.subTest(velocity=bad), self.assertRaises((ValueError, TypeError)):
                Velocity(actor, vx=bad)
        Velocity(actor, vx=1 / 256, vy=-8)
        Velocity(actor, vy=8)
        for bad in (0, 0.1, 8.25, True):
            with self.subTest(acceleration=bad), self.assertRaises((ValueError, TypeError)):
                ApproachVelocity(actor, vx=2, acceleration=bad)
        with self.assertRaises(ValueError):
            ApproachVelocity(actor)

    def test_new_actions_require_subpixel_state_and_validate_jump_frames(self):
        old = Game().actor(tile=1)
        for make in (lambda: ApproachVelocity(old, vx=2), lambda: Jump(old), lambda: CutJump(old)):
            with self.assertRaises(ValueError):
                make()
        actor = Game().actor(tile=1, subpixel=True)
        for kwargs in ({"speed": 0}, {"speed": 8.25}, {"buffer_frames": 255},
                       {"coyote_frames": -1}, {"buffer_frames": True}):
            with self.assertRaises((ValueError, TypeError)):
                Jump(actor, **kwargs)
        CutJump(actor, max_rise_speed=0)
        with self.assertRaises(ValueError):
            CutJump(actor, max_rise_speed=-1)


@unittest.skipUnless(HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME)
class MotionRuntimeTests(unittest.TestCase):
    def test_fractional_horizontal_and_vertical_velocity_accumulates_exactly(self):
        for speed in (-1.5, -0.25, 1 / 256, 0.25, 1.5, 8):
            with self.subTest(speed=speed):
                game = Game()
                actor = game.actor(tile=1, x=80, y=80, subpixel=True)
                game.every_frame(Velocity(actor, vx=speed, vy=speed))
                with RuntimeHarness(game) as run:
                    for frame in range(1, 9):
                        run.frame()
                        self.assertEqual(value(run, actor, "x"), 80 + frame * speed)
                        self.assertEqual(value(run, actor, "y"), 80 + frame * speed)
                        self.assertEqual(value(run, actor, "vx"), speed)
                        self.assertEqual(value(run, actor, "vy"), speed)
                        self.assertEqual(run.sprite_data()[3], int(80 + frame * speed))

    def test_fractional_gravity_accumulates_and_respects_fractional_terminal_speed(self):
        game = Game()
        actor = game.actor(tile=1, x=40, y=40, gravity=0.25, max_fall_speed=1.5)
        with RuntimeHarness(game) as run:
            position = 40
            for frame in range(1, 13):
                speed = min(frame * 0.25, 1.5)
                position += speed
                run.frame()
                self.assertEqual(value(run, actor, "vy"), speed)
                self.assertEqual(value(run, actor, "y"), position)

    def test_terminal_speed_below_one_pixel_floats_without_stopping(self):
        game = Game()
        actor = game.actor(tile=1, x=40, y=40, gravity=0.25, max_fall_speed=0.25)
        with RuntimeHarness(game) as run:
            for _ in range(12):
                run.frame()
            self.assertEqual(value(run, actor, "y"), 43)
            self.assertEqual(value(run, actor, "vy"), 0.25)

    def test_floor_snaps_fraction_and_stays_grounded_at_low_gravity(self):
        game = Game()
        game.map([[1] * 32], row=15, solid=True)
        actor = game.actor(tile=1, x=40, y=110, gravity=0.25)
        with RuntimeHarness(game) as run:
            for _ in range(20):
                run.frame()
            self.assertEqual(value(run, actor, "y"), 112)
            self.assertEqual(value(run, actor, "vy"), 0)
            self.assertEqual(run.variable(actor.grounded.name), 1)

    def test_fractional_sweeps_do_not_tunnel_and_wall_hits_reset_remainders(self):
        game = Game()
        game.map([[1] for _ in range(20)], column=10, row=2, solid=True)
        game.map([[1] * 10], row=5, solid=True)
        actor = game.actor(tile=1, x=69, y=51, subpixel=True)
        game.bind_pressed(Button.RIGHT, Velocity(actor, vx=7.5))
        game.bind_pressed(Button.A, Velocity(actor, vy=-7.5))
        with RuntimeHarness(game) as run:
            run.frame(Button.RIGHT)
            self.assertEqual(value(run, actor, "x"), 72)
            self.assertEqual(value(run, actor, "vx"), 0)
            run.frame(Button.A)
            self.assertEqual(value(run, actor, "y"), 48)
            self.assertEqual(value(run, actor, "vy"), 0)

    def test_screen_edges_do_not_wrap_with_negative_fractional_velocity(self):
        game = Game()
        actor = game.actor(tile=1, x=0, y=1, subpixel=True)
        game.every_frame(Velocity(actor, vx=-0.25, vy=-0.25))
        with RuntimeHarness(game) as run:
            for _ in range(4):
                run.frame()
                self.assertEqual(value(run, actor, "x"), 0)
                self.assertEqual(value(run, actor, "y"), 1)
                self.assertEqual(value(run, actor, "vx"), 0)
                self.assertEqual(value(run, actor, "vy"), 0)

    def test_fractional_right_edge_stops_at_screen_and_solid_wall(self):
        for x, wall in ((248, False), (72, True)):
            with self.subTest(wall=wall):
                game = Game()
                if wall:
                    game.map([[1] for _ in range(20)], column=10, row=2, solid=True)
                actor = game.actor(tile=1, x=x, y=80, subpixel=True)
                game.every_frame(Velocity(actor, vx=0.25))
                with RuntimeHarness(game) as run:
                    for _ in range(5):
                        run.frame()
                        self.assertEqual(value(run, actor, "x"), x)
                        self.assertEqual(value(run, actor, "vx"), 0)

    def test_direct_velocity_byte_assignments_saturate_full_fixed_value(self):
        game = Game()
        actor = game.actor(tile=1, x=80, y=80, subpixel=True)
        game.bind_pressed(Button.A, Velocity(actor, vx=0.5, vy=0.5),
                          Set(actor.vx, -120), Set(actor.vy, 120))
        game.bind_pressed(Button.B, Set(actor.vx, 127),
                          ApproachVelocity(actor, vx=0, acceleration=0.5))
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            self.assertEqual(value(run, actor, "vx"), -8)
            self.assertEqual(value(run, actor, "vy"), 8)
            run.frame(Button.B)
            self.assertEqual(value(run, actor, "vx"), 7.5)

    def test_acceleration_and_friction_cross_zero_and_never_overshoot(self):
        game = Game()
        actor = game.actor(tile=1, x=80, y=80, subpixel=True)
        game.bind_held(Button.RIGHT, ApproachVelocity(actor, vx=2.5, acceleration=0.375))
        game.bind_held(Button.LEFT, ApproachVelocity(actor, vx=-2.5, acceleration=0.375))
        game.bind_held(Button.B, ApproachVelocity(actor, vx=0, acceleration=0.375))
        with RuntimeHarness(game) as run:
            for frame in range(1, 9):
                run.frame(Button.RIGHT)
                self.assertEqual(value(run, actor, "vx"), min(frame * 0.375, 2.5))
            for frame in range(1, 16):
                run.frame(Button.LEFT)
                self.assertEqual(value(run, actor, "vx"), max(2.5 - frame * 0.375, -2.5))
            for frame in range(1, 9):
                run.frame(Button.B)
                self.assertEqual(value(run, actor, "vx"), min(-2.5 + frame * 0.375, 0))

    def test_whole_pixel_expression_velocity_clears_old_fraction(self):
        game = Game()
        actor = game.actor(tile=1, x=80, y=80, subpixel=True)
        speed = game.signed_byte("speed", initial=-2)
        game.bind_pressed(Button.A, Velocity(actor, vx=0.5))
        game.bind_pressed(Button.B, Velocity(actor, vx=speed))
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            self.assertEqual(value(run, actor, "vx"), 0.5)
            run.frame(Button.B)
            self.assertEqual(value(run, actor, "vx"), -2)
            self.assertEqual(value(run, actor, "x"), 78.5)

    def test_jump_from_ground_applies_fractional_speed_and_cannot_double_jump(self):
        game = Game()
        game.map([[1] * 32], row=15, solid=True)
        actor = game.actor(tile=1, x=40, y=112, gravity=0.25)
        game.bind_pressed(Button.A, Jump(actor, speed=4.5, buffer_frames=0, coyote_frames=4))
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            self.assertEqual(value(run, actor, "vy"), -4.25)
            self.assertEqual(value(run, actor, "y"), 107.75)
            self.assertEqual(run.variable(actor.grounded.name), 0)
            run.frame()
            run.frame(Button.A)
            self.assertEqual(value(run, actor, "vy"), -3.75)
            self.assertEqual(run.variable(actor.air_frames.name), 255)

    def test_buffered_press_launches_on_landing_and_expired_press_does_not(self):
        for buffer, expected in ((4, -4.5), (0, 0)):
            with self.subTest(buffer=buffer):
                game = Game()
                game.map([[1] * 32], row=15, solid=True)
                actor = game.actor(tile=1, x=40, y=107, gravity=0.25)
                game.bind_pressed(Button.A, Velocity(actor, vy=2),
                                  Jump(actor, speed=4.5, buffer_frames=buffer, coyote_frames=0))
                with RuntimeHarness(game) as run:
                    run.frame(Button.A)
                    self.assertEqual(value(run, actor, "vy"), 2.25)
                    run.frame()
                    run.frame()
                    self.assertEqual(value(run, actor, "y"), 112)
                    self.assertEqual(value(run, actor, "vy"), expected)
                    self.assertEqual(run.variable(actor.grounded.name), int(buffer == 0))

    def test_coyote_jump_works_after_leaving_edge_but_not_after_window(self):
        for wait, allowed in ((0, True), (3, False)):
            with self.subTest(wait=wait):
                game = Game()
                game.map([[1]], column=5, row=15, solid=True)
                actor = game.actor(tile=1, x=40, y=112, gravity=0.25)
                game.bind_pressed(Button.RIGHT, Velocity(actor, vx=8))
                game.bind_pressed(Button.A, Jump(actor, speed=4.5, buffer_frames=0, coyote_frames=2))
                with RuntimeHarness(game) as run:
                    run.frame(Button.RIGHT)
                    self.assertEqual(run.variable(actor.grounded.name), 0)
                    for _ in range(wait):
                        run.frame()
                    run.frame(Button.A)
                    self.assertEqual(value(run, actor, "vy") < 0, allowed)

    def test_cut_jump_limits_rising_speed_and_leaves_slow_rises_and_falls_unchanged(self):
        game = Game()
        actor = game.actor(tile=1, x=80, y=80, subpixel=True)
        game.bind_pressed(Button.A, Velocity(actor, vy=-4.5))
        game.bind_pressed(Button.B, CutJump(actor, max_rise_speed=1.5))
        game.bind_pressed(Button.DOWN, Velocity(actor, vy=2.5))
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            run.frame(Button.B)
            self.assertEqual(value(run, actor, "vy"), -1.5)
            run.frame()
            run.frame(Button.B)
            self.assertEqual(value(run, actor, "vy"), -1.5)
            run.frame(Button.DOWN)
            run.frame(Button.B)
            self.assertEqual(value(run, actor, "vy"), 2.5)

    def test_teleport_clears_fractions_velocity_and_pending_jump(self):
        game = Game()
        actor = game.actor(tile=1, x=80, y=80, subpixel=True)
        game.bind_pressed(Button.A, Velocity(actor, vx=0.5, vy=0.5), Jump(actor))
        game.bind_pressed(Button.B, Teleport(actor, 40, 40))
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            run.frame(Button.B)
            for key, expected in (("x", 40), ("y", 40), ("vx", 0), ("vy", 0)):
                self.assertEqual(value(run, actor, key), expected)
            self.assertEqual(run.variable(actor.jump_buffer.name), 0)
            self.assertEqual(run.variable(actor.air_frames.name), 255)

    def test_room_reentry_resets_all_motion_state(self):
        game = Game()
        first, second = game.room("first"), game.room("second")
        actor = first.actor(tile=1, x=40, y=40, subpixel=True)
        first.spawn("door", actor, x=80, y=80)
        first.bind_pressed(Button.A, Velocity(actor, vx=0.5, vy=0.5), Jump(actor))
        first.bind_pressed(Button.B, ChangeRoom(second))
        second.bind_pressed(Button.A, ChangeRoom(first, "door"))
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            self.assertEqual(value(run, actor, "x"), 40.5)
            run.frame(Button.B)
            run.frame(Button.A)
            self.assertEqual(value(run, actor, "x"), 80)
            self.assertEqual(value(run, actor, "y"), 80)
            self.assertEqual(value(run, actor, "vx"), 0)
            self.assertEqual(value(run, actor, "vy"), 0)
            self.assertEqual(run.variable(actor.jump_buffer.name), 0)
            self.assertEqual(run.variable(actor.air_frames.name), 255)

    def test_integer_and_fractional_actors_share_collision_without_state_leaking(self):
        game = Game()
        game.map([[1] * 32], row=15, solid=True)
        old = game.actor(tile=1, x=40, y=80, gravity=1)
        new = game.actor(tile=1, x=80, y=80, gravity=0.25)
        game.every_frame(Velocity(old, vx=1), Velocity(new, vx=0.5))
        with RuntimeHarness(game) as run:
            for _ in range(4):
                run.frame()
            self.assertEqual(run.variable(old.x.name), 44)
            self.assertEqual(run.variable(old.y.name), 90)
            self.assertEqual(value(run, new, "x"), 82)
            self.assertEqual(value(run, new, "y"), 82.5)


if __name__ == "__main__":
    unittest.main()
