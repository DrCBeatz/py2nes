"""Room descriptions and real 6502 transitions, persistence, and display loads."""

import unittest

from py3nes import (Add, Animate, Button, ChangeRoom, Game, Hide, If, Set,
                    Teleport, Velocity, WriteText)
from py3nes.assets import encode_text
from tests.runtime_harness import HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME, RuntimeHarness


class RoomDescriptionTests(unittest.TestCase):
    def test_room_background_collision_and_shared_assets_are_independent(self):
        game = Game()
        first, second = game.room("first"), game.room("second")
        tile = first.tile(["11111111"] * 8)
        self.assertEqual(second.tile(["11111111"] * 8), tile)
        first.map([[tile]], column=2, row=3, solid=True)
        second.text("B", column=2, row=3)
        self.assertEqual(first.nametable()[98], tile)
        self.assertEqual(second.nametable()[98], encode_text("B")[0])
        self.assertEqual(first.collision_data()[98], 1)
        self.assertEqual(second.collision_data()[98], 0)
        self.assertEqual(first.chr_data(), second.chr_data())

    def test_duplicate_room_spawn_and_variable_names_are_rejected(self):
        game = Game()
        first, second = game.room("first"), game.room("second")
        with self.assertRaises(ValueError):
            game.room("first")
        first.byte("timer")
        second.byte("timer")  # Same local name is useful in different rooms.
        with self.assertRaises(ValueError):
            first.flag("timer")
        actor = first.actor(tile=1)
        first.spawn("door", actor, x=16, y=40)
        with self.assertRaises(ValueError):
            first.spawn("door", actor, x=24, y=40)

    def test_only_persistent_variables_can_be_used_outside_their_room(self):
        game = Game()
        first, second = game.room("first"), game.room("second")
        shared = game.byte("inventory")
        permanent = first.flag("taken", persistent=True)
        temporary = first.byte("timer")
        actor = first.actor(tile=1)
        second.every_frame(Add(shared, 1), Set(permanent, False))
        for action in (Set(temporary, 0), If(temporary.eq(0), Add(shared, 1)), Hide(actor)):
            with self.subTest(action=repr(action)), self.assertRaises(ValueError):
                second.every_frame(action)

    def test_foreign_destinations_and_spawns_are_rejected(self):
        game, other = Game(), Game()
        room, foreign = game.room("room"), other.room("foreign")
        with self.assertRaises(ValueError):
            room.every_frame(ChangeRoom(foreign))
        with self.assertRaises(ValueError):
            game.start(foreign)
        foreign_actor = foreign.actor(tile=1)
        with self.assertRaises(ValueError):
            room.spawn("foreign", foreign_actor, x=16, y=40)

    def test_spawn_forward_reference_resolves_at_build_and_unknown_is_rejected(self):
        game = Game()
        first, second = game.room("first"), game.room("second")
        first.bind_pressed(Button.A, ChangeRoom(second, spawn="door"))
        with self.assertRaises(ValueError):
            game.to_assembly()
        actor = second.actor(tile=1)
        second.spawn("door", actor, x=64, y=40)
        self.assertIn("reset:", game.to_assembly())
        game.start(first, spawn="missing")
        with self.assertRaises(ValueError):
            game.to_assembly()

    def test_on_enter_rejects_nested_transitions(self):
        game = Game()
        first, second = game.room("first"), game.room("second")
        enabled = game.flag("enabled")
        for action in (ChangeRoom(second), If(enabled, ChangeRoom(second)),
                       If(enabled, Set(enabled, False), otherwise=(ChangeRoom(second),))):
            with self.subTest(action=repr(action)), self.assertRaises(ValueError):
                first.on_enter(action)

    def test_spawn_coordinates_respect_actor_bounds(self):
        game = Game()
        room = game.room("room")
        actor = room.actor(tile=game.metasprite([[1, 1], [1, 1]]))
        for x, y in ((241, 40), (20, 225), (-1, 40), (20, 0)):
            with self.subTest(x=x, y=y), self.assertRaises((TypeError, ValueError)):
                room.spawn(f"invalid_{x}_{y}", actor, x=x, y=y)


