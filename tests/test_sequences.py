"""Sequences execute explicit commands over ticks, including modal ownership."""

import unittest

from py3nes import Add, Button, Game, If, Set, Velocity, WriteText
from py3nes.physics import Freeze
from py3nes.sequences import ButtonPressed, Do, Wait, WaitForButton, WaitUntil
from tests.runtime_harness import HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME, RuntimeHarness


class SequenceDescriptionTests(unittest.TestCase):
    def test_rejects_invalid_steps_buttons_waits_and_actions(self):
        for value in (0, 256, -1, True, 1.5):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                Wait(value)
        for value in (0, 1, True, Button.A | Button.B):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ButtonPressed(value)
        for operation in (lambda: Do(lambda: None), lambda: WaitUntil("yes"),
                          lambda: Game().sequence("test"),
                          lambda: Game().sequence("test", lambda: None),
                          lambda: Game().sequence("test", *([Wait(1)] * 256))):
            with self.assertRaises((ValueError, TypeError)):
                operation()

    def test_failed_registration_rolls_back_room_names_variables_and_events(self):
        game = Game()
        room = game.room("hall")
        room.byte("sequence_scene_countdown")
        before = (room.variables, room.events, set(room._user_names))
        with self.assertRaises(ValueError):
            room.sequence("scene", Wait(1))
        self.assertEqual((room.variables, room.events, room._user_names), before)
        room.flag("sequence_scene_active")
        other = Game().byte("foreign")
        with self.assertRaises(ValueError):
            room.sequence("foreign", Do(Set(other, 1)))
        self.assertEqual(len(room.variables), 2)

    def test_freezing_requires_registered_freezable_actors(self):
        game = Game()
        actor = game.actor(tile=1)
        for actors in ((actor,), (Game().actor(tile=1, freezable=True),), (1,)):
            with self.assertRaises((ValueError, TypeError)):
                game.sequence("scene", Wait(1), freeze=actors)
        self.assertEqual(game.events, ())

    def test_exclusive_steps_do_not_sum_their_display_budgets(self):
        game = Game()
        scene = game.sequence("long", *(Do(WriteText("PAGE", column=0, row=0, width=32))
                                        for _ in range(40)))
        game.bind_pressed(Button.A, scene.start())
        self.assertIn("v_sequence_long_step", game.to_assembly())
        bad = Game()
        bad.sequence("oversized", Do(WriteText("", 0, 0, 32), WriteText("", 0, 1, 32),
                                     WriteText("", 0, 2, 1)))
        with self.assertRaisesRegex(ValueError, "65 background tile writes"):
            bad.to_assembly()


