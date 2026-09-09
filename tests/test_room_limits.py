"""Cross-room scheduling and resource budgets at the compiler boundary."""

import unittest

from py3nes import Add, Button, ChangeRoom, Game, WriteText
from tests.runtime_harness import HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME, RuntimeHarness


class RoomBudgetTests(unittest.TestCase):
    def test_display_budget_counts_only_one_active_room_and_entry_separately(self):
        game = Game()
        for name in ("first", "second", "third"):
            room = game.room(name)
            room.every_frame(WriteText("A" * 32, 0, 0), WriteText("B" * 32, 0, 1))
            room.on_enter(WriteText("C" * 32, 0, 0), WriteText("D" * 32, 0, 1))
        game.to_assembly()  # Each of six independent batches fits 64 writes.
        game.every_frame(WriteText("X", 0, 2))
        with self.assertRaisesRegex(ValueError, "65.*maximum is 64"):
            game.to_assembly()

    def test_room_entry_budget_is_checked_even_if_room_is_never_entered(self):
        game = Game()
        game.room("start")
        room = game.room("oversized")
        room.on_enter(WriteText("A" * 32, 0, 0), WriteText("B" * 32, 0, 1),
                      WriteText("C", 0, 2))
        with self.assertRaisesRegex(ValueError, "65.*maximum is 64"):
            game.to_assembly()


@unittest.skipUnless(HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME)
class GlobalRoomEventTests(unittest.TestCase):
    def test_global_transition_aborts_room_dispatch_and_post_physics(self):
        game = Game()
        first, second = game.room("first"), game.room("second")
        count = game.byte("count")
        game.bind_pressed(Button.A, Add(count, 1), ChangeRoom(second), Add(count, 2))
        first.every_frame(Add(count, 4))
        second.every_frame(Add(count, 8))
        game.after_physics(Add(count, 16))
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            self.assertEqual(run.read("rt_room"), second.index)
            self.assertEqual(run.variable("count"), 1)
            run.frame(Button.A)
            self.assertEqual(run.variable("count"), 25)

    def test_legacy_sprite_only_room_restarts_its_oam(self):
        from py3nes import Move

        game = Game()
        first, second = game.room("first"), game.room("second")
        sprite = first.sprite(tile=1, x=10, y=20)
        second.sprite(tile=2, x=40, y=50)
        first.bind_pressed(Button.A, Move(sprite, dx=10))
        first.bind_pressed(Button.B, ChangeRoom(second))
        second.bind_pressed(Button.A, ChangeRoom(first))
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            self.assertEqual(run.sprite_data(), (20, 1, 0, 20))
            run.frame(Button.B)
            self.assertEqual(run.sprite_data(), (50, 2, 0, 40))
            run.frame(Button.A)
            self.assertEqual(run.sprite_data(), (20, 1, 0, 10))
