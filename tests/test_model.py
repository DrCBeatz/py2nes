"""Boundaries and immutable build-time descriptions for supported NES objects."""

from dataclasses import FrozenInstanceError
import unittest

from py3nes.model import Button, Event, Map, Move, SetPosition, SetTile, Sprite, TextBox, Trigger


class SpriteTests(unittest.TestCase):
    def test_oam_attribute_bits(self):
        sprite = Sprite(63, 255, 255, 255, palette=3, flip_horizontal=True,
                        flip_vertical=True, behind_background=True)
        self.assertEqual(sprite.attributes, 0xE3)
        self.assertEqual(Sprite(0, 0, 0, 0).attributes, 0)

    def test_sprite_descriptions_have_identity(self):
        self.assertNotEqual(Sprite(0, 64, 80, 80), Sprite(0, 64, 80, 80))

    def test_rejects_out_of_range_oam_values(self):
        defaults = dict(index=0, tile=64, x=80, y=80)
        for name, values in (("index", (-1, 64)), ("tile", (-1, 256)),
                             ("x", (-1, 256)), ("y", (-1, 256)), ("palette", (-1, 4))):
            for value in values:
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    Sprite(**(defaults | {name: value}))
        for name in ("index", "tile", "x", "y", "palette"):
            with self.subTest(name=name), self.assertRaises(TypeError):
                Sprite(**(defaults | {name: True}))
        for name in ("flip_horizontal", "flip_vertical", "behind_background"):
            with self.subTest(name=name), self.assertRaises(TypeError):
                Sprite(**(defaults | {name: 1}))


class MapTests(unittest.TestCase):
    def test_copies_rows_and_fits_bottom_right_screen_edge(self):
        source = [[1, 2], [3, 255]]
        patch = Map(source, column=30, row=28)
        source[0][0] = 4
        self.assertEqual(patch.tiles, ((1, 2), (3, 255)))
        self.assertEqual((patch.width, patch.height), (2, 2))
        with self.assertRaises(FrozenInstanceError):
            patch.column = 0

    def test_rejects_empty_or_ragged_grid(self):
        for rows in ([], [[]], [[1], []], [[1], [1, 2]]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                Map(rows)

    def test_rejects_screen_overflow_and_bad_tiles(self):
        for kwargs in (dict(column=-1), dict(row=-1), dict(column=32), dict(row=30),
                       dict(column=31), dict(row=29)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Map([[0, 0], [0, 0]], **kwargs)
        for value in (-1, 256):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Map([[value]])
        with self.assertRaises(TypeError):
            Map([[True]])


class TextBoxTests(unittest.TestCase):
    def test_minimum_boxes_and_screen_edge(self):
        self.assertEqual(TextBox("A", 29, 27, 3, 3).width, 3)
        self.assertEqual(TextBox("A", 31, 29, 1, 1, border=False).height, 1)

    def test_border_requires_room_for_inner_content(self):
        for width, height in ((2, 3), (3, 2), (0, 3), (3, 0)):
            with self.subTest(width=width, height=height), self.assertRaises(ValueError):
                TextBox("A", 0, 0, width, height)

    def test_rejects_overflow_and_wrong_types(self):
        with self.assertRaises(ValueError):
            TextBox("A", 30, 0, 3, 3)
        with self.assertRaises(ValueError):
            TextBox("A", 0, 28, 3, 3)
        with self.assertRaises(TypeError):
            TextBox(12, 0, 0, 3, 3)
        with self.assertRaises(TypeError):
            TextBox("A", 0, 0, 3, 3, border=1)


class ActionAndEventTests(unittest.TestCase):
    def setUp(self):
        self.sprite = Sprite(0, 64, 80, 80)

    def test_actions_describe_changes_without_executing_them(self):
        movement = Move(self.sprite, dx=-255, dy=255)
        position = SetPosition(self.sprite, x=0, y=255)
        tile = SetTile(self.sprite, tile=255)
        self.assertIs(movement.sprite, self.sprite)
        self.assertIs(position.sprite, self.sprite)
        self.assertIs(tile.sprite, self.sprite)
        self.assertEqual((self.sprite.x, self.sprite.y, self.sprite.tile), (80, 80, 64))

    def test_actions_validate_targets_and_byte_ranges(self):
        for factory in (lambda: Move(object()), lambda: SetPosition(None, 0, 0),
                        lambda: SetTile(0, 0)):
            with self.subTest(factory=factory), self.assertRaises(TypeError):
                factory()
        for factory in (lambda: Move(self.sprite, dx=-256), lambda: Move(self.sprite, dy=256),
                        lambda: SetPosition(self.sprite, -1, 0), lambda: SetPosition(self.sprite, 0, 256),
                        lambda: SetTile(self.sprite, 256)):
            with self.subTest(factory=factory), self.assertRaises(ValueError):
                factory()

    def test_event_copies_actions_and_accepts_each_single_button(self):
        source = [Move(self.sprite, dx=1)]
        event = Event(Trigger.HELD, source, Button.RIGHT)
        source.clear()
        self.assertEqual(len(event.actions), 1)
        self.assertIsInstance(event.actions, tuple)
        for button in Button:
            with self.subTest(button=button):
                self.assertEqual(Event(Trigger.PRESSED, event.actions, button).button, button)
        self.assertIsNone(Event(Trigger.FRAME, event.actions).button)

    def test_event_requires_explicit_action_descriptions(self):
        with self.assertRaises(ValueError):
            Event(Trigger.FRAME, ())
        for action in (lambda: None, "Move", object()):
            with self.subTest(action=action), self.assertRaises(TypeError):
                Event(Trigger.FRAME, (action,))
        with self.assertRaises(TypeError):
            Event("held", (Move(self.sprite),), Button.RIGHT)

    def test_button_rules_reject_ambiguous_bindings(self):
        actions = (Move(self.sprite),)
        for button in (None, 1, Button(0), Button.RIGHT | Button.LEFT, Button(256)):
            with self.subTest(button=button), self.assertRaises(ValueError):
                Event(Trigger.HELD, actions, button)
        with self.assertRaises(ValueError):
            Event(Trigger.FRAME, actions, Button.A)


if __name__ == "__main__":
    unittest.main()
