"""Controller factories must generate usable, predictable gameplay rules."""

import unittest

from py3nes import Add, Button, ButtonDown, Game, If, Set
from tests.runtime_harness import HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME, RuntimeHarness


def number(run, actor, field):
    return (run.variable(getattr(actor, field).name, signed=field.startswith("v"))
            + run.variable(getattr(actor, field + "_fraction").name) / 256)


class ControlsDescriptionTests(unittest.TestCase):
    def test_buttons_and_helper_settings_fail_without_registering_partial_events(self):
        for value in (0, 1, True, Button.A | Button.B):
            with self.assertRaises(ValueError):
                ButtonDown(value)
        game = Game()
        actor = game.actor(tile=1, subpixel=True)
        for options in ({"speed": 0}, {"friction": 0}, {"jump_speed": 9},
                        {"left": Button.A}, {"enabled": "yes"}, {"jump_cut": -1},
                        {"animate": 1}, {"speed": 0.1}):
            with self.subTest(options=options), self.assertRaises((ValueError, TypeError)):
                game.platformer(actor, **options)
            self.assertEqual(game.events, ())
        with self.assertRaises(ValueError):
            game.platformer(Game().actor(tile=1, subpixel=True))
        with self.assertRaises(TypeError):
            game.platformer(game.byte("invalid_actor"))


@unittest.skipUnless(HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME)
class ControlsRuntimeTests(unittest.TestCase):
    def test_button_condition_composes_with_flags_and_negation(self):
        game = Game()
        count = game.byte("count")
        enabled = game.flag("enabled", True)
        game.every_frame(If(enabled & ButtonDown(Button.A) & ~ButtonDown(Button.B), Add(count, 1)))
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            run.frame(Button.A | Button.B)
            run.frame(Button.B)
            run.frame()
            self.assertEqual(run.variable("count"), 1)

    def test_acceleration_release_friction_and_opposite_directions(self):
        game = Game()
        actor = game.actor(frames=[1, 2], x=80, y=80, subpixel=True)
        game.platformer(actor, speed=2, acceleration=0.5, friction=0.25)
        with RuntimeHarness(game) as run:
            for expected in (0.5, 1, 1.5, 2):
                run.frame(Button.RIGHT)
                self.assertEqual(number(run, actor, "vx"), expected)
            self.assertEqual(number(run, actor, "x"), 85)
            for expected in (1.75, 1.5, 1.25, 1, 0.75, 0.5, 0.25, 0):
                run.frame()
                self.assertEqual(number(run, actor, "vx"), expected)
            run.frame(Button.LEFT | Button.RIGHT)
            self.assertEqual(number(run, actor, "vx"), 0)
            self.assertEqual(run.variable(actor.animation_enabled.name), 0)
            run.frame(Button.LEFT)
            self.assertEqual(number(run, actor, "vx"), -0.5)

    def test_holding_jump_reaches_higher_than_tapping_and_does_not_autorepeat(self):
        heights = []
        for hold in (1, 60):
            game = Game()
            game.map([[1] * 32], row=25, solid=True)
            actor = game.actor(tile=1, x=80, y=192, gravity=0.25)
            game.platformer(actor, jump_speed=5.5, jump_cut=2)
            with RuntimeHarness(game) as run:
                highest = 192
                for frame in range(70):
                    run.frame(Button.A if frame < hold else 0)
                    highest = min(highest, number(run, actor, "y"))
                heights.append(highest)
                self.assertEqual(number(run, actor, "y"), 192)
                self.assertEqual(run.variable(actor.grounded.name), 1)
        self.assertGreater(heights[0], heights[1] + 20)

    def test_disabling_controls_cancels_buffered_jump_and_horizontal_motion(self):
        game = Game()
        enabled = game.flag("enabled", True)
        game.map([[1] * 32], row=15, solid=True)
        actor = game.actor(tile=1, x=80, y=108, gravity=0.25)
        game.platformer(actor, enabled=enabled, buffer_frames=8)
        game.bind_pressed(Button.B, Set(enabled, False))
        with RuntimeHarness(game) as run:
            run.frame(Button.A | Button.RIGHT)
            self.assertGreater(run.variable(actor.jump_buffer.name), 0)
            run.frame(Button.B)
            for _ in range(12):
                run.frame(Button.A | Button.RIGHT)
            self.assertEqual(number(run, actor, "vx"), 0)
            self.assertEqual(number(run, actor, "y"), 112)
            self.assertEqual(run.variable(actor.jump_buffer.name), 0)

    def test_animation_can_be_managed_independently_of_the_controls(self):
        game = Game()
        enabled = game.flag("enabled")
        actor = game.actor(frames=[1, 2], x=80, y=80, subpixel=True, frame_ticks=1)
        game.platformer(actor, enabled=enabled, animate=False)
        with RuntimeHarness(game) as run:
            run.frame()
            self.assertEqual(run.variable(actor.animation_enabled.name), 1)
            self.assertEqual(run.variable(actor.frame.name), 1)


if __name__ == "__main__":
    unittest.main()
