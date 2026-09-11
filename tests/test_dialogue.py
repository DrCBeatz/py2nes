"""Paged dialogue uses fresh input, bounded uploads, and owned modal state."""

import unittest

from py3nes import Add, Button, Game
from py3nes.assets import encode_text
from py3nes.dialogue import Choice
from tests.runtime_harness import HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME, RuntimeHarness


def upload(run):
    while run.read("frame_ready"):
        run.interrupt()


def line(run, column, row, width):
    upload(run)
    start = 0x2000 + row * 32 + column
    return tuple(run.bus.ppu_read(start + offset) for offset in range(width))


class DialogueDescriptionTests(unittest.TestCase):
    def test_reserves_only_the_requested_background_rectangle(self):
        game = Game()
        game.map([[1] * 32 for _ in range(30)], solid=True)
        talk = game.dialogue("talk", "HELLO", column=2, row=2, width=8, height=2)
        table = game.nametable()
        self.assertEqual(tuple(table[66:74]), (0,) * 8)
        self.assertEqual(table[65], 1)
        self.assertEqual(table[74], 1)
        self.assertEqual(game.collision_data()[66], 1)
        self.assertIsNone(talk.selection)

    def test_validates_pages_choices_and_callbacks_without_partial_registration(self):
        invalid = (
            {"pages": []}, {"pages": [123]}, {"pages": ["TOO\nMANY\nLINES"], "height": 2},
            {"pages": ["HI"], "choices": [Choice("ONE")]},
            {"pages": ["HI"], "choices": ["YES", "NO"]},
            {"pages": ["HI"], "choices": [Choice("YES"), Choice("NO")], "button": Button.UP},
            {"pages": ["HI"], "choices": [Choice("YES"), Choice("NO")], "height": 2},
            {"pages": ["HI"], "choices": [Choice("TOO LONG"), Choice("NO")], "width": 5},
            {"pages": ["HI"], "on_finish": (lambda: None,)},
        )
        for options in invalid:
            with self.subTest(options=options):
                game = Game()
                with self.assertRaises((ValueError, TypeError)):
                    game.dialogue("talk", **options)
                self.assertEqual(game.variables, ())
                self.assertEqual(game.maps, ())
                self.assertEqual(game.events, ())
        for label in ("", "A\nB", 1):
            with self.assertRaises((ValueError, TypeError)):
                Choice(label)

    def test_duplicate_name_rolls_back_selection_and_reserved_map(self):
        game = Game()
        room = game.room("hall")
        room.sequence("talk", Add(room.byte("value"), 1))
        before = (len(room.variables), len(room.events), len(room.maps), set(room._user_names))
        with self.assertRaises(ValueError):
            room.dialogue("talk", "HI", choices=(Choice("YES"), Choice("NO")))
        self.assertEqual((len(room.variables), len(room.events), len(room.maps), room._user_names), before)

    def test_modal_dialogues_share_one_exclusive_display_budget(self):
        game = Game()
        for name in ("first", "second", "third", "fourth"):
            game.dialogue(name, "HELLO", width=28)
        self.assertEqual(len(game.events), 1)
        self.assertIn("v_sequence_fourth_step", game.to_assembly())


