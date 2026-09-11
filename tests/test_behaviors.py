"""Compile reusable gameplay rules and inspect their executed 6502 state."""

import unittest

from py3nes import (Add, AnimationClip, Button, ChangeRoom, Face, Freeze, Game, Hide,
                    If, PlayAnimation, Set, State, Transition, Velocity)
from py3nes.physics import Metasprite, SpritePart
from py3nes.assets import Tile
from tests.runtime_harness import HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME, RuntimeHarness


class BehaviorValidationTests(unittest.TestCase):
    def test_actor_animation_errors_do_not_consume_tiles_or_actor_state(self):
        game = Game()
        tile = Tile.from_rows(("12301230",) * 8)
        before = (game.chr_data(), game.variables, game.actors, game._oam_used)
        calls = (
            lambda: game.actor(animations={"idle": AnimationClip((tile, 255))}),
            lambda: game.actor(animations={"idle": AnimationClip((tile,) * 32),
                                          "walk": AnimationClip((tile,))}),
            lambda: game.actor(tile=tile, animations={"idle": AnimationClip((tile,))}),
            lambda: game.actor(frames=(tile,), animations={"idle": AnimationClip((tile,))}),
            lambda: game.actor(animations={"bad name": AnimationClip((tile,))}),
        )
        for call in calls:
            with self.assertRaises((TypeError, ValueError)):
                call()
            self.assertEqual((game.chr_data(), game.variables, game.actors, game._oam_used), before)

    def test_maximum_states_and_transition_counts_fit_ir_nesting(self):
        game = Game()
        trigger = game.flag("trigger")
        transitions = tuple(Transition(trigger, f"s{i}") for i in range(16))
        game.state_machine("many", states={f"s{i}": State(transitions=transitions) for i in range(16)})
        self.assertLessEqual(game.events[0].actions[0].depth, 32)
        self.assertIn("v_state_many", game.to_assembly())

    def test_new_actor_state_is_opt_in_and_actions_validate(self):
        game = Game()
        actor = game.actor(tile=1)
        self.assertEqual(len(actor.variables), 9)
        for action in (lambda: Freeze(actor), lambda: Face(actor, "left"),
                       lambda: PlayAnimation(actor, "idle")):
            with self.assertRaises(ValueError):
                action()
        named = game.actor(animations={"idle": AnimationClip((1,))}, freezable=True)
        self.assertEqual(len(named.variables), 12)
        self.assertEqual(named.facing, "right")
        with self.assertRaises(ValueError):
            Face(named, "up")
        with self.assertRaises(TypeError):
            Freeze(named, 1)

    def test_failed_helpers_roll_back_room_names_state_and_events(self):
        game = Game()
        room = game.room("hall")
        player = room.actor(tile=1, x=40, y=40)
        foreign = Game().flag("foreign")
        before = (len(room.variables), room.events, room.post_events, set(room._user_names))
        for action in (
            lambda: room.health(player, on_hurt=(Set(foreign, 1),)),
            lambda: room.state_machine("bad", states={"idle": State(tick=(Set(foreign, 1),))}),
            lambda: room.patrol(player, left=30, right=80, speed=0.5),
            lambda: room.timer("bad", enabled=foreign),
        ):
            with self.assertRaises((TypeError, ValueError)):
                action()
            self.assertEqual((len(room.variables), room.events, room.post_events, set(room._user_names)), before)
        self.assertIsNotNone(room.health(player))

    def test_state_and_checkpoint_reject_unknown_destinations(self):
        game = Game()
        actor = game.actor(tile=1)
        with self.assertRaises(ValueError):
            game.state_machine("bad", states={"idle": State(transitions=(Transition(True, "missing"),))})
        machine = game.state_machine("good", states={"idle": State()})
        with self.assertRaises(ValueError):
            machine.change("missing")
        with self.assertRaises(TypeError):
            State(tick=(lambda: None,))
        with self.assertRaises(ValueError):
            game.checkpoint(actor, points={"edge": (255, 1)})
        checkpoint = game.checkpoint(actor)
        with self.assertRaises(ValueError):
            checkpoint.activate("missing")


