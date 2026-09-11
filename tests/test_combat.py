"""Execute attack timing, edge geometry, and recoil on the generated 6502."""

import unittest

from py3nes import (Add, AnimationClip, Button, ChangeRoom, Face, Game, Hitbox,
                    If, Set)
from tests.runtime_harness import HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME, RuntimeHarness


def fighter(game, **options):
    return game.actor(animations={
        "idle": AnimationClip((1,)), "walk": AnimationClip((1, 2)),
        "attack": AnimationClip((3, 4), frame_ticks=2, loop=False),
        "hurt": AnimationClip((5, 6), frame_ticks=2),
    }, **options)


class CombatValidationTests(unittest.TestCase):
    def test_attack_and_hurtbox_fail_atomically(self):
        game = Game()
        actor = fighter(game, x=40, y=40)
        health = game.health(actor)
        foreign = Game().byte("foreign")
        before = (game.variables, game.events, game.post_events, game._oam_used)
        for call in (
            lambda: game.attack(actor, reach=0),
            lambda: game.attack(actor, active_frames=250, cooldown_frames=20),
            lambda: game.attack(actor, offset_y=-32),
            lambda: game.attack(actor, animation="missing"),
            lambda: game.attack(actor, on_start=(Set(foreign, 1),)),
            lambda: game.hurtbox(health, knockback=0.5),
            lambda: game.hurtbox(health, stun_frames=0),
            lambda: game.hurtbox(health, on_hurt=(Set(foreign, 1),)),
        ):
            with self.assertRaises((TypeError, ValueError)):
                call()
            self.assertEqual((game.variables, game.events, game.post_events, game._oam_used), before)
        attack = game.attack(actor)
        self.assertEqual(len(game.variables) - len(before[0]), 3)
        self.assertEqual(game._oam_used, before[3])
        self.assertIsNotNone(attack.start())

    def test_foreign_targets_callbacks_and_self_hits_are_rejected(self):
        game = Game()
        player = fighter(game)
        enemy = fighter(game, x=50)
        attack = game.attack(player)
        health = game.health(enemy)
        reaction = game.hurtbox(health)
        foreign = Game().actor(tile=1)
        for call in (
            lambda: attack.hits(player), lambda: attack.hits(foreign),
            lambda: attack.hit(enemy), lambda: attack.hit(health, damage=0),
            lambda: attack.hit(health, on_hit=(lambda: None,)),
            lambda: reaction.damage(source=foreign),
            lambda: game.attack(foreign),
            lambda: game.hurtbox(enemy),
        ):
            with self.assertRaises((TypeError, ValueError)):
                call()


