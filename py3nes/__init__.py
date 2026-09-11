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
from .rooms import ChangeRoom, Room, Spawn
from .images import TileSheet, load_png
from .tiled import ImportedRoom, TiledMap, TiledObject, load_tiled
from .controls import ButtonDown
from .physics import ApproachVelocity, CutJump, Jump
from .physics import AnimationClip, Face, Freeze, PlayAnimation
from .behaviors import Checkpoint, Health, Patrol, State, StateMachine, Timer, Transition
from .sequences import ButtonPressed, Do, Sequence, Wait, WaitForButton, WaitUntil
from .dialogue import Choice, Dialogue
from .effects import SoundEffect
from .music import (Music, MusicExportError, PauseMusic, PlayMusic, StopMusic,
                    export_famistudio, load_famistudio)

__version__ = "0.5.0"
__all__ = ["Action", "BuildError", "BuildResult", "Button", "CHAR_TO_TILE",
           "DEFAULT_PALETTE", "Event", "Game", "Map", "Move", "SetPosition",
           "SetTile", "Sprite", "TextBox", "Tile", "Trigger",
           "Add", "Condition", "Expr", "If", "Set", "Variable", "Actor", "Animate",
           "Hide", "Hitbox", "Metasprite", "Overlaps", "Show", "SpritePart", "Teleport",
           "Velocity", "PlaySound", "SetBackgroundTile", "StopSound", "Tone", "WriteNumber", "WriteText",
           "ChangeRoom", "Room", "Spawn", "TileSheet", "load_png",
           "ImportedRoom", "TiledMap", "TiledObject", "load_tiled",
           "ButtonDown", "ApproachVelocity", "CutJump", "Jump",
           "AnimationClip", "Face", "Freeze", "PlayAnimation",
           "Checkpoint", "Health", "Patrol", "State", "StateMachine", "Timer", "Transition",
           "ButtonPressed", "Do", "Sequence", "Wait", "WaitForButton", "WaitUntil",
           "Choice", "Dialogue", "SoundEffect", "Music", "MusicExportError",
           "PauseMusic", "PlayMusic", "StopMusic", "export_famistudio", "load_famistudio"]
