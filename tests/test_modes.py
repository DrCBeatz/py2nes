"""Assembled scheduler tests: menus advance while gameplay state is preserved."""

from pathlib import Path
import unittest

from py3nes import (Add, AnimationClip, Button, ChangeRoom, Game, If, PauseMusic,
                    PlayMusic, Set, Velocity, WriteText, load_famistudio, Choice, Hide, Teleport)
from py3nes.modes import ChangeMode, GameMode, ModeActive
from py3nes.sequences import Do, Wait
from tests.runtime_harness import HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME, RuntimeHarness


class ModeDescriptionTests(unittest.TestCase):
    def test_mode_and_scope_ownership_and_validation(self):
        game = Game()
        playing = game.mode("playing", gameplay=True)
        foreign = Game().mode("foreign")
        count = game.byte("count")
        for operation in (lambda: game.mode("playing"), lambda: game.mode("bad name"),
                          lambda: game.mode("bad", gameplay=1), lambda: game.start_mode("playing"),
                          lambda: game.start_mode(foreign),
                          lambda: game.every_frame(Add(count, 1), scope=foreign),
                          lambda: game.every_frame(Add(count, 1), scope="missing"),
                          lambda: game.every_frame(foreign.change()),
                          lambda: game.every_frame(If(foreign.active, Add(count, 1))),
                          lambda: ChangeMode(playing, restart=1), lambda: ModeActive("playing"),
                          lambda: playing.on_enter(playing.change())):
            with self.assertRaises((ValueError, TypeError)):
                operation()
        room = game.room("hall")
        with self.assertRaises(ValueError):
            room.mode("room_mode")
        with self.assertRaises(ValueError):
            room.on_enter(playing.change())
        self.assertEqual(len(game.modes), 1)

    def test_context_restores_scope_and_helpers_inherit_it(self):
        game = Game()
        title = game.mode("title")
        game.mode("playing", gameplay=True)
        room = game.room("hall")
        with game.during(title):
            title_timer = room.timer("title_timer", frames=3)
            with room.during("always"):
                room.every_frame(Add(title_timer.remaining, 1))
            room.every_frame(Add(title_timer.remaining, 1))
        room.every_frame(Add(title_timer.remaining, 1))
        self.assertEqual([event.scope for event in room.events], [title, "always", title, None])
        with self.assertRaises(RuntimeError):
            with game.during(title):
                raise RuntimeError()
        self.assertIsNone(game._current_event_scope)

    def test_exclusive_modes_have_separate_display_budgets(self):
        game = Game()
        first, second = game.mode("first"), game.mode("second")
        for mode in (first, second):
            game.every_frame(WriteText("", 0, 0, 32), WriteText("", 0, 1, 32), scope=mode)
        game.to_assembly()
        game.every_frame(WriteText("A", 0, 2), scope="always")
        with self.assertRaisesRegex(ValueError, "65 background tile writes"):
            game.to_assembly()
        game = Game()
        game.mode("title").on_enter(WriteText("", 0, 0, 32), WriteText("", 0, 1, 32), WriteText("A", 0, 2))
        with self.assertRaisesRegex(ValueError, "65 background tile writes"):
            game.to_assembly()

    def test_games_without_modes_add_no_scheduler_state(self):
        game = Game()
        game.every_frame(Add(game.byte("count"), 1))
        self.assertNotIn("rt_mode_", game.to_assembly())

    def test_equivalent_gameplay_scopes_share_modal_display_budget(self):
        game = Game()
        game.mode("playing", gameplay=True)
        first = game.dialogue("first", "FIRST", column=0, width=32, height=3)
        with game.during("gameplay"):
            second = game.dialogue("second", "SECOND", column=0, width=32, height=3)
        game.every_frame(WriteText("A", 0, 10))
        game.to_assembly()
        self.assertEqual(len(game._sequence_modal_groups), 1)
        self.assertEqual(len(game.events), 2)

    def test_noop_mode_change_still_counts_following_display_writes(self):
        game = Game()
        playing = game.mode("playing", gameplay=True)
        game.every_frame(WriteText("", 0, 0, 32), playing.change(),
                         WriteText("", 0, 1, 32), WriteText("A", 0, 2))
        with self.assertRaisesRegex(ValueError, "65 background tile writes"):
            game.to_assembly()