@unittest.skipUnless(HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME)
class BehaviorRuntimeTests(unittest.TestCase):
    def test_timer_saturates_pauses_and_restarts_with_full_duration(self):
        game = Game()
        enabled = game.flag("enabled", True)
        countdown = game.timer("cooldown", frames=2, enabled=enabled)
        game.bind_pressed(Button.A, countdown.start(3))
        game.bind_pressed(Button.B, Set(enabled, False))
        game.bind_pressed(Button.START, Set(enabled, True))
        with RuntimeHarness(game) as run:
            run.frame()
            self.assertEqual(run.variable(countdown.remaining.name), 1)
            run.frame()
            run.frame()
            self.assertEqual(run.variable(countdown.remaining.name), 0)
            run.frame(Button.A)
            self.assertEqual(run.variable(countdown.remaining.name), 3)
            run.frame(Button.B)
            self.assertEqual(run.variable(countdown.remaining.name), 2)
            run.frame()
            run.frame()
            self.assertEqual(run.variable(countdown.remaining.name), 2)
            run.frame(Button.START)
            run.frame()
            self.assertEqual(run.variable(countdown.remaining.name), 1)
            run.frame()
            self.assertEqual(run.variable(countdown.remaining.name), 0)

    def test_state_entry_once_first_transition_wins_and_no_double_tick(self):
        game = Game()
        enters = game.byte("enters")
        ticks = game.byte("ticks")
        enabled = game.flag("enabled", True)
        machine = game.state_machine("enemy", initial="idle", enabled=enabled, states={
            "idle": State(enter=(Add(enters, 1),), tick=(Add(ticks, 1),), transitions=(
                Transition(ticks.ge(2), "run"), Transition(ticks.ge(2), "wrong"))),
            "run": State(enter=(Add(enters, 10),), tick=(Add(ticks, 10),)),
            "wrong": State(tick=(Set(ticks, 255),)),
        })
        game.bind_pressed(Button.A, Set(enabled, False))
        game.bind_pressed(Button.B, Set(enabled, True))
        game.bind_pressed(Button.START, machine.change("idle"))
        with RuntimeHarness(game) as run:
            run.frame()
            self.assertEqual((run.variable("enters"), run.variable("ticks")), (1, 1))
            run.frame(Button.A)
            self.assertEqual((run.variable("enters"), run.variable("ticks")), (1, 2))
            self.assertEqual(run.variable(machine.current.name), 1)
            run.frame()
            self.assertEqual((run.variable("enters"), run.variable("ticks")), (1, 2))
            run.frame(Button.B)
            run.frame()
            self.assertEqual((run.variable("enters"), run.variable("ticks")), (11, 12))
            run.frame()
            self.assertEqual((run.variable("enters"), run.variable("ticks")), (11, 22))
            run.frame(Button.START)
            run.frame()
            self.assertEqual(run.variable("enters"), 12)
            self.assertEqual(run.variable("ticks"), 33)

    def test_health_repeated_contact_invu_and_checkpoint_clears_fractional_jump(self):
        game = Game()
        actor = game.actor(tile=1, x=40, y=40, subpixel=True)
        checkpoint = game.checkpoint(actor, points={"start": (40, 40), "ledge": (90, 100)})
        hurt = game.byte("hurt")
        hp = game.health(actor, points=2, invulnerability_frames=3, on_hurt=(Add(hurt, 1),))
        game.bind_pressed(Button.A, checkpoint.activate("ledge"))
        game.bind_pressed(Button.B, Set(actor.x_fraction, 128), Set(actor.jump_buffer, 4))
        game.after_physics(hp.damage(on_death=(checkpoint.respawn(), hp.restore())))
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            self.assertEqual((run.variable(hp.points.name), run.variable("hurt")), (1, 1))
            run.frame()
            run.frame(Button.B)
            self.assertEqual(run.variable(hp.points.name), 1)
            run.frame()
            self.assertEqual(run.variable(hp.points.name), 2)
            self.assertEqual((run.variable(actor.x.name), run.variable(actor.y.name)), (90, 100))
            self.assertEqual(run.variable(actor.x_fraction.name), 0)
            self.assertEqual(run.variable(actor.jump_buffer.name), 0)
            self.assertEqual(run.variable(hp.invulnerability.name), 3)
            self.assertEqual(run.variable("hurt"), 1)

    def test_lethal_damage_saturates_and_default_death_hides_once(self):
        game = Game()
        actor = game.actor(tile=1)
        hp = game.health(actor, points=2)
        game.after_physics(hp.damage(255))
        with RuntimeHarness(game) as run:
            run.frame()
            self.assertEqual(run.variable(hp.points.name), 0)
            self.assertEqual(run.variable(actor.visible.name), 0)
            run.frame()
            self.assertEqual(run.variable(hp.points.name), 0)

    def test_patrol_fractional_motion_stays_in_bounds_and_mirrors_facing(self):
        game = Game()
        actor = game.actor(tile=1, x=40, y=40, subpixel=True, facing="right")
        patrol = game.patrol(actor, left=40, right=45, speed=1.5)
        with RuntimeHarness(game) as run:
            positions = []
            for _ in range(20):
                run.frame()
                positions.append(run.variable(actor.x.name))
            self.assertEqual(min(positions), 40)
            self.assertEqual(max(positions), 45)
            self.assertGreater(len(set(positions)), 3)
            self.assertEqual(run.sprite_data()[2] & 64, run.variable(actor.facing_left.name) * 64)
            self.assertIn(run.variable(patrol.moving_left.name), (0, 1))

    def test_patrol_below_one_pixel_leaves_left_edge_on_every_cycle(self):
        game = Game()
        actor = game.actor(tile=1, x=40, y=40, subpixel=True, facing="right")
        game.patrol(actor, left=40, right=45, speed=.75)
        with RuntimeHarness(game) as run:
            positions = []
            for _ in range(70):
                run.frame()
                positions.append(run.variable(actor.x.name) * 256 + run.variable(actor.x_fraction.name))
            self.assertEqual(positions[0], 40 * 256 + 192)
            self.assertGreaterEqual(positions.count(40 * 256), 4)
            self.assertGreaterEqual(positions.count(45 * 256), 4)
            self.assertGreater(positions[-2], positions[-1])
            self.assertTrue(all(40 * 256 <= position <= 45 * 256 for position in positions))

    def test_room_reentry_resets_health_timer_machine_and_checkpoint(self):
        game = Game()
        first, other = game.room("first"), game.room("other")
        actor = first.actor(tile=1, x=40, y=40)
        hp = first.health(actor)
        countdown = first.timer("timer", frames=5)
        checkpoint = first.checkpoint(actor, points={"start": (40, 40), "other": (80, 80)})
        machine = first.state_machine("machine", states={"idle": State(), "done": State()})
        first.bind_pressed(Button.A, hp.damage(), checkpoint.activate("other"), machine.change("done"))
        first.bind_pressed(Button.B, ChangeRoom(other))
        other.bind_pressed(Button.B, ChangeRoom(first))
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            self.assertEqual(run.variable(hp.points.name), 2)
            run.frame(Button.B)
            run.frame()
            run.frame(Button.B)
            self.assertEqual(run.variable(hp.points.name), 3)
            self.assertEqual(run.variable(countdown.remaining.name), 5)
            self.assertEqual(run.variable(machine.current.name), 0)
            self.assertEqual(run.variable(checkpoint.current.name), 0)


