# Changelog

## 0.5.0

- Add declarative timers, named state machines, patrols, health with
  invulnerability, and room-local checkpoints.
- Add named animation clips, actor facing, and optional freezing.
- Add paged dialogue, choices, and explicit action/wait sequences.
- Add FamiStudio imports and portable exports, music controls, and prioritized
  sound-effect sequences. Bundle the pinned engine with its MIT license.
- Add the living adventure example and original editable exploration/victory
  music. Existing examples remain supported.
- Verify 255 tests, five full-emulator checks, and an isolated wheel build.
- Add GitHub Actions tests, example ROM builds, emulator checks, and package
  artifacts for pushes and pull requests.

## 0.4.0

- Import PNG tile sheets and finite Tiled JSON rooms, including actor placements,
  entrances, exits, collision, and background palettes.
- Add optional fractional movement, acceleration, friction, variable jump
  height, jump buffering, and coyote time.
- Add the visual adventure example with editable art and maps.

## 0.3.0

- Add named rooms, entrances, room transitions, explicit variable lifetime,
  and a three-room adventure with persistent inventory.

## 0.2.0

- Add runtime state and conditions, actor physics and collision, safe display
  updates, animation, metasprites, and sound effects.

## 0.1.0

- Generate self-contained 6502 assembly and NROM cartridges from Python
  descriptions of text, backgrounds, sprites, and controller actions.