@unittest.skipUnless(HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME)
class RoomRuntimeTests(unittest.TestCase):
    def assert_text(self, runtime, text, column=0, row=0):
        actual = tuple(runtime.bus.ppu_read(0x2000 + row * 32 + column + offset)
                       for offset in range(len(text)))
        self.assertEqual(actual, encode_text(text))

    def test_transition_loads_background_spawn_and_hides_old_oam(self):
        game = Game()
        first, second = game.room("first"), game.room("second")
        first.text("FIRST")
        second.text("SECOND")
        source = first.actor(tile=1, x=40, y=40)
        first.actor(tile=2, x=60, y=40)
        first.sprite(tile=3, x=80, y=40)
        target = second.actor(tile=4, x=80, y=80)
        second.spawn("door", target, x=120, y=112)
        saw_spawn = game.byte("saw_spawn")
        second.on_enter(Set(saw_spawn, target.x), WriteText("ENTERED", 2, 2))
        first.bind_pressed(Button.A, ChangeRoom(second, spawn="door"))
        with RuntimeHarness(game) as run:
            self.assertEqual(run.rom[:6], b"NES\x1a\x02\x01")
            self.assertEqual(len(run.rom), 16 + 32768 + 8192)
            self.assertEqual(run.read("rt_room"), first.index)
            self.assert_text(run, "FIRST")
            self.assertEqual(run.sprite_data(source.oam_start)[3], 40)
            run.frame(Button.A)
            self.assertEqual(run.read("rt_room"), second.index)
            self.assert_text(run, "SECOND")
            self.assert_text(run, "ENTERED", 2, 2)
            self.assertEqual(run.variable(saw_spawn.name), 120)
            self.assertEqual((run.variable(target.x.name), run.variable(target.y.name)), (120, 112))
            self.assertEqual(run.sprite_data(target.oam_start), (111, 4, 0, 120))
            self.assertTrue(all(run.sprite_data(index)[0] == 255 for index in range(1, 64)))
            run.interrupt()
            self.assertEqual(bytes(run.bus.oam), bytes(run.bus.ram[0x200:0x300]))
            self.assertEqual(run.bus.ppumask & 0x18, 0x18)

    def test_first_transition_aborts_remaining_actions_rules_and_old_display_queue(self):
        game = Game()
        first, second, third = (game.room(name) for name in ("first", "second", "third"))
        marker = game.byte("marker")
        first.text("FIRST")
        second.text("SECOND")
        first.every_frame(WriteText("STALE!", 0, 0), Add(marker, 1),
                          If(marker.ge(1), If(marker.lt(10), ChangeRoom(second), Set(marker, 90)),
                             Set(marker, 91)), Set(marker, 92))
        first.every_frame(Set(marker, 93), ChangeRoom(third))
        first.after_physics(Set(marker, 94))
        second.every_frame(Add(marker, 2))
        with RuntimeHarness(game) as run:
            stack = run.cpu.sp
            run.frame()
            self.assertEqual(run.read("rt_room"), second.index)
            self.assertEqual(run.variable(marker.name), 1)
            self.assertEqual(run.cpu.sp, stack)
            self.assert_text(run, "SECOND")
            run.frame()
            self.assertEqual(run.variable(marker.name), 3)
            self.assert_text(run, "SECOND")

    def test_local_reset_persistent_inventory_and_collected_item_on_reentry(self):
        game = Game()
        first, second = game.room("garden"), game.room("hall")
        inventory = game.byte("inventory", 2)
        visits = game.byte("visits")
        temporary = first.byte("timer", 3)
        taken = first.flag("taken", persistent=True)
        actor = first.actor(frames=[1, 2], x=40, y=40, frame_ticks=9)
        key = first.actor(tile=3, x=80, y=40, collides=False)
        first.text("KEY PRESENT", column=2, row=2)
        first.on_enter(Add(visits, 1), If(taken, Hide(key), WriteText("KEY IS GONE", 2, 2)))
        first.bind_pressed(Button.A, Set(temporary, 77), Add(inventory, 1), Set(taken, True),
                           Teleport(actor, 100, 80), Velocity(actor, vx=3, vy=2),
                           Set(actor.frame, 1), Animate(actor, False), Hide(actor), Hide(key))
        first.bind_pressed(Button.B, ChangeRoom(second))
        second.bind_pressed(Button.B, ChangeRoom(first))
        with RuntimeHarness(game) as run:
            self.assertEqual(run.variable(visits.name), 1)
            run.frame(Button.A)
            self.assertEqual(run.variable(temporary.name), 77)
            run.frame(Button.B)
            self.assertEqual(run.read("rt_room"), second.index)
            run.frame(Button.B)
            self.assertEqual(run.read("rt_room"), second.index,
                             "holding the transition button must not create another pressed edge")
            run.frame()
            run.frame(Button.B)
            self.assertEqual(run.read("rt_room"), first.index)
            self.assertEqual(run.variable(visits.name), 2)
            self.assertEqual(run.variable(temporary.name), 3)
            self.assertEqual(run.variable(inventory.name), 3)
            self.assertEqual(run.variable(taken.name), 1)
            for variable, expected in ((actor.x, 40), (actor.y, 40), (actor.vx, 0),
                                       (actor.vy, 0), (actor.frame, 0), (actor.frame_timer, 0),
                                       (actor.visible, 1), (actor.animation_enabled, 1), (key.visible, 0)):
                self.assertEqual(run.variable(variable.name), expected, variable.name)
            self.assert_text(run, "KEY IS GONE", 2, 2)

    def test_room_collision_and_physics_follow_active_room_only(self):
        game = Game()
        first, second = game.room("low_floor"), game.room("high_floor")
        first.map([[1] * 32], row=25, solid=True)
        second.map([[2] * 32], row=15, solid=True)
        source = first.actor(tile=1, x=40, y=100, gravity=1, max_fall_speed=8)
        target = second.actor(tile=1, x=40, y=100, gravity=1, max_fall_speed=8)
        source_ticks = game.byte("source_ticks")
        first.every_frame(Add(source_ticks, 1))
        first.after_physics(If(source.grounded, ChangeRoom(second)))
        with RuntimeHarness(game) as run:
            for _ in range(30):
                run.frame()
                if run.read("rt_room") == second.index:
                    break
            else:
                self.fail("source actor never reached its floor and exited")
            self.assertEqual(run.variable(source.y.name), 192)
            ticks = run.variable(source_ticks.name)
            for _ in range(15):
                run.frame()
            self.assertEqual(run.variable(target.y.name), 112)
            self.assertEqual(run.variable(target.grounded.name), 1)
            self.assertEqual(run.variable(source.y.name), 192)
            self.assertEqual(run.variable(source_ticks.name), ticks)

    def test_explicit_same_room_restart_and_nonfirst_start_spawn(self):
        game = Game()
        game.room("unused")
        room = game.room("start_here")
        permanent = room.byte("permanent", 8, persistent=True)
        local = room.byte("local", 3)
        actor = room.actor(tile=1, x=40, y=40)
        room.spawn("start", actor, x=80, y=80)
        room.on_enter(Add(permanent, 1))
        room.bind_pressed(Button.A, Set(local, 99), Teleport(actor, 100, 100))
        room.bind_pressed(Button.START, Set(permanent, 0), ChangeRoom(room, spawn="start"))
        game.start(room, spawn="start")
        with RuntimeHarness(game) as run:
            self.assertEqual(run.read("rt_room"), room.index)
            self.assertEqual(run.variable(actor.x.name), 80)
            self.assertEqual(run.variable(permanent.name), 9)
            run.frame(Button.A)
            self.assertEqual(run.variable(local.name), 99)
            run.frame(Button.START)
            self.assertEqual(run.variable(local.name), 3)
            self.assertEqual(run.variable(permanent.name), 1)
            self.assertEqual((run.variable(actor.x.name), run.variable(actor.y.name)), (80, 80))


if __name__ == "__main__":
    unittest.main()