@unittest.skipUnless(HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME)
class NamedAnimationRuntimeTests(unittest.TestCase):
    def test_select_clip_preserves_progress_restart_and_nonloop_holds_last(self):
        game = Game()
        actor = game.actor(animations={"idle": AnimationClip((1,)),
                                       "walk": AnimationClip((2, 3), frame_ticks=1),
                                       "hurt": AnimationClip((4, 5), frame_ticks=1, loop=False)})
        game.bind_held(Button.RIGHT, PlayAnimation(actor, "walk"))
        game.bind_pressed(Button.A, PlayAnimation(actor, "hurt"))
        game.bind_pressed(Button.B, PlayAnimation(actor, "hurt", restart=True))
        with RuntimeHarness(game) as run:
            self.assertEqual(run.sprite_data()[1], 1)
            run.frame(Button.RIGHT)
            self.assertEqual(run.sprite_data()[1], 2)
            run.frame(Button.RIGHT)
            self.assertEqual(run.sprite_data()[1], 3)
            run.frame(Button.RIGHT)
            self.assertEqual(run.sprite_data()[1], 2)
            run.frame(Button.A)
            self.assertEqual(run.sprite_data()[1], 4)
            run.frame()
            self.assertEqual(run.sprite_data()[1], 5)
            for _ in range(4):
                run.frame()
            self.assertEqual(run.sprite_data()[1], 5)
            self.assertEqual(run.variable(actor.animation_enabled.name), 0)
            run.frame(Button.B)
            self.assertEqual(run.sprite_data()[1], 4)

    def test_facing_reflects_positions_xors_part_flip_and_keeps_hitbox(self):
        game = Game()
        graphic = Metasprite((SpritePart(1, palette=2), SpritePart(2, dx=8, flip_horizontal=True)))
        actor = game.actor(tile=graphic, x=40, y=40, facing="right")
        game.bind_pressed(Button.LEFT, Face(actor, "left"))
        game.bind_pressed(Button.RIGHT, Face(actor, "right"))
        with RuntimeHarness(game) as run:
            self.assertEqual(run.sprite_data(0), (39, 1, 2, 40))
            self.assertEqual(run.sprite_data(1), (39, 2, 64, 48))
            run.frame(Button.LEFT)
            self.assertEqual(run.sprite_data(0), (39, 1, 66, 48))
            self.assertEqual(run.sprite_data(1), (39, 2, 0, 40))
            self.assertEqual(run.variable(actor.x.name), 40)
            run.frame(Button.RIGHT)
            self.assertEqual(run.sprite_data(0)[3], 40)

    def test_freeze_preserves_motion_animation_jump_and_ignores_controls(self):
        game = Game()
        actor = game.actor(animations={"idle": AnimationClip((1,)),
                                       "walk": AnimationClip((2, 3), frame_ticks=1)},
                           x=40, y=40, gravity=.25, freezable=True)
        game.bind_pressed(Button.B, Freeze(actor))
        game.bind_pressed(Button.START, Freeze(actor, False))
        game.platformer(actor)
        with RuntimeHarness(game) as run:
            run.frame(Button.RIGHT)
            run.frame(Button.RIGHT)
            before = tuple(run.variable(v.name) for v in actor.variables if v is not actor.frozen)
            run.frame(Button.B | Button.LEFT | Button.A)
            for _ in range(4):
                run.frame(Button.LEFT | Button.A)
            after = tuple(run.variable(v.name) for v in actor.variables if v is not actor.frozen)
            self.assertEqual(after, before)
            self.assertNotEqual(run.sprite_data()[0], 255)
            run.frame(Button.START | Button.RIGHT)
            self.assertEqual(run.variable(actor.frozen.name), 0)
            self.assertNotEqual(run.variable(actor.y_fraction.name), before[10])

    def test_platformer_automatically_selects_idle_walk_jump_and_fall(self):
        game = Game()
        game.map([[1] * 32], row=15, solid=True)
        actor = game.actor(animations={"idle": AnimationClip((1,)),
                                       "walk": AnimationClip((2, 3), frame_ticks=3),
                                       "jump": AnimationClip((4,)),
                                       "fall": AnimationClip((5,))},
                           x=40, y=112, gravity=.5)
        game.platformer(actor, acceleration=1, friction=1)
        with RuntimeHarness(game) as run:
            run.frame()
            self.assertEqual(run.sprite_data()[1], 1)
            run.frame(Button.LEFT)
            self.assertIn(run.sprite_data()[1], (2, 3))
            self.assertEqual(run.sprite_data()[2] & 64, 64)
            run.frame(Button.A)
            self.assertEqual(run.sprite_data()[1], 4)
            for _ in range(6):
                run.frame()
            self.assertEqual(run.sprite_data()[1], 5)
