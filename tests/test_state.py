"""Runtime state validation and execution of generated 6502 expressions."""

import itertools
import operator
import unittest

from py3nes import Add, Button, Game, If, Set
from tests.runtime_harness import HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME, RuntimeHarness


class StateDescriptionTests(unittest.TestCase):
    def test_variable_initial_values_and_names_are_validated(self):
        game = Game()
        for name in ("", "1score", "has-key", "space name", "café", "_private", "actor_player", "rt_temp"):
            with self.subTest(name=name), self.assertRaises((ValueError, TypeError)):
                game.byte(name)
        value = game.byte("score_2", initial=255)
        self.assertEqual(value.kind, "u8")
        with self.assertRaises(ValueError):
            game.flag("score_2")
        for initial in (-1, 256, True, 1.5):
            with self.subTest(initial=initial), self.assertRaises((ValueError, TypeError)):
                game.byte("invalid", initial=initial)
        for initial in (-129, 128, True):
            with self.subTest(signed=initial), self.assertRaises((ValueError, TypeError)):
                game.signed_byte("invalid_signed", initial=initial)
        self.assertEqual(game.signed_byte("velocity", initial=-128).kind, "i8")

    def test_flags_remain_boolean_and_reject_arithmetic_mutations(self):
        game = Game()
        flag = game.flag("grounded", initial=True)
        other = game.flag("unlocked")
        counter = game.byte("counter")
        for value in (False, True, 0, 1, other):
            game.every_frame(Set(flag, value))
        for value in (2, -1, counter, counter + 1):
            with self.subTest(value=repr(value)), self.assertRaises((ValueError, TypeError)):
                game.every_frame(Set(flag, value))
        with self.assertRaises((ValueError, TypeError)):
            game.every_frame(Add(flag, 1))
        for value in (2, -1):
            with self.subTest(initial=value), self.assertRaises((ValueError, TypeError)):
                game.flag("invalid_flag", initial=value)

    def test_python_truth_testing_cannot_silently_evaluate_runtime_logic(self):
        game = Game()
        value = game.byte("value")
        flag = game.flag("flag")
        for expression in (value, flag, value + 1, value.eq(0), ~value.eq(0), value.eq(1) & flag, flag & flag):
            with self.subTest(expression=repr(expression)), self.assertRaises(TypeError):
                bool(expression)
        with self.assertRaises(TypeError):
            _ = value.eq(0) and value.eq(1)

    def test_foreign_variables_are_rejected_in_nested_targets_values_and_conditions(self):
        game, other = Game(), Game()
        local, foreign = game.byte("value"), other.byte("value")
        cases = (
            Set(foreign, 1),
            Set(local, 1 + foreign),
            Add(local, (local + 1) & foreign),
            If(foreign.eq(0), Set(local, 1)),
            If(local.eq(0), If(local.lt(foreign), Set(local, 2))),
            If(local.eq(0), Set(local, 1), otherwise=(Set(local, foreign),)),
            If(local.eq(0), Set(local, 1), otherwise=(Set(foreign, 2),)),
        )
        for action in cases:
            with self.subTest(action=repr(action)), self.assertRaises(ValueError):
                game.every_frame(action)
        self.assertEqual(game.events, ())


