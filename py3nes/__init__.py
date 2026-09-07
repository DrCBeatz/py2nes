"""Describe NES games in Python; run their generated 6502 code on the NES."""

from .assets import CHAR_TO_TILE, DEFAULT_PALETTE, Tile
from .build import BuildError, BuildResult
from .game import Game
from .model import (Action, Button, Event, Map, Move, SetPosition, SetTile,
                    Sprite, TextBox, Trigger)

__version__ = "0.1.0"
__all__ = ["Action", "BuildError", "BuildResult", "Button", "CHAR_TO_TILE",
           "DEFAULT_PALETTE", "Event", "Game", "Map", "Move", "SetPosition",
           "SetTile", "Sprite", "TextBox", "Tile", "Trigger"]