@unittest.skipUnless(HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME)
class DialogueRuntimeTests(unittest.TestCase):
    def test_pages_require_fresh_press_and_clear_before_finishing(self):
        game = Game()
        done = game.byte("done")
        talk = game.dialogue("talk", ["HELLO", "BYE"], column=2, row=2, width=8, height=2,
                             on_finish=(Add(done, 1),))
        game.bind_pressed(Button.A, talk.start())
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            for _ in range(5):
                run.frame(Button.A)
            self.assertEqual(line(run, 2, 2, 8), encode_text("HELLO") + (0,) * 3)
            self.assertEqual(run.variable(talk.active.name), 1)
            run.frame()
            run.frame(Button.A)
            run.frame(Button.A)
            run.frame(Button.A)
            self.assertEqual(line(run, 2, 2, 8), encode_text("BYE") + (0,) * 5)
            for _ in range(2):
                run.frame(Button.A)
            self.assertEqual(run.variable(done.name), 0)
            run.frame()
            run.frame(Button.A)
            for _ in range(2):
                run.frame()
                self.assertEqual(run.variable(done.name), 0)
            self.assertEqual(line(run, 2, 2, 8), (0,) * 8)
            run.frame()
            self.assertEqual(run.variable(done.name), 1)
            self.assertEqual(run.variable(talk.active.name), 0)

    def test_choices_wrap_move_cursor_once_per_press_and_run_selected_actions_once(self):
        game = Game()
        answer, done = game.byte("answer"), game.byte("done")
        talk = game.dialogue("talk", "PICK", column=2, row=2, width=8, height=3,
                             choices=(Choice("YES", Add(answer, 1)), Choice("NO", Add(answer, 2))),
                             on_finish=(Add(done, 1),))
        game.bind_pressed(Button.A, talk.start())
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            for _ in range(3):
                run.frame(Button.A)
            self.assertEqual(line(run, 2, 3, 5), encode_text("> YES"))
            run.frame(Button.UP)
            self.assertEqual(run.variable(talk.selection.name), 1)
            self.assertEqual(line(run, 2, 3, 1), encode_text(" "))
            self.assertEqual(line(run, 2, 4, 4), encode_text("> NO"))
            run.frame(Button.UP)
            self.assertEqual(run.variable(talk.selection.name), 1)
            run.frame(Button.DOWN)
            self.assertEqual(run.variable(talk.selection.name), 0)
            run.frame()
            run.frame(Button.DOWN)
            run.frame(Button.A)
            self.assertEqual(run.variable(answer.name), 2)
            for _ in range(6):
                run.frame(Button.A)
            self.assertEqual(run.variable(answer.name), 2)
            self.assertEqual(run.variable(done.name), 1)
            self.assertEqual(run.variable(talk.active.name), 0)
            run.frame()
            run.frame(Button.A)
            self.assertEqual(run.variable(talk.selection.name), 0)

    def test_cancel_clears_and_keeps_actor_frozen_until_finish(self):
        game = Game()
        actor = game.actor(tile=1, x=80, y=80, gravity=0.25, freezable=True)
        done, answer = game.byte("done"), game.byte("answer")
        talk = game.dialogue("talk", "PICK", column=2, row=2, width=8, height=3,
                             choices=(Choice("YES", Add(answer, 1)), Choice("NO", Add(answer, 2))),
                             on_finish=(Add(done, 1),), freeze=(actor,))
        game.bind_pressed(Button.A, talk.start())
        game.bind_pressed(Button.B, talk.cancel())
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            for _ in range(3):
                run.frame()
            run.frame(Button.B)
            for _ in range(3):
                run.frame()
                self.assertEqual(run.variable(actor.frozen.name), 1)
            self.assertEqual(line(run, 2, 2, 8), (0,) * 8)
            run.frame()
            self.assertEqual(run.variable(actor.frozen.name), 0)
            self.assertEqual(run.variable(done.name), 1)
            self.assertEqual(run.variable(answer.name), 0)
            run.frame(Button.B)
            self.assertEqual(run.variable(done.name), 1)

    def test_dialogues_serialize_even_without_actor_freezing(self):
        game = Game()
        first = game.dialogue("first", "FIRST", column=2, row=2, width=8, height=1)
        second = game.dialogue("second", "SECOND", column=2, row=2, width=8, height=1)
        game.bind_pressed(Button.A, first.start())
        game.bind_pressed(Button.B, second.start())
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            run.frame(Button.B)
            self.assertEqual(run.variable(first.active.name), 1)
            self.assertEqual(run.variable(second.active.name), 0)
            self.assertEqual(line(run, 2, 2, 8), encode_text("FIRST") + (0,) * 3)


if __name__ == "__main__":
    unittest.main()