@unittest.skipUnless(HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME)
class SequenceRuntimeTests(unittest.TestCase):
    def test_actions_wait_exact_tick_counts_finish_once_and_restart(self):
        game = Game()
        count, finished = game.byte("count"), game.byte("finished")
        scene = game.sequence("scene", Add(count, 1), Wait(3), Add(count, 10),
                              on_start=(Add(count, 2),), on_finish=(Add(finished, 1),))
        game.bind_pressed(Button.A, scene.start())
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            self.assertEqual(run.variable(count.name), 2)
            run.frame()
            self.assertEqual(run.variable(count.name), 3)
            for _ in range(3):
                run.frame()
                self.assertEqual(run.variable(count.name), 3)
            run.frame()
            self.assertEqual(run.variable(count.name), 13)
            self.assertEqual(run.variable(scene.active.name), 0)
            self.assertEqual(run.variable(finished.name), 1)
            run.frame()
            run.frame(Button.A)
            self.assertEqual(run.variable(count.name), 15)
            self.assertEqual(run.variable(finished.name), 1)

    def test_wait_one_and_wait_255_have_no_extra_initialization_tick(self):
        for ticks in (1, 2, 255):
            with self.subTest(ticks=ticks):
                game = Game()
                done = game.flag("done")
                scene = game.sequence("scene", Wait(ticks), Set(done, True))
                game.bind_pressed(Button.A, scene.start())
                with RuntimeHarness(game) as run:
                    run.frame(Button.A)
                    for _ in range(ticks):
                        run.frame()
                        self.assertEqual(run.variable(done.name), 0)
                    run.frame()
                    self.assertEqual(run.variable(done.name), 1)

    def test_wait_condition_and_fresh_button_do_not_accept_held_opening_press(self):
        game = Game()
        ready, done = game.flag("ready"), game.flag("done")
        scene = game.sequence("scene", WaitUntil(ready), WaitForButton(Button.A), Set(done, True))
        game.bind_pressed(Button.A, scene.start())
        game.bind_pressed(Button.B, Set(ready, True))
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            run.frame(Button.A)
            self.assertEqual(run.variable(scene.step.name), 0)
            run.frame(Button.A | Button.B)
            run.frame(Button.A)
            run.frame(Button.A)
            self.assertEqual(run.variable(scene.step.name), 1)
            run.frame()
            run.frame(Button.A)
            self.assertEqual(run.variable(scene.step.name), 2)
            self.assertEqual(run.variable(done.name), 0)
            run.frame()
            self.assertEqual(run.variable(done.name), 1)

    def test_start_while_active_ignored_and_cancel_finishes_once(self):
        game = Game()
        starts, ends = game.byte("starts"), game.byte("ends")
        scene = game.sequence("scene", Wait(100), on_start=(Add(starts, 1),),
                              on_finish=(Add(ends, 1),))
        game.bind_pressed(Button.A, scene.start())
        game.bind_pressed(Button.B, scene.cancel())
        with RuntimeHarness(game) as run:
            for buttons in (Button.A, 0, Button.A, 0, Button.B, 0, Button.B):
                run.frame(buttons)
            self.assertEqual(run.variable(starts.name), 1)
            self.assertEqual(run.variable(ends.name), 1)
            self.assertEqual(run.variable(scene.active.name), 0)

    def test_frozen_actor_pauses_physics_then_resumes_velocity(self):
        game = Game()
        actor = game.actor(tile=1, x=80, y=80, gravity=0.25, freezable=True)
        game.every_frame(If(~actor.frozen, Velocity(actor, vx=1)))
        scene = game.sequence("scene", Wait(3), freeze=(actor,))
        game.bind_pressed(Button.A, scene.start())
        game.bind_pressed(Button.B, scene.cancel())
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            held = (run.variable(actor.x.name), run.variable(actor.y.name))
            for _ in range(2):
                run.frame()
                self.assertEqual((run.variable(actor.x.name), run.variable(actor.y.name)), held)
                self.assertEqual(run.variable(actor.frozen.name), 1)
            run.frame()
            self.assertEqual(run.variable(actor.frozen.name), 0)
            self.assertGreater(run.variable(actor.x.name), held[0])

    def test_modal_ownership_serializes_and_does_not_unfreeze_existing_owner(self):
        game = Game()
        actor = game.actor(tile=1, x=80, y=80, freezable=True)
        first = game.sequence("first", Wait(20), freeze=(actor,))
        second = game.sequence("second", Wait(20), freeze=(actor,))
        game.bind_pressed(Button.A, first.start())
        game.bind_pressed(Button.B, second.start(), second.cancel())
        game.bind_pressed(Button.SELECT, first.cancel())
        game.bind_pressed(Button.START, Freeze(actor))
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            run.frame(Button.B)
            self.assertEqual(run.variable(first.active.name), 1)
            self.assertEqual(run.variable(second.active.name), 0)
            self.assertEqual(run.variable(actor.frozen.name), 1)
            run.frame(Button.SELECT)
            self.assertEqual(run.variable(actor.frozen.name), 0)
            run.frame(Button.START)
            run.frame(Button.A)
            self.assertEqual(run.variable(first.active.name), 0)
            self.assertEqual(run.variable(actor.frozen.name), 1)

    def test_room_entry_resets_sequence_and_releases_modal_state(self):
        from py3nes import ChangeRoom
        game = Game()
        hall, other = game.room("hall"), game.room("other")
        actor = hall.actor(tile=1, x=80, y=80, freezable=True)
        scene = hall.sequence("scene", Wait(100), freeze=(actor,))
        hall.bind_pressed(Button.A, scene.start())
        hall.bind_pressed(Button.B, ChangeRoom(other))
        other.bind_pressed(Button.B, ChangeRoom(hall))
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            self.assertEqual(run.variable(scene.active.name), 1)
            run.frame(Button.B)
            run.frame()
            run.frame(Button.B)
            self.assertEqual(run.variable(scene.active.name), 0)
            self.assertEqual(run.variable(actor.frozen.name), 0)
            self.assertEqual(run.variable(hall._sequence_modal_busy.name), 0)
            run.frame(Button.A)
            self.assertEqual(run.variable(scene.active.name), 1)


if __name__ == "__main__":
    unittest.main()
