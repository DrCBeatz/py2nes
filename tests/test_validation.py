"""Guard against Python silently replacing runtime predicates with constants."""

import operator
import unittest

from py3nes import Game, If, Set
from py3nes.physics import Overlaps


class RuntimePredicateValidationTests(unittest.TestCase):
    def test_description_depth_is_bounded_before_recursive_compilation(self):
        game = Game()
        value = game.byte("value")
        expression, condition, action = value, value.eq(0), Set(value, 1)
        for _ in range(32):
            expression = expression + 1
            condition = ~condition
            action = If(value.eq(0), action)
        game.every_frame(action, Set(value, expression), If(condition, Set(value, 2)))
        self.assertIn("update_events", game.to_assembly())
        for build in (lambda: expression + 1, lambda: ~condition,
                      lambda: If(value.eq(0), action)):
            with self.assertRaisesRegex(ValueError, "32"):
                build()

    def test_python_equality_cannot_discard_runtime_variable_or_expression(self):
        game = Game()
        score = game.byte("score", initial=3)
        for expression in (score, score + 1, game.flag("collected")):
            for compare in (operator.eq, operator.ne):
                for reverse in (False, True):
                    with self.subTest(expression=type(expression).__name__, compare=compare.__name__, reverse=reverse):
                        with self.assertRaisesRegex(TypeError, r"\.eq|\.ne|runtime"):
                            compare(3, expression) if reverse else compare(expression, 3)

    def test_python_equality_cannot_discard_runtime_condition(self):
        game = Game()
        score = game.byte("score")
        first = game.actor(tile=1, x=40, y=40)
        second = game.actor(tile=2, x=40, y=40)
        for condition in (score.eq(3), score.lt(3) & score.gt(0), ~score.eq(3), Overlaps(first, second)):
            for compare in (operator.eq, operator.ne):
                with self.subTest(condition=type(condition).__name__, compare=compare.__name__):
                    with self.assertRaisesRegex(TypeError, "runtime|condition"):
                        compare(condition, True)


if __name__ == "__main__":
    unittest.main()
