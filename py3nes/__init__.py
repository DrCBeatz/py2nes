"""Describe NES games in Python; run their generated 6502 code on the NES."""

from .assets import CHAR_TO_TILE, DEFAULT_PALETTE, Tile
from .build import BuildError, BuildResult
from .game import Game
from .model import (Action, Button, Event, Map, Move, SetPosition, SetTile,
                    Sprite, TextBox, Trigger)
from .ir import Add, Condition, Expr, If, Set, Variable
from .physics import (Actor, Animate, Hide, Hitbox, Metasprite, Overlaps,
                      Show, SpritePart, Teleport, Velocity)
from .effects import PlaySound, SetBackgroundTile, StopSound, Tone, WriteNumber, WriteText

__version__ = "0.2.0"
__all__ = ["Action", "BuildError", "BuildResult", "Button", "CHAR_TO_TILE",
           "DEFAULT_PALETTE", "Event", "Game", "Map", "Move", "SetPosition",
           "SetTile", "Sprite", "TextBox", "Tile", "Trigger",
           "Add", "Condition", "Expr", "If", "Set", "Variable", "Actor", "Animate",
           "Hide", "Hitbox", "Metasprite", "Overlaps", "Show", "SpritePart", "Teleport",
           "Velocity", "PlaySound", "SetBackgroundTile", "StopSound", "Tone", "WriteNumber", "WriteText"]