@unittest.skipUnless(HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME)
class ModeRuntimeTests(unittest.TestCase):
    def test_initial_mode_entry_updates_first_oam_and_teleport_support(self):
        game = Game()
        title = game.mode("title")
        hidden = game.actor(name="hidden", tile=1, x=40, y=40)
        moved = game.actor(name="moved", tile=2, x=50, y=40)
        game.map([[1]], column=10, row=11, solid=True)
        title.on_enter(Hide(hidden), Teleport(moved, 80, 80))
        with RuntimeHarness(game) as run:
            self.assertEqual(run.bus.oam[0], 255)
            self.assertEqual(tuple(run.bus.oam[4:8]), (79, 2, 0, 80))
            self.assertEqual(run.variable(moved.grounded.name), 1)
            self.assertEqual(run.variable(moved.frame_timer.name), 0)

    def test_transitioning_sequence_finalizer_has_one_display_budget(self):
        game = Game()
        title, playing = game.mode("title"), game.mode("playing", gameplay=True)
        completed = game.byte("completed")
        with game.during(title):
            scene = game.sequence("start", Do(playing.change()),
                                  on_finish=(Add(completed, 1), WriteText("A" * 32, 0, 0),
                                             WriteText("B" * 32, 0, 1)))
        title.on_enter(scene.start())
        with RuntimeHarness(game) as run:
            run.frame()
            self.assertEqual(run.read("rt_mode_current"), playing.index)
            self.assertEqual(run.variable(completed.name), 1)
            self.assertEqual(run.variable(scene.active.name), 0)
    def test_pause_preserves_physics_animation_timers_rules_and_fresh_input(self):
        game = Game()
        playing = game.mode("playing", gameplay=True)
        paused = game.mode("paused")
        game.bind_pressed(Button.START, paused.change(), scope=playing)
        game.bind_pressed(Button.START, playing.change(), scope=paused)
        tick, menu_tick, post = game.byte("tick"), game.byte("menu_tick"), game.byte("post")
        actor = game.actor(name="player", frames=(game.metasprite(((1,),)), game.metasprite(((2,),))),
                           x=20, y=40, gravity=0, frame_ticks=1, subpixel=True)
        timer = game.timer("countdown", frames=20)
        game.every_frame(Add(tick, 1), Velocity(actor, vx=0.5))
        game.after_physics(Add(post, 1))
        game.every_frame(Add(menu_tick, 1), scope="always")
        with RuntimeHarness(game) as run:
            run.frame()
            snapshot = [run.variable(v.name) for v in (actor.x, actor.x_fraction, actor.frame,
                                                       actor.frame_timer, timer.remaining, tick, post)]
            run.frame(Button.START)
            for _ in range(5):
                run.frame(Button.START)
            self.assertEqual(run.read("rt_mode_current"), paused.index)
            self.assertEqual([run.variable(v.name) for v in (actor.x, actor.x_fraction, actor.frame,
                                                              actor.frame_timer, timer.remaining, tick, post)], snapshot)
            self.assertEqual(run.variable(menu_tick.name), 6)
            run.frame()
            run.frame(Button.START)
            self.assertEqual(run.read("rt_mode_current"), playing.index)
            self.assertEqual(run.variable(tick.name), 1)
            run.frame(Button.START)
            self.assertEqual(run.read("rt_mode_current"), playing.index)
            self.assertEqual(run.variable(tick.name), 2)

    def test_title_sequence_runs_while_gameplay_waits_and_can_be_revisited(self):
        game = Game()
        playing, title = game.mode("playing", gameplay=True), game.mode("title")
        game.start_mode(title)
        count, finished = game.byte("count"), game.byte("finished")
        with game.during(title):
            sequence = game.sequence("title", Wait(2), Do(Add(count, 1), playing.change()),
                                     on_finish=(Add(finished, 1),))
        title.on_enter(sequence.start())
        game.bind_pressed(Button.SELECT, title.change())
        with RuntimeHarness(game) as run:
            self.assertEqual(run.variable(sequence.active.name), 1)
            for _ in range(3):
                run.frame()
            self.assertEqual(run.read("rt_mode_current"), playing.index)
            self.assertEqual(run.variable(sequence.active.name), 0)
            self.assertEqual(run.variable(finished.name), 1)
            run.frame(Button.SELECT)
            for _ in range(3):
                run.frame()
            self.assertEqual(run.variable(count.name), 2)
            self.assertEqual(run.variable(finished.name), 2)

    def test_mode_entry_runs_once_and_nested_change_aborts_source_actions(self):
        game = Game()
        first, second = game.mode("first", gameplay=True), game.mode("second", gameplay=True)
        count, entered, forbidden = game.byte("count"), game.byte("entered"), game.byte("forbidden")
        second.on_enter(Add(entered, 1), WriteText("NEW", 0, 0))
        game.bind_pressed(Button.A, Add(count, 1), WriteText("OLD", 0, 0),
                          If(True, second.change(), Add(forbidden, 1)), Add(forbidden, 1))
        game.every_frame(Add(forbidden, 1))
        game.bind_pressed(Button.B, second.change(restart=True))
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            self.assertEqual(run.variable(count.name), 1)
            self.assertEqual(run.variable(forbidden.name), 0)
            self.assertEqual(run.variable(entered.name), 1)
            run.interrupt()
            self.assertEqual(bytes(run.bus.ppu_memory[0x2000:0x2003]), bytes((46, 37, 55)))
            run.frame()
            run.frame(Button.A)
            self.assertEqual(run.variable(entered.name), 1)
            self.assertEqual(run.variable(forbidden.name), 4)
            run.frame(Button.B)
            self.assertEqual(run.variable(entered.name), 2)

    def test_global_transition_skips_room_events_and_entry_can_select_room(self):
        game = Game()
        title, playing = game.mode("title"), game.mode("playing", gameplay=True)
        first, second = game.room("first"), game.room("second")
        count = game.byte("count")
        actor = second.actor(name="player", tile=1, x=20, y=40)
        second.spawn("entry", actor, x=70, y=80)
        second.on_enter(Add(count, 10))
        playing.on_enter(ChangeRoom(second, "entry"), Add(count, 100))
        game.bind_pressed(Button.START, playing.change(), scope=title)
        first.every_frame(Add(count, 1), scope="always")
        second.every_frame(Add(count, 2))
        with RuntimeHarness(game) as run:
            run.frame(Button.START)
            self.assertEqual(run.read("rt_room"), second.index)
            self.assertEqual(run.variable(count.name), 10)
            self.assertEqual(run.variable(actor.x.name), 70)
            run.frame()
            self.assertEqual(run.variable(count.name), 12)

    def test_initial_mode_entry_can_change_room_and_retain_its_mode(self):
        game = Game()
        title = game.mode("title")
        game.room("unused")
        menu = game.room("menu")
        entered = game.byte("entered")
        menu.on_enter(Add(entered, 1))
        title.on_enter(ChangeRoom(menu))
        with RuntimeHarness(game) as run:
            self.assertEqual(run.read("rt_room"), menu.index)
            self.assertEqual(run.read("rt_mode_current"), title.index)
            self.assertEqual(run.variable(entered.name), 1)

    def test_initial_room_entry_sees_the_selected_start_mode(self):
        game = Game()
        game.mode("playing", gameplay=True)
        title = game.mode("title")
        game.start_mode(title)
        room = game.room("hall")
        selected = game.byte("selected")
        room.on_enter(If(title.active, Set(selected, 1)))
        with RuntimeHarness(game) as run:
            self.assertEqual(run.variable(selected.name), 1)

    def test_modal_sequences_keep_independent_scopes(self):
        game = Game()
        playing, title = game.mode("playing", gameplay=True), game.mode("title")
        actor = game.actor(tile=1, gravity=0, freezable=True)
        done = game.byte("done")
        with game.during(playing):
            gameplay = game.sequence("play", Wait(2), Add(done, 1), freeze=(actor,))
        with game.during(title):
            menu = game.sequence("menu", Wait(2), Add(done, 10), freeze=(actor,))
        game.start_mode(title)
        title.on_enter(menu.start())
        playing.on_enter(gameplay.start())
        game.bind_pressed(Button.START, playing.change(), scope=title)
        with RuntimeHarness(game) as run:
            for _ in range(3):
                run.frame()
            self.assertEqual(run.variable(done.name), 10)
            run.frame(Button.START)
            for _ in range(3):
                run.frame()
            self.assertEqual(run.variable(done.name), 11)

    def test_mode_music_pause_preserves_manual_pause_and_entry_play_commands(self):
        music = load_famistudio(Path(__file__).resolve().parents[1] / "examples/assets/music/little_rooms.music.json")
        game = Game()
        playing = game.mode("playing", gameplay=True)
        paused = game.mode("paused", pause_music=True)
        playing.on_enter(PlayMusic(music))
        paused.on_enter(PlayMusic(music, "Victory", restart=True))
        game.bind_pressed(Button.START, paused.change(), scope=playing)
        game.bind_pressed(Button.START, playing.change(), scope=paused)
        game.bind_pressed(Button.A, PauseMusic(), scope="always")
        game.bind_pressed(Button.B, PauseMusic(False), scope="always")
        with RuntimeHarness(game) as run:
            run.interrupt()
            run.frame(Button.START)
            run.interrupt()
            self.assertTrue(run.read("famistudio_song_speed") & 0x80)
            self.assertEqual(run.read("fx_music_current_song"), 1)
            run.frame(Button.B)
            run.interrupt()
            self.assertTrue(run.read("famistudio_song_speed") & 0x80)
            run.frame(Button.START)
            run.interrupt()
            self.assertFalse(run.read("famistudio_song_speed") & 0x80)
            run.frame(Button.A)
            run.interrupt()
            self.assertTrue(run.read("famistudio_song_speed") & 0x80)
        plain = game.mode("plain_pause", pause_music=True)
        game.bind_pressed(Button.SELECT, plain.change(), scope=playing)
        game.bind_pressed(Button.SELECT, playing.change(), scope=plain)
        with RuntimeHarness(game) as run:
            run.frame(Button.A)
            run.frame(Button.SELECT)
            run.frame()
            run.frame(Button.SELECT)
            run.interrupt()
            self.assertTrue(run.read("famistudio_song_speed") & 0x80)

    def test_mode_audio_hold_is_not_visible_to_nmi_before_publish(self):
        music = load_famistudio(Path(__file__).resolve().parents[1] / "examples/assets/music/little_rooms.music.json")
        game = Game()
        playing = game.mode("playing", gameplay=True)
        paused = game.mode("paused", pause_music=True)
        playing.on_enter(PlayMusic(music))
        game.bind_pressed(Button.START, paused.change())
        with RuntimeHarness(game) as run:
            run.interrupt()
            run.bus.buttons = int(Button.START)
            run.run_until(lambda: run.read("rt_mode_pause_music") == 1)
            self.assertEqual(run.read("frame_ready"), 0)
            run.interrupt()
            self.assertFalse(run.read("famistudio_song_speed") & 0x80)
            run.run_until(lambda: run.cpu.pc == run.labels["main_loop"] and run.read("frame_ready"))
            run.interrupt()
            self.assertTrue(run.read("famistudio_song_speed") & 0x80)

    def test_dialogue_choice_transition_advances_before_suspending(self):
        game = Game()
        playing = game.mode("playing", gameplay=True)
        paused = game.mode("paused")
        chosen = game.byte("chosen")
        scene = game.dialogue("ask", "GO?", width=8, height=3,
                              choices=(Choice("YES", Add(chosen, 1), paused.change()), Choice("NO")))
        game.bind_pressed(Button.B, scene.start())
        game.bind_pressed(Button.START, playing.change(), scope=paused)
        with RuntimeHarness(game) as run:
            run.frame(Button.B)
            for _ in range(3):
                run.frame()
            run.frame(Button.A)
            self.assertEqual(run.read("rt_mode_current"), paused.index)
            self.assertEqual(run.variable(chosen.name), 1)
            run.frame(Button.START)
            for _ in range(5):
                run.frame()
            self.assertEqual(run.variable(scene.active.name), 0)
            self.assertEqual(run.variable(chosen.name), 1)