@unittest.skipUnless(HAS_RUNTIME_TOOLS, REQUIRES_RUNTIME)
class CompiledStateTests(unittest.TestCase):
    def test_initial_state_is_in_ram_and_assignments_read_current_values(self):
        game = Game()
        source = game.byte("source", initial=254)
        destination = game.byte("destination", initial=17)
        flag = game.flag("started", initial=False)
        signed = game.signed_byte("signed", initial=-127)
        game.every_frame(Add(source, 1), Set(destination, source), Set(flag, True), Add(signed, -2))
        with RuntimeHarness(game) as runtime:
            self.assertEqual(runtime.variable("source"), 254)
            self.assertEqual(runtime.variable("destination"), 17)
            self.assertEqual(runtime.variable("started"), 0)
            self.assertEqual(runtime.variable("signed", signed=True), -127)
            runtime.frame()
            self.assertEqual(runtime.variable("source"), 255)
            self.assertEqual(runtime.variable("destination"), 255)
            self.assertEqual(runtime.variable("started"), 1)
            self.assertEqual(runtime.variable("signed", signed=True), 127)
            runtime.frame()
            self.assertEqual(runtime.variable("source"), 0)
            self.assertEqual(runtime.variable("destination"), 0)
            self.assertEqual(runtime.variable("signed", signed=True), 125)

    def _check_comparisons(self, signed):
        game = Game()
        factory = game.signed_byte if signed else game.byte
        left, right = factory("left"), factory("right")
        predicates = {"eq": operator.eq, "ne": operator.ne, "lt": operator.lt,
                      "le": operator.le, "gt": operator.gt, "ge": operator.ge}
        for name in predicates:
            result = game.flag("result_" + name)
            game.every_frame(If(getattr(left, name)(right), Set(result, True), otherwise=(Set(result, False),)))
        boundaries = (-128, -127, -1, 0, 1, 126, 127) if signed else (0, 1, 127, 128, 254, 255)
        with RuntimeHarness(game) as runtime:
            for a, b in itertools.product(boundaries, repeat=2):
                runtime.bus[runtime.labels["v_left"]] = a & 255
                runtime.bus[runtime.labels["v_right"]] = b & 255
                runtime.frame()
                for name, expected in predicates.items():
                    with self.subTest(signed=signed, a=a, b=b, comparison=name):
                        self.assertEqual(runtime.variable("result_" + name), int(expected(a, b)))

    def test_unsigned_comparisons_at_sign_and_wrap_boundaries(self):
        self._check_comparisons(signed=False)

    def test_signed_comparisons_at_sign_and_wrap_boundaries(self):
        self._check_comparisons(signed=True)

    def test_expression_arithmetic_wraps_before_comparison(self):
        game = Game()
        high, low = game.byte("high", initial=255), game.byte("low", initial=1)
        signed = game.signed_byte("signed", initial=127)
        result = game.byte("result")
        underflow = game.byte("underflow")
        inverted = game.byte("inverted")
        wrap_flag = game.flag("wrapped")
        signed_flag = game.flag("signed_wrapped")
        game.every_frame(
            Set(result, (high + low) | ((high ^ 0xAA) & 0x0F)),
            Set(underflow, low - (low + 1)),
            Set(inverted, ~low),
            If((high + low).eq(0), Set(wrap_flag, True)),
            If((signed + 1).lt(0), Set(signed_flag, True)),
        )
        with RuntimeHarness(game) as runtime:
            runtime.frame()
            self.assertEqual(runtime.variable("result"), 5)
            self.assertEqual(runtime.variable("underflow"), 255)
            self.assertEqual(runtime.variable("inverted"), 254)
            self.assertEqual(runtime.variable("wrapped"), 1)
            self.assertEqual(runtime.variable("signed_wrapped"), 1)

    def test_nested_boolean_conditions_and_else_use_live_state(self):
        game = Game()
        keys = game.byte("keys")
        collected = game.flag("collected")
        won = game.flag("won")
        marker = game.byte("marker")
        game.bind_held(Button.A, If(~collected, Add(keys, 1), Set(collected, True)))
        game.bind_held(Button.B, Set(collected, False))
        game.every_frame(If((collected & keys.ge(2)) | won, Set(won, True),
                            If(keys.eq(2), Set(marker, 2), otherwise=(Set(marker, 3),)),
                            otherwise=(Set(marker, 1),)))
        with RuntimeHarness(game) as runtime:
            runtime.frame(Button.A)
            self.assertEqual(runtime.variable("keys"), 1)
            self.assertEqual(runtime.variable("marker"), 1)
            runtime.frame(Button.A)
            self.assertEqual(runtime.variable("keys"), 1)
            runtime.frame(Button.B)
            runtime.frame(Button.A)
            self.assertEqual(runtime.variable("keys"), 2)
            self.assertEqual(runtime.variable("won"), 1)
            self.assertEqual(runtime.variable("marker"), 2)
            runtime.frame(Button.B)
            runtime.frame(Button.A)
            self.assertEqual(runtime.variable("keys"), 3)
            self.assertEqual(runtime.variable("marker"), 3)

    def test_event_registration_order_includes_button_and_frame_events(self):
        game = Game()
        count = game.byte("count")
        observed = game.byte("observed")
        game.every_frame(Set(count, 1))
        game.bind_held(Button.RIGHT, Add(count, 2))
        game.every_frame(Set(observed, count))
        with RuntimeHarness(game) as runtime:
            runtime.frame(Button.RIGHT)
            self.assertEqual(runtime.variable("observed"), 3)
            runtime.frame()
            self.assertEqual(runtime.variable("observed"), 1)

    def test_large_conditional_branches_assemble_and_take_correct_path(self):
        game = Game()
        enabled = game.flag("enabled", initial=True)
        count = game.byte("count")
        game.every_frame(If(enabled, *(Add(count, 1) for _ in range(80)),
                            otherwise=tuple(Add(count, 2) for _ in range(80))))
        game.bind_pressed(Button.A, Set(enabled, False))
        with RuntimeHarness(game) as runtime:
            runtime.frame()
            self.assertEqual(runtime.variable("count"), 80)
            runtime.frame(Button.A)
            self.assertEqual(runtime.variable("count"), 160)
            runtime.frame()
            self.assertEqual(runtime.variable("count"), 64)

    def test_nested_expression_evaluation_survives_nmi_at_each_instruction(self):
        game = Game()
        a, b = game.byte("a", initial=250), game.byte("b", initial=7)
        c, d = game.byte("c", initial=130), game.byte("d", initial=42)
        result = game.byte("result")
        game.every_frame(
            Set(result, (a + (b ^ (c - d))) - ((b | c) & (a + d))),
            If((a + b).ge(c - d) & (~b.eq(c) | d.lt(a)), Add(result, 5),
               otherwise=(Add(result, 6),)),
        )
        with RuntimeHarness(game) as runtime:
            runtime.interrupt()
            runtime.run_until(lambda: runtime.cpu.pc == runtime.labels["update_events"])
            for _ in range(2000):
                if runtime.read("frame_ready"):
                    break
                cpu = runtime.cpu
                before = (cpu.pc, cpu.sp, cpu.a, cpu.x, cpu.y, cpu.p & 0xEF)
                runtime.interrupt()
                self.assertEqual((cpu.pc, cpu.sp, cpu.a, cpu.x, cpu.y, cpu.p & 0xEF), before)
                cpu.step()
            else:
                self.fail("interrupted gameplay failed to finish")
            # (250 + (7 ^ 88)) wraps to 89; (135 & 36) is 4.
            # The expression is 85, then (250+7)%256 >= 88 is false: +6.
            self.assertEqual(runtime.variable("result"), 91)


if __name__ == "__main__":
    unittest.main()