@unittest.skipUnless(HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME)
class CombatRuntimeTests(unittest.TestCase):
    def test_active_duration_cooldown_and_one_hit_per_target_per_swing(self):
        game = Game()
        player = fighter(game, x=40, y=40)
        first = fighter(game, x=52, y=40)
        second = fighter(game, x=54, y=40)
        hp1 = game.health(first, points=3, invulnerability_frames=0)
        hp2 = game.health(second, points=3, invulnerability_frames=0)
        starts, active, recovering = (game.byte(name) for name in ("starts", "active", "recovering"))
        sword = game.attack(player, active_frames=3, cooldown_frames=2,
                            animation="attack", on_start=(Add(starts, 1),))
        game.bind_held(Button.B, sword.start())
        game.after_physics(sword.hit(hp1), sword.hit(hp2),
                           If(sword.active, Add(active, 1)),
                           If(sword.recovering, Add(recovering, 1)))
        with RuntimeHarness(game) as run:
            for _ in range(5):
                run.frame(Button.B)
                self.assertEqual(run.variable(hp1.points.name), 2)
                self.assertEqual(run.variable(hp2.points.name), 2)
            self.assertEqual(run.variable("starts"), 1)
            self.assertEqual(run.variable("active"), 3)
            self.assertEqual(run.variable("recovering"), 2)
            self.assertEqual(run.variable(player.clip.name), 2)
            run.frame(Button.B)
            self.assertEqual(run.variable("starts"), 2)
            self.assertEqual(run.variable(hp1.points.name), 1)
            self.assertEqual(run.variable(hp2.points.name), 1)

    def test_invulnerable_contact_is_consumed_without_late_damage(self):
        game = Game()
        player = fighter(game, x=40, y=40)
        enemy = fighter(game, x=50, y=40)
        hp = game.health(enemy, points=3, invulnerability_frames=0)
        accepted = game.byte("accepted")
        sword = game.attack(player, active_frames=7, cooldown_frames=0)
        game.bind_pressed(Button.A, Set(hp.invulnerability, 3), sword.start())
        game.bind_pressed(Button.B, sword.start())
        game.after_physics(sword.hit(hp, on_hit=(Add(accepted, 1),)))
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            for _ in range(7):
                run.frame()
            self.assertEqual(run.variable(hp.invulnerability.name), 0)
            self.assertEqual(run.variable(hp.points.name), 3)
            self.assertEqual(run.variable("accepted"), 0)
            run.frame(Button.B)
            self.assertEqual(run.variable(hp.points.name), 2)
            self.assertEqual(run.variable("accepted"), 1)

    def test_terminal_hit_feedback_runs_after_lethal_health_damage(self):
        game = Game()
        game.mode("playing", gameplay=True)
        victory = game.mode("victory")
        player = fighter(game, x=40, y=40)
        enemy = fighter(game, x=50, y=40)
        hp = game.health(enemy, points=1)
        sword = game.attack(player)
        game.bind_pressed(Button.B, sword.start())
        game.after_physics(sword.hit(hp, on_hit=(victory.change(),)))
        with RuntimeHarness(game) as run:
            run.frame(Button.B)
            self.assertEqual(run.read("rt_mode_current"), victory.index)
            self.assertEqual(run.variable(hp.points.name), 0)
            self.assertEqual(run.variable(enemy.visible.name), 0)

    def test_hit_feedback_cannot_prevent_damage_by_setting_invulnerability(self):
        game = Game()
        player = fighter(game, x=40, y=40)
        enemy = fighter(game, x=50, y=40)
        callbacks = game.byte("callbacks")
        hp = game.health(enemy, points=3, on_hurt=(Add(callbacks, 1),))
        hurt = game.hurtbox(hp, on_hurt=(Add(callbacks, 2),))
        sword = game.attack(player)
        game.bind_pressed(Button.B, sword.start())
        game.after_physics(sword.hit(hurt, on_hit=(Set(hp.invulnerability, 123),)))
        with RuntimeHarness(game) as run:
            run.frame(Button.B)
            self.assertEqual(run.variable(hp.points.name), 2)
            self.assertEqual(run.variable(hp.invulnerability.name), 123)
            self.assertEqual(run.variable(hurt.remaining.name), hurt.stun_frames)
            self.assertEqual(run.variable("callbacks"), 3)

    def test_facing_is_captured_at_start(self):
        game = Game()
        player = fighter(game, x=40, y=40)
        left = fighter(game, x=30, y=40)
        right = fighter(game, x=50, y=40)
        left_hp, right_hp = game.health(left), game.health(right)
        sword = game.attack(player, active_frames=2, cooldown_frames=0)
        game.bind_pressed(Button.B, sword.start(), Face(player, "left"))
        game.after_physics(sword.hit(left_hp), sword.hit(right_hp))
        with RuntimeHarness(game) as run:
            run.frame(Button.B)
            self.assertEqual(run.variable(player.facing_left.name), 1)
            self.assertEqual(run.variable(left_hp.points.name), 3)
            self.assertEqual(run.variable(right_hp.points.name), 2)
            run.frame()
            run.frame(Button.B)
            self.assertEqual(run.variable(left_hp.points.name), 2)

    def test_rectangles_use_hitboxes_and_do_not_wrap_at_screen_edges(self):
        # actor x/y, target x/y, facing, reach, vertical offset, expected overlap
        cases = (
            (248, 40, 0, 40, "right", 12, 0, False),
            (0, 40, 248, 40, "left", 12, 0, False),
            (40, 40, 60, 40, "right", 12, 0, False),
            (40, 40, 59, 40, "right", 12, 0, True),
            (40, 40, 20, 40, "left", 12, 0, False),
            (40, 40, 21, 40, "left", 12, 0, True),
            (40, 1, 50, 230, "right", 12, -16, False),
            (40, 40, 50, 48, "right", 12, 0, False),
            (40, 40, 50, 48, "right", 12, 1, True),
        )
        for ax, ay, tx, ty, facing, reach, offset, expected in cases:
            with self.subTest(case=(ax, ay, tx, ty, facing, offset)):
                game = Game()
                actor = game.actor(tile=1, x=ax, y=ay, facing=facing)
                target = game.actor(tile=1, x=tx, y=ty)
                seen = game.flag("seen")
                sword = game.attack(actor, reach=reach, offset_y=offset)
                game.bind_pressed(Button.B, sword.start())
                game.after_physics(If(sword.hits(target), Set(seen, True)))
                with RuntimeHarness(game) as run:
                    run.frame(Button.B)
                    self.assertEqual(run.variable("seen"), int(expected))

    def test_narrow_offset_hitboxes_and_hidden_targets(self):
        game = Game()
        actor = game.actor(tile=1, x=40, y=40, hitbox=Hitbox(2, 2, 2, 2), facing="right")
        target = game.actor(tile=1, x=45, y=42, hitbox=Hitbox(1, 1))
        sword = game.attack(actor, reach=2)
        seen = game.byte("seen")
        game.bind_held(Button.B, sword.start())
        game.bind_pressed(Button.A, Set(target.visible, False))
        game.after_physics(If(sword.hits(target), Add(seen, 1)))
        with RuntimeHarness(game) as run:
            run.frame(Button.B)
            self.assertEqual(run.variable("seen"), 1)
            run.frame(Button.A)
            self.assertEqual(run.variable("seen"), 1)

    def test_recoil_suspends_platformer_and_cancels_buffered_jump(self):
        game = Game()
        player = fighter(game, x=80, y=80, subpixel=True)
        enemy = game.actor(tile=1, x=60, y=80)
        hp = game.health(player, points=3, invulnerability_frames=0)
        hurt = game.hurtbox(hp, stun_frames=4, knockback=2.5, lift=1, animation="hurt")
        game.platformer(player, suspended=hurt.stunned)
        game.bind_pressed(Button.B, Set(player.jump_buffer, 5))
        hit = game.flag("hit")
        game.after_physics(If(~hit, Set(hit, True), hurt.damage(source=enemy)))
        with RuntimeHarness(game) as run:
            run.frame(Button.B)
            x = run.variable(player.x.name)
            self.assertEqual(run.variable(player.jump_buffer.name), 0)
            self.assertEqual(run.variable(player.clip.name), 3)
            run.frame(Button.LEFT)
            self.assertEqual(run.variable(player.x.name), x + 2)
            self.assertEqual(run.variable(player.vx_fraction.name), 128)
            self.assertEqual(run.variable(player.clip.name), 3)
            run.frame(Button.LEFT)
            self.assertEqual(run.variable(player.x.name), x + 5)
            run.frame(Button.LEFT)
            run.frame(Button.LEFT)
            self.assertEqual(run.variable(hurt.remaining.name), 0)
            self.assertEqual(run.variable(player.vx.name, signed=True), -1)

    def test_recoil_survives_patrol_until_stun_expires(self):
        game = Game()
        source = game.actor(tile=1, x=40, y=40)
        guard = fighter(game, x=55, y=40)
        hp = game.health(guard, invulnerability_frames=0)
        hurt = game.hurtbox(hp, stun_frames=4, knockback=3)
        game.patrol(guard, left=50, right=90, speed=1, suspended=hurt.stunned)
        game.bind_pressed(Button.B, hurt.damage(source=source))
        with RuntimeHarness(game) as run:
            run.frame(Button.B)
            x = run.variable(guard.x.name)
            run.frame()
            self.assertEqual(run.variable(guard.x.name), x + 3)
            run.frame()
            self.assertEqual(run.variable(guard.x.name), x + 6)
            run.frame()
            run.frame()
            self.assertEqual(run.variable(hurt.remaining.name), 0)
            self.assertEqual(run.variable(guard.vx.name), 1)

    def test_death_override_preserves_callbacks_and_clears_prior_stun(self):
        game = Game()
        player = fighter(game, x=40, y=40)
        count, feedback = game.byte("count"), game.byte("feedback")
        hp = game.health(player, points=2, invulnerability_frames=0, on_hurt=(Add(count, 1),))
        hurt = game.hurtbox(hp, on_hurt=(Add(feedback, 1),))
        checkpoint = game.checkpoint(player)
        game.bind_pressed(Button.B, hurt.damage(on_death=(checkpoint.respawn(), hp.restore())))
        with RuntimeHarness(game) as run:
            run.frame(Button.B)
            self.assertEqual(run.variable("count"), 1)
            self.assertEqual(run.variable("feedback"), 1)
            run.frame()
            run.frame(Button.B)
            self.assertEqual(run.variable(hp.points.name), 2)
            self.assertEqual(run.variable(hurt.remaining.name), 0)
            self.assertEqual(run.variable(player.visible.name), 1)
            self.assertEqual(run.variable("count"), 1)

    def test_room_reentry_resets_attack_contact_mask_and_stun(self):
        game = Game()
        room, other = game.room("room"), game.room("other")
        player = fighter(room, x=40, y=40)
        target = fighter(room, x=50, y=40)
        hp = room.health(target, invulnerability_frames=0)
        hurt = room.hurtbox(hp)
        sword = room.attack(player)
        room.bind_pressed(Button.B, sword.start())
        room.after_physics(sword.hit(hurt))
        room.bind_pressed(Button.A, ChangeRoom(other))
        other.bind_pressed(Button.A, ChangeRoom(room))
        with RuntimeHarness(game) as run:
            run.frame(Button.B)
            self.assertGreater(run.variable(sword.touched.name), 0)
            self.assertGreater(run.variable(hurt.remaining.name), 0)
            run.frame(Button.A)
            run.frame()
            run.frame(Button.A)
            self.assertEqual(run.variable(sword.remaining.name), 0)
            self.assertEqual(run.variable(sword.touched.name), 0)
            self.assertEqual(run.variable(hurt.remaining.name), 0)
            self.assertEqual(run.variable(hp.points.name), 3)

    def test_pause_preserves_attack_window_stun_and_recoil_position(self):
        game = Game()
        playing = game.mode("playing", gameplay=True)
        paused = game.mode("paused")
        game.bind_pressed(Button.START, paused.change(), scope=playing)
        game.bind_pressed(Button.START, playing.change(), scope=paused)
        player = fighter(game, x=40, y=40)
        enemy = fighter(game, x=50, y=40)
        hp = game.health(enemy)
        hurt = game.hurtbox(hp, knockback=2)
        sword = game.attack(player)
        game.bind_pressed(Button.B, sword.start())
        game.after_physics(sword.hit(hurt))
        with RuntimeHarness(game) as run:
            run.frame(Button.B)
            values = (sword.remaining, hurt.remaining, enemy.x, sword.touched)
            before = tuple(run.variable(value.name) for value in values)
            run.frame(Button.START)
            for _ in range(6):
                run.frame()
            self.assertEqual(tuple(run.variable(value.name) for value in values), before)
            run.frame(Button.START)
            self.assertEqual(tuple(run.variable(value.name) for value in values), before)
            run.frame()
            self.assertEqual(run.variable(sword.remaining.name), before[0] - 1)
            self.assertEqual(run.variable(hurt.remaining.name), before[1] - 1)
            self.assertEqual(run.variable(enemy.x.name), before[2] + 2)


if __name__ == "__main__":
    unittest.main()
